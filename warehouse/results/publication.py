import json
from dataclasses import dataclass
from warehouse.execution.runner import OutputRow
from warehouse.source.coordinates import decode_coordinate
from warehouse.results.runs import RunState, RunStateError


class ResultUnavailable(LookupError):
    pass


class PublicationIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishedResult:
    run_id: str
    batch_id: str
    plan_revision: str
    row_count: int
    rows: tuple


class PublicationStore:
    def __init__(self, database, runs, staging):
        self.db, self.runs, self.staging = database, runs, staging

    def publish(self, run_id, expected_count):
        if not self.db.connection.in_transaction:
            raise RunStateError('publication requires a work transaction')
        run = self.runs.get(run_id)
        if run.state is not RunState.RUNNING:
            raise RunStateError('only running work may publish')
        if self.staging.count(run_id) != expected_count:
            raise PublicationIntegrityError('staged count mismatch')
        for index, row in enumerate(self.staging.iter_rows(run_id)):
            if row.output_index != index or row.coordinate.source.batch_id != run.batch_id:
                raise PublicationIntegrityError('invalid staged ownership or ordering')
        if self.db.execute('SELECT count(*) FROM results WHERE run_id=?',
                           (run_id,)).fetchone()[0]:
            raise PublicationIntegrityError('result already exists')
        self.db.execute('INSERT INTO results SELECT * FROM staging WHERE run_id=?', (run_id,))
        self.db.checkpoint('publication.rows')
        self.runs.mark_succeeded(run_id, expected_count)
        self.db.checkpoint('publication.state')
        self.staging.clear(run_id)

    def read_success(self, run_id):
        try:
            run = self.runs.get(run_id)
        except KeyError as error:
            raise ResultUnavailable(str(error)) from error
        if run.state is not RunState.SUCCEEDED:
            raise ResultUnavailable(f'run {run_id} is {run.state.value}')
        rows = []
        for index, row in enumerate(self.db.execute(
                'SELECT * FROM results WHERE run_id=? ORDER BY output_index', (run_id,))):
            coordinate = decode_coordinate(json.loads(row['coordinate']))
            if row['output_index'] != index or coordinate.source.batch_id != run.batch_id:
                raise PublicationIntegrityError('published row ownership or order mismatch')
            rows.append(OutputRow(index, coordinate, json.loads(row['payload'])))
        if len(rows) != run.row_count:
            raise PublicationIntegrityError('published row count mismatch')
        return PublishedResult(run_id, run.batch_id, run.plan_revision,
                               run.row_count, tuple(rows))
