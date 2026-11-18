import json
import uuid
from enum import Enum
from dataclasses import dataclass
from warehouse.expressions.errors import EvaluationError


class RunState(Enum):
    CREATED = 'CREATED'
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'


class RunStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    batch_id: str
    plan_revision: str
    state: RunState
    row_count: int | None
    error: dict | None


class RunStore:
    def __init__(self, database):
        self.db = database

    def create(self, batch_id, revision):
        run_id = uuid.uuid4().hex
        with self.db.transaction('run.created.before_commit'):
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,NULL,NULL)',
                            (run_id, batch_id, revision, RunState.CREATED.value))
        return run_id

    def _transition(self, run_id, old, new, count=None, error=None):
        cursor = self.db.execute(
            'UPDATE runs SET state=?,row_count=?,error=? WHERE run_id=? AND state=?',
            (new.value, count, json.dumps(error) if error is not None else None,
             run_id, old.value))
        if cursor.rowcount != 1:
            raise RunStateError(f'illegal transition for run {run_id}: {old.value}')

    def start(self, run_id):
        self._transition(run_id, RunState.CREATED, RunState.RUNNING)

    def mark_succeeded(self, run_id, row_count):
        self._transition(run_id, RunState.RUNNING, RunState.SUCCEEDED, row_count)

    def mark_failed(self, run_id, error):
        summary = error.to_data() if isinstance(error, EvaluationError) else {
            'type': type(error).__name__, 'message': str(error), 'code': 'STORAGE'}
        with self.db.transaction('run.failure.before_commit'):
            self.db.checkpoint('run.failure')
            self._transition(run_id, RunState.CREATED, RunState.FAILED, error=summary)

    def get(self, run_id):
        row = self.db.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(f'unknown run: {run_id}')
        return RunRecord(row['run_id'], row['batch_id'], row['plan_revision'],
                         RunState(row['state']), row['row_count'],
                         json.loads(row['error']) if row['error'] else None)
