import unittest
from warehouse import Warehouse, FunctionContext
from warehouse.execution.bindings import BindingCell, BindingState
from warehouse.execution.environments import Environment
from warehouse.expressions.errors import (
    FunctionFailure, TypeMismatch, BindingCycleError, ErrorLocation)
from warehouse.expressions.semantics import evaluate_expression
from warehouse.planning.compile import compile_plan
from warehouse.source.coordinates import SourceCoordinate
from samples import literal, field, ref, call, binding, operation
from tests.oracle import interpret


class ExpressionTests(unittest.TestCase):
    def run_expression(self, expr, record=None, bindings=()):
        with Warehouse() as warehouse:
            record = {} if record is None else record
            batch = warehouse.ingest('r', [record])
            definition = {'bindings': list(bindings), 'output': [binding('value', expr)]}
            plan = warehouse.register_plan('p', definition)
            context = FunctionContext()
            expected = interpret([record], definition, batch.batch_id)
            if expected['error']:
                with self.assertRaises(Exception) as caught:
                    warehouse.run(batch.batch_id, plan.plan_revision, context)
                self.assertEqual(caught.exception.to_data(), expected['error'])
                value = expected['error']
            else:
                run = warehouse.run(batch.batch_id, plan.plan_revision, context)
                value = warehouse.read_result(run.run_id).rows[0].values['value']
                self.assertEqual(value, expected['rows'][0]['values']['value'])
            self.assertEqual(context.trace, expected['trace'])
            return value, context.trace

    def test_unused_branch_has_no_effect(self):
        value, trace = self.run_expression(
            operation('if', literal(False),
                      call('fail', call('next_ticket')), call('next_ticket')),
            bindings=[binding('unused', call('fail', literal('unused')))])
        self.assertEqual(value, 1)
        self.assertEqual([t['function'] for t in trace], ['next_ticket'])
        for op, left, expected in (('and', False, False), ('or', True, True)):
            value, trace = self.run_expression(
                operation(op, literal(left), call('fail', literal('unused'))))
            self.assertEqual(value, expected)
            self.assertEqual(trace, [])

    def test_strict_types_and_field_paths(self):
        cases = [
            (operation('if', literal(1), literal(1), literal(2)), 'TypeMismatch'),
            (operation('and', literal(True), literal(1)), 'TypeMismatch'),
            (operation('add', literal(True), literal(1)), 'TypeMismatch'),
            (operation('lt', literal('1'), literal(2)), 'TypeMismatch'),
            (field('root', 'missing'), 'MissingField'),
            (field('root', 'a', 4), 'MissingField'),
            (field('root', 'a', -1), 'MissingField'),
            (field('root', 'a', 0, 'bad'), 'TypeMismatch'),
            (call('length', literal(1)), 'TypeMismatch'),
            (call('fail', literal(1)), 'TypeMismatch')]
        for expr, kind in cases:
            with self.subTest(expr=expr):
                error, _ = self.run_expression(expr, {'a': [3]})
                self.assertEqual(error['type'], kind)
        for a, b in ((True, 1), (1, 1.0), ([True], [1]), ({'x': True}, {'x': 1})):
            value, _ = self.run_expression(operation('eq', literal(a), literal(b)))
            self.assertFalse(value)
        value, _ = self.run_expression(operation('add', literal(10**100), literal(2)))
        self.assertEqual(value, 10**100 + 2)
        value, _ = self.run_expression(call('length', literal([1, 2])))
        self.assertEqual(value, 2)

    def test_argument_order_and_repeated_demand(self):
        value, trace = self.run_expression(operation('add', ref('t'), operation(
            'add', call('next_ticket'), ref('t'))),
            bindings=[binding('t', call('next_ticket'))])
        self.assertEqual(value, 4)
        self.assertEqual(len(trace), 2)

    def test_failure_cache_preserves_original_error(self):
        compiled = compile_plan({'bindings': [
            binding('bad', call('fail', literal('first failure')))]})
        environment = Environment.root(compiled.root, SourceCoordinate('b', 0), {})
        context = FunctionContext()
        cell = environment.cells['s0:bad']
        expr = compiled.root.bindings[0].expr
        first = None
        for _ in range(2):
            with self.assertRaises(FunctionFailure) as caught:
                cell.demand(lambda: evaluate_expression(expr, environment, context),
                            ErrorLocation(expr.location, environment.coordinate))
            if first is None:
                first = caught.exception
            self.assertIs(first, caught.exception)
            self.assertEqual(first.code, 'FUNCTION_FAILURE')
        self.assertEqual(len(context.trace), 1)
        self.assertIs(cell.peek_state(), BindingState.ERROR)
        self.assertEqual(first.location.coordinate, environment.coordinate)

    def test_recursive_cell_reentry_is_rejected(self):
        cell = BindingCell()
        location = ErrorLocation('$', Environment.root(
            compile_plan({}).root, SourceCoordinate('b', 0), {}).coordinate)
        with self.assertRaises(BindingCycleError):
            cell.demand(lambda: cell.demand(lambda: 1, location), location)
        self.assertIs(cell.peek_state(), BindingState.ERROR)
