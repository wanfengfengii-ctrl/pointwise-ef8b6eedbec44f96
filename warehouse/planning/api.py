from dataclasses import dataclass
from warehouse.planning.model import PlanValidationError, plan_to_data
from warehouse.planning.compile import compile_plan


@dataclass(frozen=True)
class PlanReceipt:
    plan_revision: str
    name: str
    definition: dict


class PlanService:
    def __init__(self, store):
        self.store = store

    def register_plan(self, name, definition):
        if type(name) is not str or not name.strip():
            raise PlanValidationError('plan name must be nonempty')
        compiled = compile_plan(definition)
        snapshot = plan_to_data(compiled)
        revision = self.store.save_revision(name, snapshot)
        return PlanReceipt(revision, name, snapshot)

    def get_revision(self, revision):
        return self.store.load_revision(revision)
