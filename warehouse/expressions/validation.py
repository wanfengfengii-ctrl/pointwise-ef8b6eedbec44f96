from warehouse.expressions.model import Expression, FieldPath
from warehouse.expressions.functions import default_registry
from warehouse.source.validation import snapshot_json_value, SourceValidationError


class ExpressionValidationError(ValueError):
    pass


def validate_expression(data, location='$'):
    def reject(message):
        raise ExpressionValidationError(f'{location}: {message}')
    if type(data) is not dict or type(data.get('op')) is not str:
        reject('expression requires op')
    op = data['op']
    allowed = {'literal': {'op', 'value'}, 'field': {'op', 'base', 'path'},
               'ref': {'op', 'name'}, 'call': {'op', 'name', 'args'},
               **{name: {'op', 'args'} for name in ('if', 'and', 'or', 'eq', 'lt', 'add')}}
    if op not in allowed or set(data) != allowed[op]:
        reject('unknown operation or incorrect attributes')
    if op == 'literal':
        try:
            value = snapshot_json_value(data['value'])
        except SourceValidationError as error:
            reject(str(error))
        return Expression(op, value, location=location)
    if op == 'field':
        if type(data['base']) is not str or not data['base']:
            reject('field base must be nonempty')
        path = data['path']
        if type(path) is not list or any(type(p) not in (str, int) for p in path):
            reject('path requires string keys or integer indices')
        return Expression(op, FieldPath(data['base'], tuple(path)), location=location)
    if op == 'ref':
        if type(data['name']) is not str or not data['name']:
            reject('reference requires a name')
        return Expression(op, data['name'], location=location)
    args = data['args']
    if type(args) is not list:
        reject('args must be an array')
    value = None
    if op == 'call':
        try:
            spec = default_registry().get(data['name'])
        except ValueError as error:
            reject(str(error))
        arity, value = spec.arity, spec.name
    else:
        arity = 3 if op == 'if' else 2
    if len(args) != arity:
        reject('wrong operand count')
    parsed = tuple(validate_expression(arg, f'{location}.args[{i}]')
                   for i, arg in enumerate(args))
    return Expression(op, value, parsed, location)


def collect_binding_references(expr):
    refs = [expr.value] if expr.op == 'ref' else []
    for arg in expr.args:
        refs.extend(collect_binding_references(arg))
    return refs
