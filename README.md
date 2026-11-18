# Nested Warehouse

Python 3.11 standard-library/SQLite warehouse for ordered nested records.
No installation or network access is needed. Run in this directory:

    python3.11 -B -m unittest discover -s tests -t . -v
    python3.11 -B samples.py

The suite uses real temporary SQLite databases for close/reopen cases.
The demo uses SQLite in memory and prints actual details, function calls and
a failed run which leaves a previous successful result readable.

## Public API and source identity

Import Warehouse and FunctionContext from warehouse. Warehouse(path=':memory:')
is a context manager; close() is idempotent.

ingest(request_id, records) returns IngestReceipt(batch_id, record_count,
receipt). Input is an ordered list/tuple of string-keyed records. Nested values
are JSON null, bool, int, finite float, string, list or string-keyed dict.
Cycles, nonfinite numbers and other objects fail before any database write.
Accepted values are snapshots; later caller mutations have no effect.
Equal records have different record_index values. Request replay compares full
canonical content, preserving array order and bool/int/float distinctions.
Object key order is immaterial. Same request/content returns the original
receipt; different content raises IngestConflict. Other request IDs create
independent batches. SourceValidationError identifies invalid values.

register_plan(name, definition) returns PlanReceipt(plan_revision, name,
definition). warehouse.plans.get_revision(id) returns the saved definition and
compiled plan. Each registration creates a new immutable revision, even for
the same name. Caller mutation cannot change saved definitions. Unknown
identities raise KeyError. Rejected definitions publish no revision.

## Plan grammar

A scope has optional bindings, where, expand and output properties.
Bindings and outputs are ordered arrays of {"name": NAME, "expr": EXPR}.
Expand has exactly {"alias": NAME, "expr": EXPR, "mode": "inner" or "left",
"scope": SCOPE}. Each scope has at most one expansion. Unknown properties fail.
Binding names are unique per scope; output names are unique across the plan.
The field base name root is reserved.

Expression nodes require exactly the listed properties besides op:

| op | Properties |
| --- | --- |
| literal | value: JSON value |
| field | base: root or visible alias; path: array of string keys/integer indices |
| ref | name: visible binding |
| call | name: function; args: ordered array |
| if | args: condition, true expression, false expression |
| and, or, eq, lt, add | args: two expressions |

Same-scope forward references are legal when acyclic. Child bindings shadow
ancestors. Parent expressions cannot see descendant bindings or aliases.
Expand's expression is evaluated in its parent scope; its alias is visible
only in the child and descendants. Negative indices fail rather than using
Python indexing. Unknown structure, operations, functions, signatures,
references or dependency cycles raise PlanValidationError at registration.
Source fields have no declared schema: absent source data is a runtime error.

Functions: next_ticket() allocates one integer, fail(string) raises
FunctionFailure, length(string/array/object) returns its length.
FunctionContext(start=1).trace returns a defensive copy of actual calls with
function, arguments and evaluation-environment coordinate. Ordinary arguments
run left to right. Conditions and where require bool; numbers do not coerce.
add and lt accept int/float but reject bool and strings; arithmetic overflow
fails. eq requires matching JSON types recursively: true, 1 and 1.0 differ.

## Execution and coordinates

run(batch_id, plan_revision, function_context=None) returns
RunReceipt(run_id, row_count). Both identities are fixed before creating a
run. Each invocation creates a new run; omitted context means a fresh context.
Traversal is depth first in source and array order. Where precedes expansion;
a false branch executes neither its expansion nor its output.

Bindings are lazy. Every source occurrence owns independent root cells; each
element occurrence owns independent child cells. Descendants share their
actual ancestors' cells. Success and failure are cached at first demand.
Equal-valued sources/elements never share cells. Unused bindings and
unselected if/and/or operands have no effects. Ordinary output expressions
execute per retained leaf; binding references provide once-per-owner reuse.

Inner [] yields no rows. Left [] creates exactly one empty-side child whose
element_index is null. This differs from a real null element at index 0.
Field access based on an empty-side alias returns null. Access through real
null still fails when an object/array is required. Child filtering and deeper
expansion apply normally. Expansion of a nonarray raises TypeMismatch.

Only retained leaves produce details. Outputs evaluate outer-to-inner in
declaration order, using their declaration environments. OutputRow has
output_index, coordinate, values. Coordinates contain source(batch_id,
record_index) and ordered elements(scope_id, element_index). Scope IDs s0,
s1, ... follow declaration order. Output indices start at zero and are
contiguous. Two equal sources each with two elements produce root-bound
tickets 1,1,2,2 when each leaf demands the same root binding.

## Errors, runs and historical results

EvaluationError subclasses: FunctionFailure, TypeMismatch, MissingField,
BindingCycleError. Fields code and location identify the failing expression
and first actual demand coordinate. A parent binding evaluates with its
parent's data; an error retains the descendant location that first demanded
it. to_data() returns the persisted summary; run_id identifies the failed run.
Repeated demand of a failed cell rethrows its original error without a call.

CREATED is persisted before work. A single work transaction changes state to
RUNNING, stages details, publishes all details and marks SUCCEEDED. Failure
rolls back all work, then persists FAILED separately. FunctionContext calls
do not roll back. If failure recording also fails, StorageFailure is returned
and the run may remain CREATED. Neither CREATED nor FAILED is readable.
There is no automatic recovery; retry creates a new run and, when desired, a
fresh deterministic context. Terminal runs cannot restart.

read_result(run_id) returns PublishedResult(run_id, batch_id, plan_revision,
row_count, rows). Only that exact SUCCEEDED run is readable. Unknown or
non-successful IDs raise ResultUnavailable, without fallback. Successful
zero-row results are readable. Row count, contiguous order and batch ownership
are checked. Same-name registrations, other failures and reopening cannot
change old definitions, bindings or results.

For deterministic boundary tests, warehouse.database.inject_once(point,
after=0) raises StorageFailure on encounter after+1 and removes the injection.
Points: source.record, source.before_commit, plan.before_commit,
run.created.before_commit, stage.append, publication.rows, publication.state,
run.before_commit, run.failure, run.failure.before_commit. These checkpoints
operate within actual SQLite transactions; stores are not substituted.

## Implementation and regression map

warehouse/source/ owns validation, snapshots, receipts, stored records and
coordinates. warehouse/expressions/ owns syntax, validation, strict semantics,
errors and deterministic functions. warehouse/planning/ owns lexical
resolution, compilation and immutable revisions. warehouse/execution/ owns
occurrence environments, demand cells, expansion and ordered projection.
warehouse/results/ owns SQLite lifecycle, run transitions, staging and atomic
publication. warehouse/api.py composes the services.

tests/test_source.py: identity, replay, invalid middle records, snapshot,
rollback and reopen. tests/test_planning.py: lexical visibility, shadowing,
forward references, cycles, registration rollback and fixed revisions.
tests/test_execution.py: complete details, coordinates and traces, nested
duplicate elements, left empty sides, filtering and zero rows.
tests/test_expressions.py: short circuit, strict types, argument order and
cached errors. tests/test_results.py: late failure, publication boundaries,
failure-record errors, exact historical reads and reopen.
tests/oracle.py independently interprets public definitions with lexical
loops, comparing rows, coordinates, traces and first errors without production
compiler/evaluator imports.

Single-worker batches only. Distributed scheduling, checkpoint continuation,
incremental maintenance and external expression SDKs are outside this product.
