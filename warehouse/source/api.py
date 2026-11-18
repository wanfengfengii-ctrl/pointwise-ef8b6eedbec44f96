from dataclasses import dataclass
from warehouse.source.validation import validate_records, canonical_payload


class IngestConflict(ValueError):
    pass


@dataclass(frozen=True)
class IngestReceipt:
    batch_id: str
    record_count: int
    receipt: str


class SourceService:
    def __init__(self, database, store):
        self.db, self.store = database, store

    def ingest(self, request_id, records):
        if type(request_id) is not str or not request_id.strip():
            raise ValueError('request_id must be a nonempty string')
        snapshot = validate_records(records)
        canonical = canonical_payload(snapshot)
        with self.db.transaction('source.before_commit'):
            previous = self.store.find_receipt(request_id)
            if previous is not None:
                if previous['canonical'] != canonical:
                    raise IngestConflict('request_id already denotes different content')
                saved = previous
            else:
                saved = self.store.commit_batch(request_id, canonical, snapshot)
        return IngestReceipt(saved['batch_id'], saved['record_count'], saved['receipt'])
