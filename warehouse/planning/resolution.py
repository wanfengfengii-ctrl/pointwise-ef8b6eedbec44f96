from dataclasses import dataclass, replace
from warehouse.expressions.model import BindingReference
from warehouse.expressions.validation import collect_binding_references
from warehouse.planning.model import PlanValidationError, ScopeDefinition


@dataclass
class ScopeTable:
    scope_id: str
    names: frozenset
    aliases: frozenset
    parent: object = None
    child: object = None


def build_scope_table(root):
    next_scope = 0

    def build(scope, parent=None, aliases=frozenset({'root'})):
        nonlocal next_scope
        table = ScopeTable(f's{next_scope}', frozenset(b.name for b in scope.bindings),
                           aliases, parent)
        next_scope += 1
        if scope.expand:
            table.child = build(scope.expand.scope, table, aliases | {scope.expand.alias})
        return table

    return build(root)


def resolve_reference(name, table):
    current = table
    while current is not None:
        if name in current.names:
            # A reference denotes the declaring scope's binding, even when a
            # lexically nearer scope declares the same name.
            return BindingReference(f'{current.scope_id}:{name}', current.scope_id, name)
        current = current.parent
    raise PlanValidationError(f'{table.scope_id}: unknown binding {name}')


def validate_binding_graph(bindings):
    """Reject cycles between compiled bindings, keyed by binding identity.

    Names are resolved lexically before this check, so shadowed bindings are
    separate nodes and only genuine dependency cycles are rejected.
    """
    graph = {binding.binding_id: [ref.binding_id
                                  for ref in collect_binding_references(binding.expr)]
             for binding in bindings}
    done, active = set(), []

    def check(binding_id):
        if binding_id in active:
            owner, _, name = binding_id.partition(':')
            raise PlanValidationError(f'binding dependency cycle at {owner}:{name}')
        if binding_id in done:
            return
        active.append(binding_id)
        for target in graph.get(binding_id, ()):
            check(target)
        active.pop()
        done.add(binding_id)

    for binding_id in graph:
        check(binding_id)


def resolve_plan(plan):
    tables = build_scope_table(plan.root)
    compiled_bindings = []

    def expression(expr, table):
        value = expr.value
        if expr.op == 'ref':
            value = resolve_reference(value, table)
        if expr.op == 'field' and value.base not in table.aliases:
            raise PlanValidationError(f'{expr.location}: unknown field base {value.base}')
        return replace(expr, value=value,
                       args=tuple(expression(arg, table) for arg in expr.args))

    def scope(node, table):
        bindings = tuple(replace(b, expr=expression(b.expr, table),
                                 binding_id=f'{table.scope_id}:{b.name}',
                                 owner_scope=table.scope_id) for b in node.bindings)
        compiled_bindings.extend(bindings)
        outputs = tuple(replace(o, expr=expression(o.expr, table)) for o in node.output)
        expand = None
        if node.expand:
            expand = replace(node.expand, expr=expression(node.expand.expr, table),
                             scope=scope(node.expand.scope, table.child))
        return ScopeDefinition(bindings,
                               expression(node.where, table) if node.where else None,
                               expand, outputs, table.scope_id)

    root = scope(plan.root, tables)
    validate_binding_graph(compiled_bindings)
    return root
