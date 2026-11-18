import math
from warehouse.expressions.errors import (
    EvaluationError, ErrorLocation, MissingField, TypeMismatch, attach_first_location)


def require_boolean(value):
    if type(value) is not bool:
        raise TypeMismatch('expected boolean')
    return value


def _number(value):
    if type(value) not in (int, float):
        raise TypeMismatch('expected non-boolean number')
    return value


def compare_values(left, right, op='eq'):
    if op == 'lt':
        return _number(left) < _number(right)
    if type(left) is not type(right):
        return False
    if type(left) is list:
        return len(left) == len(right) and all(
            compare_values(a, b) for a, b in zip(left, right))
    if type(left) is dict:
        return left.keys() == right.keys() and all(
            compare_values(left[key], right[key]) for key in left)
    return left == right


def add_values(left, right):
    try:
        result = _number(left) + _number(right)
    except OverflowError:
        raise TypeMismatch('numeric overflow') from None
    if type(result) is float and not math.isfinite(result):
        raise TypeMismatch('numeric overflow')
    return result


def read_field(environment, field):
    from warehouse.execution.environments import EMPTY_SIDE
    value = environment.read_base(field.base)
    if value is EMPTY_SIDE:
        return None
    for part in field.path:
        if type(part) is str:
            if type(value) is not dict:
                raise TypeMismatch('field key requires object')
            if part not in value:
                raise MissingField(f'missing field: {part}')
            value = value[part]
        else:
            if type(value) is not list:
                raise TypeMismatch('field index requires array')
            if part < 0 or part >= len(value):
                raise MissingField(f'index out of range: {part}')
            value = value[part]
    return value


def evaluate_expression(expr, environment, context, demand_coordinate=None):
    demand = environment.coordinate if demand_coordinate is None else demand_coordinate
    def evaluate(arg):
        return evaluate_expression(arg, environment, context, demand)
    try:
        if expr.op == 'literal':
            return expr.value
        if expr.op == 'field':
            return read_field(environment, expr.value)
        if expr.op == 'ref':
            return environment.resolve_binding(expr.value, context, demand)
        if expr.op == 'if':
            condition = require_boolean(evaluate(expr.args[0]))
            return evaluate(expr.args[1] if condition else expr.args[2])
        if expr.op == 'and':
            left = require_boolean(evaluate(expr.args[0]))
            return require_boolean(evaluate(expr.args[1])) if left else False
        if expr.op == 'or':
            left = require_boolean(evaluate(expr.args[0]))
            return True if left else require_boolean(evaluate(expr.args[1]))
        args = [evaluate(arg) for arg in expr.args]
        if expr.op == 'call':
            return context.invoke(expr.value, args, environment.coordinate)
        if expr.op == 'eq':
            return compare_values(*args)
        if expr.op == 'lt':
            return compare_values(*args, op='lt')
        if expr.op == 'add':
            return add_values(*args)
        raise TypeMismatch(f'unknown compiled operation: {expr.op}')
    except EvaluationError as error:
        raise attach_first_location(error, ErrorLocation(expr.location, demand))
