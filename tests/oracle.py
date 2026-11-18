import copy
import math


class OracleFailure(Exception):
    def __init__(self, kind, code, message):
        super().__init__(message)
        self.kind, self.code, self.location = kind, code, None


def interpret(records, definition, batch_id, start=1):
    plan = copy.deepcopy(definition)
    counter = 0
    def identify(scope):
        nonlocal counter
        scope['_id'] = f's{counter}'
        counter += 1
        if 'expand' in scope:
            identify(scope['expand']['scope'])
    identify(plan)
    trace, rows = [], []
    ticket = start
    empty = object()

    def error(kind, message):
        codes = {'TypeMismatch': 'TYPE_MISMATCH', 'MissingField': 'MISSING_FIELD',
                 'FunctionFailure': 'FUNCTION_FAILURE', 'BindingCycleError': 'BINDING_CYCLE'}
        raise OracleFailure(kind, codes[kind], message)

    def boolean(value):
        if type(value) is not bool:
            error('TypeMismatch', 'expected boolean')
        return value

    def number(value):
        if type(value) not in (int, float):
            error('TypeMismatch', 'expected non-boolean number')
        return value

    def equal(a, b):
        if type(a) is not type(b):
            return False
        if type(a) is list:
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        if type(a) is dict:
            return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        return a == b

    def evaluate(expr, env, path, demand):
        nonlocal ticket
        try:
            op = expr['op']
            def arg(index):
                return evaluate(expr['args'][index], env, f'{path}.args[{index}]', demand)
            if op == 'literal':
                return expr['value']
            if op == 'field':
                owner = env
                if expr['base'] == 'root':
                    value = env['root']
                else:
                    while owner['alias'] != expr['base']:
                        owner = owner['parent']
                    value = owner['value']
                if value is empty:
                    return None
                for part in expr['path']:
                    if type(part) is str:
                        if type(value) is not dict:
                            error('TypeMismatch', 'field key requires object')
                        if part not in value:
                            error('MissingField', f'missing field: {part}')
                        value = value[part]
                    else:
                        if type(value) is not list:
                            error('TypeMismatch', 'field index requires array')
                        if part < 0 or part >= len(value):
                            error('MissingField', f'index out of range: {part}')
                        value = value[part]
                return value
            if op == 'ref':
                owner = env
                while expr['name'] not in owner['bindings']:
                    owner = owner['parent']
                name = expr['name']
                if name not in owner['cache']:
                    item, i = owner['bindings'][name]
                    try:
                        value = evaluate(item['expr'], owner,
                                         f"{owner['path']}.bindings[{i}].expr", demand)
                        owner['cache'][name] = (True, value)
                    except OracleFailure as failure:
                        owner['cache'][name] = (False, failure)
                ok, value = owner['cache'][name]
                if not ok:
                    raise value
                return value
            if op == 'if':
                return arg(1) if boolean(arg(0)) else arg(2)
            if op == 'and':
                return boolean(arg(1)) if boolean(arg(0)) else False
            if op == 'or':
                return True if boolean(arg(0)) else boolean(arg(1))
            values = [arg(i) for i in range(len(expr['args']))]
            if op == 'call':
                name = expr['name']
                trace.append({'function': name, 'args': copy.deepcopy(values),
                              'coordinate': copy.deepcopy(env['coord'])})
                if name == 'next_ticket':
                    ticket += 1
                    return ticket - 1
                if name == 'fail':
                    if type(values[0]) is not str:
                        error('TypeMismatch', 'fail expects a string')
                    error('FunctionFailure', values[0])
                if type(values[0]) not in (str, list, dict):
                    error('TypeMismatch', 'length expects string, array or object')
                return len(values[0])
            if op == 'eq':
                return equal(*values)
            if op == 'lt':
                return number(values[0]) < number(values[1])
            try:
                result = number(values[0]) + number(values[1])
            except OverflowError:
                error('TypeMismatch', 'numeric overflow')
            if type(result) is float and not math.isfinite(result):
                error('TypeMismatch', 'numeric overflow')
            return result
        except OracleFailure as failure:
            if failure.location is None:
                failure.location = {'expression': path, 'coordinate': copy.deepcopy(demand)}
            raise

    def enter(scope, parent, root, coord, path, alias=None, value=None):
        return {'scope': scope, 'parent': parent, 'root': root, 'coord': coord,
                'path': path, 'alias': alias, 'value': value, 'cache': {},
                'bindings': {item['name']: (item, i)
                             for i, item in enumerate(scope.get('bindings', []))}}

    def walk(env, ancestors):
        scope, path = env['scope'], env['path']
        if 'where' in scope:
            selected = evaluate(scope['where'], env, path + '.where', env['coord'])
            try:
                if not boolean(selected):
                    return
            except OracleFailure as failure:
                failure.location = {'expression': path + '.where',
                                    'coordinate': copy.deepcopy(env['coord'])}
                raise
        lineage = ancestors + [env]
        if 'expand' in scope:
            exp = scope['expand']
            array = evaluate(exp['expr'], env, path + '.expand.expr', env['coord'])
            if type(array) is not list:
                failure = OracleFailure('TypeMismatch', 'TYPE_MISMATCH', 'expand requires array')
                failure.location = {'expression': path + '.expand.expr',
                                    'coordinate': copy.deepcopy(env['coord'])}
                raise failure
            occurrences = list(enumerate(array))
            if not array and exp['mode'] == 'left':
                occurrences = [(None, empty)]
            for index, value in occurrences:
                coord = copy.deepcopy(env['coord'])
                coord['elements'].append({'scope_id': exp['scope']['_id'],
                                          'element_index': index})
                walk(enter(exp['scope'], env, env['root'], coord, path + '.expand.scope',
                           exp['alias'], value), lineage)
        else:
            values = {}
            for owner in lineage:
                for i, item in enumerate(owner['scope'].get('output', [])):
                    values[item['name']] = evaluate(item['expr'], owner,
                        f"{owner['path']}.output[{i}].expr", env['coord'])
            rows.append({'output_index': len(rows),
                         'coordinate': copy.deepcopy(env['coord']), 'values': values})
    try:
        for index, record in enumerate(records):
            coordinate = {'batch_id': batch_id, 'record_index': index, 'elements': []}
            walk(enter(plan, None, record, coordinate, '$'), [])
    except OracleFailure as failure:
        return {'rows': [], 'trace': trace,
                'error': {'type': failure.kind, 'code': failure.code,
                          'message': str(failure), 'location': failure.location}}
    return {'rows': rows, 'trace': trace, 'error': None}
