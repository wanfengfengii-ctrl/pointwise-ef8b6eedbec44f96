import json
from dataclasses import asdict
from warehouse import Warehouse, FunctionContext
from warehouse.expressions.errors import FunctionFailure

RECORDS = [{'station': 'A', 'items': [{'v': 3}, {'v': 3}]},
           {'station': 'A', 'items': [{'v': 3}, {'v': 3}]}]


def literal(value):
    return {'op': 'literal', 'value': value}


def field(base, *path):
    return {'op': 'field', 'base': base, 'path': list(path)}


def ref(name):
    return {'op': 'ref', 'name': name}


def call(name, *args):
    return {'op': 'call', 'name': name, 'args': list(args)}


def operation(op, *args):
    return {'op': op, 'args': list(args)}


def binding(name, expr):
    return {'name': name, 'expr': expr}


def expand(expr, child=None, alias='item', mode='inner'):
    return {'expr': expr, 'alias': alias, 'mode': mode,
            'scope': {} if child is None else child}


def ownership_plan():
    return {
        'bindings': [binding('source_ticket', call('next_ticket'))],
        'output': [binding('source_ticket', ref('source_ticket')),
                   binding('station', field('root', 'station'))],
        'expand': expand(field('root', 'items'), {
            'bindings': [binding('element_ticket', call('next_ticket'))],
            'output': [binding('element_ticket', ref('element_ticket')),
                       binding('v', field('item', 'v'))]})}


def demo():
    with Warehouse() as warehouse:
        batch = warehouse.ingest('sample', RECORDS)
        plan = warehouse.register_plan('detail', ownership_plan())
        context = FunctionContext()
        receipt = warehouse.run(batch.batch_id, plan.plan_revision, context)
        print(json.dumps({'result': asdict(warehouse.read_result(receipt.run_id)),
                          'trace': context.trace}, ensure_ascii=False))
        bad = warehouse.register_plan('detail', {
            'output': [binding('bad', call('fail', literal('quality rejected')))]})
        try:
            warehouse.run(batch.batch_id, bad.plan_revision)
        except FunctionFailure as error:
            print(json.dumps({'failed': error.to_data(),
                              'state': warehouse.runs.get(error.run_id).state.value,
                              'old_row_count': warehouse.read_result(receipt.run_id).row_count}))


if __name__ == '__main__':
    demo()
