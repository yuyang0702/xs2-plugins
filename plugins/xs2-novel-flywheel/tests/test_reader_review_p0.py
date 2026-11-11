from runtime_graph import literary_graph
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from test_expression_evidence import checks, module as expression_module

PLUGIN = Path(__file__).resolve().parents[1]


def review():
    path = PLUGIN / 'resources/script-library/xs2/reader_review/reader_review.py'
    spec = importlib.util.spec_from_file_location('reader_review_p0', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return target


BODY = '她没见过验单。\n买方说不同意就付给陆。\n陆同意分付。'


def blind():
    return {'verdict': 'revise', 'summary': '让步缺少依据', 'issues': [
        {'id': 'blind-1', 'kind': 'causality', 'decision_id': 'd1', 'location': '结款',
         'priority': 'high', 'excerpts': ['买方说不同意就付给陆。', '陆同意分付。'],
         'impact': '拒绝没有损失，突然让步缺少承接。', 'goal': '建立已知的议价筹码。'}],
        'decisions': [{'id': 'd1', 'actor': '陆', 'choice': '同意分付',
                       'known_before': '买方可以直接付陆', 'leverage': '没有写出拒绝损失',
                       'alternatives': '拒绝分付', 'consequence': '同意分付',
                       'assessment': 'gap', 'excerpts': ['买方说不同意就付给陆。', '陆同意分付。']}], 'expression_checks': expression_checks()}


def expression_checks():
    rows=checks(expression_module())
    for row in rows:row['excerpts']=['她没见过验单。']
    return rows


def final(mode='restricted', status='outside_scope'):
    return {'verdict': 'pass', 'continue_reading_score': 90, 'summary': '局部任务完成',
            'issues': [], 'dimensions': {}, 'repair_constraints': ['只改开头'],
            'fact_review': {'verdict': 'pass', 'summary': '金额无误'},
            'expression_review': {'verdict': 'pass', 'summary': '文字通顺', 'issues': []}, 'expression_checks': expression_checks(),
            'revision_scope': {'mode': mode, 'summary': '只开放开头', 'assessments': [
                {'issue_id': 'blind-1', 'status': status, 'reason': '结款不在开头'}]}}


def book(root):
    write(root, 'story/0001/chapter.md', BODY)
    write(root, 'quality/old.json', {'continue_reading_score': 99, 'summary': 'SECRET_REVIEW'})
    write(root, 'feedback.md', 'SECRET_SCOPE 只改开头')
    write(root, '.novel-project.json', {'mode': 'short', 'title': '题名', 'analysisModel': 'test:model',
          'values': {'genre': '古风', 'narrative_pov': 'third_person',
                     'human_intent': 'SECRET_INTENT 上次已经修改完成',
                     'advisor_guidance': 'SECRET_PLAN', 'author_feedback_file': 'feedback.md'}})


def test_blind_input_is_allowlisted_and_task_frozen(tmp_path):
    r = review(); book(tmp_path)
    outputs = r.prepare(tmp_path, '0001', 'task-a')
    payload = (tmp_path / outputs['reader_blind_input']).read_text(encoding='utf-8')
    assert BODY in json.loads(payload)['manuscript']
    assert all(word not in payload for word in ['SECRET_REVIEW', 'SECRET_SCOPE', 'SECRET_INTENT', 'SECRET_PLAN'])
    assert json.loads(payload)['narrative_pov'] == 'third_person'
    assert r.prepare(tmp_path, '0001', 'task-a') == outputs
    write(tmp_path, 'story/0001/chapter.md', BODY + '正文变了。')
    with pytest.raises(ValueError, match='变化|不同'):
        r.prepare(tmp_path, '0001', 'task-a')
    assert r.prepare(tmp_path, '0001', 'task-b')['reader_blind_input'] != outputs['reader_blind_input']


def test_reader_binding_cannot_survive_a_changed_chapter_composition_budget(tmp_path):
    r=review();book(tmp_path);outputs=r.prepare(tmp_path,'0001','quota-review')
    write(tmp_path,'planning/length/0001.json',{'new_plan':'不同的分段意图与预算'})
    with pytest.raises(ValueError):r._bound(tmp_path,outputs['reader_review_binding'],outputs['reader_review_binding_sha'])


@pytest.mark.parametrize('quote', ['从未出现的话', '买方说……付给陆。', '买方说不同意就付给陆。陆同意分付。'])
def test_causal_findings_require_actual_continuous_manuscript_evidence(quote):
    r = review(); data = blind(); data['issues'][0]['excerpts'] = [quote]
    with pytest.raises(ValueError, match='引用|原文'):
        r.validate_blind(data, BODY)


def test_causal_gaps_cannot_disappear_into_a_pass_or_empty_issue_list():
    r = review(); data = blind(); data.update(verdict='pass', issues=[])
    with pytest.raises(ValueError, match='因果|问题'):
        r.validate_blind(data, BODY)


def test_quiet_scene_can_pass_without_manufactured_decisions():
    r = review()
    assert r.validate_blind({'verdict': 'pass', 'summary': '安静收尾成立', 'issues': [], 'decisions': []}, '她把灯点上。')['verdict'] == 'pass'


def test_out_of_scope_quality_issue_stays_visible_and_blocks_automatic_repair():
    r = review(); source = final(); before = copy.deepcopy(source)
    result = r.merge_review(source, blind(), BODY)
    assert source == before
    assert result['assessment_scope'] == 'whole_chapter'
    assert result['quality_verdict'] == result['verdict'] == 'revise'
    assert result['requires_scope_confirmation'] is True
    assert result['issues'][0]['id'] == 'blind-1'
    assert result['issues'][0]['editability'] == 'outside_scope'
    assert result['blind_review']['decisions'][0]['assessment'] == 'gap'


def test_editable_issue_still_requires_revision_but_does_not_pause_for_scope():
    result = review().merge_review(final('unrestricted', 'editable'), blind(), BODY)
    assert result['verdict'] == 'revise'
    assert result['requires_scope_confirmation'] is False


@pytest.mark.parametrize('source_changed',[False,True])
@pytest.mark.parametrize('stage',['context','blind'])
def test_invalid_context_report_retries_only_the_auditor_not_changed_source(tmp_path,monkeypatch,capsys,source_changed,stage):
    import sys
    from src.workflow.nodes.script import _parse_reject_upstream
    r=review();book(tmp_path);outputs=r.prepare(tmp_path,'0001','invalid-context')
    write(tmp_path,outputs['reader_blind_raw_path'],blind())
    committed=r.commit_blind(tmp_path,outputs['reader_review_binding'],outputs['reader_review_binding_sha'])
    data=final();data['revision_scope']['assessments'][0]['issue_id']='nonexistent-issue'
    write(tmp_path,outputs['reader_context_report_path'],data)
    if stage=='blind':
        data=blind();data['issues'][0]['priority']='low';data['decisions'][0]['assessment']='uncertain'
        write(tmp_path,outputs['reader_blind_raw_path'],data)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys,'argv',['reader_review.py','commit' if stage=='context' else 'commit-blind','--binding',outputs['reader_review_binding'],
        '--binding-sha',outputs['reader_review_binding_sha'],'--blind-sha',committed['reader_blind_report_sha']])
    if source_changed:
        write(tmp_path,'story/0001/chapter.md',BODY+'原文已改。')
        with pytest.raises(ValueError,match='变化'):r.main()
        assert _parse_reject_upstream(capsys.readouterr().out) is None
    else:
        r.main();reason,target=_parse_reject_upstream(capsys.readouterr().out)
        expected='问题编号' if stage=='context' else '实质问题'
        assert target==('agent_reader' if stage=='context' else 'agent_blind_reader') and expected in reason
        assert expected in (tmp_path/outputs['reader_'+stage+'_feedback']).read_text(encoding='utf-8')
        assert not (tmp_path/'story/0001/reader_report.json').exists()
        assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')==BODY
        wf=literary_graph(json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8')))
        merge=next(n for n in wf['nodes'] if n['id']==('script_reader_merge' if stage=='context' else 'script_reader_blind_commit'))
        assert merge['enable_reject_upstream'] and merge['max_reject_count']==3


def test_restricted_scope_missing_classification_is_unclear_not_permission():
    data = final(); data['revision_scope']['assessments'] = []
    result = review().merge_review(data, blind(), BODY)
    assert result['issues'][0]['editability'] == 'unclear'
    assert result['requires_scope_confirmation'] is True


def test_contextual_resolution_requires_visible_current_text_counterevidence():
    r = review(); data = final(); data['blind_resolutions'] = [
        {'issue_id': 'blind-1', 'reason': '前文已有约定', 'excerpts': ['她保留交付确认。']}]
    with pytest.raises(ValueError, match='引用|原文'):
        r.merge_review(data, blind(), BODY)
    body = '她保留交付确认。\n' + BODY
    result = r.merge_review(data, blind(), body)
    assert result['verdict'] == 'pass' and result['issues'] == []
    assert result['blind_review']['issues'][0]['id'] == 'blind-1'
    assert result['blind_resolutions'][0]['reason'] == '前文已有约定'


def test_tampering_with_new_report_cannot_turn_known_issues_into_a_pass():
    r = review(); report = r.merge_review(final(), blind(), BODY)
    report.update(verdict='pass', quality_verdict='pass', issues=[], requires_scope_confirmation=False)
    checked = r.gate_review(report, BODY)
    assert checked['verdict'] == 'revise' and checked['requires_scope_confirmation'] is True
    assert checked['issues'][0]['id'] == 'blind-1'


def test_committing_checks_frozen_body_feedback_and_blind_report(tmp_path):
    r = review(); book(tmp_path); outputs = r.prepare(tmp_path, '0001', 'task-a')
    write(tmp_path, outputs['reader_blind_raw_path'], blind())
    committed = r.commit_blind(tmp_path, outputs['reader_review_binding'], outputs['reader_review_binding_sha'])
    write(tmp_path, outputs['reader_context_report_path'], final())
    write(tmp_path, 'feedback.md', 'Changed after initial reading')
    with pytest.raises(ValueError, match='变化|不同'):
        r.commit(tmp_path, outputs['reader_review_binding'], outputs['reader_review_binding_sha'],
                 committed['reader_blind_report_sha'])
    assert not (tmp_path / 'story/0001/reader_report.json').exists()


def test_production_pauses_before_planning_repairs_outside_author_scope(tmp_path):
    from test_length_quality import policy
    r = review(); book(tmp_path)
    report = r.merge_review(final(), blind(), BODY)
    report.update(chapter_number='0001', body_sha256=hashlib.sha256((tmp_path/'story/0001/chapter.md').read_bytes()).hexdigest())
    report['review_binding'] = {'task_id':'manual-fixture','scope_source':r._scope_source(tmp_path),
                               'body_sha256':report['body_sha256']}
    write(tmp_path, 'story/0001/reader_report.json', report)
    state = {'mode': 'short', 'values': {'chapter_number': '0001'}, 'autoRepairLimit': 2}
    decision = policy().next_action(tmp_path, state, 'reader-sim')
    assert decision['action'] == 'pause' and '范围' in decision['reason']


@pytest.mark.parametrize('list_alternatives', [False, True])
def test_actual_initial_agent_receives_only_frozen_input_and_has_no_file_tools(tmp_path, list_alternatives):
    import asyncio
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    from src.agent.definition import _config_to_definition, resolve_agent_tools
    r = review(); book(tmp_path); outputs = r.prepare(tmp_path, '0001', 'task-a')
    definition = literary_graph(json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8')))
    wf = WorkflowDef.from_dict(definition)
    node = next(n for n in wf.nodes if n.id == 'agent_blind_reader')
    captured = {}
    response = blind()
    if list_alternatives:
        response['decisions'][0]['alternatives'] = ['拒绝分付', '接受分付']
    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            captured.update(kwargs)
            self.sessions['blind'] = SimpleNamespace(record=[{'type':'user','content':kwargs['task_description']},
                {'type':'assistant','content':json.dumps(response, ensure_ascii=False)}])
            kwargs['on_auto_complete']('blind', 'done', 'success', '')
            return {'success':True,'session_id':'blind'}
    async def run():
        return await asyncio.wait_for(AgentNode().execute(NodeContext(definition=wf, node_def=node,
            node_state=NodeExecutionState(node_id=node.id), session_manager=Manager(), shared_ws=tmp_path,
            parameter_values={**outputs, 'chapter_number':'0001'})), timeout=5)
    result = asyncio.run(run())
    assert result.status == 'completed'
    message = captured['task_description']
    assert 'SECRET_' not in message and '买方说不同意就付给陆。' in message
    agents = json.loads((PLUGIN/'resources/agents.json').read_text(encoding='utf-8'))['agents']
    agent = _config_to_definition('xs2-blind-reader', agents['xs2-blind-reader'])
    assert resolve_agent_tools(agent, [SimpleNamespace(name='read_file'), SimpleNamespace(name='write_file')], []) == []
    assert json.loads((tmp_path/outputs['reader_blind_raw_path']).read_text(encoding='utf-8'))['issues'][0]['kind'] == 'causality'


@pytest.mark.parametrize('alternatives', ['拒绝分付或接受分付', ['拒绝分付', '接受分付']])
def test_causal_alternatives_accept_text_or_nonempty_named_choices(alternatives):
    data = blind();data['decisions'][0]['alternatives'] = alternatives
    assert review().validate_blind(data, BODY)['decisions'][0]['alternatives'] == alternatives


@pytest.mark.parametrize('alternatives', ['', [], [None], [''], True, 12])
def test_causal_alternatives_reject_empty_or_invalid_choices(alternatives):
    data = blind();data['decisions'][0]['alternatives'] = alternatives
    with pytest.raises(ValueError, match='可选行为|alternatives|文字字段'):
        review().validate_blind(data, BODY)


def test_assessment_only_finishes_without_repairing_out_of_scope_findings(tmp_path):
    from test_length_quality import policy
    r = review(); book(tmp_path)
    report = r.merge_review(final(), blind(), BODY)
    report['review_binding'] = {'task_id':'manual-fixture','scope_source':r._scope_source(tmp_path),
                               'body_sha256':report.get('body_sha256')}
    write(tmp_path, 'story/0001/reader_report.json', report)
    state = {'mode':'short','assessmentOnly':True,'values':{'chapter_number':'0001'}}
    assert policy().next_action(tmp_path, state, 'reader-sim')['action'] == 'finish'


def test_contextual_expression_issue_is_classified_before_scope_validation():
    data = final()
    data['revision_scope']['assessments'] = []
    data['expression_review'] = {'verdict':'revise','summary':'重复结论','issues':[
        {'id':'context-1','location':'结尾','priority':'medium','excerpts':['陆同意分付。'],
         'impact':'已成立的结果再次解释','goal':'合并说明'}]}
    data['revision_scope']['assessments'].append(
        {'issue_id':'context-1','status':'outside_scope','reason':'只允许改开头'})
    checked = review().merge_review(data, {'verdict':'pass','summary':'初审无问题','issues':[],'decisions':[]}, BODY)
    assert checked['verdict'] == 'revise' and checked['requires_scope_confirmation'] is True
    assert checked['issues'][0]['id'] == 'context-1'


def test_published_scope_is_invalidated_when_author_changes_permission(tmp_path):
    from test_length_quality import policy
    r = review(); book(tmp_path)
    outputs = r.prepare(tmp_path, '0001', 'task-scope')
    write(tmp_path, outputs['reader_blind_raw_path'], blind())
    bound = r.commit_blind(tmp_path, outputs['reader_review_binding'], outputs['reader_review_binding_sha'])
    write(tmp_path, outputs['reader_context_report_path'], final('unrestricted', 'editable'))
    r.commit(tmp_path, outputs['reader_review_binding'], outputs['reader_review_binding_sha'], bound['reader_blind_report_sha'])
    write(tmp_path, 'feedback.md', '现在只能改开头，结款不许动')
    state = {'mode':'short','values':{'chapter_number':'0001'}}
    with pytest.raises(ValueError, match='范围|要求|变化'):
        policy().next_action(tmp_path, state, 'reader-sim')


@pytest.mark.parametrize('area', ['verdict', 'fact_review'])
def test_nonpass_report_without_locatable_material_cause_cannot_launch_repairs(area):
    data = final(); data['revision_scope']['assessments'] = []
    if area == 'verdict':data['verdict'] = 'revise'
    else:data['fact_review']['verdict'] = 'revise'
    with pytest.raises(ValueError, match='实质问题|定位|依据'):
        review().merge_review(data, {'verdict':'pass','summary':'初审无问题','issues':[],'decisions':[]}, BODY)


def test_contextual_id_cannot_alias_an_independent_out_of_scope_finding():
    data = final(status='editable')
    data['issues'] = [{'id':'blind-1','location':'开头','priority':'medium',
                      'impact':'开头说明重复','goal':'合并开头','excerpts':['她没见过验单。']}]
    with pytest.raises(ValueError, match='编号|重复|冲突'):
        review().merge_review(data, blind(), BODY)


def test_contextual_expression_verdict_can_refer_to_preserved_initial_findings():
    initial = {'verdict':'revise','summary':'重复说明','decisions':[], 'issues':[
        {'id':'blind-1','kind':'expression','location':'结款','priority':'medium',
         'excerpts':['陆同意分付。'],'impact':'重复已经成立的结果','goal':'合并说明'}]}
    contextual = final()
    contextual['expression_review'] = {'verdict':'revise','summary':'初审表达问题仍成立，不重复抄写','issues':[]}
    r = review();merged = r.merge_review(contextual, initial, BODY)
    assert merged['verdict']=='revise' and merged['requires_scope_confirmation'] is True
    assert [i['id'] for i in merged['issues']]==['blind-1']
    assert [i['id'] for i in merged['expression_review']['issues']]==['blind-1']
    assert r.gate_review(merged, BODY)==merged


@pytest.mark.parametrize('case',['findings','pass','retry_context'])
def test_full_reader_graph_runs_actual_plugin_clis_without_touching_body(tmp_path, monkeypatch,case):
    """Model boundary uses fixtures; scheduler, rendered inputs, CLIs and publication are real."""
    import asyncio
    import os
    import shlex
    import sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef, WorkflowTask, WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin, NodeResult, registry
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    from test_length_quality import policy
    book(tmp_path)
    original = (tmp_path/'story/0001/chapter.md').read_bytes()
    raw=literary_graph(json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8')))
    wf=WorkflowDef.from_dict(raw); assert not wf.validate()
    calls=[];started=set();both_started=asyncio.Event()
    class Manager:
        sessions={}
        main_session_id=''
        async def create_sub_session(self, **kwargs):
            node=kwargs['node_id'];calls.append(node)
            if node in ('agent_blind_reader','agent_context_reader'):
                started.add(node)
                if len(started)==2:both_started.set()
                await asyncio.wait_for(both_started.wait(),timeout=3)
            if node=='agent_blind_reader':
                assert 'SECRET_' not in kwargs['task_description']
                output=blind()
                if case!='findings':output.update(verdict='pass',issues=[],decisions=[])
            elif node=='agent_context_reader':
                assert 'SECRET_SCOPE' in kwargs['task_description']
                assert 'blind-1' not in kwargs['task_description']
                output=final();output['revision_scope']['assessments']=[];output['blind_resolutions']=[]
                if case=='retry_context' and calls.count(node)==1:output['blind_resolutions']=[{'issue_id':'guessed'}]
            else:
                assert 'SECRET_SCOPE' in kwargs['task_description']
                assert 'blind-1' in kwargs['task_description']
                output=final()
            self.sessions[node]=SimpleNamespace(record=[{'type':'user','content':kwargs['task_description']},
                {'type':'assistant','content':json.dumps(output,ensure_ascii=False)}])
            kwargs['on_auto_complete'](node,'done','success','')
            return {'success':True,'session_id':node}
    class CLI(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            calls.append(ctx.node_def.id)
            params=ctx.node_def.node_params
            if 'script_argv' in params:
                args=[await resolve_placeholders(x,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for x in params['script_argv']]
            else:
                args=shlex.split(await resolve_placeholders(params['script_args'],ctx.parameter_values,ctx.definition.variables,str(tmp_path)))
            script=PLUGIN/'resources/script-library'/params['script_group']/params['script_name']/(params['script_name']+'.py')
            child=await asyncio.create_subprocess_exec(sys.executable,str(script),*args,cwd=tmp_path,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},
                creationflags=0x08000000 if sys.platform=='win32' else 0)
            stdout,stderr=await child.communicate()
            return NodeResult(status='completed' if child.returncode==0 else 'failed',
                outputs=_parse_wf_vars(stdout.decode('utf-8')),error=stderr.decode('utf-8'))
    monkeypatch.setitem(registry._plugins,'agent',AgentNode)
    monkeypatch.setitem(registry._plugins,'script',CLI)
    engine=WorkflowEngine(Manager())
    async def no_save(*_args):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save)
    monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_args:None)
    state=json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf-8'))
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(policy().parameters(state,raw))
    task=WorkflowTask(task_id='task-reader-integration',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run():
        from src.workflow.failure_policy import activate_scheduled_retry
        for _ in range(8):
            for key,value in list(task.node_states.items()):
                if value.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(value)
            outcome=await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),
                disabled_ids=set(),shared_ws=tmp_path,parent_id='test',on_node_started=lambda *_:None,
                needs_approval=False,run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
            if outcome!='retry_waiting':return outcome
    assert asyncio.run(run())=='completed', {key:s.error for key,s in task.node_states.items() if s.error}
    assert started=={'agent_blind_reader','agent_context_reader'}
    assert calls.index('script_story_context') < calls.index('agent_blind_reader') < calls.index('script_reader_join')
    assert calls.count('agent_blind_reader')==1
    assert calls.count('agent_context_reader')==(2 if case=='retry_context' else 1)
    assert calls.count('agent_reader')==(1 if case=='findings' else 0)
    frozen=json.loads(next((tmp_path/'cache/reader-review').rglob('parallel-sources.json')).read_text(encoding='utf8'))
    assert frozen['context_path']=='cache/story-support/context.md'
    report=json.loads((tmp_path/'story/0001/reader_report.json').read_text(encoding='utf-8'))
    assert report['verdict']==('revise' if case=='findings' else 'pass')
    assert report['requires_scope_confirmation']==(case=='findings')
    assert report['review_binding']['task_id']=='task-reader-integration'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==original
