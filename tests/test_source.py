import tempfile
import unittest
from pathlib import Path
from warehouse import Warehouse
from warehouse.source.api import IngestConflict
from warehouse.source.validation import SourceValidationError
from warehouse.results.database import StorageFailure


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()
        self.addCleanup(self.w.close)

    def counts(self):
        return tuple(self.w.database.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                     for table in ('batches', 'records'))

    def test_equal_records_keep_distinct_coordinates(self):
        rows = [{'x': [1, 2]}, {'x': [1, 2]}]
        first = self.w.ingest('r', rows)
        self.assertEqual(first, self.w.ingest('r', rows))
        stored = self.w.source_store.read_batch(first.batch_id)
        self.assertEqual(first.record_count, 2)
        self.assertEqual([p.record_index for p, _ in stored], [0, 1])
        self.assertEqual(self.counts(), (1, 2))

    def test_invalid_middle_record_rejects_batch(self):
        with self.assertRaises(SourceValidationError):
            self.w.ingest('r', [{'x': 1}, {'x': object()}])
        self.assertEqual(self.counts(), (0, 0))
        self.assertIsNone(self.w.source_store.find_receipt('r'))

    def test_typed_replay_and_snapshot(self):
        rows = [{'b': [True, 1, 1.0], 'a': {'x': 2}}]
        saved = self.w.ingest('r', rows)
        self.assertEqual(saved, self.w.ingest('r', [{'a': {'x': 2}, 'b': [True, 1, 1.0]}]))
        for changed in ([1, 1, 1.0], [True, 1.0, 1], [1.0, 1, True]):
            with self.assertRaises(IngestConflict):
                self.w.ingest('r', [{'a': {'x': 2}, 'b': changed}])
        rows[0]['a']['x'] = 99
        self.assertEqual(self.w.source_store.read_batch(saved.batch_id)[0][1]['a']['x'], 2)
        other = self.w.ingest('other', [{'a': {'x': 2}, 'b': [True, 1, 1.0]}])
        self.assertNotEqual(saved.batch_id, other.batch_id)

    def test_cyclic_and_invalid_values(self):
        cycle = []
        cycle.append(cycle)
        for value in (cycle, float('nan'), float('inf'), {1: 'bad'}, (1,)):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(SourceValidationError):
                    self.w.ingest('r', [{'x': value}])
                self.assertEqual(self.counts(), (0, 0))
        for request in ('', ' ', None):
            with self.assertRaises(ValueError):
                self.w.ingest(request, [])

    def test_storage_reject_is_atomic(self):
        for point, after in (('source.record', 1), ('source.before_commit', 0)):
            self.w.database.inject_once(point, after)
            with self.assertRaises(StorageFailure):
                self.w.ingest('r', [{'x': 1}, {'x': 2}])
            self.assertEqual(self.counts(), (0, 0))
        accepted = self.w.ingest('r', [{'x': 1}, {'x': 2}])
        self.assertEqual(accepted.record_count, 2)

    def test_reopen_coordinates(self):
        with tempfile.TemporaryDirectory(prefix='warehouse-') as directory:
            path = Path(directory) / 'source.sqlite'
            with Warehouse(path) as first:
                first.database.inject_once('source.record', 1)
                with self.assertRaises(StorageFailure):
                    first.ingest('failed', [{'x': 1}, {'x': 2}])
                saved = first.ingest('r', [{'x': 1}, {'x': 1}])
            with Warehouse(path) as reopened:
                self.assertIsNone(reopened.source_store.find_receipt('failed'))
                self.assertEqual(saved, reopened.ingest('r', [{'x': 1}, {'x': 1}]))
                self.assertEqual([p.record_index for p, _ in
                                  reopened.source_store.read_batch(saved.batch_id)], [0, 1])
