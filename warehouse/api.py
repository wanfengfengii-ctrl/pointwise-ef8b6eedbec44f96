from warehouse.results.database import Database
from warehouse.source.storage import SourceStore
from warehouse.source.api import SourceService
from warehouse.planning.storage import PlanStore
from warehouse.planning.api import PlanService
from warehouse.results.runs import RunStore
from warehouse.results.staging import StagingStore
from warehouse.results.publication import PublicationStore
from warehouse.results.api import ResultService
from warehouse.execution.runner import ExecutionRunner


class Warehouse:
    def __init__(self, path=':memory:'):
        self.database = Database(path)
        self.source_store = SourceStore(self.database)
        self.source = SourceService(self.database, self.source_store)
        self.plan_store = PlanStore(self.database)
        self.plans = PlanService(self.plan_store)
        self.runs = RunStore(self.database)
        self.staging = StagingStore(self.database, self.runs)
        self.publication = PublicationStore(self.database, self.runs, self.staging)
        self.results = ResultService(
            self.database, self.source_store, self.plan_store, self.runs,
            self.staging, self.publication, ExecutionRunner())

    def ingest(self, request_id, records):
        return self.source.ingest(request_id, records)

    def register_plan(self, name, definition):
        return self.plans.register_plan(name, definition)

    def run(self, batch_id, plan_revision, function_context=None):
        return self.results.run(batch_id, plan_revision, function_context)

    def read_result(self, run_id):
        return self.results.read_result(run_id)

    def close(self):
        self.database.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
