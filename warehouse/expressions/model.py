from dataclasses import dataclass

ExpressionLocation = str


@dataclass(frozen=True)
class BindingReference:
    binding_id: str
    owner_scope: str
    name: str


@dataclass(frozen=True)
class FieldPath:
    base: str
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class Expression:
    op: str
    value: object = None
    args: tuple = ()
    location: ExpressionLocation = '$'


def parse_expression(data, location='$'):
    from warehouse.expressions.validation import validate_expression
    return validate_expression(data, location)


def expression_to_data(expr):
    if expr.op == 'literal':
        return {'op': 'literal', 'value': expr.value}
    if expr.op == 'field':
        return {'op': 'field', 'base': expr.value.base, 'path': list(expr.value.path)}
    if expr.op == 'ref':
        name = expr.value.name if isinstance(expr.value, BindingReference) else expr.value
        return {'op': 'ref', 'name': name}
    data = {'op': expr.op, 'args': [expression_to_data(arg) for arg in expr.args]}
    if expr.op == 'call':
        data['name'] = expr.value
    return data
