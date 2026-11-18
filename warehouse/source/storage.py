import json
import uuid
from warehouse.source.coordinates import SourceCoordinate


class SourceStore:
    def __init__(self, database):
        self.db = database

    def find_receipt(self, request_id):
        return self.db.execute('SELECT * FROM batches WHERE request_id=?',
                               (request_id,)).fetchone()

    def commit_batch(self, request_id, canonical, records):
        batch_id, receipt = uuid.uuid4().hex, uuid.uuid4().hex
        self.db.execute('INSERT INTO batches VALUES(?,?,?,?,?)',
                        (batch_id, request_id, canonical, len(records), receipt))
        for index, record in enumerate(records):
            self.db.checkpoint('source.record')
            self.db.execute('INSERT INTO records VALUES(?,?,?)',
                            (batch_id, index, json.dumps(record, allow_nan=False)))
        return {'batch_id': batch_id, 'record_count': len(records), 'receipt': receipt}

    def read_batch(self, batch_id):
        batch = self.db.execute('SELECT record_count FROM batches WHERE batch_id=?',
                                (batch_id,)).fetchone()
        if batch is None:
            raise KeyError(f'unknown batch: {batch_id}')
        rows = self.db.execute(
            'SELECT record_index,payload FROM records WHERE batch_id=? ORDER BY record_index',
            (batch_id,)).fetchall()
        if len(rows) != batch['record_count'] or any(
                row['record_index'] != i for i, row in enumerate(rows)):
            from warehouse.results.database import StorageFailure
            raise StorageFailure('source batch is incomplete')
        return tuple((SourceCoordinate(batch_id, row['record_index']),
                      json.loads(row['payload'])) for row in rows)
