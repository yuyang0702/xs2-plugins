import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN=Path(__file__).resolve().parents[1]


def helper():
    path=PLUGIN/'resources/script-library/xs2/prose_policy/book_contract.py'
    spec=importlib.util.spec_from_file_location('book_contract_tests',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def put(root,path,value):
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False) if isinstance(value,dict) else value,encoding='utf-8')


def test_unspecified_style_preserves_voice_and_does_not_infer_scope_from_genre(tmp_path):
    put(tmp_path,'.novel-project.json',{'values':{'genre':'玄幻','narrative_pov':'third_person'}})
    c=helper().resolve(tmp_path)
    assert c['genre']=='玄幻' and c['narrator_scope']=='preserve'
    assert c['style_intent']=='' and c['intentional_devices']==[]
    assert '付款后取工具' not in json.dumps(c,ensure_ascii=False)


def test_explicit_book_contract_is_independent_of_genre_and_supports_impossible_world(tmp_path):
    put(tmp_path,'.novel-project.json',{'values':{'genre':'科幻','narrative_pov':'third_person','human_intent':'秘密结局'}})
    put(tmp_path,'meta/narrative_contract.json',{'schema':1,'narrator_scope':'omniscient',
        'style_intent':'允许解释技术与进入多人的内心','intentional_devices':['有意复沓'],
        'protected_phrases':['门会记住潮声'],'allow_repeated_passages':True})
    put(tmp_path,'meta/world_foundation.md','本书假设记忆可以由门保存；秘密世界真相。')
    c=helper().resolve(tmp_path)
    assert c['narrator_scope']=='omniscient' and c['allow_repeated_passages'] is True
    assert '记忆可以由门保存' in c['world_sources'][0]['text']
    public=helper().public_style(c)
    assert public['narrator_scope']=='omniscient' and public['protected_phrases']==['门会记住潮声']
    assert '秘密' not in json.dumps(public,ensure_ascii=False)


def test_contract_freeze_binds_world_and_style_changes_without_touching_sources(tmp_path):
    put(tmp_path,'meta/style_profile.md','缓慢抒情，容许回环。')
    before=(tmp_path/'meta/style_profile.md').read_bytes()
    m=helper();f=m.freeze(tmp_path,'book-test')
    assert m.freeze(tmp_path,'book-test')==f
    assert (tmp_path/f['prompt_file']).is_file()
    assert (tmp_path/'meta/style_profile.md').read_bytes()==before
    put(tmp_path,'meta/style_profile.md','快节奏动作。')
    with pytest.raises(ValueError,match='变化|新任务'):
        m.freeze(tmp_path,'book-test')
    assert m.digest(m.resolve(tmp_path))!=f['sha256']


@pytest.mark.parametrize('patch',[{'narrator_scope':'all_books_limited'},
    {'allow_repeated_passages':'yes'},{'protected_phrases':'一句话'},{'external_file':'../other-book'}])
def test_invalid_contract_is_not_silently_coerced(tmp_path,patch):
    put(tmp_path,'meta/narrative_contract.json',{'schema':1,**patch})
    with pytest.raises(ValueError):helper().resolve(tmp_path)


def test_reader_blind_input_gets_style_but_not_private_world_or_author_plot(tmp_path):
    from test_reader_review_p0 import review
    put(tmp_path,'.novel-project.json',{'values':{'genre':'言情','human_intent':'私密情节计划'}})
    put(tmp_path,'meta/narrative_contract.json',{'schema':1,'narrator_scope':'unreliable','style_intent':'第一人称回忆，允许回环'})
    put(tmp_path,'meta/world_foundation.md','不能提前告诉读者的世界真相')
    put(tmp_path,'story/0001/chapter.md','她把信收起来。')
    paths=review().prepare(tmp_path,'0001','book-reader')
    payload=json.loads((tmp_path/paths['reader_blind_input']).read_text(encoding='utf-8'))
    assert payload['style_contract']['narrator_scope']=='unreliable'
    assert '私密情节计划' not in json.dumps(payload,ensure_ascii=False)
    assert '世界真相' not in json.dumps(payload,ensure_ascii=False)


def test_shared_templates_do_not_require_one_books_choreography_or_limited_pov():
    root=PLUGIN/'resources/workflows'
    for path in root.glob('*/definition.json'):
        d=json.loads(path.read_text(encoding='utf-8'))
        text='\n'.join(n.get('first_message','') for n in d['nodes'])
        for term in ['付款后取工具','陆承远','沈照夜','整批验收合格、实际点收、交清成品',
                     '不因句子更顺就放过钱款、身份、限知视角']:
            assert term not in text,(path,term)


def test_shared_viewpoint_instructions_do_not_contradict_the_book_contract():
    forbidden=['正文使用第三人称叙述，并保持当前焦点角色稳定，不得把叙述者写成',
               '正文叙述只能使用第一人称视角（我/我们），只能写叙述者当下能感知']
    paths=list((PLUGIN/'resources/workflows').glob('*/definition.json'))+[PLUGIN/'resources/prompts.json']
    for path in paths:
        data=json.loads(path.read_text(encoding='utf-8'))
        for term in forbidden:
            assert term not in json.dumps(data,ensure_ascii=False),(path,term)


def test_writing_contextual_review_and_revision_share_the_contract_file():
    for stage in ['mvp','polish','reader-sim']:
        d=json.loads((PLUGIN/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8'))
        assert any(v['key']=='book_contract_file' and v['type']=='file' for v in d['variables'])
        for n in d['nodes']:
            if n['node_type']=='agent' and 'blind' not in n['id']:
                model_views={'agent_sc':'revision_source_model','agent_pl':'revision_editor_model','agent_local_review':'revision_review_model',
                    'agent_composition_plan':'composition_request_model','agent_composition_review':'composition_review_model',
                    'agent_guard_facts_repair':'guard_facts_model','agent_guard_facts_audit':'guard_facts_audit_model',
                    'agent_guard_expression_repair':'guard_expression_model','agent_guard_expression_audit':'guard_expression_audit_model'}
                if n['id'] in model_views:
                    assert '{{'+model_views[n['id']]+'}}' in n['first_message'] and 'book_contract' in n['first_message']
                else:assert '{{book_contract_file}}' in n['first_message'],(stage,n['id'])


def test_declared_refrain_and_variable_narration_are_not_scene_regex_errors():
    path=PLUGIN/'resources/script-library/xs2/multi_scene/multi_scene.py'
    spec=importlib.util.spec_from_file_location('book_scene_contract',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    refrain='我走过这一条很长很长的海堤，听见潮声一遍又一遍越过窗沿。'
    c={'narrator_scope':'variable','allow_repeated_passages':True}
    assert m.scene_problem(refrain+'\n\n'+refrain,1,500,'third_person',book_contract=c) is None


def test_author_settings_can_describe_scope_and_style_without_a_genre_preset():
    path=PLUGIN/'resources/script-library/xs2/console_service/configuration.py'
    spec=importlib.util.spec_from_file_location('book_style_configuration',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    _,items=m.parse_configuration(json.dumps({'reply':'按作者要求。','suggestions':[
        {'key':'narrator_scope','value':'omniscient'},{'key':'style_intent','value':'技术说明与抒情交错'}]}),'short')
    assert {i['key'] for i in items}=={'narrator_scope','style_intent'}


def test_existing_prose_preference_mode_is_part_of_the_contract_binding(tmp_path,monkeypatch):
    from types import SimpleNamespace
    m=helper();selected={'mode':'original','instructions':''}
    monkeypatch.setattr(m,'policy',lambda:SimpleNamespace(effective_context=lambda *_:dict(selected)))
    original=m.digest(m.resolve(tmp_path))
    selected.update(mode='narrative_led',instructions='作者明确选择叙述主导')
    assert m.digest(m.resolve(tmp_path))!=original


def test_single_writer_uses_the_same_frozen_plan_and_two_stage_guard(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    raw=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    wf=WorkflowDef.from_dict(raw);calls=[]
    class Trace(BaseNodePlugin):
        async def execute(self,ctx):
            calls.append(ctx.node_def.id)
            return NodeResult(status='completed',outputs={'guard_enabled':'yes'} if ctx.node_def.id=='script_guard_prepare' else {})
    monkeypatch.setitem(registry._plugins,'script',Trace);monkeypatch.setitem(registry._plugins,'agent',Trace)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(writer_type='single',guard_enabled='yes')
    task=WorkflowTask(task_id='single-contract',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run():
        return await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(start_node_id='script_multi_prepare'),
            disabled_ids=set(),shared_ws=tmp_path,parent_id='test',on_node_started=lambda _:None,needs_approval=False,run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    assert asyncio.run(run())=='completed'
    assert 'agent_sw' in calls
    assert calls.index('agent_nw')<calls.index('agent_sw')<calls.index('agent_guard_facts_repair')<calls.index('agent_guard_expression_repair')
