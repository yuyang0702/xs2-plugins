"""Bounded real-model learning/adoption/plan/revision/review on an independent copy.

Uses native node prompts, schemas, CLI and commit gates. Never starts the novel
driver. A literary rejection is recorded, never rewritten into a passing test.
"""
import argparse
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from compare_performance_p0 import read,save,sha,manifest,load,identity
from compare_performance_p1 import system_for,apply_runtime_aliases

PLUGIN=Path(__file__).resolve().parents[1];RES=PLUGIN/'resources';SCRIPTS=RES/'script-library/xs2'
MODEL='lingsuan:gpt-6.1-sol'


def guard(out):
    path=out/'protected.json'
    if not path.exists():
        base=Path('C:/xs2/data/verification/20261108-local-revision-v1/cases')
        roots=[base/c/'book' for c in ('ancient','apocalypse','fantasy','romance','scifi')]
        roots.append(Path('C:/xs2/data/verification/20261108-longrun-100k/book'))
        save(path,{str(p):manifest(p) for p in roots})
    for name,files in read(path).items():
        if manifest(Path(name))!=files:raise ValueError('Protected source changed: '+name)
    stopped=Path('C:/xs2/data/verification/20261108-longrun-100k/book')
    state=read(stopped/'.novel-project.json')
    if read(stopped/'observability/driver.json')['paused'] is not True or state.get('autoNext') or state.get('autoArmed'):raise ValueError('100k must remain stopped')


def cli(book,script,*args,task='',stdin=None):
    env={**os.environ,'TASK_ID':task,'PYTHONUTF8':'1'}
    result=subprocess.run([sys.executable,str(SCRIPTS/f'{script}/{script}.py'),*args],cwd=book,env=env,
        input=stdin,text=True,encoding='utf8',capture_output=True,timeout=60)
    if result.returncode:raise ValueError(result.stderr)
    if '<WF_REJECT_UPSTREAM' in result.stdout:raise ValueError(result.stdout)
    return dict(re.findall(r'<WF_VAR>([^:]+):(.*?)</WF_VAR>',result.stdout))


async def main(args):
    out=Path(args.output).resolve();source=Path(args.source_book).resolve();out.mkdir(parents=True,exist_ok=True)
    if out==source or out.is_relative_to(source) or source.is_relative_to(out) or out.is_relative_to(PLUGIN):raise ValueError('Copy must be independent')
    guard(out);book=out/'book'
    if not book.exists():shutil.copytree(source,book,ignore=shutil.ignore_patterns('__pycache__'))
    os.environ.update(DETERMINFLOW_CONFIG_DIR='C:/xs2/DeterminFlow/config',DETERMINFLOW_DATA_DIR=str(out/'runtime-data'),
        DETERMINFLOW_LOGS_DIR=str(out/'logs'),LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S='300')
    sys.path.insert(0,'C:/xs2/DeterminFlow')
    from scripts.start_local import load_startup_environment
    load_startup_environment()
    from src.workflow.definition import WorkflowDef
    from src.workflow.variable_resolution import resolve_placeholders
    from src.workflow.output_selection import _json_document
    from jsonschema import validate,ValidationError
    from openai import APIConnectionError,APITimeoutError,RateLimitError,InternalServerError
    transport=load('reading_chain_transport',PLUGIN/'runtime/longrun/transport.py');ledger=transport.ledger()
    route=read(Path('C:/xs2/data/verification/20261108-longrun-100k/book/meta/longrun_contract.json'))['routes'][MODEL]
    ledger.initialize(out,{'schema':1,'models':[MODEL],'routes':{MODEL:route},'target_new_characters':1,
        'purpose':'bounded_reading_chain_copy_verification','limits':{'max_calls':24,'max_total_tokens':None},
        'authorization':'User requested plugin learning-to-writing integration and one prior short-story copy validation; same approved edge.lingsuan.org route.'},[])
    roles=read(RES/'prompts.json')['agents'];results=[]

    async def ask(workflow,node_id,values,label,validate_semantic=None):
        wf_data=read(RES/f'workflows/{workflow}/definition.json');wf=WorkflowDef.from_dict(wf_data)
        node=next(n for n in wf_data['nodes'] if n['id']==node_id)
        vals={v['key']:v.get('default','') for v in wf_data['variables']};vals.update(values)
        system=await system_for(node,roles[node['agent_type']],vals,wf.variables,book)
        user=await resolve_placeholders(node['first_message'],vals,wf.variables,str(book))
        directory=out/'requests'/label;directory.mkdir(parents=True,exist_ok=True)
        for name,text in [('system.txt',system),('request.txt',user)]:
            p=directory/name
            if p.exists() and p.read_text(encoding='utf8')!=text:raise ValueError('Frozen request changed: '+label)
            if not p.exists():p.write_text(text,encoding='utf8')
        schema=node.get('node_params',{}).get('json_output_schema');errors=''
        for attempt in range(1,4):
            file=directory/f'response-{attempt}.txt'
            if file.exists():text=file.read_text(encoding='utf8')
            else:
                print(json.dumps({'request':label,'attempt':attempt,'node':node_id},ensure_ascii=False),flush=True)
                try:
                    text=await transport.request(out,MODEL,system,user+errors,{'stage':'reading-chain-copy','chapter':'0001','node_id':label,'attempt':attempt})
                except (APIConnectionError,APITimeoutError,RateLimitError,InternalServerError) as exc:
                    save(directory/f'transport-error-{attempt}.json',{'type':type(exc).__name__,'message':str(exc),'usage':'unknown; see immutable call ledger'})
                    if attempt==3:raise
                    await asyncio.sleep(2);continue
                file.write_text(text,encoding='utf8')
            try:
                data=_json_document(text)
                if schema:validate(data,schema)
                if validate_semantic:validate_semantic(data)
                save(directory/'validated.json',data);return data
            except (ValueError,TypeError,KeyError,AssertionError,ValidationError) as exc:
                errors='\n上次结构或来源依据校验失败，按真实输入重新交付，不修改文学结论来凑通过：'+str(exc)[:2200]
                save(directory/f'error-{attempt}.json',{'error':str(exc)})
        raise ValueError('Three invalid reports: '+label)

    local=load('reading_chain_local',SCRIPTS/'local_revision/local_revision.py')
    comp=load('reading_chain_composition',SCRIPTS/'composition_plan/composition_plan.py')
    reader=load('reading_chain_reader',SCRIPTS/'reader_review/reader_review.py')
    state=read(book/'.novel-project.json');values=state['values'];target=values['target_word_count']
    before=sha(book/'story/0001/chapter.md')
    with transport.metered_models(out):
        if not args.resume_reader:
            # Source is an already generated user-owned short story, not a claimed
            # platform exemplar. Optional focus tests transfer, not platform fidelity.
            reference=book/'references/chain-source.txt'
            if not reference.exists():reference.parent.mkdir(parents=True,exist_ok=True);reference.write_bytes((source/'story/0001/chapter.md').read_bytes())
            learning=cli(book,'reference_distill','split','--input','references/chain-source.txt','--source-mode','short_full','--learning-direction','zhihu_short')
            window=read(book/'learning/cache/windows.json')['windows'][0]
            learning.update(values);learning.update(window_id=window['window_id'],window_file='learning/cache/window-0001.json',source_mode='short_full')
            # The actual CLI advertises the concrete window packet path.
            candidates=list((book/'learning/cache').rglob('*window-0001*'))
            window_path=next((p for p in candidates if p.suffix=='.json' and p.name!='windows.json'),None)
            if not window_path:raise ValueError('Native window packet missing')
            learning['window_file']=window_path.relative_to(book).as_posix()
            def normalize_analysis(data):
                save(book/'learning/cache/chain-analysis.json',data)
                cli(book,'reference_distill','normalize','--input','learning/cache/chain-analysis.json','--window-id',window['window_id'])
            analysis=await ask('reference-distillation','agent_distill_window',learning,'01-learn',normalize_analysis)
            cli(book,'reference_distill','merge')
            data=read(book/'learning/candidates.json');selected=next((r for r in data['candidates'] if r.get('reading_objectives')),None)
            if not selected:raise ValueError('Live analyst produced no source-backed transferable goal')
            selection={'candidates_sha256':data['candidates_sha256'],'selected_candidate_ids':[selected['candidate_id']]}
            save(out/'explicit-test-selection.json',{'selection':selection,'basis':'本次用户授权副本验证；仅选择真实分析中有证据的一个抽象机制，未自动采用其他候选。'})
            cli(book,'reference_distill','adopt','--selection-json',json.dumps(selection,ensure_ascii=False))
            cli(book,'reference_distill','prepare-context','--scope','polish')
            contract=local.book.resolve(book);save(out/'adopted-reading-contract.json',contract['reading_contract'])
            revision=comp.code_profile()[:8];plan_task='reading-chain-plan-'+revision;plan_dir='cache/composition/'+plan_task
            request=comp.prepare(book,'0001',plan_task,target)
            pvalues={**values,'composition_request_file':plan_dir+'/request.json','composition_feedback_file':plan_dir+'/feedback.md'}
            (book/pvalues['composition_feedback_file']).write_text('',encoding='utf8')
            plan=await ask('polish','agent_composition_plan',pvalues,'02-plan-'+revision,lambda p:comp.validate_plan(request,p))
            save(book/(plan_dir+'/plan.json'),plan)
            save(book/(plan_dir+'/review-input.json'),{'request':request,'plan':plan,'request_digest':request['request_digest'],'plan_digest':comp.identity(plan)})
            pvalues['composition_review_input']=plan_dir+'/review-input.json'
            review=await ask('polish','agent_composition_review',pvalues,'03-plan-review-'+revision)
            comp.accept(book,plan_task,plan,review)
            # Native source/edit/review chain; retain rejected improved edits and
            # force the reviewer to inspect a changed candidate on every retry.
            outvars=local.prepare(book,'0001','reading-chain-revision',target)
            v={**values,**outvars}
            critique=await ask('polish','agent_sc',v,'04-critic')
            save(book/'cache/sc/critique.json',critique)
            local.writer_input(book,outvars['revision_dir'],'cache/sc/critique.json')
            accepted=False
            for cycle in range(1,4):
                patch=await ask('polish','agent_pl',v,f'05-writer-{cycle}')
                save(book/outvars['revision_patch_path'],patch)
                local.candidate(book,outvars['revision_dir'])
                context=read(book/outvars['revision_review_input'])
                audit=await ask('polish','agent_local_review',v,f'06-review-{cycle}',lambda r:local.review_decision(r,context))
                save(book/outvars['revision_review_path'],audit)
                try:
                    local.commit(book,outvars['revision_dir'],json.dumps(audit,ensure_ascii=False));accepted=True;break
                except local.Retry as exc:
                    if exc.target!='agent_pl':raise
                    (book/outvars['revision_feedback_file']).write_text(local.retry_feedback(book,outvars['revision_dir'],exc),encoding='utf8')
            results.append({'stage':'local_revision','accepted':accepted,'cycles':cycle,'edits':len(context['edits']),
                'reading_checks':audit.get('reading_checks',[]),'remaining':local.review_decision(audit,context)})
        else:
            receipt=read(book/'cache/local-revision/reading-chain-revision/receipt.json')
            context=read(book/'cache/local-revision/reading-chain-revision/review-input.json')
            audit=read(book/'cache/local-revision/reading-chain-revision/review.json')
            if receipt.get('accepted') is not True or sha(book/'story/0001/chapter.md')!=receipt['after_sha256']:raise ValueError('Accepted copy changed')
            local.bound(book,'cache/local-revision/reading-chain-revision',accepted_sha=receipt['after_sha256'])
            if local.review_decision(audit,context):raise ValueError('Actual accepted report no longer passes')
            accepted=True;contract=local.book.resolve(book);before=receipt['before_sha256']
            cycles=len(read(book/'cache/local-revision/reading-chain-revision/content-rejections.json'))+1
            results.append({'stage':'local_revision','accepted':True,'cycles':cycles,'edits':len(context['edits']),
                'reading_checks':audit.get('reading_checks',[]),'remaining':[],'resumed_from_verified_receipt':True})
        if accepted:
            ro=reader.prepare(book,'0001','reading-chain-reader')
            runtime=reader.book_contract.policy().prepare_runtime(book,'0001',task_id='reading-chain-reader')
            rv=apply_runtime_aliases({**values,**ro,'book_contract_file':'cache/book-contract/reading-chain-reader/prompt.md',
                'chapter_file':'story/0001/chapter.md','story_support_context':'cache/story-support/context.md',
                'prose_policy_prompt':runtime['prompt_file'],'prose_policy_runtime':runtime['directory']},runtime)
            body=(book/'story/0001/chapter.md').read_text(encoding='utf8')
            blind=await ask('reader-sim','agent_blind_reader',rv,'07-blind',
                lambda r:reader.validate_blind(r,body,reader.book_contract.public_style(contract).get('reading_contract',{})))
            save(book/ro['reader_blind_raw_path'],blind)
            reader.commit_blind(book,ro['reader_review_binding'],ro['reader_review_binding_sha'])
            blind_sha=sha(book/ro['reader_blind_report']);rv['reader_blind_report_sha']=blind_sha
            contextual=await ask('reader-sim','agent_reader',rv,'08-context')
            save(book/ro['reader_context_report_path'],contextual)
            final=reader.commit(book,ro['reader_review_binding'],ro['reader_review_binding_sha'],blind_sha)
            save(out/'final-reader-report.json',final)
            results.append({'stage':'whole_story_reader','verdict':final['verdict'],'fact':final['fact_review']['verdict'],
                'expression':final['expression_review']['verdict'],'reading_checks':final.get('reading_checks',[]),
                'issues':final['issues']})
    with closing(ledger.connect(out)) as db:calls=ledger._call_rows(db)
    guard(out)
    summary={'mode':'real_models_native_node_copy_chain','source':str(source),'copy':str(book),'model':MODEL,
        'analysis_focus':'zhihu_short','sample_is_not_claimed_zhihu_exemplar':True,'style':values['genre'],
        'narrator_scope':values['narrator_scope'],'author_range_preserved':comp.current(book,'0001')['minimum']==1 and comp.current(book,'0001')['maximum']==5000,
        'before_sha256':before,'after_sha256':sha(book/'story/0001/chapter.md'),
        'actual_characters':reader.quality().count_prose((book/'story/0001/chapter.md').read_text(encoding='utf8')),
        'results':results,'usage':ledger.usage_summary(calls),'all_five_sources_unchanged':True,'100k_still_paused':True,
        'limitation':'One bounded copy checks pipeline and source-bound review behavior; not universal platform style quality or million-word stability. Model pricing unavailable; record tokens only.'}
    save(out/'validation-summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-book',required=True);p.add_argument('--output',required=True)
    p.add_argument('--resume-reader',action='store_true',help='Verify accepted copy receipt and resume only final reader nodes')
    asyncio.run(main(p.parse_args()))
