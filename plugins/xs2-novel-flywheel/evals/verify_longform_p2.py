"""Offline P2 integration checks on copies of five real style profiles.

Planner/reviewer outputs and appended chapters are explicit test fixtures.
This is not a model-generation run or a literary-quality evaluation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def hashes(root):return {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plugin-root',type=Path,required=True)
    parser.add_argument('--source-cases',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    source_before=hashes(args.source_cases)
    script=args.plugin_root/'resources/script-library/xs2/story_support/story_support.py'
    spec=importlib.util.spec_from_file_location('p2_eval_support',script)
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    serial=support.serial();results=[]

    def archive(book,chapter,task,progress=None):
        os.environ['TASK_ID']=task
        support.begin_review(book,chapter)
        support.write(book,support.review_file(chapter,'observer.json'),{'confirmed_state':{'characters':[]}})
        support.write(book,support.review_file(chapter,'arbiter.json'),{'story_confirmed':{},'serial_progress':progress or []})
        return support.commit(book,chapter)

    def cli(book,action,chapter,task):
        result=subprocess.run([sys.executable,str(script),'serial','--serial-action',action,'--chapter',chapter],
            cwd=book,env=dict(os.environ,TASK_ID=task,PYTHONIOENCODING='utf-8'),
            capture_output=True,text=True,encoding='utf-8',timeout=120)
        assert result.returncode==0,result.stderr
        assert 'WF_REJECT_UPSTREAM' not in result.stdout,result.stdout
        return result.stdout

    def plan(book,chapter,task):
        cli(book,'prepare',chapter,task)
        request=support.load(book,serial.task_path(task,'request.json'))
        # One shared evidence anchor is sufficient for this mechanics fixture.
        source='story/0001/chapter.md';text=support.read(book,source)
        quote=next(line.strip()[:30] for line in text.splitlines() if len(line.strip())>=30)
        candidate={'fixture':True,'chapters':[{'chapter':f'{n:04d}','title':'离线流程验证',
            'intent':'沿用本书规则，保持尚未解决的选择；这是测试计划，不是小说正文。',
            'setup':[{'source_id':source,'quote':quote}]} for n in range(int(chapter),request['finish']+1)]}
        support.write(book,serial.task_path(task,'candidate.json'),candidate)
        cli(book,'normalize',chapter,task)
        normalized=support.load(book,serial.task_path(task,'normalized.json'))
        support.write(book,serial.task_path(task,'review.json'),{'fixture':True,'verdict':'pass','scope_change':False,
            'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256'],'findings':[]})
        return request

    for name in ('ancient','romance','apocalypse','scifi','fantasy'):
        book=args.output/name;shutil.copytree(args.source_cases/name/'book',book)
        manuscript=book/'story/0001/chapter.md';before=sha(manuscript)
        book_contract=support.archive_store().contract(book,persistent=True)
        support.write(book,'meta/serial_contract.json',{'schema':1,
            'planning':{'horizon':2,'authority':'bounded'},
            'volumes':[{'id':'one','title':'验证前卷','start':1,'end':1},
                       {'id':'two','title':'验证后卷','start':2,'end':3},
                       {'id':'three','title':'后续开放卷','start':4,'end':None}],
            'threads':[{'id':'open-choice','intent':'允许持续悬置；没有强制解决要求'}],
            'run_limits':{'max_dispatches':5,'max_chapters':4,'max_stage_attempts':2}})
        archive(book,'0001','p2-archive-'+name)
        status=serial.status(book,'0002')
        assert status['volume']['id']=='two' and status['entry']['chapter']=='0001'
        assert status['threads']['open-choice']['status']=='unconfirmed'
        task='p2-window-'+name;plan(book,'0002',task)
        cli(book,'commit','0002',task);first=support.read(book,f'planning/serial/receipts/{task}.json')
        cli(book,'commit','0002',task)
        assert support.read(book,f'planning/serial/receipts/{task}.json')==first
        assert serial.need_plan(book,'0002')['ready'] and serial.need_plan(book,'0003')['ready']
        # Append a clearly labelled test-only chapter to exercise actual post-hoc.
        fixture='离线流程测试资料：本章保留尚未解决的选择。此段不是模型生成的小说。'
        support.write(book,'story/0002/chapter.md',fixture)
        archive(book,'0002','p2-fixture-'+name,[{'thread_id':'open-choice','status':'intentionally_open',
            'evidence':'本章保留尚未解决的选择','requires_replan':True}])
        assert serial.need_plan(book,'0003')['reason_code']=='rolling_plan_stale'
        plan(book,'0003','p2-replan-'+name);cli(book,'commit','0003','p2-replan-'+name)
        assert serial.need_plan(book,'0003')['ready']
        support.write(book,'story/0003/chapter.md',fixture)
        archive(book,'0003','p2-fixture-three-'+name)
        next_volume=serial.status(book,'0004')
        assert next_volume['ready'] and next_volume['volume']['id']=='three'
        assert next_volume['threads']['open-choice']['status']=='intentionally_open'
        plan(book,'0004','p2-third-'+name)
        # Exercise durable pending publication and restart using the real journal.
        journal=serial.support().archive_store();atomic=journal.atomic
        def crash(*_):raise OSError('P2 offline injected interruption')
        journal.atomic=crash
        try:
            try:serial.commit(book,'p2-third-'+name)
            except OSError:pass
            else:raise AssertionError('failure injection did not execute')
        finally:journal.atomic=atomic
        cli(book,'commit','0004','p2-third-'+name)
        assert serial.need_plan(book,'0004')['ready']
        # The production run controller is loaded through the shipped module.
        path=args.plugin_root/'resources/script-library/xs2/console_service/run_control.py'
        spec=importlib.util.spec_from_file_location('p2_eval_run',path)
        run=importlib.util.module_from_spec(spec);spec.loader.exec_module(run)
        state={'values':{'chapter_number':'0004'}}
        reservation=run.admit(book,state,'outline')
        assert run.admit(book,state,'outline')==reservation
        run.observe(book,state,'outline',{'task_id':'budget-'+name,'status':'failed','run_id':'a'})
        run.observe(book,state,'outline',{'task_id':'budget-'+name,'status':'failed','run_id':'b'})
        try:run.observe(book,state,'outline',{'task_id':'budget-'+name,'status':'failed','run_id':'c'})
        except ValueError:pass
        else:raise AssertionError('restart bypassed attempt budget')
        assert sha(manuscript)==before and support.archive_store().contract(book,persistent=True)==book_contract
        row={'book':name,'source_manuscript_unchanged':True,'style_contract_unchanged':True,
            'cross_volume_actual_entry':True,'open_thread_carried':True,'rolling_window_published':True,
            'actual_deviation_replanned':True,'duplicate_commit_idempotent':True,
            'interrupted_commit_recovered':True,'restart_retry_budget_enforced':True,
            'final_window':['0004','0005'],'run':run.status(book,state)}
        results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    assert source_before==hashes(args.source_cases)
    result={'kind':'offline integration fixtures; no model calls or generated novels',
        'source_files_checked':len(source_before),'source_files_unchanged':True,'books':results}
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
