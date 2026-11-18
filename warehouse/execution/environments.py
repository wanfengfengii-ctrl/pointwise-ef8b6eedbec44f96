from copy import copy
from dataclasses import dataclass
from warehouse.execution.bindings import BindingCell
from warehouse.source.coordinates import OccurrenceCoordinate, child_coordinate
from warehouse.expressions.errors import BindingCycleError, ErrorLocation


class _EmptySide:
    pass


EMPTY_SIDE = _EmptySide()


@dataclass(frozen=True)
class ProjectionSite:
    scope: object
    coordinate: OccurrenceCoordinate
    aliases: dict


class Environment:
    def __init__(self, scope, coordinate, root_record, aliases=None, projections=()):
        self.scope = scope
        self.coordinate = coordinate
        self.root_record = root_record
        self.aliases = {} if aliases is None else aliases
        self.site = ProjectionSite(scope, coordinate, self.aliases)
        self.projections = projections + (self.site,)
        self.bindings = {b.name: b for b in scope.row_bindings}
        self.slots = {name: f'{scope.scope_id}:{name}' for name in self.bindings}
        self.cells = {slot: BindingCell() for slot in self.slots.values()}

    @classmethod
    def root(cls, scope, source, record):
        return cls(scope, OccurrenceCoordinate(source), record)

    def child(self, scope, alias, element, index):
        coordinate = child_coordinate(self.coordinate, scope.scope_id, index)
        return Environment(scope, coordinate, self.root_record,
                           self.aliases | {alias: element}, self.projections)

    def at_projection(self, site):
        view = copy(self)
        view.scope = site.scope
        view.coordinate = site.coordinate
        view.aliases = site.aliases
        return view

    def resolve_binding(self, reference, context, demand_coordinate):
        from warehouse.expressions.semantics import evaluate_expression
        name = reference.name
        if name not in self.bindings:
            raise BindingCycleError(f'unknown row binding {name}')
        binding = self.bindings[name]
        return self.cells[self.slots[name]].demand(
            lambda: evaluate_expression(binding.expr, self, context, demand_coordinate),
            ErrorLocation(binding.expr.location, demand_coordinate))

    def read_base(self, name):
        if name == 'root':
            return self.root_record
        if name not in self.aliases:
            raise BindingCycleError(f'no field base {name}')
        return self.aliases[name]
