import json
import unittest

from samples import binding, call, expand, field, literal, operation, ref
from warehouse import FunctionContext, Warehouse
from warehouse.expressions.errors import EvaluationError
from warehouse.planning.model import PlanValidationError
from warehouse.source.coordinates import encode_coordinate


MARKER = 'BINDING_OWNERSHIP_MISMATCH'


def audit(shadowed):
    records = [{'values': [7, 7]}, {'values': [7, 7]}]
    parent = 'fee' if shadowed else 'serial'
    bindings = [binding('serial', call('next_ticket'))]
    if shadowed:
        bindings.insert(0, binding('fee', ref('serial')))
    child = {'output': [binding('value', field('item'))]}
    if shadowed:
        child['bindings'] = [binding('serial', operation('add', ref('fee'), literal(100)))]
        child['output'].append(binding('item_fee', ref('serial')))
    definition = {
        'bindings': bindings,
        'output': [binding('source_fee', ref(parent))],
        'expand': expand(field('root', 'values'), child),
    }
    with Warehouse() as warehouse:
        batch = warehouse.ingest('incident', records)
        context = FunctionContext()

        def coordinate(source, elements):
            return {'batch_id': batch.batch_id, 'record_index': source, 'elements': elements}

        rows = []
        trace = []
        for source, fee in enumerate((1, 2)):
            trace.append({'function': 'next_ticket', 'args': [],
                          'coordinate': coordinate(source, [])})
            for element in (0, 1):
                values = {'source_fee': fee, 'value': 7}
                if shadowed:
                    values['item_fee'] = fee + 100
                location = coordinate(source, [{'scope_id': 's1', 'element_index': element}])
                rows.append({'output_index': len(rows), 'coordinate': location, 'values': values})
        expected = {'rows': rows, 'trace': trace}
        try:
            plan = warehouse.register_plan('fees', definition)
        except PlanValidationError as error:
            return {'registration_error': str(error)}, expected
        try:
            run = warehouse.run(batch.batch_id, plan.plan_revision, context)
        except EvaluationError as error:
            return {'evaluation_error': error.to_data(), 'trace': context.trace}, expected
        result = warehouse.read_result(run.run_id)
        actual = {'rows': [{'output_index': row.output_index,
                            'coordinate': encode_coordinate(row.coordinate), 'values': row.values}
                           for row in result.rows], 'trace': context.trace}
        return actual, expected


class BindingIncidentTests(unittest.TestCase):
    def test_duplicate_source_fee(self):
        actual, expected = audit(False)
        self.assertEqual(actual, expected)

    def test_shadowed_serial_remains_lexical(self):
        actual, expected = audit(True)
        self.assertEqual(actual, expected)


def main():
    failed = False
    for name, shadowed in (('repeated-sources', False), ('shadowed-serial', True)):
        actual, expected = audit(shadowed)
        matched = actual == expected
        failed |= not matched
        print(json.dumps({'case': name, 'matched': matched, 'actual': actual,
                          'expected': expected}, ensure_ascii=False, sort_keys=True))
    if failed:
        print(MARKER)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
