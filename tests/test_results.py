import tempfile
import unittest
from pathlib import Path
from warehouse import Warehouse, FunctionContext
from warehouse.expressions.errors import FunctionFailure
from warehouse.results.api import ResultUnavailable
from warehouse.results.database import StorageFailure
from warehouse.results.runs import RunState, RunStateError
from samples import literal, field, ref, call, operation, binding, expand


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()
        self.addCleanup(self.w.close)

    def register(self, definition):
        return self.w.register_plan('p', definition).plan_revision

    def constant(self, value):
        return self.register({'output': [binding('value', literal(value))]})

    def assert_no_output(self, warehouse, run_id):
        with self.assertRaises(ResultUnavailable):
            warehouse.read_result(run_id)
        for table in ('staging', 'results'):
            self.assertEqual(warehouse.database.execute(
                f'SELECT count(*) FROM {table} WHERE run_id=?', (run_id,)).fetchone()[0], 0)

    def test_late_demand_failure_publishes_nothing(self):
        batch = self.w.ingest('r', [{'a': [False, True]}])
        old = self.w.run(batch.batch_id, self.constant('old'))
        plan = self.register({
            'bindings': [binding('bad', call('fail', literal('late')))],
            'expand': expand(field('root', 'a'), {'output': [
                binding('value', operation('if', field('item'), ref('bad'), literal(1)))]})})
        context = FunctionContext()
        with self.assertRaises(FunctionFailure) as caught:
            self.w.run(batch.batch_id, plan, context)
        error = caught.exception
        record = self.w.runs.get(error.run_id)
        self.assertIs(record.state, RunState.FAILED)
        self.assertEqual(record.error, error.to_data())
        self.assertEqual(error.location.expression, '$.bindings[0].expr')
        self.assertEqual(error.location.coordinate.elements[0].element_index, 1)
        self.assertEqual(context.trace[0]['coordinate']['elements'], [])
        self.assertEqual(len(context.trace), 1)
        self.assert_no_output(self.w, error.run_id)
        self.assertEqual(self.w.read_result(old.run_id).rows[0].values, {'value': 'old'})

    def test_publication_failure_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='warehouse-') as directory:
            path = Path(directory) / 'results.sqlite'
            with Warehouse(path) as warehouse:
                batch = warehouse.ingest('r', [{}, {}])
                p1 = warehouse.register_plan('p', {
                    'output': [binding('v', literal('A'))]}).plan_revision
                old = warehouse.run(batch.batch_id, p1)
                p2 = warehouse.register_plan('p', {
                    'output': [binding('v', literal('B'))]}).plan_revision
                warehouse.database.inject_once('run.before_commit')
                with self.assertRaises(StorageFailure) as caught:
                    warehouse.run(batch.batch_id, p2)
                failed_id = caught.exception.run_id
                self.assert_no_output(warehouse, failed_id)
            with Warehouse(path) as reopened:
                self.assertEqual([r.values for r in reopened.read_result(old.run_id).rows],
                                 [{'v': 'A'}, {'v': 'A'}])
                self.assertIs(reopened.runs.get(failed_id).state, RunState.FAILED)
                self.assert_no_output(reopened, failed_id)
                again = reopened.run(batch.batch_id, p1)
                self.assertEqual(reopened.read_result(again.run_id).rows[0].values, {'v': 'A'})
                new = reopened.run(batch.batch_id, p2, FunctionContext())
                self.assertNotEqual(new.run_id, failed_id)
                self.assertEqual([r.values for r in reopened.read_result(new.run_id).rows],
                                 [{'v': 'B'}, {'v': 'B'}])

    def test_commit_boundaries_are_atomic(self):
        batch = self.w.ingest('r', [{}, {}])
        plan = self.register({'output': [binding('v', call('next_ticket'))]})
        old = self.w.run(batch.batch_id, self.constant('old'))
        for point, after in (('stage.append', 1), ('publication.rows', 0),
                             ('publication.state', 0), ('run.before_commit', 0)):
            with self.subTest(point=point):
                self.w.database.inject_once(point, after)
                context = FunctionContext()
                with self.assertRaises(StorageFailure) as caught:
                    self.w.run(batch.batch_id, plan, context)
                failed_id = caught.exception.run_id
                self.assertIs(self.w.runs.get(failed_id).state, RunState.FAILED)
                self.assert_no_output(self.w, failed_id)
                self.assertEqual(len(context.trace), 2)
                self.assertEqual(self.w.read_result(old.run_id).rows[0].values, {'value': 'old'})
                retry = self.w.run(batch.batch_id, plan, FunctionContext())
                self.assertNotEqual(retry.run_id, failed_id)
                self.assertEqual([r.values['v'] for r in
                                  self.w.read_result(retry.run_id).rows], [1, 2])

    def test_failure_record_storage_error_leaves_unreadable_created(self):
        batch = self.w.ingest('r', [{}])
        plan = self.register({'output': [binding('bad', call('fail', literal('bad')))]})
        self.w.database.inject_once('run.failure')
        with self.assertRaises(StorageFailure) as caught:
            self.w.run(batch.batch_id, plan)
        run_id = caught.exception.run_id
        self.assertIs(self.w.runs.get(run_id).state, RunState.CREATED)
        self.assert_no_output(self.w, run_id)

    def test_exact_read_zero_rows_and_terminal_states(self):
        batch = self.w.ingest('r', [])
        plan = self.constant(1)
        run = self.w.run(batch.batch_id, plan)
        self.assertEqual(self.w.read_result(run.run_id).row_count, 0)
        self.assertEqual(self.w.read_result(run.run_id).rows, ())
        with self.assertRaises(ResultUnavailable):
            self.w.read_result('missing')
        before = self.w.database.execute('SELECT count(*) FROM runs').fetchone()[0]
        for batch_id, revision in (('missing', plan), (batch.batch_id, 'missing')):
            with self.assertRaises(KeyError):
                self.w.run(batch_id, revision)
        self.assertEqual(self.w.database.execute('SELECT count(*) FROM runs').fetchone()[0], before)
        with self.w.database.transaction():
            with self.assertRaises(RunStateError):
                self.w.runs.start(run.run_id)

    def test_result_integrity_is_checked(self):
        from warehouse.results.publication import PublicationIntegrityError
        batch = self.w.ingest('r', [{}, {}])
        run = self.w.run(batch.batch_id, self.constant(1))
        with self.w.database.transaction():
            self.w.database.execute('DELETE FROM results WHERE run_id=? AND output_index=1',
                                    (run.run_id,))
        with self.assertRaises(PublicationIntegrityError):
            self.w.read_result(run.run_id)

    def test_failure_summary_commit_rollback(self):
        batch = self.w.ingest('r', [{}])
        plan = self.register({'output': [binding('bad', call('fail', literal('bad')))]})
        self.w.database.inject_once('run.failure.before_commit')
        with self.assertRaises(StorageFailure) as caught:
            self.w.run(batch.batch_id, plan)
        self.assertIs(self.w.runs.get(caught.exception.run_id).state, RunState.CREATED)
        self.assert_no_output(self.w, caught.exception.run_id)
