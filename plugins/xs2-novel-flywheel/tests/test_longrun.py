import importlib.util
import json
from pathlib import Path

import pytest
from test_story_support import support, commit_chapter

HERE=support.HERE.parent/'longrun'


def ledger():
    path=HERE/'ledger.py'
    assert path.is_file(),'Long-run observation ledger is not implemented'
    spec=importlib.util.spec_from_file_location('test_longrun_ledger',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def config(**changes):
    return {'schema':1,'target_new_characters':100000,'models':['test:writer'],
        'limits':{'max_calls':10,'max_total_tokens':1000},'pricing':{
            'version':'unconfigured','currency':'USD','timezone':'UTC','unit_tokens':1000000,'rules':[]},**changes}


def setup(root,**changes):
    module=ledger();module.initialize(root,config(**changes),baseline_chapters=['0001']);return module


def test_copy_initialization_preserves_source_and_protects_existing_destinations(tmp_path):
    module=ledger();source=tmp_path/'original';support.write(source,'story/0001/chapter.md','第一章原稿。')
    support.write(source,'.novel-project.json',{'mode':'short'})
    copy=tmp_path/'copy';module.initialize_copy(source,copy,config())
    assert (copy/'story/0001/chapter.md').read_bytes()==(source/'story/0001/chapter.md').read_bytes()
    assert module.check_sources(copy)['unchanged']
    with pytest.raises(ValueError):module.initialize_copy(source,copy,config())
    with pytest.raises(ValueError):module.initialize_copy(source,source/'nested',config())
    support.write(source,'story/0001/chapter.md','原稿在外部被修改。')
    with pytest.raises(ValueError,match='来源|原稿'):module.check_sources(copy)


def test_restarted_call_reservation_cannot_reset_token_budget(tmp_path):
    module=setup(tmp_path)
    call=module.reserve_call(tmp_path,{'model_id':'test:writer'},600)
    assert call
    with pytest.raises(ValueError,match='预算'):ledger().reserve_call(tmp_path,{'model_id':'test:writer'},600)
    assert ledger().report(tmp_path)['usage']['reserved_unknown_tokens']==600


def test_actual_call_completion_is_idempotent_and_missing_price_is_not_free(tmp_path):
    module=setup(tmp_path);call=module.reserve_call(tmp_path,{'model_id':'test:writer'},600)
    result={'status':'completed','usage_status':'complete','prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
    module.finish_call(tmp_path,call,result);module.finish_call(tmp_path,call,result)
    report=ledger().report(tmp_path)
    assert report['usage']['actual_tokens']==120 and report['usage']['call_count']==1
    assert report['usage']['reserved_unknown_tokens']==0
    assert report['cost']['status']=='unpriced' and report['cost']['amount'] is None
    with pytest.raises(ValueError,match='凭据|变化|不同'):
        module.finish_call(tmp_path,call,{**result,'total_tokens':121})


def test_failed_request_without_provider_usage_retains_uncertain_reservation(tmp_path):
    module=setup(tmp_path);call=module.reserve_call(tmp_path,{'model_id':'test:writer'},600)
    module.finish_call(tmp_path,call,{'status':'failed','usage_status':'unknown','error_type':'TimeoutError'})
    report=module.report(tmp_path)
    assert report['usage']['actual_tokens']==0
    assert report['usage']['unknown_call_count']==1
    assert report['usage']['reserved_unknown_tokens']==600
    assert report['acceptance']['status']!='passed'


def test_same_task_observation_does_not_duplicate_events_or_usage(tmp_path):
    module=setup(tmp_path);state={'values':{'chapter_number':'0002'}}
    task={'task_id':'one','status':'failed','node_states':{},'error':'fixture interruption'}
    module.observe_task(tmp_path,state,'mvp',task,'stage_failed')
    module.observe_task(tmp_path,state,'mvp',task,'stage_failed')
    assert len(module.report(tmp_path)['recoveries']['failures'])==1


def test_only_new_current_confirmed_exported_prose_counts(tmp_path):
    module=setup(tmp_path);commit_chapter(tmp_path,'0001');commit_chapter(tmp_path,'0002')
    for number in ('0001','0002'):
        support.write(tmp_path,f'story/{number}/reader_report.json',{'verdict':'pass','chapter_number':number,
            'body_sha256':support.digest(tmp_path,f'story/{number}/chapter.md')})
        module.accept_chapter(tmp_path,number,{'task_id':'export-'+number,'status':'completed'})
    before=module.report(tmp_path)
    assert before['progress']['accepted_new_chapters']==['0002']
    assert before['progress']['accepted_new_characters']>0
    assert before['acceptance']['audit_coverage_complete'] is False
    support.write(tmp_path,'story/0002/chapter.md','正文在审核后被改了。')
    after=module.report(tmp_path)
    assert after['progress']['accepted_new_characters']==0
    assert '0002' in after['progress']['invalidated_chapters']


def test_audit_rejects_fabricated_evidence_and_keeps_valid_findings(tmp_path):
    module=setup(tmp_path);commit_chapter(tmp_path,'0001')
    request={'chapter':'0001','sources':{'story/0001/chapter.md':support.read(tmp_path,'story/0001/chapter.md')},
        'source_hashes':{'story/0001/chapter.md':support.digest(tmp_path,'story/0001/chapter.md')}}
    result={'verdict':'issues','issues':[{'kind':'memory_omission','severity':'medium','description':'遗漏了决定',
        'evidence':[{'source_id':'story/0001/chapter.md','quote':'正文不存在的证据'}]}]}
    with pytest.raises(ValueError,match='证据'):module.accept_audit(tmp_path,request,result)
    result['issues'][0]['evidence'][0]['quote']='决定留下救人'
    module.accept_audit(tmp_path,request,result)
    assert len(module.report(tmp_path)['audits']['issues'])==1


def test_unapproved_model_cannot_consume_a_call_reservation(tmp_path):
    module=setup(tmp_path)
    with pytest.raises(ValueError,match='模型|授权'):module.reserve_call(tmp_path,{'model_id':'other:model'},100)


def helper(name):
    file=(HERE.parents[3]/'runtime/longrun'/(name+'.py')) if name in ('driver','transport') else HERE/(name+'.py')
    assert file.is_file(),name+' is not implemented'
    spec=importlib.util.spec_from_file_location('test_longrun_'+name,file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_provider_usage_is_measured_and_missing_usage_stays_unknown():
    from types import SimpleNamespace
    module=helper('transport')
    result=module.normalize_usage(SimpleNamespace(usage_metadata={'input_tokens':100,'output_tokens':25,'total_tokens':125},response_metadata={}))
    assert result['usage_status']=='complete' and result['total_tokens']==125
    assert result['raw_usage_metadata']['input_tokens']==100
    absent=module.normalize_usage(SimpleNamespace(usage_metadata={},response_metadata={}))
    assert absent['usage_status']=='unknown' and 'prompt_tokens' not in absent


def test_process_lock_rejects_concurrent_driver(tmp_path):
    module=helper('driver')
    with module.run_lock(tmp_path):
        with pytest.raises((ValueError,OSError),match='运行|锁|lock|access|another'):
            with module.run_lock(tmp_path):pass
    with module.run_lock(tmp_path):pass


def test_audit_packet_pins_historical_sources_not_live_current_ledgers(tmp_path):
    setup(tmp_path);commit_chapter(tmp_path,'0001');commit_chapter(tmp_path,'0002')
    request=helper('audits').prepare(tmp_path,'0002')
    assert 'story/0001/chapter.md' in request['sources']
    assert 'story/0002/confirmed_state.json' in request['source_hashes']
    assert 'meta/hooks.md' not in request['source_hashes']
    support.write(tmp_path,'meta/hooks.md','下一章才新增的伏笔汇总。')
    support.verify(tmp_path,request['source_hashes'])


def test_host_observation_reconciles_callback_run_id_without_double_charging(tmp_path):
    module=setup(tmp_path);call=module.reserve_call(tmp_path,{'model_id':'test:writer','run_id':'run-a'},600)
    usage={'status':'completed','usage_status':'complete','prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
    module.finish_call(tmp_path,call,usage)
    task={'task_id':'t','status':'completed','node_states':{'writer':{'status':'completed','token_usage_calls':[
        {**usage,'call_id':'native-session:1','model_id':'test:writer','run_id':'run-a'}]}}}
    module.observe_task(tmp_path,{'values':{'chapter_number':'0002'}},'mvp',task,'stage_complete')
    assert module.report(tmp_path)['usage']['actual_tokens']==120


def test_driver_uses_native_host_session_manager_and_script_plugin(tmp_path):
    import os,subprocess,sys
    helper('driver')
    from src import config as host_config
    host=Path(host_config.__file__).resolve().parents[1]
    code='''import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('isolated_driver',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from src.agent.session_manager import SessionManager
from src.workflow.nodes.script import ScriptNode
from src.workflow.nodes import registry
runtime=module.native_runtime(Path(sys.argv[2]))
assert isinstance(runtime['sessions'],SessionManager)
assert registry._plugins['script'] is ScriptNode
from src.workflow.script_library import get_script_library
assert get_script_library().attest('xs2','story_support','python')['revision']
import asyncio
from src.workflow.definition import WorkflowDef,NodeExecutionState
from src.workflow.nodes import NodeContext
from src.workflow.runtime_guards import freeze_workflow_runtime_guards
raw={'workflow_id':'longrun-probe','nodes':[{'id':'context','node_type':'script','node_params':{
    'script_source':'library','script_group':'xs2','script_name':'story_support','script_type':'python',
    'script_argv':['context','--chapter','0001']}}],'edges':[{'source':'__start__','target':'context'},{'source':'context','target':'__end__'}]}
freeze_workflow_runtime_guards(raw,workflow_dir=Path.cwd(),parameter_values={},effective_agent_resolver=runtime['sessions'].get_effective_agent_definition)
definition=WorkflowDef.from_dict(raw)
ctx=NodeContext(definition=definition,node_def=definition.nodes[0],node_state=NodeExecutionState(node_id='context'),
    shared_ws=Path.cwd(),task_id='native-script-probe',workflow_id='longrun-probe')
result=asyncio.run(ScriptNode().execute(ctx))
assert result.status in ('completed','success'),(result.error,result.stderr)
assert 'book_contract_file' in result.outputs,(result.outputs,result.stdout)
assert (Path.cwd()/result.outputs['book_contract_file']).is_file()
async def persistence_probe():
    manager=module.start_native_persistence()
    assert manager._timer_task is not None and not manager._timer_task.done()
    await manager.stop()
asyncio.run(persistence_probe())
'''
    result=subprocess.run([sys.executable,'-c',code,str(HERE.parents[3]/'runtime/longrun/driver.py'),str(support.HERE.parents[2])],
        cwd=tmp_path,env={**os.environ,'PYTHONPATH':str(host),'DETERMINFLOW_CONFIG_DIR':str(host/'config'),
            'DETERMINFLOW_DATA_DIR':str(tmp_path/'runtime-data'),'PYTHONUTF8':'1'},capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stderr


def test_audit_verdict_and_checks_cannot_hide_reported_issues(tmp_path):
    module=setup(tmp_path);commit_chapter(tmp_path,'0001')
    source='story/0001/chapter.md'
    request={'chapter':'0001','sources':{source:support.read(tmp_path,source)},'source_hashes':{source:support.digest(tmp_path,source)}}
    result={'verdict':'issues','issues':[],'checks':[{'dimension':d,'status':'issue','reason':'发现问题',
        'evidence':[{'source_id':source,'quote':'决定留下救人'}]} for d in ('memory','cognition','volume')]}
    with pytest.raises(ValueError,match='问题|一致|结论'):module.accept_audit(tmp_path,request,result)


def test_controller_checkpoint_recovers_both_state_and_cursor(tmp_path,monkeypatch):
    setup(tmp_path);module=helper('driver');s=module.load('ledger').support();journal=s.archive_store()
    module.save_state(tmp_path,{'values':{'chapter_number':'0001'}},{'stage':'export','task_id':'old'})
    atomic=journal.atomic
    def crash(root,relative,content):
        if relative=='observability/driver.json':raise OSError('interrupted state transition')
        atomic(root,relative,content)
    with monkeypatch.context() as patch:
        patch.setattr(journal,'atomic',crash)
        with pytest.raises(OSError):module.save_state(tmp_path,{'values':{'chapter_number':'0002'}},{'stage':'outline','task_id':None})
    module.recover_state(tmp_path)
    assert s.load(tmp_path,'.novel-project.json')['values']['chapter_number']=='0002'
    assert s.load(tmp_path,'observability/driver.json')['stage']=='outline'


def test_controller_transition_can_change_its_own_chapter_intent(tmp_path):
    setup(tmp_path);module=helper('driver');s=module.load('ledger').support()
    module.save_state(tmp_path,{'values':{'chapter_number':'0001','human_intent':'已有方向','world_intent':'本章约定'}},{'stage':'export'})
    module.save_state(tmp_path,{'values':{'chapter_number':'0002','human_intent':'','world_intent':''}},{'stage':'outline'})
    module.recover_state(tmp_path)
    assert s.load(tmp_path,'.novel-project.json')['values']['human_intent']==''
    assert s.load(tmp_path,'observability/driver.json')['stage']=='outline'


def test_native_interrupted_node_recovery_preserves_completed_work_and_history():
    from src.workflow.definition import WorkflowDef,WorkflowTask,NodeExecutionState
    from types import SimpleNamespace
    module=helper('driver')
    definition=WorkflowDef.from_dict({'workflow_id':'probe','nodes':[
        {'id':'done','node_type':'script'},{'id':'writer','node_type':'agent','agent_type':'default'}],
        'edges':[{'source':'__start__','target':'done'},{'source':'done','target':'writer'},{'source':'writer','target':'__end__'}]})
    task=WorkflowTask(status='running',node_states={'done':NodeExecutionState(node_id='done',status='completed'),
        'writer':NodeExecutionState(node_id='writer',status='running',attempt_count=1,session_id='old')})
    resumed=module.recover_interrupted(task,definition,SimpleNamespace(get_session=lambda _:None))
    assert resumed==['writer'] and task.status=='resume_pending'
    assert task.node_states['done'].status=='completed'
    assert task.node_states['writer'].status=='pending' and not task.node_states['writer'].session_id
    assert task.node_states['writer'].attempt_count>=1 and task.node_states['writer'].attempt_history


def test_rescoping_a_copy_requires_fresh_baseline_reader_before_archive():
    module=helper('driver');cursor={'phase':'baseline_plan'}
    action=module.baseline_action(cursor,{},None)
    assert action['stage']=='reader-sim' and cursor['phase']=='baseline_reader'


def test_baseline_revision_uses_existing_scope_and_repair_policy():
    from types import SimpleNamespace
    module=helper('driver');cursor={'phase':'baseline_reader','stage':'reader-sim'}
    for expected in ({'action':'repair'},{'action':'pause','reason':'outside scope'}):
        policy=SimpleNamespace(reader_report=lambda *_:{'verdict':'revise'},
                               next_action=lambda *_:expected)
        assert module.baseline_action(cursor,{},policy,'book')==expected
        assert cursor['phase']=='baseline_reader'
    cursor['stage']='polish'
    assert module.baseline_action(cursor,{},None,'book') is None
    cursor['stage']='reader-sim'
    policy=SimpleNamespace(reader_report=lambda *_:{'verdict':'pass'})
    assert module.baseline_action(cursor,{},policy,'book')['stage']=='post-hoc'
    assert cursor['phase']=='baseline_archive'


def test_repair_packet_reuses_complete_book_rules_not_style_only(tmp_path):
    support.write(tmp_path,'.novel-project.json',{'values':{'genre':'科幻','human_intent':'只修副本'}})
    support.write(tmp_path,'meta/narrative_contract.json',{'schema':1,'narrator_scope':'omniscient',
        'style_intent':'允许专业说明和内心描写'})
    support.write(tmp_path,'meta/world_foundation.md','信号单程四分钟，不能改变过去。')
    support.write(tmp_path,'meta/style_profile.md','准确而有人情。')
    support.write(tmp_path,'story/0001/chapter.md','既有正文。')
    support.write(tmp_path,'quality/current.json',{'verdict':'revise'})
    packet=helper('driver').repair_packet(tmp_path,'0001',{'report_path':'quality/current.json'})
    contract=packet['book_contract']
    assert contract['narrator_scope']=='omniscient'
    assert contract['world_sources'][0]['text'].strip()=='信号单程四分钟，不能改变过去。'
    assert contract['author_intent']['human_intent']=='只修副本'
    assert packet['body'].strip()=='既有正文。' and packet['reader_report']['verdict']=='revise'


def test_auxiliary_requests_use_native_streaming_and_aggregate_final_text(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import src.core.llm_client as client
    setup(tmp_path,max_output_tokens=17000)
    created={}
    class Model:
        async def ainvoke(self,messages):
            assert messages[0].content=='rules' and messages[1].content=='source'
            return SimpleNamespace(content=[{'type':'text','text':'complete response'}])
    def create(**kwargs):created.update(kwargs);return Model()
    monkeypatch.setattr(client,'create_llm',create)
    result=asyncio.run(helper('transport').request(tmp_path,'test:writer','rules','source',{'stage':'audit'}))
    assert result=='complete response'
    assert created['streaming'] is True
    assert created['model_params']['max_tokens']==17000


def test_automatic_repair_feedback_is_not_mislabeled_as_user_confirmation(tmp_path):
    import hashlib
    body='原有正文，保持本书声线。'.encode()
    support.write(tmp_path,'story/0002/chapter.md',body.decode())
    body=(tmp_path/'story/0002/chapter.md').read_bytes()
    support.write(tmp_path,'story/0002/reader_report.json',{'verdict':'revise'})
    support.write(tmp_path,'.novel-project.json',{'values':{'author_feedback_file':'author.md'}})
    support.write(tmp_path,'author.md','只修改A，不得改变B；保留本书议论声线。')
    report=(tmp_path/'story/0002/reader_report.json').read_bytes()
    entry={'id':'automatic-plan','status':'completed','purpose':'reader_repair','repair_source':{
        'chapter':'0002','chapter_sha256':hashlib.sha256(body).hexdigest(),
        'report_path':'story/0002/reader_report.json','report_sha256':hashlib.sha256(report).hexdigest()}}
    result=helper('driver').prepare_automatic_repair_feedback(tmp_path,entry,'只合并已举证的重复说明。')
    feedback=(tmp_path/result['feedback_path']).read_text(encoding='utf-8')
    assert '自动生成' in feedback.splitlines()[0] and '用户确认' not in feedback.splitlines()[0]
    assert '不能覆盖' in feedback and '更多操作' in feedback
    folder=(tmp_path/result['feedback_path']).parent
    provenance=json.loads((folder/'automatic-origin.json').read_text(encoding='utf-8'))
    assert provenance['origin']=='automatic' and provenance['user_reviewed'] is False
    assert provenance['source']==entry['repair_source']
    assert (folder/'before.md').read_bytes()==body
    assert (tmp_path/'story/0002/chapter.md').read_bytes()==body
    assert '只修改A，不得改变B' in feedback
    retained=provenance['retained_feedback_sources']
    assert len(retained)==1 and retained[0]['source_id']=='author.md'
    support.write(tmp_path,'.novel-project.json',{'values':{'author_feedback_file':result['feedback_path']}})
    applied={**entry,'feedback_context':{'selected_path':'author.md'},
        'applied_at':'already-used','feedback_path':result['feedback_path']}
    assert helper('driver').prepare_automatic_repair_feedback(tmp_path,applied,'unused')['already_applied'] is True
    origin_path=folder/'automatic-origin.json';origin_before=origin_path.read_bytes()
    provenance.pop('retained_feedback_sources')
    origin_path.write_text(json.dumps(provenance,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(ValueError,match='意见|来源'):
        helper('driver').repair_packet(tmp_path,'0002',{'report_path':'story/0002/reader_report.json'})
    origin_path.write_bytes(origin_before)
    packet=helper('driver').repair_packet(tmp_path,'0002',{'report_path':'story/0002/reader_report.json'})
    assert packet['feedback_context']['retained_feedback_sources']==retained
    entry2={**entry,'id':'automatic-plan-2','feedback_context':packet['feedback_context']}
    support.write(tmp_path,'author.md','作者更新了B的约束，旧方案不能采用。')
    with pytest.raises(ValueError,match='意见|来源'):
        helper('driver').prepare_automatic_repair_feedback(tmp_path,entry2,'旧的第二轮方案')
    assert not (folder.parent/'automatic-plan-2').exists()


def test_repair_planner_reuses_expression_rules_instead_of_padding_with_actions(tmp_path):
    support.write(tmp_path,'story/0002/chapter.md','当前正文。')
    support.write(tmp_path,'story/0002/reader_report.json',{'verdict':'revise'})
    packet=helper('driver').repair_packet(tmp_path,'0002',{'report_path':'story/0002/reader_report.json'})
    assert 'expression_guidance' in packet
    assert '不能换成同义说明或无关动作填回' in packet['expression_guidance']
    assert '更多操作' in packet['instruction'] and '作者' in packet['instruction']


def test_model_pass_does_not_erase_open_manual_source_observation(tmp_path):
    module=setup(tmp_path,target_new_characters=1);commit_chapter(tmp_path,'0002')
    source='story/0002/chapter.md';digest=support.digest(tmp_path,source)
    support.write(tmp_path,'story/0002/reader_report.json',{'verdict':'pass','body_sha256':digest})
    module.accept_chapter(tmp_path,'0002',{'task_id':'export','status':'completed'})
    request={'chapter':'0002','source_hashes':{source:digest},'sources':{source:support.read(tmp_path,source)}}
    result={'verdict':'pass','issues':[],'checks':[{'dimension':dimension,'status':'pass',
        'reason':'fixture source review','evidence':[{'source_id':source,'quote':'决定留下救人'}]}
        for dimension in ('memory','cognition','volume')]}
    module.accept_audit(tmp_path,request,result)
    assert module.report(tmp_path)['acceptance']['status']=='passed'
    module.event(tmp_path,'manual_observation',{'id':'receipt-mix','status':'open','origin':'manual',
        'source_hashes':{source:digest},'description':'A source-based temporal mismatch'})
    module.accept_audit(tmp_path,request,result)
    report=module.report(tmp_path)
    assert report['acceptance']['status']=='needs_review'
    assert report['manual_observations']['open'][0]['evidence_is_current'] is True
    support.write(tmp_path,source,'作者已经修改正文，需要重查该记录。')
    assert module.report(tmp_path)['manual_observations']['open'][0]['evidence_is_current'] is False


def test_maintenance_stop_waits_for_requested_committed_boundary_and_is_not_replayed(tmp_path):
    request={'id':'upgrade-reviewed-plugin','after_stage':'export','chapter':'0002','reason':'load verified plugin'}
    support.write(tmp_path,'observability/stop-request.json',request)
    driver=helper('driver');cursor={}
    assert driver.boundary_stop_request(tmp_path,cursor,'mvp','0002') is None
    assert driver.boundary_stop_request(tmp_path,cursor,'export','0003') is None
    assert driver.boundary_stop_request(tmp_path,cursor,'export','0002')==request
    assert driver.boundary_stop_request(tmp_path,{'last_stop_request_id':request['id']},'export','0002') is None
    assert support.load(tmp_path,'observability/stop-request.json')==request


def test_report_distinguishes_process_recovery_and_controlled_restart(tmp_path):
    module=setup(tmp_path);module.event(tmp_path,'process_recovered',{'task_id':'interrupted'})
    module.event(tmp_path,'controlled_restart',{'chapter':'0005'})
    module.event(tmp_path,'boundary_stop',{'completed_chapter':'0002'})
    result=module.report(tmp_path)['recoveries']
    assert len(result['recovered'])==1 and len(result['controlled_restarts'])==1
    assert len(result['boundary_stops'])==1


def test_driver_reuses_existing_mvp_tail_checkpoint_without_enabling_writers(tmp_path):
    from test_checkpoint_recovery import rendered,load as checkpoint_load
    policy=checkpoint_load('production');state,task,definition=rendered(tmp_path)
    state.update(policy.recovery_action(state,'mvp',task,root=tmp_path)['updates'])
    support.write(tmp_path,'observability/workflows/mvp/tasks/rendered.json',task)
    result=helper('driver').checkpoint_launch(tmp_path,state,'mvp',definition,policy)
    assert result['selected_node_ids']==['script_check_originality']
    assert 'agent_aw' in result['disabled_node_ids'] and 'script_render_si' in result['disabled_node_ids']


def test_native_task_parameters_materialize_hidden_file_defaults(tmp_path):
    import asyncio
    from test_length_quality import policy
    from src.workflow.variable_resolution import resolve_placeholders
    definition={'variables':[{'key':'chapter_number','type':'text','default':'0001'},
        {'key':'chapter_file','type':'file','source_type':'input','default':'story/{{chapter_number}}/chapter.md'}]}
    support.write(tmp_path,'story/0002/chapter.md','本章完整正文已经准备。')
    values=helper('driver').task_parameters({'values':{'chapter_number':'0002'}},definition,policy())
    actual=asyncio.run(resolve_placeholders('{{chapter_file}}',values,definition['variables'],str(tmp_path)))
    assert '本章完整正文已经准备' in actual and '{{chapter_file}}' not in actual
