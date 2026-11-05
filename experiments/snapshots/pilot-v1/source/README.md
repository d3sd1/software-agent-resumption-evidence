# Local diagnostic resumption pilot: reproduction instructions

Python standard library only, CPython **3.14.4**, existing authenticated CLI **2.1.318**. No pip packages, GPU, external service installation, or data downloads. Use only the operator's approved inherited CLI authentication. Do not read credentials, override endpoints/models, introduce an API key, select a paid fallback, or publish these artifacts.

The protocol input is `pilot-plan.md`; complete budgets and criteria are in `config.json`. The study is **controlled resumption with harness-generated predecessor evidence**. It does not measure source-agent handoff generation, natural long histories, compaction or process recovery. Broad mechanism novelty is rejected. The T arm is an original small conceptual adaptation, not copied source or an exact Tether reproduction. B4 and always-recheck are **not implemented or compared**. No confirmatory experiment is authorized.

## Re-evaluate retained pilot (no model calls)

From this directory:

```sh
.venv/bin/python evaluate.py
.venv/bin/python tests.py
```

Equivalent commands from any working directory use absolute paths to these scripts. The code resolves its data relative to its own directory. Tests create and clean temporary directories only here. `evaluate.py` does not import or invoke the gate and never contacts a model.

## Set up in a fresh, separate experiment copy

Do not overwrite recorded runs or the existing fixture directory. To reproduce a new pilot, first obtain authorization for new sessions and use a new directory containing the authored root scripts, config, requirements, protocol, manifest specification and README, but no prior generated fixtures/runs/results. Existing subscription preflight evidence alone is not permission to run more calls.

```sh
python3 -m venv --without-pip .venv
.venv/bin/python generate_fixtures.py
.venv/bin/python tests.py
.venv/bin/python run_all.py --preflight
.venv/bin/python run_all.py --pilot
```

`--without-pip` is sufficient because there are no dependencies. On the pilot host normal `python3 -m venv` failed because ensurepip was absent; no system package was installed. The interpreter and CLI version checks fail closed if versions differ. Model identity is not pinned by guess: inherited selection is used and actual `modelUsage` is retained verbatim.

A single `run_all.py --pilot` orchestrates all assigned scientific sessions and evaluation after fixtures, tests and a successful JSON-action bridge preflight. It refuses to overwrite an existing assignment. It never retries failed model sessions. Errors/quota/auth failures/timeouts stop the pilot; all 28 assigned cells remain in the denominator. The separate preflight uses inspect_state and finish and is excluded from scientific outcomes. The earlier subscription route precheck remains separate too.

## Bounds and isolation

- Four tiny software fixture families, seven arms, one session/cell: at most 28 pilot CLI sessions, sequential (concurrency 1).
- At most eight executed tool calls and 120 seconds/session, at most 90 minutes globally. No generic Bash, filesystem or network tool is available to the model.
- A persistent CLI JSON-action bridge allows only fixture state reads, two fixed subprocess checks, integer-only source repair, a local release request and structured finish. The model chooses every operation; the harness parses and executes it. These are real operations, **not native MCP calls**. The model cannot read the parent repository or secrets through these tools.
- The initial explicit MCP preflight failed: safe-mode CLI 2.1.318 exposed zero tools. Its raw evidence is retained in `preflight/mcp-check/`. The tested alternative keeps safe-mode and inherited authentication, disables all native tools/MCP, and exchanges one JSON action/result per turn over stream-json stdin/stdout within one session. No account, endpoint or permission configuration is changed. The small MCP server remains as a unit-tested but CLI-inactive artifact.
- The check implementation, event log, criteria, evidence, policy, gate and scorer are outside the editable surface. This is not an OS sandbox against a malicious same-user process.
- `functional-real` executes the toy component locally, not an external integration service. `functional-mock` executes a stub and cannot satisfy real-local-functional scope. The mock-only family explicitly makes the required real check unavailable.
- Dirty means changed bytes versus the retained predecessor snapshot. No Git commit/history is created or claimed.
- G and P use the same gate function; other arms commit to a local experimental sink without enforcement, with shadow decisions logged. Unsupported synthetic releases cannot affect production.
- Every release attempt captures candidate bytes and operation-time policy/evidence. Commits are separate append-only events; a later hold cannot remove an earlier release from scoring.

## Outputs and interpretation

`results/pilot_results.json` contains per-assigned-run and per-arm metrics, including unsupported commits and attempts, accepted completion, false blocking on positive controls, gate false rejection, timeouts, checks, runtime and tokens. Effective CLI-complete and structured-complete counts are separate. Missing usage is null. Mean/std are descriptive across heterogeneous fixtures, not repeated seeds or inferential uncertainty. No p-values or power claims. The five project seeds are reserved for a later authorized phase and were not run here.

`results/assignment.json` freezes the order, config and source hashes before pilot calls. `fixtures/manifest.json` hashes actual fixture bytes and genuine predecessor subprocess logs. `runs/<family>__<arm>/` retains raw stream stdin/stdout, stderr, model-selected bridge actions, real tool results, snapshots, release events and session/modelUsage metadata. Token totals sum the CLI's explicit `model_usage_since_last_result` deltas; cumulative `modelUsage` and each raw result are retained to cross-check that no cumulative total is counted twice. `logs/runner.log` records progress and failures. Predecessor and rendering costs are recorded; handoff rendering uses no hidden model calls. Token usage is measured, **not equalized**. Raw CLI monetary fields, especially `costBasis: unknown`, are **not bills**.

The scorer evaluates structured finish assertions. Unrestricted final-text verification assertions are retained for separate manual review, not silently scored as accurate. Positive completion requires a supported local release; the two negative families require the correct hold, technical assessment and reason. False blocking is reported on unchanged-valid and repairable-dirty controls, with unchanged-only counts too.

No figures or publication artifacts are generated. Local code hygiene, if needed before running, is `.venv/bin/python hygiene.py`, using only the already-running loopback inspect/clean service, no external detector or rewriting. Never clean raw experimental logs. Hygiene does not imply human authorship.

Typical upper bound from caps is 56 minutes for 28 pilot sessions, plus local setup and the separate preflight, under the 90-minute global ceiling. Actual measured runtime is in `results/execution.json` and each session record.
