# Local access-study instrument

This is a separate prospective implementation of `protocol-v1.md`, including its revised started-slot completion and newly supplied message-byte endpoints. It does not change or re-score the historical pilot/expansion. No participant call, transport preflight, freeze or publication is part of local validation.

## Runtime

Linux, `/usr/bin/python3`, Bubblewrap and util-linux `prlimit` are required. The implementation uses only the Python standard library; no pip packages, new SDK, provider, daemon or GPU are needed. The actual interpreter binary hash/version, kernel identifier and dependency contract are captured in each preparation. The system standard library/shared-library mounts are trusted and not exhaustively hashed; this is a bounded environment identifier, not a hermetic OS image.

Always invoke the host entry point with Python isolated mode. Never execute from a downloaded tree. The entry point adds only its own `src` directory to the import path. Public packages and adapted upstream tests execute only inside the readonly/network-free sandbox. No build hooks or upstream setup scripts run.

## Safe local commands

Run from this directory or replace `study.py` and output paths with absolute paths. Each output name must be new; earlier preparation/validation receipts are preserved and are not overwritten.

```sh
python3 -I study.py test --output local-validation/unit-fresh.json
python3 -I study.py prepare --output local-validation/prepared-fresh
python3 -I study.py validate --prepared local-validation/prepared-fresh --output local-validation/controls-fresh
```

`test` executes synthetic unit vectors only, including a fake stdin/stdout process to test transport accounting. That process is not a model. `prepare` verifies the curator's source hashes, copies only the four primary cases and executes before/after functional checks. `validate` executes three deterministic controls in every G/P × access × R/U combination. Controls have privileged recovery-route/state knowledge; they are not participants or optimal lower bounds. Their message ledger is explicitly labelled reference-render-only, never actual client supply.

The four public cases are packaging-sibling-errors, itertools-large-range, itertools-peekable-slice and dotenv-backslashes. Curation/downloads are inputs only. Each case keeps its source notices, adapter attribution, exact origin and scoped-identity assumption. Documentation notes are authored local task changes; upstream before/after sources are not fabricated. The test adapter is a focused subset, not the complete upstream suite.

## Instrument and accounting

- `config.json` defines the reduced 160-assignment design and 32-action/180-second/2-worker/18,000-second envelope. Repetition labels seed scheduling only.
- `api-contract.json` defines exact actions, retrieval interfaces and coordinator receipt fields.
- `gate.py` is identical for G/P. It requires functional check/scope, stdout/parsed/command agreement, subject/test/environment binding, protected files and authorization. Applicable contradictory failures block. No historical control module is imported.
- G receives a strong historical narrative with applicability/recovery guidance. P additionally receives a computed applicability projection. Logical automatic reads and rendered outputs are separate. Initial bytes match within an arm across access regimes; G/P representation is intentionally different.
- `restore_verified` replaces only the declared executable subject and preserves notes/notices. Every scientific case permits this deterministic route. Always restoring can succeed everywhere. A final hold without delivery is a missed recoverable opportunity.
- `oracle.py` uses only the standard library; it imports neither gate nor harness/reconciliation. It checks event-chain hashes and actual immutable snapshot/release files. Code separation is not independent authorship. Success requires supported delivery, accurate finish, and no earlier unsupported commit; an earlier blocked request can recover.
- `slot-start.json` is written before arm preparation. `slot-end.json` binds start and session receipts. The session binds the instrument action count and terminal event hash. Expected event-log existence, count and terminal hash must all agree; a missing file or valid-looking prefix cannot establish a completed execution. Auditable preparation/transport/cap/deadline failures are non-completions within the envelope, not reasoning errors. Lost lifecycle/events make completion unknown, while any independently verified unsafe prefix is retained. Never-started assignments are outside the primary started-slot denominator.
- `message-ledger.jsonl` retains exact newly supplied strings, UTF-8 lengths, categories and delivery status. It counts initial system/tool instructions, initial user/handoff and every newly supplied driver response/continuation once. Role/transport framing, auth, assistant outputs, provider-internal prompts and repeated conversation history are excluded. A partial/uncertain write makes the total unknown while retaining known-prefix work. Client supply is not proof of provider consumption.
- The message writer closes with in-memory record/message/delivery counts, a whole-log hash and terminal record hash. This closure is bound into the final session receipt. Lost/truncated/empty ledgers or a missing closure make total bytes unknown, preserving only verified-prefix bytes. A real zero requires an explicitly closed empty ledger; it cannot be inferred from an absent file. A byte-ledger defect does not invalidate a separately verified completion or safety event.
- `known_started`, `completion_known/unknown` and `workload_known/unknown` are separate counters. Loss of events does not silently remove a known start or convert it to an observed failure. The primary output retains the known-start denominator and makes the total-success numerator null when completion is unknown; observed successes, observed non-completions and the conditional observed subset are explicit. Bytes can remain known when events are lost, and completion can remain known when bytes are lost.
- Retrieval payload/document/unique-byte counters are secondary. Automatic input bytes remain separate. Bytes are not tokens or physical IO. Provider explicit per-result delta categories retain missingness; cumulative totals are not summed and no billing inference is made.
- Completion and workload include all auditable started slots, not only successful ones. Safety absence in incomplete prefixes remains unknown. Full-suite contrasts use equal case/state weights and are unavailable if a required assignment is unstarted/unknown; observed-subset contrasts and coverage are labelled separately. Complete-block exclusions are explicit.

## Coordinator-only later stages — do not run now

The package does not implement or launch preflight. The coordinator must independently obtain and inspect a neutral preflight through the existing inherited route (at most eight sessions), observe the actual reported model identity and exact CLI version, and provide the receipt/raw stream described in `api-contract.json`. It must not infer a provider/model from the CLI's brand. No alternative SDK, paid route or fallback is selected.

A second implementation review must bind current source, preparation and local-validation hashes. Current executed unit-test receipts are also required. Only then can the coordinator explicitly create a **new** freeze directory.

```sh
python3 -I study.py freeze --freeze \
  --prepared local-validation/prepared-fresh \
  --validation local-validation/controls-fresh \
  --tests local-validation/unit-fresh.json \
  --preflight coordinator/neutral-preflight.json \
  --review coordinator/implementation-review.json \
  --output capsules/cohort-001
python3 -I study.py verify-freeze --frozen capsules/cohort-001
```

`freeze` hashes/copies source, configuration, protocol, public case snapshots, predecessor evidence, test inputs, prompts, document bytes, assignments and audit receipts. It refuses missing/mismatched validation, identity or budget evidence. It does not authorize a participant run.

After a separate genuine authorization, the coordinator can create an authorization audit record with `participant_run_authorized: true`, `freeze_sha256` and a real `authorization_reference`. Flags/records are not themselves consent. The only model-call path requires an explicit `run --run` command.

```sh
python3 -I study.py run --run --frozen capsules/cohort-001 \
  --authorization coordinator/participant-authorization.json \
  --output collections/cohort-001
```

The runner exclusively creates `RUN-CLAIM.json` before assigning/launching; it cannot be rerun under another output name. Never remove the claim to rerun. No unsuccessful exposure is replaced. All 160 assignments are retained, including never-started slots. Identity/tool/quota/instrument failures stop new scheduling; in-flight slots keep their original limits. A defect needs a documented prospective amendment, not silent mutation of a frozen cohort.

## Provenance and local hygiene

The bridge/session/scheduler seams are adapted from `../expansion/{cli_bridge,session,run_all}.py`; corrected label semantics were inspected in `../measurement-validation/controls_corrected.py`. Exact input hashes and adaptation notes are retained in each preparation's `provenance.json`. Historical code and results remain untouched. No real Elsevier IST feedback file was available at implementation time; simulated feedback is not labelled calibrated.

`tools/hygiene.py` uses only the loopback deterministic service, on this implementation's own files. It neither touches curation, frozen artifacts or third-party inputs nor invokes detectors/rewrite models. It records the actual service reports. Run it before the final test/preparation cycle if source changes.

No commit, push, repository creation, dataset upload, manuscript edit or publication command is provided.
