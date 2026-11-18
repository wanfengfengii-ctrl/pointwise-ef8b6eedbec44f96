from dataclasses import dataclass
from warehouse.expressions.errors import FunctionFailure, TypeMismatch
from warehouse.source.coordinates import encode_coordinate


def next_ticket(context, args):
    value = context._next
    context._next += 1
    return value


def fail(context, args):
    if type(args[0]) is not str:
        raise TypeMismatch('fail expects a string')
    raise FunctionFailure(args[0])


def length(context, args):
    if type(args[0]) not in (str, list, dict):
        raise TypeMismatch('length expects string, array or object')
    return len(args[0])


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    arity: int
    argument_rule: str
    effect: str
    implementation: object


class FunctionRegistry:
    def __init__(self, specs):
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name):
        try:
            return self._specs[name]
        except (KeyError, TypeError):
            raise ValueError(f'unknown function: {name}') from None


def default_registry():
    return FunctionRegistry((
        FunctionSpec('next_ticket', 0, 'none', 'allocate', next_ticket),
        FunctionSpec('fail', 1, 'string', 'raise', fail),
        FunctionSpec('length', 1, 'string|array|object', 'pure', length),
    ))


class FunctionContext:
    def __init__(self, start=1):
        if type(start) is not int:
            raise ValueError('ticket start must be an integer')
        self._next = start
        self._trace = []
        self.registry = default_registry()

    @property
    def trace(self):
        import copy
        return copy.deepcopy(self._trace)

    def invoke(self, name, args, coordinate):
        from warehouse.source.validation import snapshot_json_value
        spec = self.registry.get(name)
        if len(args) != spec.arity:
            raise TypeMismatch(f'{name}: wrong argument count')
        self._trace.append({'function': name,
                            'args': snapshot_json_value(list(args)),
                            'coordinate': encode_coordinate(coordinate)})
        return spec.implementation(self, args)
