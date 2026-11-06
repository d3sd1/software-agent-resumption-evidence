# Post-review diagnostic overlay (version 2.1.0)

This directory adds a bounded, deterministic diagnostic analysis to the unchanged version 2.0.0 archive (DOI 10.5281/zenodo.23981216). It contains no new model-participant sessions and does not modify any recipient observation from the three archived cohorts.

## Read this first: `audit-addendum.md` controls interpretation

A separate code audit found two limitations that the 18 output-consistency checks do not detect. The addendum supersedes broader readings of `report.txt`:

1. The machine key `full_event` is an incomplete **event summary**. It omits commit and final release identities that the written plan said it would keep. Successful completion is evaluated separately from the complete archived records; it is not reconstructed from this summary.
2. The dependency counterfactual keeps the G prompt, `contract.json` and `workspace.json` identical. The directory response still differs (dependency document length 992 versus 954 bytes). The pair therefore does not show that the complete policy-visible prefix is indistinguishable, and it is not a lower bound over retrieval policies.

Passing the verifier means the outputs are internally consistent. It does not mean that every planned measurement was implemented.

## Contents

- `plan.json`, `expectations.json`: scope and expected classifications, written before the new probes and after all recipient observations.
- `semantic-map.json`: phase-specific field meanings and delivery obligations.
- `scripts/run_followup.py`: extraction of retained controls, copied-instrument probes, information-grounded witness paths and reduced-view projections.
- `scripts/verify_outputs.py`: read-only consistency checks.
- `inputs/retained-C-controls.json`: aggregate receipt of the already executed C feasibility controls. It was not in the v2.0.0 archive. Its SHA-256 equals the hash that the archived capsule manifest declares for `local-validation.json`; the script refuses to run otherwise.
- `results/run-003/`: the retained CSV/JSON outputs, summary and execution log of the original run.
- `report.txt`: full English report (read together with the addendum).
- `cleanroom-reproduction-receipt.json`: record of a reconstruction from the public v2.0.0 ZIP.

Bulky per-path event chains and copied third-party snapshots are not distributed here; the script regenerates them from the archive.

## Reproduce

Requires Python 3.14 (standard library only) and the extracted version 2.0.0 archive.

```sh
python3 -I -B scripts/run_followup.py \
  --artifact /path/to/software-agent-resumption-evidence-v2.0.0 \
  --controls-receipt inputs/retained-C-controls.json \
  --output run-new
python3 -I -B scripts/verify_outputs.py --results run-new --receipt verification-new.json
```

The output directory must be new and inside this directory. No credentials, network access or model calls are used. In the recorded clean-copy reconstruction all eight CSV outputs were byte-identical to `results/run-003/`; only `runtime_seconds` differed in the summary. The generated `inputs-before.json` and `inputs-after.json` contain absolute local paths of the machine that runs the script.

## Scope

These are post-hoc instrument analyses: 24 final-field probes, 96 extracted control rows, 32 deterministic witness paths, one logical counterfactual pair and projections of retained records. They are not recipient evidence and do not establish optimality, an exclusive advantage for P, general benchmark utility, independent-team replication or deployment safety.

## License

The MIT license in this repository applies to the scripts and authored documentation. Archived third-party software referenced through the v2.0.0 archive keeps its own notices; see `RIGHTS.md` at the repository root.
