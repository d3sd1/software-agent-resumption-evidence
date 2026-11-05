# Evidence-bound handoffs: offline research artifacts

This **research artifact package** contains the independently authored experimental implementation, synthetic fixtures, frozen prompts, retained factual observations and controlled measurement-validation artifacts for a 28-session pilot and a 280-session diagnostic expansion. The non-model deterministic reference is separate from both participant phases. The later access study is deliberately not included. Publication status, version identifiers and archival identifiers are established by the hosting repository or deposit record, when one exists; exporting this package or running its scripts does not publish anything.

No manuscript, reference-paper PDF, originating-project asset, patent, private parent repository, authentication material or original provider transcript is part of the intended payload. Read `RIGHTS.md` before redistributing anything. The copyright notice and limited scope of the study's existing MIT license are preserved in `LICENSE` and `experiments/LICENSE`.

## Reproduce without credentials, network access or model calls

Use CPython 3.14.4 for the same interpreter version recorded by the study. The code uses only the Python standard library; no package installation, model client, LaTeX installation or author contact is needed. Another interpreter may run, but the reproduction receipt reports its version rather than claiming it is the historical environment.

From the extracted artifact directory:

```sh
python3 -m venv --without-pip .venv
.venv/bin/python -I -B reproduce_offline.py
```

The default output is a **new** `_offline_output/` directory. To run again without overwriting evidence, choose another new output directory:

```sh
.venv/bin/python -I -B reproduce_offline.py --output ../reanalysis-second-run
```

Place alternative outputs outside the artifact payload (for example `../reanalysis-second-run`) if you will run its strict payload inventory check again. The default `_offline_output/` and `.venv/` are expressly excluded from that check. Neither belongs in a release upload. Root `.git` metadata created by a local checkout is also administrative and excluded from the payload inventory, so the same command works after a clone. This exception applies only to `.git` at the package root: nested `.git` paths and arbitrary unlisted files remain rejected. Git metadata is not part of the exported scientific payload.

The command first checks the public SHA-256 manifest and refuses missing, modified or unexpected payload files. It copies the experiment tree into the selected output directory, runs the original offline evaluators and controlled test functions there, and compares the new results to the retained results. The distributed payload is not edited. The command does not execute the historical participant runners. Worker processes receive a clean environment without inherited account variables. Python audit hooks reject network connections, non-allowlisted process launches, writes outside the disposable copy and reads outside that copy or the Python runtime. These safeguards are not an operating-system sandbox for malicious code.

Read `offline-reproduction-receipt.json` and `historical-hash-coverage.json` inside the output directory. A successful receipt means that the defined scientific comparisons and expected worker outcomes matched; it does **not** mean every original validation test passed. In particular:

- The original focused validation contains a real check/scope consistency defect. Reproduction must retain its original failing classification, not suppress or repair it.
- The separate post-study corrected controls are tested separately. They were not the implementation used for the historical model sessions.
- One original raw-byte preservation test cannot run meaningfully on projected session records with excluded provider streams. It is explicitly reported as skipped, and is replaced only in scope, not in meaning, by public-file integrity checks and a historical-hash coverage inventory. No scientific test is skipped to make the release appear successful.
- All per-run observations, retained timing and token values, classifications and phase aggregates are compared exactly. Only explicitly identified reanalysis timestamps and the action-analysis hash of the timestamp-bearing result file are excluded from equality. New scripted-test timing is not substituted for retained empirical timing.
- The deterministic reference is independently rescored from its operational events, but is never pooled with model sessions.

## Historical aggregate issue — corrected with preserved provenance

The first local release candidate exposed a stale derived summary: its `aggregated_results.json` still reported zero expansion assignments despite 280 sessions in the phase results and operational records. That earlier candidate and its failing reproduction receipt are preserved separately; this package incorporates the documented correction without overwriting that failed check.

The coordinator corrected the reproduction helper to run `aggregate_phases.py`, then validate the phase counts, completion, arm metrics, family metrics, deterministic reference and explicit phase separation. The five new tests in `experiments/test_phase_summary.py` are included and executed by the root offline command. The current aggregate records 28 pilot sessions and 280 expansion sessions, with 280 expansion completions. Its canonical source hash is recorded in `experiments/results/aggregate-history/rebuild-completed.json` and checked during export.

`before-rebuild-20261105.json` preserves the exact stale aggregate; `rebuild-provenance.json` records the reason and original hash. `release-lineage.json` identifies changes between the prior and current result files. The only changes to the pilot/expansion analyses themselves are evaluation timestamps; the action-analysis input hash changes accordingly. Observed measurements and classifications do not change. The new aggregate is independently recomputed inside the disposable copy and compared against the corrected retained aggregate, excluding only its generation timestamp.

The original controlled empirical audit refers to an older evaluation timestamp. `previous-expanded-results.json` retains that exact historical result frame. Before reproducing the original audit, the offline command verifies that its scientific fields exactly match the current phase result and that its bytes match the original protected hash. It uses that frame temporarily **only inside the disposable copy**, then restores the current bytes. `audit-frame-provenance.json` records this operation. This preserves a meaningful exact comparison with the original empirical audit without pretending its historical hash applies to a later timestamp or replacing any scientific observation.

## Optional PDF and SVG figure regeneration

The generator `experiments/generate_figures.py` is included. The core reanalysis above needs neither LaTeX nor fonts. For optional figure regeneration, use an existing local `pdflatex` installation with Latin Modern and the LaTeX packages `fontenc`, `lmodern`, `xcolor` and `geometry`. No installation, model call or download is performed by the generator.

After the default offline reproduction has completed, run these commands from the artifact root. They operate on the disposable experiment copy, not the distributed payload:

```sh
E=_offline_output/standalone-copy/experiments
.venv/bin/python -I -B "$E/generate_figures.py" --results "$E/results/pilot_reanalysis.json" --label pilot
.venv/bin/python -I -B "$E/generate_figures.py" --results "$E/results/expanded_results.json" --label expanded
```

If a different reproduction output was selected, change `E` accordingly. Outputs are written under `$E/figures/`: `pilot-token-workload.pdf/.svg`, `expanded-token-workload.pdf/.svg`, underlying CSV values, derived table sources and asset metadata. PDF compilation uses `-no-shell-escape`. PDF timestamps may differ; recorded observations must not. The core reproduction receipt does not claim these optional commands were run. No manuscript compilation is required or included.

## What the package preserves

`experiments/fixtures/`, `experiments/expansion/fixtures/`, historical source snapshots and `experiments/expansion/frozen/` preserve the study inputs. The freeze checks here are file/hash checks, not a request to launch a model client or verify a subscription. `experiments/results/` preserves phase-separated observations and analyses. Operational records under the pilot runs and expansion workspaces retain action names and arguments, real local check output, evidence contexts, immutable release snapshots, structured final dispositions and measured numeric telemetry required by the evaluators. Controlled validation sources, case specifications and original/corrected observations remain under `experiments/measurement-validation/`.

Historical README files and archived source may describe the original authenticated participant execution, old authorization state or internal compilation workflow. They are provenance, not instructions for this release. **Use only the root `reproduce_offline.py` command above for offline reproduction.** There is no need to install a participant CLI, authenticate, run a preflight or execute historical `run_all.py --run` commands.

## Derived copies and historical hashes

`export-manifest.json` lists every intended payload file, its role, source hash, export hash, byte-identical or derived status, and any transformation rule. It also lists intentionally excluded source paths and their source hashes without exposing their contents. This is an audit trail, not cryptographic proof of source authenticity.

The release makes a strict distinction between original frozen bytes and derived records. Provider `session.json` objects are projected onto a documented factual field allowlist. Raw response strings, result-event objects, account/session identifiers and transport command metadata are excluded. Private filesystem prefixes in other selected copies are replaced by neutral location placeholders. Such copies are marked **derived**, never described as original frozen records. Observed measurements and enum classifications are not changed. Historical manifests are not silently rewritten with new hashes; their excluded or transformed members remain unverifiable against original bytes from this distributed package. The public export hashes verify the distributed bytes instead.

Raw provider stdin/stdout/stderr streams and bridge metadata are excluded because their privacy and redistribution rights are not established. Reanalysis of arbitrary free-text claims, private reasoning or provider identity authentication is therefore outside this package. Reproduction is of factual operational scoring, not of excluded text. The complete expansion freeze, including its prompts, synthetic fixture files and source copies, is verified separately. Any unexplained hash mismatch blocks execution.

## Interpretation limits

The pilot is descriptive feasibility. The expansion is diagnostic, not confirmatory. Fixture/order seeds vary cases and ordering; they are not controlled provider sampling seeds. A supported release is not the same as a correct hold. Zero observed unsupported releases do not establish population safety, efficacy, equivalence or superiority. Raw dollar telemetry has an unknown billing basis and is not an invoice. The corrected gate is a post-study validation variant and must not be retroactively attributed to the historical sessions.

## License, attribution and future phases

The study's software copyright is attributed to Andrei García Cuadra, 2026. MIT coverage is limited by the preserved license scope. It does not confer rights in third-party text, hosted services or model outputs. Factual logs are provided as factual research records; no new blanket copyright license for provider prose is asserted. No third-party issue or pull-request text is included merely because it appeared in a public repository. A repository's software license is not assumed to license all such text.

A future access-study release requires a separate explicit inventory, rights/privacy review and manifest. Preserve upstream author credits and license notices for any third-party component then included. Do not add that study, issue text or private assets to this package by widening a glob. Running these scripts does not publish an artifact, authorize editorial submission or certify provider terms. Consult the hosting record, rather than script execution, for publication status.
