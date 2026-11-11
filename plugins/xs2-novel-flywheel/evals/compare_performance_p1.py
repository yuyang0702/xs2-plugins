"""Copy-only P1 comparison. Reviews chapters; never invokes novel generation."""
import argparse
import asyncio
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from compare_performance_p0 import read,save,sha,manifest,load,checked_write

PLUGIN=Path(__file__).resolve().parents[1]


async def system_for(node,role,values,variables,root):
    from src.workflow.variable_resolution import resolve_placeholders
    base='\n'.join(s['content'] for s in sorted(role['sections'],key=lambda s:s.get('order',0)) if s.get('enabled',True))
    dynamic=await resolve_placeholders(node.get('system_prompt_template',''),values,variables,str(root))
    return base+('\n\n'+dynamic if dynamic.strip() else '')


def arm_timing(elapsed,cache_hits,previous_calls=0):
    resumed=bool(cache_hits or previous_calls)
    return {'elapsed_seconds':round(elapsed,3) if not resumed else None,'latency_comparable':not resumed,
        'resumed_cached_calls':cache_hits,'resumed_prior_calls':previous_calls,'resume_wall_seconds':round(elapsed,3) if resumed else None}


def detect_planted_fact(report):
    if report['fact_review']['verdict'] not in ('revise','reject'):return False
    for issue in report.get('issues',[]):
        text=json.dumps(issue,ensure_ascii=False)
        if 't=6' in text and 't=10' in text and '回执' in text and any(w in text for w in ('混淆','错误','矛盾','冲突','提前')):return True
    return False


def apply_runtime_aliases(values,runtime):
    result=dict(values)
    for key,value in values.items():
        if not key.startswith('pp_') or not isinstance(value,str):continue
        for _ in range(8):
            expanded=re.sub(r'\{\{([\w_]+)\}\}',lambda m:str(values.get(m[1],m[0])),value)
            if expanded==value:break
            value=expanded
        if value in runtime['aliases']:result[key]=runtime['aliases'][value]
    return result


def prepare(args):
    source=Path(args.source_book).resolve();before=Path(args.baseline).resolve();out=Path(args.output).resolve()
    original_manifest=read(source/'observability/source-manifest.json');original=Path(original_manifest['source']).resolve()
    for protected in (source,original,before,PLUGIN):
        if out==protected or out.is_relative_to(protected) or protected.is_relative_to(out):raise ValueError('Output overlaps protected source')
    state=read(source/'.novel-project.json');cursor=read(source/'observability/driver.json')
    if cursor.get('paused') is not True or state.get('autoNext') or state.get('autoArmed'):raise ValueError('Keep100k paused')
    guards={'source':str(source),'files':manifest(source),'original':original_manifest}
    out.mkdir(parents=True,exist_ok=True)
    protected_file=out/'protected-source.json'
    if protected_file.exists() and read(protected_file)!=guards:raise ValueError('Protected sources changed')
    save(protected_file,guards)
    def check():
        if manifest(source)!=guards['files'] or manifest(original)!=original_manifest['files']:raise ValueError('Original or paused book changed')
    check()
    context=read(Path(args.context));body=(source/'story/0002/chapter.md').read_bytes()
    if body!=context['candidate'].encode():raise ValueError('Paired context must match the accepted real copy chapter')
    mods={arm:load('p1_'+arm+'_reader',base/'resources/script-library/xs2/reader_review/reader_review.py') for arm,base in [('before',before),('after',PLUGIN)]}
    current=load('p1_pending_eval',PLUGIN/'resources/script-library/xs2/local_revision/local_revision.py')
    retained=context['edits'][:2];remaining=context['edits'][2:]
    merged=current.pending.merge(context['source_body'],retained,remaining,current.patches)
    full=current.patches.apply_patches(context['source_body'],{'source_sha256':context['source_sha256'],'edits':merged})
    old=current.patches.apply_patches(context['source_body'],{'source_sha256':context['source_sha256'],'edits':remaining})
    if full!=context['candidate'] or old==full:raise ValueError('Retention replay failed')
    recorded=read(Path(args.context).with_name('expanded-audit.json'))
    if current.review_decision(recorded,context):raise ValueError('Actual final recorded audit must still pass all cumulative edits')
    save(out/'retention-replay.json',{'mode':'offline_actual_edit_replay','not_new_model_judgments':True,'retained_edits':len(retained),
        'remaining_edits':len(remaining),'before_omission_loses_useful_edits':old!=full,'after_matches_actual_accepted_candidate':True,
        'actual_full_final_audit_replay_passes':True,'manuscript_not_published':True})
    packets={}
    for case in ('normal','known-fact'):
        value=body.decode('utf8')
        if case=='known-fact':
            phrase='站端收到执行结果回执：统一时标t=10'
            if value.count(phrase)!=1:raise ValueError('Exact defect anchor required')
            value=value.replace(phrase,phrase.replace('t=10','t=6'))
        for arm,base in [('before',before),('after',PLUGIN)]:
            directory=out/'cases'/case/arm;root=directory/'book'
            if not root.exists():
                shutil.copytree(source,root,ignore=shutil.ignore_patterns('__pycache__','observability'))
                (root/'story/0002/chapter.md').write_bytes(value.encode('utf8'))
            if (root/'story/0002/chapter.md').read_bytes()!=value.encode():raise ValueError('Frozen copy changed')
            m=mods[arm];task='perf-p1-'+case+'-'+arm
            outputs=m.prepare(root,'0002',task,parallel=True) if arm=='after' else m.prepare(root,'0002',task)
            frozen='cache/performance-p1/context.md';checked_write(root/frozen,context['confirmed_context'])
            runtime_path=directory/'policy-runtime.json'
            if runtime_path.exists():runtime=read(runtime_path)
            else:
                runtime=m.book_contract.policy().prepare_runtime(root,'0002',task_id=task);save(runtime_path,runtime)
            if arm=='after' and not (directory/'result.json').exists():m.freeze_parallel(root,outputs['reader_review_binding'],outputs['reader_review_binding_sha'],frozen,runtime['directory'])
            workflow=read(base/'resources/workflows/reader-sim/definition.json');nodes={n['id']:n for n in workflow['nodes']}
            values={v['key']:v.get('default','') for v in workflow['variables']};values.update(state.get('values',{}));values.update(outputs)
            values.update(chapter_number='0002',target_word_count=f"{context['length']['lower']}-{context['length']['upper']}",
                story_support_context=frozen,book_contract_file=f'cache/book-contract/{task}/prompt.md',
                prose_policy_prompt=runtime['prompt_file'],prose_policy_runtime=runtime['directory'])
            values=apply_runtime_aliases(values,runtime)
            checked_write(root/'cache/performance-p1/length.json',json.dumps(m.quality().measurement(value.encode(),'0002',(context['length']['lower'],context['length']['upper'])),ensure_ascii=False))
            values['length_context_file']='cache/performance-p1/length.json'
            packets[(case,arm)]={'root':root,'directory':directory,'module':m,'outputs':outputs,'workflow':workflow,'nodes':nodes,
                'values':values,'body':value,'base':base,'body_sha256':sha(root/'story/0002/chapter.md')}
    save(out/'offline-comparison.json',{'protected_source_unchanged':True,'original_unchanged':True,'same_manuscripts_and_rules':True,
        'no_novel_generation':True,'retention':'retention-replay.json','reader_cases':['normal','known-fact']})
    check();return out,source,packets,check


async def run(args,out,source,packets,check):
    os.environ.update(DETERMINFLOW_CONFIG_DIR=str(Path(args.host)/'config'),DETERMINFLOW_DATA_DIR=str(out/'runtime-data'),DETERMINFLOW_LOGS_DIR=str(out/'logs'))
    sys.path.insert(0,args.host)
    from scripts.start_local import load_startup_environment
    load_startup_environment()
    from src.workflow.definition import WorkflowDef
    from src.workflow.variable_resolution import resolve_placeholders
    from src.workflow.output_selection import _json_document
    from jsonschema import validate,ValidationError
    transport=load('p1_eval_transport',PLUGIN/'runtime/longrun/transport.py');log=transport.ledger();original=read(source/'meta/longrun_contract.json')
    model='lingsuan:gpt-6.1-sol';config={**original,'target_new_characters':1,'purpose':'bounded_p1_copy_reviews',
        'models':[model],'routes':{model:original['routes'][model]},'limits':{'max_calls':20,'max_total_tokens':None},
        'authorization':'Approved plugin P1 copy comparison; never resume100k or launch a writer.'}
    log.initialize(out,config,[])
    with closing(log.connect(out)) as db:prior_calls=log._call_rows(db)
    async def request(p,node_id,case,arm,validate_report):
        node=p['nodes'][node_id];wf=WorkflowDef.from_dict(p['workflow'])
        prompt=await resolve_placeholders(node['first_message'],p['values'],wf.variables,str(p['root']))
        role=read(p['base']/'resources/prompts.json')['agents'][node['agent_type']]
        system=await system_for(node,role,p['values'],wf.variables,p['root'])
        target=p['directory']/node_id;checked_write(target/'request.txt',prompt);checked_write(target/'system.txt',system)
        if (target/'validated.json').exists():
            p['cache_hits']=p.get('cache_hits',0)+1
            return read(target/'validated.json')
        error='';began=time.perf_counter()
        for attempt in range(1,4):
            check()
            text=await transport.request(out,model,system,prompt+error,{'stage':'performance-p1-copy-review','chapter':'0002','node_id':case+'-'+arm+'-'+node_id,'attempt':attempt})
            (target/f'response-{attempt}.txt').write_bytes(text.encode())
            try:
                response=_json_document(text);validate(response,node['node_params']['json_output_schema']);validate_report(response)
            except (ValueError,TypeError,KeyError,ValidationError) as exc:
                error='\n只修正报告结构和真实证据，不改变待审正文或为格式虚构问题：'+str(exc)[:1800];continue
            save(target/'validated.json',response);save(target/'measurement.json',{'attempts':attempt,'elapsed_seconds':time.perf_counter()-began})
            return response
        raise ValueError('Bounded review exhausted: '+str(target))
    results=[]
    with transport.metered_models(out):
        for case in ('normal','known-fact'):
            for arm in ('before','after'):
                p=packets[(case,arm)];m=p['module'];o=p['outputs'];root=p['root'];began=time.perf_counter();reconciled=False;p['cache_hits']=0
                saved=p['directory']/'result.json'
                if saved.exists():results.append(read(saved));continue
                def contextual(report,blind):m.validate_revision_scope(root,report);return m.merge_review(report,blind,p['body'])
                empty={'verdict':'pass','summary':'Independent first pass','issues':[],'decisions':[]}
                if arm=='before':
                    blind=await request(p,'agent_blind_reader',case,arm,lambda r:m.validate_blind(r,p['body']))
                    save(root/o['reader_blind_raw_path'],blind);b=m.commit_blind(root,o['reader_review_binding'],o['reader_review_binding_sha']);p['values'].update(b)
                    context=await request(p,'agent_reader',case,arm,lambda r:contextual(r,blind));save(root/o['reader_context_report_path'],context)
                    report=m.commit(root,o['reader_review_binding'],o['reader_review_binding_sha'],b['reader_blind_report_sha'])
                else:
                    def independent(r):
                        if r.get('blind_resolutions')!=[]:raise ValueError('No blind findings were supplied')
                        contextual(r,empty)
                    blind,context=await asyncio.gather(request(p,'agent_blind_reader',case,arm,lambda r:m.validate_blind(r,p['body'])),
                        request(p,'agent_context_reader',case,arm,independent))
                    save(root/o['reader_blind_raw_path'],blind);b=m.commit_blind(root,o['reader_review_binding'],o['reader_review_binding_sha']);p['values'].update(b)
                    save(root/o['reader_preflight_raw_path'],context);c=m.commit_context(root,o['reader_review_binding'],o['reader_review_binding_sha']);p['values'].update(c)
                    decision=m.join(root,o['reader_review_binding'],o['reader_review_binding_sha'],b['reader_blind_report_sha'],c['reader_preflight_sha'])
                    if decision['reader_reconcile_required']=='yes':
                        reconciled=True;context=await request(p,'agent_reader',case,arm,lambda r:contextual(r,blind));save(root/o['reader_context_report_path'],context)
                    report=m.commit(root,o['reader_review_binding'],o['reader_review_binding_sha'],b['reader_blind_report_sha'],c['reader_preflight_sha'])
                if sha(root/'story/0002/chapter.md')!=p['body_sha256']:raise ValueError('Benchmark rewrote copy prose')
                previous=sum(1 for call in prior_calls if str(call.get('node_id','')).startswith(case+'-'+arm+'-'))
                result={'case':case,'arm':arm,**arm_timing(time.perf_counter()-began,p['cache_hits'],previous),'verdict':report['verdict'],
                    'fact_verdict':report['fact_review']['verdict'],'expression_verdict':report['expression_review']['verdict'],
                    'blind_issues':len(blind['issues']),'dependent_reconciliation':reconciled,'copy_body_unchanged':True,
                    'planted_defect_detected':case=='known-fact' and detect_planted_fact(report)}
                save(p['directory']/'final-audit.json',report);save(saved,result);results.append(result);check();print(json.dumps(result,ensure_ascii=False),flush=True)
    with closing(log.connect(out)) as db:calls=log._call_rows(db)
    summary={'results':results,'usage':log.usage_summary(calls),'original_and_paused_book_unchanged':True,'longrun_still_paused':True,
        'known_fact_detected_by_both':all(r['planted_defect_detected'] for r in results if r['case']=='known-fact'),
        'limitations':'Two bounded chapter-review samples. Retention is offline replay of actual edits/audit. No chapter generation or general speed/quality guarantee.',
        'calls':[{k:r.get(k) for k in ('node_id','status','prompt_tokens','completion_tokens','total_tokens','usage_status')} for r in calls]}
    save(out/'live-comparison.json',summary);check();print(json.dumps({'comparison':str(out/'live-comparison.json'),'usage':summary['usage']},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-book','baseline','context','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--host',default='C:/xs2/DeterminFlow');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    out,source,packets,check=prepare(args)
    print(json.dumps({'offline':'passed','output':str(out),'longrun':'paused'},ensure_ascii=False),flush=True)
    if args.live:asyncio.run(run(args,out,source,packets,check))


if __name__=='__main__':main()
