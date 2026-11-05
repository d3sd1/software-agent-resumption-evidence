#!/usr/bin/env python3
"""Offline historical + access-cohort reanalysis from fresh isolated local copies."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def read(p):
    return json.loads(p.read_text())


def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify():
    manifest=read(ROOT/'export-manifest.json')
    expected={r['path'] for r in manifest['files']}|{'export-manifest.json'}
    actual={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and not any(p.is_relative_to(ROOT/n) for n in ['.git','.venv','_offline_output'])}
    if expected!=actual:
        raise RuntimeError('Unexpected/missing files in artifact payload')
    for r in manifest['files']:
        p=ROOT/r['path']
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or sha(p)!=r['export_sha256']:
            raise RuntimeError('Public manifest mismatch: '+r['path'])
    return manifest


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'_offline_output')
    args=parser.parse_args();output=args.output.resolve()
    manifest=verify()
    if output.exists() or ROOT.is_relative_to(output) or output.is_relative_to(ROOT/'experiments'):
        raise RuntimeError('Output must be new and must not replace/modify artifact inputs')
    output.mkdir(parents=True);(output/'empty-home').mkdir()
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(output/'empty-home'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0'}
    initial={r['path']:sha(ROOT/r['path']) for r in manifest['files']}
    def run(name,args):
        result=subprocess.run([sys.executable,'-I','-B',*map(str,args)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=600)
        for suffix,text in [('stdout',result.stdout),('stderr',result.stderr)]:
            (output/(name+'-'+suffix+'.txt')).write_text(text.replace(str(output),'<REANALYSIS>').replace(str(ROOT),'<ARTIFACT>'))
        return {'job':name,'exit_code':result.returncode}
    jobs=[run('historical',[ROOT/'reproduce_historical.py','--output',output/'historical'])]
    access=output/'access-phase/experiments/access-study'
    shutil.copytree(ROOT/'experiments/access-study',access)
    shutil.copytree(ROOT/'experiments/access-analysis',access.parent/'access-analysis')
    shutil.copyfile(ROOT/'access-redaction-map.json',access/'release-redaction-map.json')
    jobs.append(run('access-tests',[ROOT/'access_release_adapter.py','--job','tests','--root',access]))
    jobs.append(run('access-evaluate',[ROOT/'access_release_adapter.py','--job','evaluate','--root',access]))
    jobs.append(run('access-assets',[ROOT/'access_release_adapter.py','--job','assets','--root',access]))
    expected=read(ROOT/'experiments/access-study/collections/cohort-001/evaluation.json')
    comparison=read(access/'release-proof/evaluate/evaluation-comparison.json') if (access/'release-proof/evaluate/evaluation-comparison.json').exists() else None
    tests=read(access/'release-proof/tests/test-results.json') if (access/'release-proof/tests/test-results.json').exists() else None
    tamper=read(access/'release-proof/evaluate/tamper-tests.json') if (access/'release-proof/evaluate/tamper-tests.json').exists() else None
    historical=read(output/'historical/offline-reproduction-receipt.json') if (output/'historical/offline-reproduction-receipt.json').exists() else None
    final={r['path']:sha(ROOT/r['path']) for r in manifest['files']}
    passed=all(j['exit_code']==0 for j in jobs) and initial==final
    receipt={'successful':passed,'jobs':jobs,'historical_successful':historical.get('successful') if historical else None,
             'access_evaluation':comparison,'access_tests':tests,'tamper_tests':tamper,
             'access_assignments':len(expected['rows']),'access_contrasts':len(expected['contrasts']),
             'source_payload_unchanged':initial==final,'credentials_inherited_by_workers':False,'model_calls':0,'network_calls':0,
             'limits':['Native hashes verify explicitly re-sealed derivatives. Original seals remain in the lineage; withheld original text cannot be independently authenticated from public derivatives.',
                       'Original UTF-8 byte lengths, timestamps and classified observations are not changed.',
                       'All 66 access tests execute. Only the two exact authorized negative CLI invocations omit their enabling flags and use dummy absent paths; no collection/freeze/preflight/model operation is authorized.',
                       'This is export/reproduction verification, not a replacement for the independent scientific audit.',
                       'No new version identifier, publication or external API action is performed.']}
    save(output/'extended-offline-receipt.json',receipt)
    print(json.dumps({'successful':passed,'jobs':jobs,
                      'access_derived_evaluation_equal':comparison.get('exact_full_derived_evaluation_equal') if comparison else None,
                      'original_scientific_values_equal':comparison['comparison_with_original']['scientific_values_equal'] if comparison else None,
                      'explicit_provenance_hash_substitutions':len(comparison['comparison_with_original']['explicit_seal_substitution_paths']) if comparison else None,
                      'access_test_counts':tests.get('counts') if tests else None,
                      'tamper_tests':tamper,'historical_successful':receipt['historical_successful'],'source_payload_unchanged':initial==final,
                      'model_calls':0,'credentials_inherited_by_workers':False},indent=2))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
