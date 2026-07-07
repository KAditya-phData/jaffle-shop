# dbt command reference — index

Command catalog for authoring dbt Cloud jobs. **Load the per-command file below (`commands/<file>.md`) before adding that command to a job** — each holds the exact read/write effect, options, decision inputs, and good/bad practices. Start from [decision_tree.md](decision_tree.md) to pick a command from user intent.

| Command | Use in job | Warehouse effect | When to use | File |
|---|---|---|---|---|
| `dbt build` | step | writes-warehouse-data | Default single step for almost every scheduled/deploy job and most CI jobs (scoped with --select state:modified+). Does NOT include source freshness or docs. | [dbt_build.md](dbt_build.md) |
| `dbt run` | rarely | writes-warehouse-data | Only when you deliberately want run and test as separate, isolated steps (legacy pattern); otherwise superseded by dbt build. | [dbt_run.md](dbt_run.md) |
| `dbt test` | rarely | read-only | Only as a standalone step if you deliberately split build into run-then-test stages; otherwise redundant with dbt build, which interleaves testing. | [dbt_test.md](dbt_test.md) |
| `dbt seed` | rarely | writes-warehouse-data | Only if the job's scope owns seed CSVs that must refresh on that schedule; most projects seed once/rarely and rely on dbt build to include it when needed. | [dbt_seed.md](dbt_seed.md) |
| `dbt snapshot` | step | writes-warehouse-data | Dedicated step/job scheduled at the cadence matching source change rate (hourly-daily). Never run ad hoc/in CI — it's stateful and pollutes history. | [dbt_snapshot.md](dbt_snapshot.md) |
| `dbt compile` | rarely | writes-artifacts-only | Only as a fast, merge-triggered manifest-refresh step for CI state comparisons, or ad hoc SQL debugging. Redundant immediately before/after run/build (they compile internally). | [dbt_compile.md](dbt_compile.md) |
| `dbt show` | never | read-only | Interactive CLI development/debugging only. No automation value in a scheduled/CI job — single-node only, no reusable output. | [dbt_show.md](dbt_show.md) |
| `dbt list` | rarely | read-only | CI/debug pre-flight step to confirm a --select expression resolves as expected (e.g. log state:modified+ set as JSON) before wiring it into the real build/test step. Not useful as a standalone scheduled step. | [dbt_list.md](dbt_list.md) |
| `dbt parse` | rarely | writes-artifacts-only | Single step in a lightweight, merge-triggered 'refresh comparison manifest' job for CI deferral/state comparison (with --no-partial-parse). Never add before build/test in the same job — redundant, they parse internally. | [dbt_parse.md](dbt_parse.md) |
| `dbt docs generate` | job-parameter | writes-artifacts-only | Prefer the 'Generate docs on run' toggle (generate_docs: true) on the canonical production/nightly job so failures don't block the job. Use an explicit command step only if you need --no-compile/--select or want doc failures to hard-fail the job. Skip on ephemeral CI/PR jobs — docs would reflect a partial build. | [dbt_docs_generate.md](dbt_docs_generate.md) |
| `dbt docs serve` | never | read-only | Local development only. Never in any job — it hangs until timeout, is unreachable on dbt Cloud's ephemeral runners, and has no valid automation use. Use dbt Cloud's hosted docs/Explore site instead. | [dbt_docs_serve.md](dbt_docs_serve.md) |
| `dbt deps` | never | writes-artifacts-only | Never add explicitly — dbt Cloud automatically runs it before every job invocation already; adding it is pure duplication. | [dbt_deps.md](dbt_deps.md) |
| `dbt clean` | never | writes-artifacts-only | Never in a dbt Cloud job — every job run gets a fresh ephemeral filesystem, so there's nothing to clean. Local CLI/dev use only; docs warn against use with shared/remote filesystems. | [dbt_clean.md](dbt_clean.md) |
| `dbt run-operation` | step | writes-warehouse-data | For pre/post maintenance tasks (grants, cloning, cleanup) using a tested, version-controlled macro. Must ask what the macro does before adding — treat as a potential write by default. Avoid --sql in recurring jobs (untracked, unreviewed). | [dbt_run_operation.md](dbt_run_operation.md) |
| `dbt retry` | never | writes-warehouse-data | Never author as a job step — no jobs-as-code field exists and a fresh run has no prior run_results.json to resume. Use dbt Cloud's 'Rerun from failure' UI action or the Retry Failed Run API against a specific completed run instead. | [dbt_retry.md](dbt_retry.md) |
| `dbt source freshness` | job-parameter | read-only | Use the 'Run source freshness' toggle (run_generate_sources: true) for non-blocking monitoring, placed conceptually before build. Use an explicit command step instead when staleness should hard-block/fail the rest of the job. dbt build does NOT include this — must be added separately either way. | [dbt_source_freshness.md](dbt_source_freshness.md) |

## Job parameters vs. command steps

**dbt Cloud job PARAMETERS/toggles** (checkboxes / boolean fields in jobs.yml, not lines in the command list):
- `generate_docs` ("Generate docs on run") → runs `dbt docs generate` after the listed steps, non-blocking on failure (job continues even if this step errors, as long as other steps succeeded).
- `run_generate_sources` ("Run source freshness") → runs `dbt source freshness` as an implicit first step, also non-blocking on failure by default.
- Job environment / target selection itself is a job-level setting (Environment binding), not a `--target` flag on any command.

**Command STEPS** (explicit strings in `execute_steps`/Commands list, chained sequentially — failure of any step normally halts the rest of the job):
- `dbt build`, `dbt run`, `dbt test`, `dbt seed`, `dbt snapshot`, `dbt compile`, `dbt run-operation`, `dbt ls`, `dbt parse`, and — if the author wants blocking/hard-fail semantics instead of the lenient toggle behavior — explicit `dbt docs generate` or `dbt source freshness` commands.
- `dbt deps` is auto-run by dbt Cloud before every invocation; never add as an explicit step.

**Key distinction to get right:** the *same underlying dbt command* can be invoked two ways with different failure semantics — via its toggle (lenient, won't block the job) or as an explicit step (strict, blocks downstream steps on failure). This applies specifically to `dbt docs generate` and `dbt source freshness`. All other commands in this set have no toggle equivalent and are only ever explicit steps.

**Never a parameter, toggle, or step at all** (CLI/local-only, no jobs-as-code representation): `dbt docs serve`, `dbt clean`, `dbt retry`, `dbt show` (technically addable as a step but has zero automation value and should never be authored into a job).

## Safety warnings

- Never bake --full-refresh into a recurring scheduled build/run/seed/snapshot step — it drop-cascades and fully rebuilds incremental models/snapshots/seeds every run, multiplying cost/runtime and briefly disrupting availability. Treat it as a deliberate, occasional, ideally manually-triggered or separately-scheduled action, scoped with --select.
- dbt build does not check source freshness and does not generate docs — teams sometimes wrongly assume a green build means fresh data or updated docs. Add 'Run source freshness' / 'Generate docs on run' (or explicit steps) separately if needed.
- dbt snapshot is stateful: every execution inserts real history rows into a warehouse table with no clean undo. Never run it ad hoc in CI/PR jobs (pollutes history) and never change an existing snapshot's strategy/unique_key straight into production without testing in dev/staging first (can silently corrupt row versioning).
- dbt run-operation and its --sql form execute arbitrary macro/SQL logic dbt cannot introspect — treat every run-operation step as a potential destructive warehouse write by default and confirm what the macro does before scheduling it recurring. Never hardcode a one-off destructive macro (e.g. schema clone/drop) into a permanent recurring job step.
- Never author 'dbt retry', 'dbt clean', or 'dbt deps' as explicit job steps: retry has no prior run_results.json to resume from in a fresh invocation and will no-op or error; clean has nothing to clean in dbt Cloud's ephemeral per-run filesystem; deps already runs automatically before every job invocation, so adding it duplicates work.
- Never add 'dbt docs serve' to any job — it is a foreground webserver that never exits on its own, will hang until the run/step timeout kills it, and is unreachable outside the ephemeral job container.
- Avoid hardcoding --target in any dbt Cloud job step; rely on the job's assigned Environment to select the connection/warehouse. Manual --target overrides risk silently writing to the wrong warehouse (e.g. a CI job accidentally pointed at production) if environment configuration drifts.
- dbt show's --inline flag accepts raw SQL with no read-only enforcement by dbt itself — piping dynamic or user-supplied SQL into it (or into run-operation --sql) inside an automated job is an unaudited path to arbitrary warehouse writes; pair any such usage with a read-only warehouse role if it must exist at all.
- Failure-handling semantics differ by invocation method for docs generate and source freshness: the job toggle is lenient (won't fail the whole job), while the same command as an explicit execute_steps entry is a hard, blocking failure. Pick deliberately based on whether staleness/doc failures should block the pipeline.
