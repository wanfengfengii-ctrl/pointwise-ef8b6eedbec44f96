import unittest
from warehouse import Warehouse, FunctionContext
from warehouse.expressions.errors import EvaluationError, TypeMismatch
from warehouse.source.coordinates import encode_coordinate
from samples import literal, field, ref, call, binding, expand, operation
from tests.oracle import interpret


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()
        self.addCleanup(self.w.close)

    def check_case(self, records, definition):
        batch = self.w.ingest(str(len(self.w.plan_store.list_revisions())), records)
        plan = self.w.register_plan('p', definition)
        context = FunctionContext()
        expected = interpret(records, definition, batch.batch_id)
        try:
            run = self.w.run(batch.batch_id, plan.plan_revision, context)
        except EvaluationError as error:
            actual = {'rows': [], 'trace': context.trace, 'error': error.to_data()}
        else:
            result = self.w.read_result(run.run_id)
            actual = {'rows': [{'output_index': row.output_index,
                                'coordinate': encode_coordinate(row.coordinate),
                                'values': row.values} for row in result.rows],
                      'trace': context.trace, 'error': None}
        self.assertEqual(actual, expected)
        return actual

    def test_parent_binding_shared_across_expand(self):
        result = self.check_case([{'a': [1, 2]}, {'a': [1, 2]}], {
            'bindings': [binding('ticket', call('next_ticket'))],
            'output': [binding('ticket', ref('ticket')), binding('again', ref('ticket'))],
            'expand': expand(field('root', 'a'))})
        self.assertEqual([r['values']['ticket'] for r in result['rows']], [1, 1, 2, 2])
        self.assertEqual(len(result['trace']), 2)

    def test_nested_elements_own_inner_bindings(self):
        plan = {
            'bindings': [binding('t', call('next_ticket'))],
            'output': [binding('parent', ref('t'))],
            'expand': expand(field('root', 'a'), {
                'bindings': [binding('t', call('next_ticket'))],
                'output': [binding('child', ref('t'))],
                'expand': expand(field('item'), {
                    'bindings': [binding('t', call('next_ticket'))],
                    'output': [binding('leaf', ref('t')), binding('value', field('leaf'))]
                }, alias='leaf', mode='left')})}
        result = self.check_case([{'a': [[8, 8], []]}, {'a': [[8, 8], []]}], plan)
        self.assertEqual([r['values'] for r in result['rows']], [
            {'parent': 1, 'child': 2, 'leaf': 3, 'value': 8},
            {'parent': 1, 'child': 2, 'leaf': 4, 'value': 8},
            {'parent': 1, 'child': 5, 'leaf': 6, 'value': None},
            {'parent': 7, 'child': 8, 'leaf': 9, 'value': 8},
            {'parent': 7, 'child': 8, 'leaf': 10, 'value': 8},
            {'parent': 7, 'child': 11, 'leaf': 12, 'value': None}])
        self.assertEqual([r['output_index'] for r in result['rows']], list(range(6)))

    def test_left_empty_and_real_null_are_distinct(self):
        records = [{'a': []}, {'a': [None]}]
        for mode in ('inner', 'left'):
            result = self.check_case(records, {'expand': expand(field('root', 'a'), {
                'output': [binding('value', field('item'))]}, mode=mode)})
            indices = [r['coordinate']['elements'][0]['element_index'] for r in result['rows']]
            self.assertEqual(indices, [0] if mode == 'inner' else [None, 0])
        result = self.check_case([{'a': []}], {
            'expand': expand(field('root', 'a'), {'where': literal(False),
                'output': [binding('bad', call('fail', literal('unreachable')))]}, mode='left')})
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['trace'], [])

    def test_filter_order_and_first_demand_order(self):
        result = self.check_case([{'ok': False}, {'ok': True, 'a': [0, 0]}], {
            'where': field('root', 'ok'),
            'bindings': [binding('b', call('next_ticket')),
                         binding('unused', call('fail', literal('unused'))),
                         binding('a', call('next_ticket'))],
            'output': [binding('first', ref('a')), binding('second', ref('b'))],
            'expand': expand(field('root', 'a'))})
        self.assertEqual([r['values'] for r in result['rows']],
                         [{'first': 1, 'second': 2}, {'first': 1, 'second': 2}])
        self.assertEqual([t['function'] for t in result['trace']], ['next_ticket'] * 2)
        self.check_case([{}], {'where': literal(False), 'expand': expand(
            call('fail', literal('not needed')))})
        self.check_case([{'a': []}], {
            'output': [binding('unused', call('fail', literal('no leaf')))],
            'expand': expand(field('root', 'a'))})

    def test_non_array_expand_and_zero_rows(self):
        result = self.check_case([{'a': None}], {'expand': expand(field('root', 'a'))})
        self.assertEqual(result['error']['type'], TypeMismatch.__name__)
        for records, plan in (([], {}), ([{}], {'where': literal(False)}),
                              ([{'a': []}], {'expand': expand(field('root', 'a'))})):
            result = self.check_case(records, plan)
            self.assertIsNone(result['error'])
            self.assertEqual(result['rows'], [])

    def test_differential_finite_combinations(self):
        for mode in ('inner', 'left'):
            for array in ([], [0], [0, 0], [0, 1, 0]):
                for selected in (False, True):
                    with self.subTest(mode=mode, array=array, selected=selected):
                        self.check_case([{'a': array, 'selected': selected}] * 2, {
                            'where': field('root', 'selected'),
                            'bindings': [binding('t', call('next_ticket'))],
                            'output': [binding('p', ref('t'))],
                            'expand': expand(field('root', 'a'), {
                                'bindings': [binding('u', call('next_ticket'))],
                                'output': [binding('u', ref('u'))]}, mode=mode)})

    def test_ancestor_reference_from_child_and_error_differential(self):
        result = self.check_case([{'a': [0, 0]}, {'a': [0, 0]}], {
            'bindings': [binding('p', call('next_ticket'))],
            'expand': expand(field('root', 'a'), {
                'output': [binding('parent', ref('p'))]})})
        self.assertEqual([r['values']['parent'] for r in result['rows']], [1, 1, 2, 2])
        self.check_case([{'a': [False, True]}], {
            'bindings': [binding('bad', call('fail', literal('late')))],
            'expand': expand(field('root', 'a'), {'output': [binding('v',
                operation('if', field('item'), ref('bad'), literal(0)))]})})
        self.check_case([{}], {'where': literal(1)})
        self.check_case([{'a': [None]}], {'expand': expand(field('root', 'a'),
            {'output': [binding('v', field('item', 'missing'))]}, mode='left')})
