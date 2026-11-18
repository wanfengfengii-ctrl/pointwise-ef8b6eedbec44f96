from warehouse.expressions.validation import ExpressionValidationError
from warehouse.planning.model import (
    PlanDefinition, CompiledPlan, PlanValidationError, parse_plan_definition)
from warehouse.planning.resolution import resolve_plan


def validate_output_names(root):
    names = set()
    current = root
    while current:
        for output in current.output:
            if output.name in names:
                raise PlanValidationError(f'duplicate output name: {output.name}')
            names.add(output.name)
        current = current.expand.scope if current.expand else None


def compile_scope(definition):
    validate_output_names(definition.root)
    return resolve_plan(definition)


def compile_plan(data):
    try:
        definition = data if isinstance(data, PlanDefinition) else parse_plan_definition(data)
        return CompiledPlan(compile_scope(definition))
    except ExpressionValidationError as error:
        raise PlanValidationError(str(error)) from error
