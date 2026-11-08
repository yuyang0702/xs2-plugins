import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_continuity_contract import contract,evidence,SOURCES,PLUGIN


def module():
    path=PLUGIN/'resources/script-library/xs2/draft_guard/draft_guard.py'
    assert path.is_file(),'missing ordered draft guard'
    spec=importlib.util.spec_from_file_location('test_ordered_guard',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def run(m,root,monkeypatch,capsys,action,phase='facts',expression_format='body'):
    monkeypatch.chdir(root);monkeypatch.setenv('TASK_ID','task-guard')
    monkeypatch.setattr('sys.argv',['guard',action,'--phase',phase,'--multi-dir','cache/multi/task-guard','--target','1-500','--pov','third_person','--expression-format',expression_format])
    m.main();return capsys.readouterr().out


def prepared(root,monkeypatch,capsys,expression_format='body'):
    m=module();multi=root/'cache/multi/task-guard';save(multi/'plan.json',{'scenes':[{'id':1},{'id':2}],'continuity':contract()})
    (multi/'planning-sources.md').write_text(SOURCES,encoding='utf-8')
    save(root/'cache/si/chapter.json',{'body':'未经修订的原始试稿'})
    run(m,root,monkeypatch,capsys,'prepare',expression_format=expression_format);return m,root/'cache/draft-guard/task-guard'


def accepted_facts(root,monkeypatch,capsys):
    m,d=prepared(root,monkeypatch,capsys);body,report=evidence()
    save(d/'facts-draft.json',{'body':body});run(m,root,monkeypatch,capsys,'candidate')
    save(d/'facts-audit.json',report)
    assert 'WF_REJECT' not in run(m,root,monkeypatch,capsys,'commit')
    return m,d,body


def test_only_expression_approval_can_replace_the_assembled_draft(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']=='未经修订的原始试稿'
    assert (d/'facts-approved.json').is_file()
    _,report=evidence(body);report['checks']['repetition']=True
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']==body


def test_candidate_retry_refreshes_completed_auditor_instead_of_reusing_old_proof(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);body,report=evidence()
    save(d/'facts-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate');save(d/'facts-audit.json',report)
    save(d/'facts-draft.json',{'body':body+'她离开。'})
    result=run(m,tmp_path,monkeypatch,capsys,'commit')
    assert 'target="agent_guard_facts_audit"' in result
    audit_input=json.loads((d/'facts-audit-input.json').read_text(encoding='utf-8'))
    assert audit_input['candidate_body']==body+'她离开。'
    assert audit_input['actual_word_count']==m.length.count_prose(body+'她离开。')
    assert not (d/'facts-approved.json').exists()


def test_expression_cannot_regress_payment_even_when_model_lists_no_issues(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    body=body.replace('她付一两二钱纸债','她付一两整银又二十文纸债');_,report=evidence()
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest();report['checks']['repetition']=True
    report['money_observations'][1]['paid']={'text':'一两整银又二十文','occurrence':1}
    report['event_observations'][4]['quote']={'text':'她付一两整银又二十文纸债','occurrence':1}
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression');save(d/'expression-audit.json',report)
    output=run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert 'target="agent_guard_expression_repair"' in output and '1020' in output
    assert not (d/'final-receipt.json').exists()


def test_contract_drift_cannot_reuse_repair_or_audit_files(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);plan=tmp_path/'cache/multi/task-guard/plan.json'
    value=json.loads(plan.read_text(encoding='utf-8'));value['continuity']['facts'][0]['value']='别的铺';save(plan,value)
    with pytest.raises(ValueError,match='变化|新任务|绑定'):
        run(m,tmp_path,monkeypatch,capsys,'candidate')


def test_edited_approved_fact_body_cannot_keep_the_old_auditor_approval(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    approved=json.loads((d/'facts-approved.json').read_text(encoding='utf-8'))
    approved['body']=body+'未经核验的修改。';approved['body_sha256']=hashlib.sha256(approved['body'].encode()).hexdigest();save(d/'facts-approved.json',approved)
    current=json.loads((d/'expression-input.json').read_text(encoding='utf-8'));current['source_body']=approved['body'];save(d/'expression-input.json',current)
    save(d/'expression-draft.json',{'body':approved['body']})
    with pytest.raises(ValueError,match='核验|事实|变化'):
        run(m,tmp_path,monkeypatch,capsys,'candidate','expression')


def test_missing_or_unquoted_report_is_returned_to_the_auditor(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);body,report=evidence();save(d/'facts-draft.json',{'body':body})
    run(m,tmp_path,monkeypatch,capsys,'candidate');report['event_observations'][0]['quote']['text']='没有这句'
    save(d/'facts-audit.json',report)
    assert 'target="agent_guard_facts_audit"' in run(m,tmp_path,monkeypatch,capsys,'commit')
    assert not (d/'facts-approved.json').exists()


def test_hard_fact_repair_uses_analysis_model_and_expression_keeps_body_writer():
    path=PLUGIN/'resources/script-library/xs2/console_service/production.py'
    spec=importlib.util.spec_from_file_location('ordered_repair_models',path);production=importlib.util.module_from_spec(spec);spec.loader.exec_module(production)
    definition=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    selected=production.model_overrides({'analysisModel':'analysis:solver','writerModel':'body:writer','polishModel':'polish:editor'},definition,'mvp')
    assert selected['agent_guard_facts_repair']=='analysis:solver'
    assert selected['agent_guard_expression_repair']=='body:writer'
    assert selected['agent_guard_facts_audit']==selected['agent_guard_expression_audit']=='analysis:solver'


@pytest.mark.parametrize('retry',[False,True])
def test_real_scheduler_orders_fact_then_expression_and_reaudits_replaced_candidate(tmp_path,monkeypatch,capsys,retry):
    import asyncio
    import os
    import subprocess
    import sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.failure_policy import activate_scheduled_retry
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.script import _parse_reject_upstream,_parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    raw=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    wf=WorkflowDef.from_dict(raw)
    assert wf.get_node('script_guard_prepare') is not None
    assert not wf.validate()
    _,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches');calls=[];good,_=evidence()
    class Agent(BaseNodePlugin):
        node_type='agent'
        async def execute(self,ctx):
            key=ctx.node_def.id;calls.append(key);phase='expression' if 'expression' in key else 'facts'
            if key.endswith('_repair'):
                text=good
                if retry and phase=='facts' and calls.count(key)==1:text=text.replace('她付一两二钱纸债','她付一两整银又二十文纸债')
                save(d/f'{phase}-draft.json',{'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'edits':[]} if phase=='expression' else {'body':text})
            else:
                current=json.loads((d/f'{phase}-audit-input.json').read_text(encoding='utf-8'))['candidate_body']
                _,report=evidence();report['candidate_sha256']=hashlib.sha256(current.encode()).hexdigest()
                report['book_contract_sha256']=json.loads((d/'binding.json').read_text(encoding='utf-8'))['book_contract_sha256']
                if '一两整银又二十文' in current:
                    report['money_observations'][1]['paid']={'text':'一两整银又二十文','occurrence':1}
                    report['event_observations'][4]['quote']={'text':'她付一两整银又二十文纸债','occurrence':1}
                if phase=='expression':report['checks']['repetition']=True
                save(d/f'{phase}-audit.json',report)
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            if not ctx.node_def.id.startswith('script_guard_'):return NodeResult(status='completed')
            params=ctx.node_def.node_params
            args=[await resolve_placeholders(x,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for x in params['script_argv']]
            p=subprocess.run([sys.executable,str(PLUGIN/'resources/script-library/xs2/draft_guard/draft_guard.py'),*args],cwd=tmp_path,capture_output=True,
                env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},creationflags=0x08000000 if sys.platform=='win32' else 0)
            reject=_parse_reject_upstream(p.stdout.decode('utf-8'))
            if reject:
                reason,target=reject;assert ctx.on_reject_upstream('fixture',reason,target)['success']
                return NodeResult(status='failed',error=reason)
            return NodeResult(status='completed' if p.returncode==0 else 'failed',outputs=_parse_wf_vars(p.stdout.decode('utf-8')),error=p.stderr.decode('utf-8'))
    monkeypatch.setitem(registry._plugins,'agent',Agent);monkeypatch.setitem(registry._plugins,'script',Script)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(multi_dir='cache/multi/task-guard',target_word_count='1-500',narrative_pov='third_person')
    task=WorkflowTask(task_id='task-guard',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def execute():
        return await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(start_node_id='script_guard_prepare'),disabled_ids=set(),
            shared_ws=tmp_path,parent_id='test',on_node_started=lambda _:None,needs_approval=False,run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    for _ in range(6):
        outcome=asyncio.run(execute())
        if outcome=='completed':break
        assert outcome=='retry_waiting',{k:s.error for k,s in task.node_states.items() if s.error}
        for key,state in list(task.node_states.items()):
            if state.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(state)
    assert outcome=='completed'
    assert calls.index('agent_guard_expression_repair')>max(i for i,k in enumerate(calls) if k=='agent_guard_facts_audit')
    assert calls.count('agent_guard_facts_repair')==(2 if retry else 1)
    assert calls.count('agent_guard_facts_audit')==(2 if retry else 1)
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']==good
