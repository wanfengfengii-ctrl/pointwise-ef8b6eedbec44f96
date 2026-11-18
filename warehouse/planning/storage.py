import json
import uuid
from warehouse.planning.model import PlanRevision
from warehouse.planning.compile import compile_plan
from warehouse.source.validation import canonical_payload


class PlanStore:
    def __init__(self, database):
        self.db = database

    def save_revision(self, name, definition):
        revision = uuid.uuid4().hex
        with self.db.transaction('plan.before_commit'):
            self.db.execute('INSERT INTO plans VALUES(?,?,?)',
                            (revision, name, canonical_payload(definition)))
        return revision

    def load_revision(self, revision):
        row = self.db.execute('SELECT * FROM plans WHERE revision=?', (revision,)).fetchone()
        if row is None:
            raise KeyError(f'unknown plan revision: {revision}')
        definition = json.loads(row['definition'])
        return PlanRevision(revision, row['name'], definition, compile_plan(definition))

    def list_revisions(self, name=None):
        if name is None:
            rows = self.db.execute('SELECT revision FROM plans ORDER BY rowid')
        else:
            rows = self.db.execute('SELECT revision FROM plans WHERE name=? ORDER BY rowid',
                                   (name,))
        return tuple(row['revision'] for row in rows)
