from warehouse.execution.bindings import BindingCell
from warehouse.source.coordinates import OccurrenceCoordinate, child_coordinate
from warehouse.expressions.errors import BindingCycleError, ErrorLocation


class _EmptySide:
    pass


EMPTY_SIDE = _EmptySide()


class Environment:
    """One actual scope occurrence.

    Each source occurrence owns an independent root environment and each
    element occurrence owns an independent child environment.  Children keep
    references to their actual ancestor environments, so a binding declared
    in an ancestor is held by exactly one cell per ancestor occurrence and
    shared by every descendant that references it.  ``projections`` lists the
    actual ancestor occurrences outer-to-inner, ending with this one; it is
    used to evaluate each retained leaf's outputs in declaration order.
    """

    def __init__(self, scope, coordinate, root_record, parent=None, aliases=None):
        self.scope = scope
        self.scope_id = scope.scope_id
        self.coordinate = coordinate
        self.root_record = root_record
        self.parent = parent
        self.aliases = {} if aliases is None else aliases
        self.projections = ((parent.projections if parent is not None else ())
                            + (self,))
        self.declarations = {b.binding_id: b for b in scope.bindings}
        self.cells = {b.binding_id: BindingCell() for b in scope.bindings}

    @classmethod
    def root(cls, scope, source, record):
        return cls(scope, OccurrenceCoordinate(source), record)

    def child(self, scope, alias, element, index):
        coordinate = child_coordinate(self.coordinate, scope.scope_id, index)
        return Environment(scope, coordinate, self.root_record, self,
                           self.aliases | {alias: element})

    def owner(self, scope_id):
        environment = self
        while environment is not None:
            if environment.scope_id == scope_id:
                return environment
            environment = environment.parent
        raise BindingCycleError(f'unknown binding owner {scope_id}')

    def resolve_binding(self, reference, context, demand_coordinate):
        from warehouse.expressions.semantics import evaluate_expression
        environment = self.owner(reference.owner_scope)
        try:
            binding = environment.declarations[reference.binding_id]
        except KeyError:
            raise BindingCycleError(
                f'unknown row binding {reference.name}') from None
        return environment.cells[reference.binding_id].demand(
            lambda: evaluate_expression(binding.expr, environment, context,
                                        demand_coordinate),
            ErrorLocation(binding.expr.location, demand_coordinate))

    def read_base(self, name):
        if name == 'root':
            return self.root_record
        if name not in self.aliases:
            raise BindingCycleError(f'no field base {name}')
        return self.aliases[name]
