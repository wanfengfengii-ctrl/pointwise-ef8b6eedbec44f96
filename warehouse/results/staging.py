import json
from warehouse.source.coordinates import encode_coordinate, decode_coordinate
from warehouse.execution.runner import OutputRow
from warehouse.results.runs import RunState, RunStateError


class StagingStore:
    def __init__(self, database, runs):
        self.db, self.runs = database, runs

    def append(self, run_id, row):
        run = self.runs.get(run_id)
        if run.state is not RunState.RUNNING:
            raise RunStateError('only running work may stage rows')
        if not self.db.connection.in_transaction:
            raise RunStateError('staging requires a work transaction')
        if row.output_index != self.count(run_id):
            raise RunStateError('noncontiguous output index')
        if row.coordinate.source.batch_id != run.batch_id:
            raise RunStateError('output belongs to another batch')
        self.db.checkpoint('stage.append')
        self.db.execute('INSERT INTO staging VALUES(?,?,?,?)',
                        (run_id, row.output_index,
                         json.dumps(encode_coordinate(row.coordinate)),
                         json.dumps(row.values, allow_nan=False)))

    def count(self, run_id):
        return self.db.execute('SELECT count(*) FROM staging WHERE run_id=?',
                               (run_id,)).fetchone()[0]

    def iter_rows(self, run_id):
        for row in self.db.execute(
                'SELECT * FROM staging WHERE run_id=? ORDER BY output_index', (run_id,)):
            yield OutputRow(row['output_index'], decode_coordinate(
                json.loads(row['coordinate'])), json.loads(row['payload']))

    def clear(self, run_id):
        self.db.execute('DELETE FROM staging WHERE run_id=?', (run_id,))
