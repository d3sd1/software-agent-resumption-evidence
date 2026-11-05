#!/usr/bin/env python3
"""Offline reanalysis of a sanitized, standalone research-artifact release.

Python standard library only. No models, credentials, external tools or downloads.
Original artifacts remain read-only; all execution happens in a fresh copy.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def isolated_worker(job, experiments, output):
    """Inspected entry points only; never invoke historical execution runners."""
    sys.dont_write_bytecode = True
    # Force the audited Popen path; otherwise Python may use a second spawn event.
    subprocess._USE_POSIX_SPAWN = False
    allowed_scripts = {experiments / 'checker.py', experiments / 'mcp_server.py', experiments / 'expansion/checker.py'}
    runtime_roots = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind', 'os.system', 'os.posix_spawn', 'os.exec'}:
            raise RuntimeError('Network or non-allowlisted execution disabled')
        if event == 'subprocess.Popen':
            cmd = args[1]
            if not isinstance(cmd, (list, tuple)) or Path(cmd[0]).resolve() != Path(sys.executable).resolve():
                raise RuntimeError('Only inspected local Python subprocesses are permitted')
            paths = [Path(a).resolve() for a in cmd[1:] if isinstance(a, str) and a.endswith('.py')]
            if not paths or paths[0] not in allowed_scripts and not (paths[0].name == 'fake_client.py' and paths[0].is_relative_to(experiments)):
                raise RuntimeError('Unreviewed subprocess entry point')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1], args[2]
            writing = any(c in (mode or '') for c in 'wax+') or isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and not p.is_relative_to(experiments):
                raise RuntimeError('Write outside disposable experiment copy')
            if not writing and not p.is_relative_to(experiments) and not any(p.is_relative_to(r) for r in runtime_roots) and p not in {Path('/dev/null'), Path(__file__).resolve()}:
                raise RuntimeError('Read outside artifact copy and Python runtime')
    sys.addaudithook(audit)
    validation = experiments / 'measurement-validation'
    if job in {'pilot-evaluate', 'aggregate', 'actions'}:
        sys.path.insert(0, str(experiments))
        script = {'pilot-evaluate': 'evaluate.py', 'aggregate': 'aggregate_phases.py', 'actions': 'analyze_action_paths.py'}[job]
        if job == 'actions':
            (experiments / 'figures').mkdir(exist_ok=True)
        runpy.run_path(str(experiments / script), run_name='__main__')
        if job == 'aggregate':
            helper = load('phase_summary_validator', experiments / 'reproduce_offline.py')
            helper.validate_phase_summary(read(experiments / 'results/aggregated_results.json'),
                                          read(experiments / 'results/pilot_reanalysis.json'),
                                          read(experiments / 'results/expanded_results.json'))
        return 0
    if job in {'expansion-evaluate', 'reference-score'}:
        sys.path.insert(0, str(experiments / 'expansion'))
        evaluator = load('release_expansion_evaluator', experiments / 'expansion/evaluate.py')
        if job == 'expansion-evaluate':
            evaluator.evaluate_all()
        else:
            old = read(experiments / 'expansion/reference/results.json')
            config = read(experiments / 'expansion/config-v2.json')
            rows = []
            for row in old['per_run']:
                folder = (experiments / 'expansion' / row['events_path']).parent
                # The historical controller explicitly records these assignment fields.
                cell = {k: row[k] for k in ['case_id', 'family', 'fixture_order_seed', 'opaque_id', 'id', 'arm'] if k in row}
                rows.append(evaluator.score(cell, folder, config, is_model=False))
            save(output / 'reference-recomputed.json', rows)
        return 0
    if job in {'empirical', 'contract', 'corrected-focused', 'corrected-expansion'}:
        corrected = load('release_corrected_validation', validation / 'run_corrected.py')
        if job == 'empirical':
            current_path = experiments / 'results/expanded_results.json'
            historical_path = experiments / 'results/aggregate-history/previous-expanded-results.json'
            current_bytes = current_path.read_bytes()
            historical_bytes = historical_path.read_bytes()
            current, historical = json.loads(current_bytes), json.loads(historical_bytes)
            if not equal_science(current, historical, ['evaluated_at']):
                raise RuntimeError('Historical audit frame contains different scientific observations')
            baseline = read(validation / 'runs/run-001/protected-before.json')
            if hashlib.sha256(historical_bytes).hexdigest() != baseline['results/expanded_results.json']:
                raise RuntimeError('Historical audit frame does not match original protected hash')
            try:
                current_path.write_bytes(historical_bytes)
                result = corrected.empirical_audit(output)
            finally:
                current_path.write_bytes(current_bytes)
            save(output / 'audit-frame-provenance.json', {
                'historical_frame_sha256': hashlib.sha256(historical_bytes).hexdigest(),
                'current_frame_sha256': hashlib.sha256(current_bytes).hexdigest(),
                'only_permitted_difference': 'evaluated_at', 'scientific_fields_exactly_equal': True,
                'current_frame_restored': current_path.read_bytes() == current_bytes,
                'scope': 'Historical empirical audit frame restored only in disposable copy; original candidate unchanged.'})
            return 0 if result['successful'] else 1
        if job == 'contract':
            return corrected.contract_worker(output)
        sys.modules['controls'] = corrected.FIXED
        return corrected.BASE.worker('focused' if job == 'corrected-focused' else 'expansion', output)
    base = load('release_validation_base', validation / 'run_validation.py')
    if job == 'phase-summary-tests':
        module = load('phase_summary_tests', experiments / 'test_phase_summary.py')
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=base.RecordedResult).run(suite)
        save(output / 'test-results.json', {'group': job, 'tests_run': result.testsRun,
                                          'successful': result.wasSuccessful(), 'records': result.records})
        return 0 if result.wasSuccessful() else 1
    if job == 'pilot-tests':
        original = base.load_module
        def load_with_explicit_skip(name, path):
            module = original(name, path)
            if path.name == 'tests_audit_fixes.py':
                test = module.AuditFixTests.test_preserved_pilot_source_and_raw_files
                module.AuditFixTests.test_preserved_pilot_source_and_raw_files = unittest.skip(
                    'Full raw-byte preservation cannot be tested on a projected release; see manifest coverage. No scientific test is skipped.')(test)
            return module
        base.load_module = load_with_explicit_skip
        return base.worker('pilot', output)
    return base.worker('expansion' if job == 'expansion-tests' else 'focused', output)


def equal_science(old, new, excluded=()):
    """Exact recursive equality after removing ONLY explicitly named root fields."""
    return {k: v for k, v in old.items() if k not in excluded} == {k: v for k, v in new.items() if k not in excluded}


def observations(rows):
    return {r['id']: {k: r[k] for k in ['expected', 'observed', 'matches_expectation']} for r in rows}


def verify_manifest():
    manifest = read(ROOT / 'export-manifest.json')
    missing, changed = [], []
    for item in manifest['files']:
        p = ROOT / item['path']
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
            raise RuntimeError('Unsafe artifact path')
        if not p.is_file():
            missing.append(item['path'])
        elif digest(p) != item['export_sha256']:
            changed.append(item['path'])
    if missing or changed:
        raise RuntimeError('Artifact manifest mismatch; no reanalysis performed')
    expected = {item['path'] for item in manifest['files']} | {'export-manifest.json'}
    # Root Git metadata is administrative, not scientific payload. Nested .git
    # paths and arbitrary added files remain subject to the strict inventory.
    actual = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
              if p.is_file() and not p.is_relative_to(ROOT / '.git')
              and not p.is_relative_to(ROOT / '.venv') and not p.is_relative_to(ROOT / '_offline_output')}
    if actual != expected:
        raise RuntimeError('Unexpected files in artifact payload; use a clean package')
    return manifest


def coverage(experiments, manifest):
    covered = {r['path']: r for r in manifest['files']}
    report = {}
    def check(name, pairs):
        entries = []
        for relative, expected in pairs:
            p = experiments / relative
            exported = covered.get('experiments/' + relative)
            status = 'omitted' if not p.exists() else 'original-bytes-verified' if digest(p) == expected else 'derived-bytes-not-historical'
            if status == 'derived-bytes-not-historical' and (not exported or exported['status'] != 'derived-copy'):
                raise RuntimeError('Unexplained historical hash mismatch: ' + relative)
            entries.append({'path': relative, 'status': status})
        report[name] = {'counts': dict(Counter(e['status'] for e in entries)), 'entries': entries}
    pilot = experiments / 'snapshots/pilot-v1'
    check('pilot_protected', read(pilot / 'protected-artifacts.json').items())
    check('pilot_snapshot_source', [('snapshots/pilot-v1/source/' + n, h) for n, h in read(pilot / 'snapshot.json')['source_hashes'].items()])
    frozen = read(experiments / 'expansion/frozen/manifest.json')
    pairs = [('expansion/' + n, h) for n, h in frozen['fixture_hashes'].items()]
    pairs += [('expansion/frozen/source/' + n, h) for n, h in frozen['source_hashes'].items()]
    pairs += [('expansion/' + cell['prompt'], cell['prompt_sha256']) for cell in frozen['planned']]
    pairs += [('expansion/frozen/system-prompt.txt', frozen['system_prompt_sha256'])]
    check('expansion_frozen', pairs)
    if any(x['status'] != 'original-bytes-verified' for x in report['expansion_frozen']['entries']):
        raise RuntimeError('Expansion freeze is incomplete or changed')
    return report


def reproduce(output):
    manifest = verify_manifest()
    if output.exists():
        raise RuntimeError('Output must be new; never overwrite a previous reproduction')
    if output.is_relative_to(ROOT / 'experiments') or ROOT.is_relative_to(output):
        raise RuntimeError('Output must not contain or replace the artifact payload')
    output.mkdir(parents=True)
    experiment_copy = output / 'standalone-copy/experiments'
    shutil.copytree(ROOT / 'experiments', experiment_copy)
    before = {r['path']: digest(ROOT / r['path']) for r in manifest['files']}
    hashes = coverage(experiment_copy, manifest)
    save(output / 'historical-hash-coverage.json', hashes)
    originals = {name: read(experiment_copy / 'results' / name) for name in ['pilot_reanalysis.json', 'expanded_results.json', 'aggregated_results.json', 'action_path_analysis.json']}
    settings = read(experiment_copy / 'expansion/config-v2.json')
    jobs = ['pilot-tests', 'expansion-tests', 'original-focused', 'corrected-expansion', 'corrected-focused', 'contract',
            'empirical', 'reference-score', 'phase-summary-tests', 'pilot-evaluate', 'expansion-evaluate', 'aggregate', 'actions']
    records = []
    # Only this clean environment reaches child processes. No inherited account state.
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(output / 'empty-home'), 'LANG': 'C.UTF-8',
                   'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0', 'TMPDIR': str(experiment_copy)}
    (output / 'empty-home').mkdir()
    for job in jobs:
        folder = experiment_copy / 'measurement-validation/release-rerun' / job
        folder.mkdir(parents=True)
        command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker', job,
                   '--experiments', str(experiment_copy), '--output', str(folder)]
        done = subprocess.run(command, cwd=experiment_copy, env=environment, capture_output=True, text=True, timeout=240)
        # No content from original provider traces is read or printed by these workers.
        for label, text in [('stdout', done.stdout), ('stderr', done.stderr)]:
            text = text.replace(str(output), '<REANALYSIS>').replace(str(ROOT), '<ARTIFACT>')
            (folder / (label + '.txt')).write_text(text, encoding='utf-8')
        result = read(folder / 'test-results.json') if (folder / 'test-results.json').exists() else None
        records.append({'job': job, 'exit_code': done.returncode,
                        'tests_run': result.get('tests_run') if result else None,
                        'test_status_counts': dict(Counter(r['status'] for r in result['records'])) if result else None})
    base = experiment_copy / 'measurement-validation'
    comparisons = {}
    for name in ['pilot_reanalysis.json', 'expanded_results.json']:
        comparisons[name] = equal_science(originals[name], read(experiment_copy / 'results' / name), ['evaluated_at'])
    comparisons['aggregated_results.json'] = equal_science(originals['aggregated_results.json'], read(experiment_copy / 'results/aggregated_results.json'), ['created_at'])
    action = read(experiment_copy / 'results/action_path_analysis.json')
    comparisons['action_path_analysis.json'] = equal_science(originals['action_path_analysis.json'], action, ['source_sha256'])
    reference = read(experiment_copy / 'expansion/reference/results.json')['per_run']
    reference_new = read(base / 'release-rerun/reference-score/reference-recomputed.json')
    comparisons['non_model_reference_all_per_run_fields'] = reference == reference_new
    for label, original in [('original-focused', 'runs/run-001/focused/observations.json'),
                             ('corrected-focused', 'runs/run-002/focused/observations.json'),
                             ('contract', 'runs/run-002/contract/observations.json')]:
        comparisons[label + '_observations'] = observations(read(base / original)) == observations(read(base / 'release-rerun' / label / 'observations.json'))
    empirical = read(base / 'release-rerun/empirical/empirical-audit.json')
    old_empirical = read(base / 'runs/run-002/empirical-audit.json')
    comparisons['empirical_audit_exact'] = empirical == old_empirical
    frame = read(base / 'release-rerun/empirical/audit-frame-provenance.json')
    comparisons['historical_frame_science_equal_and_current_restored'] = frame['scientific_fields_exactly_equal'] and frame['current_frame_restored']
    # The known original check/scope defect MUST remain a failing historical test.
    historical = read(base / 'runs/run-001/focused/test-results.json')
    actual = read(base / 'release-rerun/original-focused/test-results.json')
    comparisons['historical_failure_classifications_preserved'] = [(r['test'].split('.')[-1], r['status']) for r in historical['records']] == [(r['test'].split('.')[-1], r['status']) for r in actual['records']]
    expected_original_exit = 0 if historical['successful'] else 1
    worker_outcomes = all(r['exit_code'] == (expected_original_exit if r['job'] == 'original-focused' else 0) for r in records)
    after = {r['path']: digest(ROOT / r['path']) for r in manifest['files']}
    successful = worker_outcomes and all(comparisons.values()) and before == after
    scientific_equal = all(value for key, value in comparisons.items() if key != 'aggregated_results.json')
    aggregate_old = originals['aggregated_results.json']['expansion']
    aggregate_new = read(experiment_copy / 'results/aggregated_results.json')['expansion']
    aggregate_difference = {key: {'retained': aggregate_old.get(key), 'recomputed': aggregate_new.get(key)}
                            for key in ['assigned', 'launched', 'action_exposed', 'complete_structured', 'execution_state']
                            if aggregate_old.get(key) != aggregate_new.get(key)}
    receipt = {'successful': successful, 'primary_scientific_reanalysis_equal': scientific_equal,
               'expected_worker_outcomes_matched': worker_outcomes,
               'historical_aggregate_mismatch': aggregate_difference,
               'aggregate_correction_provenance': 'experiments/results/aggregate-history/rebuild-completed.json',
               'empirical_audit_frame': frame,
               'model_calls': 0, 'network_calls': 0,
               'credentials_inherited': False, 'source_artifact_unchanged': before == after,
               'python_version': platform.python_version(), 'recorded_python_version': settings['python_exact'],
               'assigned_pilot': originals['pilot_reanalysis.json']['assigned'],
               'assigned_expansion': originals['expanded_results.json']['assigned'],
               'workers': records, 'comparisons': comparisons,
               'historical_original_focused_exit_expected': expected_original_exit,
               'explicit_skip': 'One raw-byte preservation test is unavailable because raw provider records are excluded. Historical coverage and new public hashes are checked separately; no scientific test/observed classification was altered.',
               'non_comparable_fields': ['results/*: evaluated_at or created_at only as specified',
                                         'action analysis: source_sha256 changes because reevaluation timestamps change'],
               'scope': 'Reanalysis of all retained factual observations and scripted validation, not rerunning model sessions or authenticating excluded provider prose.',
               'runtime_safety': 'Inspected stdlib workers; Python audit hooks block sockets, non-allowlisted subprocesses, writes outside copy and reads outside copy/Python runtime. Not an OS sandbox against adversarial code.'}
    save(output / 'offline-reproduction-receipt.json', receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if successful else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '_offline_output')
    parser.add_argument('--worker', choices=['pilot-tests', 'expansion-tests', 'original-focused', 'corrected-expansion', 'corrected-focused',
                         'contract', 'empirical', 'reference-score', 'phase-summary-tests', 'pilot-evaluate', 'expansion-evaluate', 'aggregate', 'actions'], help=argparse.SUPPRESS)
    parser.add_argument('--experiments', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not args.experiments or not args.output.resolve().is_relative_to(args.experiments.resolve()):
            parser.error('Worker output must be within the disposable copy')
        return isolated_worker(args.worker, args.experiments.resolve(), args.output.resolve())
    return reproduce(args.output.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
