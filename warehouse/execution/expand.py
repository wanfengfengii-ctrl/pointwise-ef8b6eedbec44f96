from dataclasses import dataclass
from warehouse.execution.environments import EMPTY_SIDE
from warehouse.expressions.semantics import evaluate_expression
from warehouse.expressions.errors import TypeMismatch, ErrorLocation


@dataclass(frozen=True)
class ExpandedOccurrence:
    index: int | None
    element: object


def make_empty_side():
    return ExpandedOccurrence(None, EMPTY_SIDE)


def iter_array_occurrences(value, mode):
    for index, element in enumerate(value):
        yield ExpandedOccurrence(index, element)
    if not value and mode == 'left':
        yield make_empty_side()


def expand_scope(expand, parent, context):
    value = evaluate_expression(expand.expr, parent, context)
    if type(value) is not list:
        raise TypeMismatch('expand requires array',
                           ErrorLocation(expand.expr.location, parent.coordinate))
    for occurrence in iter_array_occurrences(value, expand.mode):
        yield parent.child(expand.scope, expand.alias, occurrence.element, occurrence.index)
