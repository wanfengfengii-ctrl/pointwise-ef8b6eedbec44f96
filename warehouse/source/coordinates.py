from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCoordinate:
    batch_id: str
    record_index: int


@dataclass(frozen=True)
class ElementCoordinate:
    scope_id: str
    element_index: int | None


@dataclass(frozen=True)
class OccurrenceCoordinate:
    source: SourceCoordinate
    elements: tuple[ElementCoordinate, ...] = ()


def child_coordinate(parent, scope_id, element_index):
    return OccurrenceCoordinate(parent.source,
                                parent.elements + (ElementCoordinate(
                                    scope_id, element_index),))


def encode_coordinate(coordinate):
    return {'batch_id': coordinate.source.batch_id,
            'record_index': coordinate.source.record_index,
            'elements': [{'scope_id': e.scope_id, 'element_index': e.element_index}
                         for e in coordinate.elements]}


def decode_coordinate(data):
    return OccurrenceCoordinate(
        SourceCoordinate(data['batch_id'], data['record_index']),
        tuple(ElementCoordinate(e['scope_id'], e['element_index'])
              for e in data['elements']))
