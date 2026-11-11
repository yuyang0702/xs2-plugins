"""Bounded read-only review comparison on copies. Never runs the novel driver."""
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
from contextlib import closing

PLUGIN=Path(__file__).resolve().parents[1]
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def identity(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def manifest(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def compact(report):
    data=copy.deepcopy(report)
    for key in ('candidate_sha256','book_contract_sha256','review_input_sha256'):data.pop(key)
    data['protocol']='local-review-v2'
    for row in data['change_reviews']:
        row.pop('before_excerpt');row.pop('after_excerpt')
    return data
def checked_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=text.encode('utf-8'):raise ValueError('Frozen comparison input changed: '+str(path))
    if not path.exists():path.write_bytes(text.encode('utf-8'))


def prepare(args):
    source=Path(args.source_book).resolve();out=Path(args.output).resolve();before=Path(args.baseline).resolve()
    if source==out or out.is_relative_to(source) or source.is_relative_to(out):raise ValueError('Comparison copies must be separate')
    if out==PLUGIN or out.is_relative_to(PLUGIN):raise ValueError('Artifacts must be outside plugin source')
    cursor=read(source/'observability/driver.json');state=read(source/'.novel-project.json')
    if cursor.get('paused') is not True or state.get('autoArmed') or state.get('autoNext'):raise ValueError('Keep the100k run stopped')
    original_manifest=read(source/'observability/source-manifest.json')
    original=Path(original_manifest['source']).resolve()
    for protected in (original,before):
        if out==protected or out.is_relative_to(protected) or protected.is_relative_to(out):
            raise ValueError('Comparison output overlaps a protected original or baseline')
    out.mkdir(parents=True,exist_ok=True);guard=out/'protected-source.json'
    captured={'source':str(source),'files':manifest(source),'original':original_manifest}
    if guard.exists():
        if read(guard)!=captured:raise ValueError('Protected manuscript or paused run changed')
    else:save(guard,captured)
    def check_sources():
        if manifest(source)!=captured['files']:raise ValueError('Paused source was modified')
        original=Path(captured['original']['source'])
        if manifest(original)!=captured['original']['files']:raise ValueError('Original manuscript was modified')
    check_sources()
    current_body=source/'story/0002/chapter.md';body_sha=sha(current_body)
    selected=[]
    for path in (source/'cache/local-revision').glob('*/receipt.json'):
        receipt=read(path)
        if receipt.get('accepted') and receipt.get('after_sha256')==body_sha:selected.append(path)
    if not selected:raise ValueError('Need a real accepted copy revision for paired replay')
    folder=max(selected,key=lambda p:p.stat().st_mtime).parent
    context=read(folder/'review-input.json');recorded=read(folder/'review.json')
    modules={name:load('perf_'+name+'_local',base/'resources/script-library/xs2/local_revision/local_revision.py')
        for name,base in [('before',before),('after',PLUGIN)]}
    if modules['before'].review_decision(recorded,context):raise ValueError('Baseline source report is not a passing actual audit')
    patches=modules['before'].patches
    if patches.apply_patches(context['source_body'],{'source_sha256':context['source_sha256'],'edits':context['edits']})!=context['candidate']:
        raise ValueError('Source/candidate change chain is inconsistent')
    normal=copy.deepcopy(context);normal['task_id']='paired-normal'
    normal['review_input_sha256']=identity({k:v for k,v in normal.items() if k!='review_input_sha256'})
    bad=copy.deepcopy(normal);bad['task_id']='paired-known-fact'
    phrase='站端收到执行结果回执：统一时标t=10'
    paragraph=next((r for r in patches.paragraphs(bad['source_body']) if phrase in r['text']),None)
    if not paragraph:raise ValueError('Known-defect anchor missing; no guessing')
    bad['edits']=[{'paragraph_id':paragraph['id'],'old':phrase,'occurrence':1,'replacement':phrase.replace('t=10','t=6')}]
    payload={'source_sha256':bad['source_sha256'],'edits':bad['edits']}
    bad['candidate']=patches.apply_patches(bad['source_body'],payload)
    bad['candidate_sha256']=hashlib.sha256(bad['candidate'].encode()).hexdigest();bad['patch_digest']=identity(payload)
    bad['evidence_catalog']=modules['before'].evidence.catalog(bad['candidate'])
    bounds=(bad['length']['lower'],bad['length']['upper'])
    bad['length']=modules['before'].quality.measurement(bad['candidate'].encode(),'0002',bounds)
    bad['review_input_sha256']=identity({k:v for k,v in bad.items() if k!='review_input_sha256'})
    cases={'normal':normal,'known-fact':bad};packets={};offline=[]
    for name,ctx in cases.items():
        for arm,base in [('before',before),('after',PLUGIN)]:
            target=out/'cases'/name/arm
            projected=ctx if arm=='before' else modules['after'].packet.local(ctx,'reviewer')
            checked_write(target/'canonical-input.json',json.dumps(ctx,ensure_ascii=False,indent=2)+'\n')
            checked_write(target/'model-input.json',json.dumps(projected,ensure_ascii=False,indent=2)+'\n')
            checked_write(target/'source.md',ctx['source_body']);checked_write(target/'candidate.md',ctx['candidate'])
            workflow=read(base/'resources/workflows/polish/definition.json');node=next(n for n in workflow['nodes'] if n['id']=='agent_local_review')
            prompts=read(base/'resources/prompts.json')['agents'][node['agent_type']]
            system='\n'.join(s['content'] for s in sorted(prompts['sections'],key=lambda s:s.get('order',0)) if s.get('enabled',True))
            replacements={'revision_review_input':json.dumps(ctx,ensure_ascii=False,indent=2),
                'revision_review_model':json.dumps(projected,ensure_ascii=False,indent=2),
                'revision_feedback_file':'','book_contract_file':modules[arm].book.prompt(ctx['book_contract'])}
            user=re.sub(r'\{\{([\w_]+)\}\}',lambda m:replacements[m[1]],node['first_message'])
            checked_write(target/'system.txt',system);checked_write(target/'request.txt',user)
            packets[(name,arm)]={'system':system,'user':user,'schema':node['node_params']['json_output_schema'],
                'context':ctx,'target':target,'module':modules[arm]}
        # Replay actual model judgments, explicitly not a new model measurement.
        replay=copy.deepcopy(recorded)
        replay.update({k:normal[k] for k in ('candidate_sha256','book_contract_sha256','review_input_sha256')})
        if name=='normal':
            assert not modules['before'].review_decision(replay,ctx)
            assert not modules['after'].review_decision(compact(replay),ctx)
        old_bytes=len((packets[(name,'before')]['system']+packets[(name,'before')]['user']).encode())
        new_bytes=len((packets[(name,'after')]['system']+packets[(name,'after')]['user']).encode())
        offline.append({'case':name,'before_input_bytes':old_bytes,'after_input_bytes':new_bytes,
            'input_reduction_fraction':round(1-new_bytes/old_bytes,4),'source_candidate_identical_between_arms':True})
    result={'mode':'offline-replay','not_a_novel_generation_run':True,'input_comparison':offline,
        'protected_source_unchanged':True,'original_unchanged':True,'source_context':str(folder),
        'limitation':'Same frozen chapter and planted fact defect; not a universal literary-quality or end-to-end latency claim.'}
    save(out/'offline-comparison.json',result);check_sources()
    return out,source,packets,result,check_sources


async def live(args,out,source,packets,offline,check_sources):
    os.environ.update(DETERMINFLOW_CONFIG_DIR=str(Path(args.host)/'config'),DETERMINFLOW_DATA_DIR=str(out/'runtime-data'),
        DETERMINFLOW_LOGS_DIR=str(out/'logs'))
    sys.path.insert(0,str(Path(args.host)))
    from scripts.start_local import load_startup_environment
    load_startup_environment()
    from src.workflow.output_selection import _json_document
    from jsonschema import validate,ValidationError
    transport=load('perf_review_transport',PLUGIN/'runtime/longrun/transport.py');log=transport.ledger()
    original=read(source/'meta/longrun_contract.json');model='lingsuan:gpt-6.1-sol'
    config={**original,'target_new_characters':1,'purpose':'bounded_read_only_review_comparison',
        'models':[model],'routes':{model:original['routes'][model]},'limits':{'max_calls':12,'max_total_tokens':None},
        'authorization':'User approved plugin P0 copy comparison; stopped100k run must not resume.'}
    log.initialize(out,config,[]);results=[]
    with transport.metered_models(out):
        # Counterbalance arm ordering; never launch a writing workflow.
        for name,arm in [('normal','before'),('normal','after'),('known-fact','after'),('known-fact','before')]:
            check_sources();p=packets[(name,arm)];saved=p['target']/'result.json'
            if saved.exists():results.append(read(saved));continue
            error='';began=time.perf_counter();complete=False
            for attempt in range(1,4):
                text=await transport.request(out,model,p['system'],p['user']+error,
                    {'stage':'performance-copy-review','chapter':'0002','node_id':name+'-'+arm,'attempt':attempt})
                (p['target']/f'response-{attempt}.txt').write_text(text,encoding='utf-8')
                try:
                    response=_json_document(text);validate(response,p['schema'])
                    reasons=p['module'].review_decision(response,p['context'])
                    expanded=p['module'].wire.expand(response,p['context']) if arm=='after' else response
                    complete=True;break
                except (ValueError,TypeError,KeyError,ValidationError) as exc:
                    error='\n上一份报告未通过结构或证据验证，请仅修正报告，不改正文、不捏造问题：'+str(exc)[:1800]
            if not complete:raise ValueError(f'{name}/{arm} failed3 bounded review attempts')
            item={'case':name,'arm':arm,'model':model,'attempts':attempt,'elapsed_seconds':round(time.perf_counter()-began,3),
                'gate_accepts':not reasons,'compatible':expanded['compatible'],
                'fact_issues':len(expanded['issues']),'expression_verdict':expanded['expression_review']['verdict'],
                'wire_protocol':response.get('protocol','v1'),'response_bytes':len(text.encode()),'reasons':reasons,
                'planted_defect_detected':name=='known-fact' and any(
                    't=6' in issue.get('candidate_quote','') and
                    ('t=10' in issue.get('source_quote','') or 't=10' in issue.get('reason',''))
                    for issue in expanded['issues'])}
            save(saved,item);save(p['target']/'expanded-audit.json',expanded);results.append(item)
            print(json.dumps(item,ensure_ascii=False),flush=True);check_sources()
    with closing(log.connect(out)) as db:calls=log._call_rows(db)
    usage=log.usage_summary(calls)
    summary={**offline,'mode':'live-paired-review','results':results,'usage':usage,
        'quality_checks':{'known_fact_detected_by_both':all(r['planted_defect_detected'] for r in results if r['case']=='known-fact'),
            'normal_acceptance':{r['arm']:r['gate_accepts'] for r in results if r['case']=='normal'}},
        'calls':[{k:r.get(k) for k in ('chapter','node_id','status','prompt_tokens','completion_tokens','total_tokens','usage_status')} for r in calls]}
    save(out/'live-comparison.json',summary);check_sources()
    print(json.dumps({'comparison':str(out/'live-comparison.json'),'quality':summary['quality_checks'],'usage':usage},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-book',required=True);parser.add_argument('--baseline',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--host',default='C:/xs2/DeterminFlow');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    out,source,packets,result,check=prepare(args)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if args.live:asyncio.run(live(args,out,source,packets,result,check))


if __name__=='__main__':main()
