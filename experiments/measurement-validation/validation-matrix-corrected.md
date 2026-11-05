# Corrected measurement-validation variant

## Status and provenance

This is a post-study corrective validation round. The original study used the original controls, not this variant. The original matrix, expectations, run-001, historical implementation and frozen artifacts remain unchanged. The corrected implementation exists only in measurement-validation/controls_corrected.py.

The patch admits only the checker-defined pairs compile/compile and functional/real-local-functional-v2. Record and stdout labels must agree; any cached parsed labels must agree too. Complete capture-format records must identify exactly one matching --check value in command_template. No local check can establish physical-fit. This is provenance consistency, not cryptographic authenticity. Missing command provenance is an explicitly stricter post-study capture-format requirement.

Existing classification, staleness, conflict precedence and permission logic are otherwise unchanged. Inadmissible records are excluded; they do not erase an independent valid pass. The new test vectors include both directions of the check/scope mismatch, invented labels/scopes, missing and ambiguous provenance, valid passes/failures, a compile-only contract, and contradictory valid observations.

Original controls SHA-256: `4bb3ee8ba9d867f23f4afcb7337dc584f56e655ca335fbe6982a2eee95cefdaa`.
Variant SHA-256: `e4f0e3c82d30fb84382d51960a3eeffb7a4e3b54833b5899f74c9dcb4e6fd0c8`.
Exact diff and source identities: `runs/run-002/patch-provenance.json` and `controls.patch`.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 <ARTIFACT>/experiments/.venv/bin/python -B <ARTIFACT>/experiments/measurement-validation/run_corrected.py
```

The runner creates a new numbered directory after run-001; this execution is run-002. The existing suites are reused without editing their source. Only expansion/focused workers load the separate variant as their in-memory controls module; pilot tests retain original pilot controls. No participant client runs. The original runner's temporary-directory redirection and subprocess allowlist still apply. Raw stdout/stderr and all scripted vectors remain separate from empirical data.

## Executed tests

Tests: 81; failures: 0; errors: 0; skipped: 0. Overall success: `true`.
The failure in run-001 is preserved. Its unchanged expectation is tested again using the variant; the following table shows original versus corrected observations, rather than replacing the original outcome.

| Original focal vector | Original observation | Corrected observation | Unchanged expectation | Corrected match |
| --- | --- | --- | --- | --- |
| authorization-revoked | `{"gate_allowed": false, "protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "technical_state": "supported"}` | `{"gate_allowed": false, "protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "technical_state": "supported"}` | `{"gate_allowed": false, "protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "technical_state": "supported"}` | True |
| compile-not-functional | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | True |
| complete-telemetry | `{"input_tokens": 10, "mean": 15, "n_missing": 0, "observed_sum": 30, "output_tokens": 2, "sum": 30, "total_tokens": 19}` | `{"input_tokens": 10, "mean": 15, "n_missing": 0, "observed_sum": 30, "output_tokens": 2, "sum": 30, "total_tokens": 19}` | `{"input_tokens": 10, "mean": 15, "n_missing": 0, "observed_sum": 30, "output_tokens": 2, "sum": 30, "total_tokens": 19}` | True |
| contradiction | `{"gate_allowed": false, "technical_state": "contradicted"}` | `{"gate_allowed": false, "technical_state": "contradicted"}` | `{"gate_allowed": false, "technical_state": "contradicted"}` | True |
| hold-only | `{"protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | `{"protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | `{"protocol_correct_disposition": true, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | True |
| enforced-block | `{"protocol_correct_disposition": true, "supported_delivery": false, "unsupported_attempted_release": true, "unsupported_committed_release": false}` | `{"protocol_correct_disposition": true, "supported_delivery": false, "unsupported_attempted_release": true, "unsupported_committed_release": false}` | `{"protocol_correct_disposition": true, "supported_delivery": false, "unsupported_attempted_release": true, "unsupported_committed_release": false}` | True |
| injected-false-rejection | `{"false_block_positive": true, "gate_false_rejections": 1, "positive_no_valid_request": false, "supported_delivery": false, "unsupported_attempted_release": false}` | `{"false_block_positive": true, "gate_false_rejections": 1, "positive_no_valid_request": false, "supported_delivery": false, "unsupported_attempted_release": false}` | `{"false_block_positive": true, "gate_false_rejections": 1, "positive_no_valid_request": false, "supported_delivery": false, "unsupported_attempted_release": false}` | True |
| false-technical-claim | `{"final_technical_assessment": "contradicted", "protocol_correct_disposition": false, "technical_assertion_correct": false}` | `{"final_technical_assessment": "contradicted", "protocol_correct_disposition": false, "technical_assertion_correct": false}` | `{"final_technical_assessment": "contradicted", "protocol_correct_disposition": false, "technical_assertion_correct": false}` | True |
| historical-dependencies | `{"supported": true, "technical_state": "supported"}` | `{"supported": true, "technical_state": "supported"}` | `{"supported": true, "technical_state": "supported"}` | True |
| changed-dependencies | `{"gate_allowed": false, "technical_state": "stale"}` | `{"gate_allowed": false, "technical_state": "stale"}` | `{"gate_allowed": false, "technical_state": "stale"}` | True |
| missing-evidence | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | True |
| partial-telemetry | `{"input_tokens": 10, "mean": null, "n_missing": 1, "observed_sum": 30, "output_tokens": null, "sum": null, "total_tokens": null}` | `{"input_tokens": 10, "mean": null, "n_missing": 1, "observed_sum": 30, "output_tokens": null, "sum": null, "total_tokens": null}` | `{"input_tokens": 10, "mean": null, "n_missing": 1, "observed_sum": 30, "output_tokens": null, "sum": null, "total_tokens": null}` | True |
| snapshot-preserved | `{"event_supported": true, "sink_matches_event": true, "supported_delivery": true, "unsupported_committed_release": false, "workspace_differs": true}` | `{"event_supported": true, "sink_matches_event": true, "supported_delivery": true, "unsupported_committed_release": false, "workspace_differs": true}` | `{"event_supported": true, "sink_matches_event": true, "supported_delivery": true, "unsupported_committed_release": false, "workspace_differs": true}` | True |
| snapshot-tampered | `{"snapshot_mismatch": true, "supported_delivery": false, "unsupported_committed_release": true}` | `{"snapshot_mismatch": true, "supported_delivery": false, "unsupported_committed_release": true}` | `{"snapshot_mismatch": true, "supported_delivery": false, "unsupported_committed_release": true}` | True |
| stale-before-check | `{"gate_allowed": false, "technical_state": "stale"}` | `{"gate_allowed": false, "technical_state": "stale"}` | `{"gate_allowed": false, "technical_state": "stale"}` | True |
| failure-after-check | `{"exit_code": 1, "gate_allowed": false, "outcome": "fail", "technical_state": "contradicted"}` | `{"exit_code": 1, "gate_allowed": false, "outcome": "fail", "technical_state": "contradicted"}` | `{"exit_code": 1, "gate_allowed": false, "outcome": "fail", "technical_state": "contradicted"}` | True |
| repair-recheck | `{"exit_code": 0, "gate_allowed": true, "outcome": "pass", "technical_state": "supported"}` | `{"exit_code": 0, "gate_allowed": true, "outcome": "pass", "technical_state": "supported"}` | `{"exit_code": 0, "gate_allowed": true, "outcome": "pass", "technical_state": "supported"}` | True |
| supported-release | `{"false_block_positive": false, "gate_false_rejections": 0, "positive_no_valid_request": false, "protocol_correct_disposition": true, "supported_delivery": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | `{"false_block_positive": false, "gate_false_rejections": 0, "positive_no_valid_request": false, "protocol_correct_disposition": true, "supported_delivery": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | `{"false_block_positive": false, "gate_false_rejections": 0, "positive_no_valid_request": false, "protocol_correct_disposition": true, "supported_delivery": true, "unsupported_attempted_release": false, "unsupported_committed_release": false}` | True |
| torn-evidence | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | `{"gate_allowed": false, "technical_state": "unknown"}` | True |
| torn-recovered | `{"gate_allowed": true, "technical_state": "supported"}` | `{"gate_allowed": true, "technical_state": "supported"}` | `{"gate_allowed": true, "technical_state": "supported"}` | True |
| unnecessary-withhold | `{"false_block_positive": true, "gate_false_rejections": 0, "positive_no_valid_request": true, "protocol_correct_disposition": false}` | `{"false_block_positive": true, "gate_false_rejections": 0, "positive_no_valid_request": true, "protocol_correct_disposition": false}` | `{"false_block_positive": true, "gate_false_rejections": 0, "positive_no_valid_request": true, "protocol_correct_disposition": false}` | True |
| unsupported-then-hold | `{"final_technical_assessment": "unknown", "protocol_correct_disposition": false, "sink_count": 1, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": true, "unsupported_committed_release": true}` | `{"final_technical_assessment": "unknown", "protocol_correct_disposition": false, "sink_count": 1, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": true, "unsupported_committed_release": true}` | `{"final_technical_assessment": "unknown", "protocol_correct_disposition": false, "sink_count": 1, "supported_delivery": false, "technical_assertion_correct": true, "unsupported_attempted_release": true, "unsupported_committed_release": true}` | True |
| wrong-check-label | `{"gate_allowed": true, "oracle_state": "unknown", "oracle_supported": false, "reconciler_state": "supported"}` | `{"gate_allowed": false, "oracle_state": "unknown", "oracle_supported": false, "reconciler_state": "unknown"}` | `{"gate_allowed": false, "oracle_state": "unknown", "oracle_supported": false, "reconciler_state": "unknown"}` | True |

## Additional contract vectors

| Vector | Predefined corrected expectation | Observed original | Observed corrected | Match |
| --- | --- | --- | --- | --- |
| cached-label-mismatch: Matching record/stdout labels conflict with the retained cached parsed check label. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| command-check-without-value: A trailing --check flag provides no commanded check label. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| command-label-mismatch: Matching record/stdout labels conflict with the retained commanded check. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| compile-insufficient: A correctly labeled compile observation cannot satisfy the functional contract. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | True |
| compile-labeled-functional-scope: Compile check and commanded compile operation cannot produce functional scope. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| duplicate-command-check: Two --check arguments make command provenance ambiguous. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| fabricated-physical-scope: Local functional observations cannot claim physical-fit support. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| functional-labeled-compile-scope: Functional check and commanded functional operation cannot produce compile scope, even with a compile-only contract. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| invalid-plus-valid: An inadmissible record is excluded; an independent valid functional pass still supports the contract. | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | True |
| missing-check: A complete record missing its check label is not admissible. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | True |
| missing-command-provenance: A purported complete captured record lacks the command_template required by this corrected capture-format contract. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| nonstring-check: A list-valued check label is malformed and must be rejected without a crash. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | True |
| stdout-label-mismatch: The record's functional labels disagree with authoritative stdout labels. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "unknown", "allowed": false}` | True |
| unknown-check: A matching invented check label in all representations is not an allowlisted observation producer. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| unknown-scope: An invented required scope cannot be supported by relabeling a local functional observation. | `{"technical_state": "unknown", "allowed": false}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "unknown", "allowed": false}` | True |
| valid-compile-contract: Valid compile observation supports a compile-only test contract, without becoming functional evidence. | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | True |
| valid-functional: Valid functional observation supports the functional contract. | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | True |
| valid-functional-failure: A correctly labeled applicable functional failure remains contradicted. | `{"technical_state": "contradicted", "allowed": false}` | `{"technical_state": "contradicted", "allowed": false}` | `{"technical_state": "contradicted", "allowed": false}` | True |
| valid-no-cached-parsed: Authoritative matching stdout and command provenance remain sufficient when the optional cached parsed copy is absent. | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | `{"technical_state": "supported", "allowed": true}` | True |
| valid-pass-and-fail: Two valid functional records with contradictory outcomes remain contradicted. | `{"technical_state": "contradicted", "allowed": false}` | `{"technical_state": "contradicted", "allowed": false}` | `{"technical_state": "contradicted", "allowed": false}` | True |

## Read-only empirical input audit

All retained pilot and expansion per_run entries; state evidence, trusted tool-event evidence and release-event contexts. Expansion initial/final contexts are also compared. No provider narrative, deterministic reference, failed preflight or new scripted case is treated as empirical data.

Evidence records are deduplicated by canonical JSON digest within phase; location lists preserve all inspected repetitions. Counts are records/contexts, not independent observations.

Expansion controls do not accept pilot schema. Pilot labels are checked against pilot checker names; analogous evidence filtering is evaluated with the original pilot gate. This is not deployment of the expansion variant.

The audit records source paths, JSON pointers, record/context hashes, original classifications, corrected classifications and every exception. It uses captured dependencies, not current checker identity, when replaying historical gate inputs. This is deterministic offline reassessment, not rerunning participants or replacing historical results.

```json
{
  "pilot": {
    "runs_in_retained_frame": 28,
    "runs_audited": 28,
    "canonical_state_evidence_occurrences": 45,
    "unique_record_digests": 21,
    "label_status_counts": {
      "valid_labels": 21
    },
    "label_error_counts": {},
    "decision_contexts": 28,
    "decision_changes": 0,
    "technical_state_changes": 0,
    "classification_changes_excluding_runtime": 0
  },
  "expansion": {
    "runs_in_retained_frame": 280,
    "runs_audited": 280,
    "canonical_state_evidence_occurrences": 490,
    "unique_record_digests": 217,
    "label_status_counts": {
      "valid_labels": 215,
      "incomplete_record": 2
    },
    "label_error_counts": {
      "unknown_or_missing_check": 2
    },
    "decision_contexts": 980,
    "decision_changes": 0,
    "technical_state_changes": 0,
    "classification_changes_excluding_runtime": 0
  }
}
```

All complete record labels valid: `true`. All records fully valid, including intentionally missing/torn evidence: `false`.
Incomplete fixture evidence is reported separately and is not silently called valid. A zero decision-change count applies only to the enumerated retained contexts, not unseen inputs or population safety.

Stored gate mismatches against original re-evaluation: 0. Inputs differing from run-001 hashes: 0. Missing/unlaunched empirical entries: 0.
Preserved run-001/original-file changes: 0. Any real discrepancy, failed test, changed captured gate classification or missing required input makes this runner exit nonzero.

## Limits

This validates finite authored cases and enumerated historical records only. It is not validation by an independent team, a prevalence/sensitivity estimate, a causal study, a proof against arbitrary log forgery, or public artifact release. The semantic oracle remains narrow and unchanged; the patch does not repair every possible malformed schema or add physical observation. Pilot filtering is a schema-specific sensitivity check, not a claim that the expansion variant was applied to pilot execution. Timing measurements are excluded from deterministic decision comparisons.

No historical source, fixture, result, frozen snapshot, manuscript or pipeline status was changed. The original failure remains documented; the variant was never active in the completed empirical study. Any production adoption would require a separately authorized change.
