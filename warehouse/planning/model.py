from dataclasses import dataclass
from warehouse.source.validation import snapshot_json_value, SourceValidationError
from warehouse.expressions.model import parse_expression, expression_to_data


class PlanValidationError(ValueError):
    pass


@dataclass(frozen=True)
class BindingDefinition:
    name: str
    expr: object
    binding_id: str = ''
    owner_scope: str = ''


@dataclass(frozen=True)
class OutputDefinition:
    name: str
    expr: object


@dataclass(frozen=True)
class ExpandDefinition:
    alias: str
    expr: object
    mode: str
    scope: object


@dataclass(frozen=True)
class ScopeDefinition:
    bindings: tuple
    where: object
    expand: ExpandDefinition | None
    output: tuple
    scope_id: str = ''
    row_bindings: tuple = ()


@dataclass(frozen=True)
class PlanDefinition:
    root: ScopeDefinition


@dataclass(frozen=True)
class CompiledPlan:
    root: ScopeDefinition


@dataclass(frozen=True)
class PlanRevision:
    plan_revision: str
    name: str
    definition: dict
    compiled: CompiledPlan


def _name(value, location):
    if type(value) is not str or not value.strip():
        raise PlanValidationError(f'{location}: expected nonempty name')
    return value


def parse_plan_definition(data):
    try:
        data = snapshot_json_value(data)
    except SourceValidationError as error:
        raise PlanValidationError(str(error)) from error

    def scope(raw, location):
        if type(raw) is not dict or set(raw) - {'bindings', 'where', 'expand', 'output'}:
            raise PlanValidationError(f'{location}: invalid scope properties')
        bindings, outputs = [], []
        for key, target, cls in (('bindings', bindings, BindingDefinition),
                                 ('output', outputs, OutputDefinition)):
            items = raw.get(key, [])
            if type(items) is not list:
                raise PlanValidationError(f'{location}.{key}: expected array')
            for i, item in enumerate(items):
                path = f'{location}.{key}[{i}]'
                if type(item) is not dict or set(item) != {'name', 'expr'}:
                    raise PlanValidationError(f'{path}: expected name and expr')
                target.append(cls(_name(item['name'], path),
                                  parse_expression(item['expr'], path + '.expr')))
        names = [binding.name for binding in bindings]
        if len(names) != len(set(names)):
            raise PlanValidationError(f'{location}: duplicate binding')
        where = (parse_expression(raw['where'], location + '.where')
                 if 'where' in raw else None)
        expand = None
        if 'expand' in raw:
            exp = raw['expand']
            if type(exp) is not dict or set(exp) != {'alias', 'expr', 'mode', 'scope'}:
                raise PlanValidationError(f'{location}.expand: invalid properties')
            alias = _name(exp['alias'], location + '.expand.alias')
            if alias == 'root' or exp['mode'] not in ('inner', 'left'):
                raise PlanValidationError(f'{location}.expand: invalid alias or mode')
            expand = ExpandDefinition(alias, parse_expression(
                exp['expr'], location + '.expand.expr'), exp['mode'],
                scope(exp['scope'], location + '.expand.scope'))
        return ScopeDefinition(tuple(bindings), where, expand, tuple(outputs))
    return PlanDefinition(scope(data, '$'))


def plan_to_data(plan):
    def scope(node):
        result = {
            'bindings': [{'name': b.name, 'expr': expression_to_data(b.expr)}
                         for b in node.bindings],
            'output': [{'name': o.name, 'expr': expression_to_data(o.expr)}
                       for o in node.output]}
        if node.where is not None:
            result['where'] = expression_to_data(node.where)
        if node.expand is not None:
            e = node.expand
            result['expand'] = {'alias': e.alias, 'mode': e.mode,
                                'expr': expression_to_data(e.expr), 'scope': scope(e.scope)}
        return result
    return scope(plan.root)
