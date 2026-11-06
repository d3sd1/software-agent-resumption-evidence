# Audit addendum to the post-review diagnostics

Date: 2026-11-06. Scope: interpretation of retained `run-003` and its original scripts, not a replacement execution or a change to historical scoring.

A separate implementation reviewer inspected the plan, scripts, outputs, 32 witness event chains, and 24 semantic probes. Their supplied verifier invocation passed all 18 checks; the receipt is `output-verification-independent-20261106.json`. The reviewer nevertheless found two limitations not covered by those checks. This addendum supersedes broader interpretations of the original report, while preserving that report and all executed inputs and outputs.

## Partial event projection, not complete verification record

`plan.json` describes commit identity as part of `full_event`. In `scripts/run_followup.py`, `generic_views` instead emits request/commit eligibility sequences, reduced final fields, current eligibility, and completeness flags. `final_view` omits `release_id`. Thus the emitted projection does not fulfill the identity portion of the plan.

The reviewer changed only the final release identifier of a preserved witness in memory; the emitted projection stayed identical. This demonstrates why that projection must not be described as sufficient for the full C completion rule. The source also makes the distinction explicit: `full_positive` is obtained from `oracle.evaluate` on the complete retained records, not computed from the emitted projection.

The paper therefore calls this view an **event summary**, while retaining the original machine key `full_event` for provenance. The 160 positive-indicator agreements remain agreements among a reduced terminal indicator, a committed-eligibility indicator, and a separately evaluated complete-record outcome. They do not prove sufficiency of the event summary. The three retained control pairs still differ or agree in the emitted fields as recorded; they are not competitor comparisons.

No historical misclassification has been established by this omission. No source, plan, output, or original count was rewritten to make the implementation appear to have matched the plan.

## Restricted information subset, not the entire visible prefix

The dependency counterfactual preserves G's initial prompt, contract document, and workspace document. However, the decision function first requests `list_context`, which exposes document lengths. The reviewer observed dependency-document lengths of 992 bytes in the baseline and 954 bytes in the counterfactual. Therefore the full directory responses differ.

The preserved pair supports only the narrow equality of the explicitly selected prompt/contract/workspace subset. It does not demonstrate indistinguishability of the complete policy-visible prefix. A length difference alone does not identify a valid binding, but its presence invalidates a stronger equality claim. The manuscript states this limitation and does not infer a lower bound or an exclusive advantage for P.

The observed 32 sufficient paths remain conditional on their declared trust assumptions. P/U/distributed retrieves contract and workspace only; the other cells retrieve all four documents. None establishes model behavior, optimality, independent research-team replication, or general transfer.

## Publication boundary

Any public follow-up package must include this addendum or an equivalent explicit correction. The existing v2 archive and v2.0.2 source tag remain unchanged. This addendum does not authorize publication of the manuscript or claim that the follow-up package has already been published.
