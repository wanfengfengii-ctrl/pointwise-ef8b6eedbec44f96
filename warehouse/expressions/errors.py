from dataclasses import dataclass
from warehouse.source.coordinates import encode_coordinate
from warehouse.expressions.model import ExpressionLocation


@dataclass(frozen=True)
class ErrorLocation:
    expression: ExpressionLocation
    coordinate: object

    def to_data(self):
        return {'expression': self.expression,
                'coordinate': encode_coordinate(self.coordinate)}


class EvaluationError(Exception):
    code = 'EVALUATION'

    def __init__(self, message, location=None):
        super().__init__(message)
        self.location = location
        self.run_id = None

    def to_data(self):
        return {'type': type(self).__name__, 'code': self.code,
                'message': str(self),
                'location': self.location.to_data() if self.location else None}


class FunctionFailure(EvaluationError):
    code = 'FUNCTION_FAILURE'


class TypeMismatch(EvaluationError):
    code = 'TYPE_MISMATCH'


class MissingField(EvaluationError):
    code = 'MISSING_FIELD'


class BindingCycleError(EvaluationError):
    code = 'BINDING_CYCLE'


def attach_first_location(error, location):
    if error.location is None:
        error.location = location
    return error
