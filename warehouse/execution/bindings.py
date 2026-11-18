from enum import Enum
from warehouse.expressions.errors import (
    EvaluationError, BindingCycleError, attach_first_location)


class BindingState(Enum):
    UNDEMANDED = 'UNDEMANDED'
    EVALUATING = 'EVALUATING'
    VALUE = 'VALUE'
    ERROR = 'ERROR'


class BindingCell:
    def __init__(self):
        self.state = BindingState.UNDEMANDED
        self.value = None
        self.error = None

    def peek_state(self):
        return self.state

    def demand(self, evaluator, location):
        if self.state is BindingState.VALUE:
            return self.value
        if self.state is BindingState.ERROR:
            raise self.error
        if self.state is BindingState.EVALUATING:
            raise BindingCycleError('recursive binding demand', location)
        self.state = BindingState.EVALUATING
        try:
            self.value = evaluator()
        except EvaluationError as error:
            self.error = attach_first_location(error, location)
            self.state = BindingState.ERROR
            raise self.error
        except BaseException:
            self.state = BindingState.UNDEMANDED
            raise
        else:
            self.state = BindingState.VALUE
            return self.value
