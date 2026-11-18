import copy
import unittest
from warehouse import Warehouse
from warehouse.planning.model import PlanValidationError
from warehouse.results.database import StorageFailure
from samples import literal, field, ref, call, binding, expand


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()
        self.addCleanup(self.w.close)

    def reject(self, definition):
        before = self.w.plan_store.list_revisions()
        with self.assertRaises(PlanValidationError):
            self.w.register_plan('p', definition)
        self.assertEqual(before, self.w.plan_store.list_revisions())

    def test_inner_binding_cannot_escape_scope(self):
        self.reject({'output': [binding('bad', ref('inner'))],
                     'expand': expand(literal([1]), {
                         'bindings': [binding('inner', literal(3))]})})
        self.reject({'output': [binding('bad', field('item'))],
                     'expand': expand(literal([1]))})

    def test_invalid_definition(self):
        invalid = [
            {'unknown': 1},
            {'bindings': [binding('x', literal(1)), binding('x', literal(2))]},
            {'output': [binding('', literal(1))]},
            {'output': [binding('x', {'op': 'unknown'})]},
            {'output': [binding('x', call('unknown'))]},
            {'output': [binding('x', call('length'))]},
            {'output': [binding('x', {'op': 'literal', 'value': 1, 'extra': 2})]},
            {'output': [binding('x', field('missing'))]},
            {'output': [binding('x', literal(1))], 'expand': expand(literal([1]), {
                'output': [binding('x', literal(2))]})},
            {'expand': expand(literal([]), mode='outer')},
        ]
        for definition in invalid:
            with self.subTest(definition=definition):
                self.reject(definition)

    def test_binding_cycles_and_forward_references(self):
        self.reject({'bindings': [binding('a', ref('b')), binding('b', ref('a'))]})
        self.reject({'bindings': [binding('a', ref('a'))]})
        self.reject({'bindings': [binding('a', ref('child'))],
                     'expand': expand(literal([1]), {
                         'bindings': [binding('child', ref('a'))]})})
        plan = self.w.register_plan('p', {
            'bindings': [binding('a', ref('b')), binding('b', literal(7))],
            'output': [binding('x', ref('a'))]})
        batch = self.w.ingest('r', [{}])
        result = self.w.read_result(self.w.run(batch.batch_id, plan.plan_revision).run_id)
        self.assertEqual(result.rows[0].values, {'x': 7})

    def test_shadow_resolution_and_owner_transfer(self):
        plan = self.w.register_plan('p', {
            'bindings': [binding('x', literal(1))],
            'output': [binding('outer', ref('x'))],
            'expand': expand(literal([1]), {
                'bindings': [binding('x', literal(2)), binding('y', ref('x'))],
                'output': [binding('inner', ref('y'))]})})
        root = self.w.plans.get_revision(plan.plan_revision).compiled.root
        self.assertEqual(root.output[0].expr.value.owner_scope, 's0')
        child = root.expand.scope
        self.assertEqual(child.bindings[1].expr.value.binding_id, 's1:x')
        batch = self.w.ingest('r', [{}])
        rows = self.w.read_result(self.w.run(batch.batch_id, plan.plan_revision).run_id).rows
        self.assertEqual(rows[0].values, {'outer': 1, 'inner': 2})

    def test_atomic_revision_and_snapshot(self):
        data = {'output': [binding('x', literal({'v': [1]}))]}
        original = copy.deepcopy(data)
        p1 = self.w.register_plan('p', data)
        data['output'][0]['expr']['value']['v'][0] = 9
        p1.definition['output'][0]['expr']['value']['v'][0] = 8
        self.assertEqual(self.w.plans.get_revision(p1.plan_revision).definition['output'],
                         original['output'])
        self.w.database.inject_once('plan.before_commit')
        with self.assertRaises(StorageFailure):
            self.w.register_plan('p', {'output': [binding('x', literal(2))]})
        self.assertEqual(len(self.w.plan_store.list_revisions()), 1)
        p2 = self.w.register_plan('p', {'output': [binding('x', literal(2))]})
        self.assertNotEqual(p1.plan_revision, p2.plan_revision)
        self.assertEqual(len(self.w.plan_store.list_revisions('p')), 2)
