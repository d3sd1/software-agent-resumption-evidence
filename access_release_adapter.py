#!/usr/bin/env python3
"""Verify explicitly re-sealed derivatives with unchanged native frozen evaluators.

No hashing or scoring function is patched. Equal-length pseudonymization preserves
measured UTF-8 counts. New seals are derivative-only; original seals are preserved
in a manifest-bound lineage. Scientific comparison allows only listed digest
substitutions, never changed counts, observations, classifications or timestamps.
"""
from collections import Counter
import hashlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


def load_json(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


NEGATIVE_CLI_PROBES=[]


def negative_cli_commands(root):
    """Exact authorized guard probes; no real paths or affirmative flags."""
    run=[sys.executable,'-I',str(root/'study.py'),'run','--frozen','/absent',
         '--output',str(root/'never-created'),'--authorization','/absent']
    freeze=[sys.executable,'-I',str(root/'study.py'),'freeze']
    for key in ('prepared','validation','tests','preflight','review','output'):
        freeze.extend(['--'+key,'/absent'])
    return {'run-without-flag':run,'freeze-without-flag':freeze}


def negative_cli_kind(command,root):
    if not isinstance(command,(list,tuple)):
        return None
    return next((kind for kind,expected in negative_cli_commands(root).items() if list(command)==expected),None)


def install_guard(root, assets=False, negative_cli=False):
    sys.dont_write_bytecode = True
    subprocess._USE_POSIX_SPAWN = False
    runtime = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    NEGATIVE_CLI_PROBES.clear()
    if negative_cli and (Path('/absent').exists() or (root/'never-created').exists()):
        raise RuntimeError('Negative probes require absent dummy input/output paths')
    def audit(event, args):
        if event in {'socket.connect','socket.getaddrinfo','socket.bind','os.system','os.posix_spawn','os.exec'}:
            raise RuntimeError('Network and non-allowlisted process execution disabled')
        if event == 'subprocess.Popen':
            command=args[1]
            if not isinstance(command,(list,tuple)) or Path(command[0]).resolve()!=Path(sys.executable).resolve():
                raise RuntimeError('Only the inspected Python fake transport is allowed')
            scripts=[Path(a).resolve() for a in command[1:] if isinstance(a,str) and a.endswith('.py')]
            kind=negative_cli_kind(command,root) if negative_cli else None
            if kind:
                NEGATIVE_CLI_PROBES.append({'probe':kind,'argv_exactly_allowlisted':True,'dummy_paths_only':True,
                                            'affirmative_flag_present':False,'expected_parser_exit':2})
            elif scripts != [root/'tests/fake_transport.py']:
                raise RuntimeError('Only fake transport or the two exact authorized negative CLI probes are allowed')
        if event == 'open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).resolve();mode,flags=args[1],args[2]
            write=any(c in (mode or '') for c in 'wax+') or isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
            in_assets=assets and path.is_relative_to(root.parent/'access-analysis')
            if write and not path.is_relative_to(root) and not in_assets:
                raise RuntimeError('Write outside disposable access copy')
            if not write and not path.is_relative_to(root) and not in_assets and path != Path(__file__).resolve() and path != Path('/dev/null') and not any(path.is_relative_to(r) for r in runtime):
                raise RuntimeError('Read outside disposable copy/Python runtime')
    sys.addaudithook(audit)


def scientific_comparison(original, derived, bindings):
    changed_seals=[];mismatches=[]
    def visit(a,b,pointer):
        if isinstance(a,dict) and isinstance(b,dict):
            if a.keys()!=b.keys():mismatches.append(pointer+' [keys]')
            for k in a.keys()&b.keys():visit(a[k],b[k],pointer+'/'+k)
        elif isinstance(a,list) and isinstance(b,list):
            if len(a)!=len(b):mismatches.append(pointer+' [length]')
            for i,(x,y) in enumerate(zip(a,b)):visit(x,y,pointer+'/'+str(i))
        elif type(a) is not type(b):
            mismatches.append(pointer+' [type]')
        elif a!=b:
            allowed_path=re.fullmatch(r'/rows/[0-9]+/(?:observed_prefix/)?event_audit/verified_terminal_sha256',pointer)
            if allowed_path and isinstance(a,str) and isinstance(b,str) and len(a)==len(b)==64 and bindings.get(a)==b:
                changed_seals.append(pointer)
            else:mismatches.append(pointer)
    visit(original,derived,'')
    return {'scientific_values_equal':not mismatches,'explicit_seal_substitution_paths':changed_seals,'mismatch_paths':mismatches}


def tests(root, output):
    sys.path.insert(0,str(root/'src'))
    sys.path.insert(0,str(root/'tests'))
    # Frozen tests execute unchanged, including the two expressly authorized
    # negative CLI probes. The process guard admits only their exact dummy argv.
    class Result(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.records=[]
        def addSuccess(self,t):
            super().addSuccess(t);self.records.append({'test':t.id(),'status':'PASS'})
        def addFailure(self,t,e):
            super().addFailure(t,e);self.records.append({'test':t.id(),'status':'FAIL'})
        def addError(self,t,e):
            super().addError(t,e);self.records.append({'test':t.id(),'status':'ERROR'})
        def addSkip(self,t,reason):
            super().addSkip(t,reason);self.records.append({'test':t.id(),'status':'SKIP','reason':reason})
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    probes_ok=Counter(p['probe'] for p in NEGATIVE_CLI_PROBES)=={'run-without-flag':1,'freeze-without-flag':1}
    no_output=not (root/'never-created').exists() and not Path('/absent').exists()
    passed=result.wasSuccessful() and result.testsRun==66 and not result.skipped and probes_ok and no_output
    receipt={'successful':passed,'tests_run':result.testsRun,'records':result.records,
             'counts':dict(Counter(r['status'] for r in result.records)),'explicit_scope_skips':[],
             'negative_cli_probes':list(NEGATIVE_CLI_PROBES),'exactly_two_negative_probes':probes_ok,
             'negative_probes_created_no_output':no_output,
             'model_calls':0,'transport':'FAKE only; two exact negative argparse guards also tested',
             'no_collection_freeze_preflight_or_model_operation':True}
    save(output/'test-results.json',receipt)
    (output/'test-log.txt').write_text(stream.getvalue().replace(str(root),'<ACCESS-COPY>'))
    return passed


def evaluate(root, output):
    mapping=load_json(root/'release-redaction-map.json')
    sys.path.insert(0,str(root/'src'))
    from access_study import common, oracle
    from access_study import evaluate as evaluator, messages
    collection=root/'collections/cohort-001'
    retained=load_json(collection/'evaluation.json')
    # The original evaluator refuses overwrites. Preserve expected values separately.
    (collection/'evaluation.json').rename(output/'retained-evaluation.json')
    computed=evaluator.evaluate_run(collection)
    exact=computed==retained
    original=load_json(collection/'evaluation-original.json')
    science=scientific_comparison(original,computed,mapping['source_to_export'])
    save(output/'evaluation-comparison.json',{'exact_full_derived_evaluation_equal':exact,
         'rows_equal':computed['rows']==retained['rows'],'contrasts_equal':computed['contrasts']==retained['contrasts'],
         'flow_equal':computed['flow']==retained['flow'],'row_count':len(computed['rows']),
         'contrast_count':len(computed['contrasts']),'comparison_with_original':science,
         'native_hash_functions_unmodified':True,
         'qualification':'Native hashes verify explicitly derived chains. Original seals are separately retained; withheld original strings cannot be independently authenticated from the release.'})
    # A changed byte must NOT gain validity through the correspondence table.
    chosen=next(p for p in sorted((collection/'sessions').iterdir()) if (p/'message-ledger.jsonl').exists())
    tamper=output/'tamper-fixture';tamper.mkdir()
    ledger=(chosen/'message-ledger.jsonl').read_bytes()
    rows=[json.loads(line) for line in ledger.splitlines()]
    first=next(r for r in rows if r['event']=='content' and r['content'])
    first['content']=('X' if first['content'][0]!='X' else 'Y')+first['content'][1:]
    (tamper/'message-ledger.jsonl').write_bytes(b''.join(common.canonical(row)+b'\n' for row in rows))
    closure=load_json(chosen/'session.json')['message_closure']
    invalid=messages.measure(tamper,closure)
    eventdir=output/'event-tamper-fixture';shutil.copytree(chosen,eventdir)
    eventpath=eventdir/'events.jsonl';events=[json.loads(line) for line in eventpath.read_bytes().splitlines()]
    events[0]['seconds']+=1
    eventpath.write_bytes(b''.join(common.canonical(row)+b'\n' for row in events))
    altered=oracle.evaluate(eventdir,load_json(chosen/'session.json')['event_closure'])
    tamper_result={'message_edit_rejected':not invalid['fully_accounted'],
                   'event_edit_rejected':not altered['events_complete'],
                   'native_digest_checks_not_bypassed':True}
    save(output/'tamper-tests.json',tamper_result)
    return exact and science['scientific_values_equal'] and all(tamper_result.values())


def regenerate_assets(root, output):
    import runpy
    assets=root.parent/'access-analysis'
    target=assets/'assets-reproduced'
    current=root/'collections/cohort-001/evaluation.json'
    original=root/'collections/cohort-001/evaluation-original.json'
    saved=current.read_bytes()
    try:
        current.write_bytes(original.read_bytes())
        sys.argv=[str(assets/'generate_assets.py'),'--source',str(current),'--output',str(target)]
        runpy.run_path(str(assets/'generate_assets.py'),run_name='__main__')
    finally:
        current.write_bytes(saved)
    comparisons={p.name:p.read_bytes()==(target/p.name).read_bytes() for p in (assets/'assets').iterdir() if p.is_file()}
    save(output/'asset-reproduction.json',{'all_outputs_byte_identical':all(comparisons.values()),'files':comparisons,
         'input':'Exact preserved original factual evaluation; derivative view restored after rendering.',
         'derivative_view_restored':current.read_bytes()==saved,'model_calls':0})
    return all(comparisons.values()) and current.read_bytes()==saved


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',choices=['tests','evaluate','assets'],required=True)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();output=root/'release-proof'/args.job
    output.mkdir(parents=True,exist_ok=False)
    # Directory-relative cleanup opens must resolve within the disposable tree.
    os.chdir(root)
    install_guard(root,assets=args.job=='assets',negative_cli=args.job=='tests')
    passed={'tests':tests,'evaluate':evaluate,'assets':regenerate_assets}[args.job](root,output)
    print(json.dumps({'job':args.job,'successful':passed,'model_calls':0}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
