# Software-agent resumption: source code

This repository contains **source code, configuration, protocols, tests and notices**, not the large observation dataset. The complete, versioned code-and-data artifact is archived in Zenodo:

- **Version 2.0.0:** [doi:10.5281/zenodo.23981216](https://doi.org/10.5281/zenodo.23981216).
- ZIP: `software-agent-resumption-evidence-v2.0.0.zip` (59,206,069 bytes).
- ZIP SHA-256: `e7ed0839e3d4347c9721ad477a0aa4e37cfda5f76cba94e8ece2c92317248f87`.

The archive contains three separate observation frames: the 28-session pilot, the 280-session diagnostic expansion, and the prospectively specified 160-session access cohort. They are not pooled into a population safety or efficacy estimate. The source-only checkout stays small; the full dataset belongs in the archive rather than the Git tree.

## Complete reproduction without contacting the author

1. Open the version-specific Zenodo record above and download the named ZIP from its Files section.
2. Verify its SHA-256 against the value above, for example with `sha256sum software-agent-resumption-evidence-v2.0.0.zip`.
3. Extract into a new directory separate from this checkout. Do not overlay Git files onto the archive: the archive binds its own code and data through its manifest.
4. From the extracted artifact root, use the recorded CPython 3.14.4 environment:

   ```sh
   python3 -m venv --without-pip .venv
   .venv/bin/python -I -B reproduce_offline.py
   ```

The offline core uses only the Python standard library. After download it needs no model client, credentials, network or new participant executions. It writes a new `_offline_output/` tree and refuses to overwrite an existing output. Optional historical PDF/SVG generation uses an existing LaTeX/Latin Modern installation; follow the archive README for those separate commands.

**A clone alone is not the complete reproducibility package.** Do not run dataset-dependent commands here expecting observations that intentionally reside in Zenodo. Missing files are not an instruction to invoke participant collection, preflight or freeze, fetch unpinned replacement data, or create a new paid route.

## Included code

The checkout provides the historical implementations/evaluators, separate corrected conformance code, access-study instrument and native integrity checks, synthetic tests and fake transport, configuration/protocol files, figure/table generators, release-verification source, and exact shared adapters with their original notices. Paths are preserved relative to the full archive. Copied source/configuration/test/adapter/license files are byte-identical to their archive counterparts; `code-manifest.json` records the explicit selection and hashes.

The manifest's `full_archive_manifest_sha256` identifies the archive's **export manifest**, not its ZIP checksum. This repository README and the code manifest are checkout-specific documentation. No recursive wildcard selected code from participant workspaces or data snapshots. Some explicitly selected adapters/notices retain capsule-compatible paths; the original `.gitignore` excludes large capsule data, so maintainers must stage only the exact allowlisted files rather than recursively forcing the full tree.

## Manuscript table presentation

Source-code revision `v2.0.1` adds `experiments/access-analysis/format_publication_tables.py` after the immutable data archive was published. It is a presentation helper, not a change to the instrument, observations or primary endpoints. It renders explicit retrieval-call headings, byte-level descriptive contrasts and linked case contracts from the unchanged archived records. The original archived presentation remains available.

From this source checkout, point the helper to the extracted v2 artifact and a new output directory:

```sh
ARCHIVE=/absolute/path/to/extracted/software-agent-resumption-evidence-v2.0.0
python3 -I experiments/access-analysis/format_publication_tables.py \
  --evaluation "$ARCHIVE/experiments/access-study/collections/cohort-001/evaluation-original.json" \
  --output ./publication-tables-new
```

It uses the standard library, reads the archived case metadata beside that evaluation, and refuses an existing output directory. Its mean/SD presentation describes five order-paired blocks; it does not create matched provider randomness, population confidence intervals or new participant measurements. `code-manifest.json` identifies this added owned helper separately from files copied byte-identically from the archive.

## Outcomes, provenance and limits

The 160-session follow-up contains supported completion in every condition, complete retrieval of all four documents, and no fresh recipient checks. Its interface-byte contrast is explained by serialization overhead and timing-string length, not a demonstrated advantage in release judgment. This does not establish equivalence, population safety, general repair ability or provider-authenticated model identity.

The public access records are explicitly re-sealed derivatives. Equal-UTF-8-length path pseudonyms preserve measured input-byte counts, categories and timestamps; provider streams, raw action strings and free-text final explanations are excluded. Original versus export hashes and the transformation lineage are retained. Native public integrity checks verify the derivatives, not withheld original text. These limits are not waived by successful offline reanalysis.

The original historical conformance defect remains an expected failing test, and one original raw-byte preservation test remains explicitly unavailable after sanitization. The extended access instrument's 66 tests, including its two negative CLI refusal tests without affirmative execution flags, are reproduced. No participant collection or freeze is created by those negative tests. The archive README and reproduction receipts distinguish all these outcomes rather than calling every historical test a pass.

## Cases and mixed licenses

The access cohort uses four pinned cases from `packaging`, `more-itertools` and `python-dotenv`. The unchanged shared adapter contains classes for eight curator candidates, but only four were used; unused classes are not additional observations. Original BSD/MIT/Apache notices apply to their respective upstream source and test adaptations. Project MIT covers independently authored study software only. `RIGHTS.md` is copied from the full artifact and describes its mixed scope, including data that are not present in this checkout. No blanket license is asserted over provider prose or unrelated third-party material.

## Preserved earlier version

Version 1.0.0 remains available at [doi:10.5281/zenodo.23977097](https://doi.org/10.5281/zenodo.23977097) and Git tag `v1.0.0` (archive commit `1d7c34f5f351708e53c2d220137f3fa01bf737f2`). It contains the earlier 28/280-session phases and their conformance record, not the later access cohort. Its Git history, tag and archived bytes are preserved. No manuscript, private parent repository, patent or originating-project asset is included in either publication.
