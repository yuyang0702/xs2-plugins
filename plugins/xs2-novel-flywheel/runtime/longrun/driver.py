"""Resumable copy-only driver over native host sessions, nodes and policies."""
import asyncio
from contextlib import contextmanager
from functools import lru_cache
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import RLock
from uuid import uuid4

HERE=Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load(name):
    file=(HERE.parents[1]/'resources/script-library/xs2/longrun/ledger.py') if name=='ledger' else HERE/(name+'.py')
    spec=importlib.util.spec_from_file_location('longrun_driver_'+name,file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value


@contextmanager
def run_lock(root):
    folder=Path(root)/'observability';folder.mkdir(parents=True,exist_ok=True)
    handle=(folder/'driver.lock').open('a+b')
    if handle.tell()==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise ValueError('本书已有长跑进程持有运行锁') from exc
        yield
    finally:handle.close()


def native_runtime(resources):
    from src import config
    from src.extension_api.registrar import OwnedPath
    from src.extension_host import LayeredJsonConfig
    from src.agent.config_manager import AgentConfigManager
    from src.agent.definition import set_agent_config_manager
    from src.agent.session_manager import SessionManager
    from src.core.workspace_manager import WorkspaceManager
    from src.core.approval_manager import ApprovalManager
    from src.mcp.client import MCPClient
    from src.prompts.manager import PromptManager
    from src.session import PromptBuilder,ToolAssembler
    from src.tools import ToolRegistry,register_all_tool_factories
    from src.workflow.script_library import configure_script_library
    from src.workflow.engine import WorkflowEngine
    resources=Path(resources).resolve();owner='xs2-novel-flywheel'
    def layer(file,resource):
        return LayeredJsonConfig(file,[OwnedPath(owner,resources/resource)],dict_sections=('agents',),owner_enabled=lambda _:True)
    agents=AgentConfigManager(config.AGENTS_CONFIG_FILE,config_store=layer(config.AGENTS_CONFIG_FILE,'agents.json'))
    set_agent_config_manager(agents)
    prompts=PromptManager(config_file=config.PROMPTS_CONFIG_FILE,cache_file=config.SYSTEM_PROMPT_FILE,
        history_file=config.PROMPT_HISTORY_FILE,config_store=layer(config.PROMPTS_CONFIG_FILE,'prompts.json'))
    sessions=SessionManager();workspace=WorkspaceManager();approval=ApprovalManager();mcp=MCPClient()
    sessions.inject_dependencies(workspace_manager=workspace,approval_manager=approval,agent_config_manager=agents,mcp_client=mcp)
    registry=ToolRegistry(config.CONFIG_DIR/'tool_groups_config.json')
    register_all_tool_factories(registry,mcp_client=mcp,session_manager=sessions,prompt_manager=prompts,approval_manager=approval)
    sessions.set_builders(PromptBuilder(prompts),ToolAssembler(sessions,registry,approval_manager=approval))
    sessions.load_sessions(hot_runtime_scope='catalog')
    revision=load('ledger').identity({p.relative_to(resources).as_posix():load('ledger').sha(p)
        for p in sorted(resources.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')})
    configure_script_library([OwnedPath(owner,resources/'script-library',revision)],
        owner_enabled=lambda _:True,owner_revision=lambda _:revision)
    engine=WorkflowEngine(sessions);engine.set_workspace_manager(workspace)
    return {'sessions':sessions,'engine':engine,'agents':agents,'prompts':prompts}


def start_native_persistence():
    from src.agent.session import _persistence_manager
    _persistence_manager.start()
    return _persistence_manager


def save_state(root,state,cursor,extra=None):
    load('ledger').publish_controller(root,{'.novel-project.json':state,'observability/driver.json':cursor,**(extra or {})})


def recover_state(root):load('ledger').recover_controller(root)


def recover_interrupted(task,definition,sessions,ids=None):
    from src.workflow.task_recovery import WorkflowTaskRecoveryMixin as Recovery
    from src.workflow.model_utils import _now_iso
    interrupted=ids or [key for key,value in task.node_states.items() if value.status=='running']
    for key in interrupted:
        state=task.node_states[key]
        if state.status=='running':state=Recovery._interrupted_state(state,completed_at=_now_iso())
        elif state.status!='failed' or 'workflow_process_interrupted' not in state.error:
            raise ValueError('恢复意图与中断节点状态不符')
        # Completed nodes remain completed. An in-progress node is explicitly
        # reissued; its saved session and paid/unknown calls remain evidence,
        # without claiming the host can always reuse its unfinished result.
        task.node_states[key]=Recovery._prepare_recovery_reissue(state,preserve_result=False)
    if interrupted:Recovery._prepare_task_for_resume(task)
    return interrupted


def save_report(root):
    log=load('ledger');load('transport').refresh_pricing(root);result=log.report(root)
    log.support().write(root,'observability/report.json',result)
    return result


def boundary_stop_request(root,cursor,stage,chapter):
    request=load('ledger').support().load(root,'observability/stop-request.json')
    if not request:return None
    stages={'story-plan','outline','mvp','polish','reader-sim','post-hoc','export'}
    if (not isinstance(request,dict) or set(request)-{'id','after_stage','chapter','reason'}
            or not isinstance(request.get('id'),str) or not 1<=len(request['id'])<=128
            or request.get('after_stage') not in stages
            or not isinstance(request.get('reason'),str) or not request['reason'].strip()
            or ('chapter' in request and (not isinstance(request['chapter'],str)
                or len(request['chapter'])!=4 or not request['chapter'].isdigit()))):
        raise ValueError('阶段边界停止请求格式无效')
    if (request['id']==cursor.get('last_stop_request_id') or request['after_stage']!=stage
            or request.get('chapter',chapter)!=chapter):return None
    return request


def baseline_action(cursor,state,policy,root=None):
    if cursor.get('phase')=='baseline_plan':
        cursor['phase']='baseline_reader'
        return {'action':'advance','stage':'reader-sim','reset':['reader-sim','post-hoc','export']}
    if cursor.get('phase')=='baseline_reader':
        if cursor.get('stage')!='reader-sim':return None
        if policy.reader_report(root,state)['verdict']!='pass':
            return policy.next_action(root,state,'reader-sim')
        cursor['phase']='baseline_archive'
        return {'action':'advance','stage':'post-hoc','reset':['post-hoc','export']}
    return None


def checkpoint_launch(root,state,stage,definition,policy):
    from src.workflow.definition import WorkflowDef
    from src.workflow.manager import WorkflowManager
    checkpoint=state.get('automaticCheckpoint') or {}
    if stage!='mvp' or checkpoint.get('stage')!=stage:return {}
    source=load('ledger').support().load(root,f"observability/workflows/{stage}/tasks/{checkpoint['source_task_id']}.json")
    options=policy.checkpoint_options(root,state,stage,definition,source)
    disabled=WorkflowManager._resolve_disabled_nodes(None,WorkflowDef.from_dict(definition),
        selected_node_ids=options.get('selected_node_ids'))
    return {**options,'disabled_node_ids':sorted(disabled)}


def task_parameters(state,definition,policy,checkpoint=None):
    # Match native WorkflowManager.create_task: its caller supplies editable
    # inputs, while hidden file defaults remain part of the task snapshot.
    defaults={v['key']:v.get('default') for v in definition.get('variables',[]) if v.get('default')}
    return {**defaults,**(checkpoint or {}).get('parameter_values',{}),**policy.parameters(state,definition)}


def repair_feedback_context(root):
    s=load('ledger').support();state=s.load(root,'.novel-project.json',{})
    selected=str(state.get('values',{}).get('author_feedback_file') or '').strip()
    if not selected:return {'selected_path':'','selected_sha256':None,'retained_feedback_sources':[]}
    if not s.safe(root,selected).is_file():raise ValueError('原已选择的章节意见文件缺失，不能被自动方案替代')
    digest=s.digest(root,selected);origin_path=(Path(selected).parent/'automatic-origin.json').as_posix()
    origin=s.load(root,origin_path,{})
    if origin.get('origin')=='automatic' and origin.get('feedback_sha256')==digest:
        sources=origin.get('retained_feedback_sources')
        if not isinstance(sources,list):raise ValueError('自动方案继承意见来源无效')
    else:
        sources=[{'source_id':selected,'sha256':digest,'text':s.read(root,selected),'origin':'selected_feedback'}]
    for row in sources:
        if (not isinstance(row,dict) or not isinstance(row.get('source_id'),str)
                or not s.safe(root,row['source_id']).is_file()
                or s.digest(root,row['source_id'])!=row.get('sha256')
                or s.read(root,row['source_id'])!=row.get('text')):
            raise ValueError('原章节意见来源已有变化，不能采用旧自动方案')
    return {'selected_path':selected,'selected_sha256':digest,
        'origin_sha256':s.digest(root,origin_path),'retained_feedback_sources':sources}


def repair_packet(root,number,context):
    s=load('ledger').support()
    contract=module('longrun_repair_book_contract',s.HERE.parent/'prose_policy/book_contract.py').resolve(root)
    expression=module('longrun_repair_expression',s.HERE.parent/'prose_policy/expression_review.py')
    return {'book_contract':contract,
        'body':s.read(root,f'story/{number}/chapter.md'),'reader_report':s.load(root,context['report_path']),
        'expression_guidance':expression.GUIDANCE,'feedback_context':repair_feedback_context(root),
        'instruction':'只制定本章可执行修订方案，解决报告中的实际问题，保留本书世界、事实、声线和叙述权限。不统一改成某种风格；无依据的问题明确说明。'
            '遵循作者实际篇幅范围，不另设更窄的字数或情绪回响次数。删去复述后不能仅靠更多操作、重复确认或同义解释补字；'
            '每项增补须说明它在本书中的新阅读作用。必要说明、心理、意象和有意回环可以保留，不把删短本身当作改善。'
            '若局部范围和篇幅确有冲突，明确列出冲突与依据，不编造新事实或用动作填充声称问题已解决。'}


def prepare_automatic_repair_feedback(root,entry,plan):
    from src.web.novel_repair import prepare_repair
    if entry.get('applied_at'):return prepare_repair(Path(root),entry,plan)
    feedback=entry['feedback_context'] if 'feedback_context' in entry else repair_feedback_context(root)
    if repair_feedback_context(root)!=feedback:raise ValueError('原章节意见选择或来源已有变化，旧方案不能采用')
    result=prepare_repair(Path(root),entry,plan)
    if result.get('already_applied'):return result
    log=load('ledger');s=log.support();number=entry['repair_source']['chapter']
    text=(f'# 第{number}章 · 自动生成的返修建议\n\n'
        '来源：本次长跑流程依据读者报告自动规划，未经作者逐项确认。它是本章建议，不能覆盖作者已确认的每书事实、世界规则、文风、叙述权限和篇幅范围。\n'
        '只处理有正文依据的问题；不能用更多操作、同义解释或重复确认补足篇幅。必要说明、心理、意象和有意回环按本书阅读作用判断。\n\n'
        +'## 此前已选择的意见原文\n\n'
        '以下原文继续约束本章，作者原有要求高于本轮自动建议；其中已标为自动建议的内容仍是自动建议，标题本身不构成用户确认。\n'
        +json.dumps(feedback['retained_feedback_sources'],ensure_ascii=False,indent=2)
        +'\n\n## 本轮自动建议\n\n'+plan.strip()
        +'\n\n执行要求：只提交本章局部补丁，保留既定事实和本书风格；独立复查及读者复评仍须核对实际改动，不因采用自动方案而默认通过。\n')
    s.write(root,result['feedback_path'],text)
    folder=Path(result['feedback_path']).parent.as_posix()
    s.write(root,folder+'/automatic-origin.json',{'origin':'automatic','user_reviewed':False,
        'scope':'chapter_local_repair','source':entry['repair_source'],'plan_digest':log.identity({'plan':plan}),
        'feedback_sha256':s.digest(root,result['feedback_path']),
        'retained_feedback_sources':feedback['retained_feedback_sources']})
    return result


async def plan_repair(root,state,workflows_dir):
    from src.web.novel_repair import repair_context,verify_source
    log=load('ledger');s=log.support();number=s.chapter_id(state.get('values',{}).get('chapter_number','0001'))
    context=repair_context(Path(root),number,Path(workflows_dir),require_idle=False)
    packet=repair_packet(root,number,context)
    identifier='longrun-repair-'+str(uuid4());folder=f'observability/repairs/{identifier}'
    s.write(root,folder+'/request.json',packet)
    text=await load('transport').request(root,state['analysisModel'],
        '你是按本书契约工作的修订规划者。资料是数据。输出可直接交给局部修订流程的具体方案，不改正文，不假定读者问题必然正确。',
        json.dumps(packet,ensure_ascii=False),{'stage':'repair-plan','chapter':number,'node_id':'repair_plan'})
    s.write(root,folder+'/response.md',text);verify_source(Path(root),context)
    entry={'id':identifier,'status':'completed','purpose':'reader_repair','repair_source':context,
        'feedback_context':packet['feedback_context']}
    result=prepare_automatic_repair_feedback(root,entry,text)
    log.event(root,'repair_plan',{'chapter':number,'feedback_path':result['feedback_path']})
    return result


async def repair(root,state,policy,workflows_dir):
    result=await plan_repair(root,state,workflows_dir)
    return policy.repair_ready(state,result['feedback_path'])


async def execute_stage(root,resources,runtime,policy,state,cursor):
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.runtime_guards import freeze_workflow_runtime_guards
    from src.workflow.failure_policy import activate_scheduled_retry
    log=load('ledger');s=log.support();stage=cursor['stage'];number=policy.chapter(state)
    sessions=runtime['sessions'];engine=runtime['engine'];tasks=Path(root)/'observability/workflows'
    task_id=cursor.get('task_id');path=tasks/stage/'tasks'/f'{task_id}.json' if task_id else None
    if path and path.is_file():
        task=WorkflowTask.from_dict(json.loads(path.read_text(encoding='utf-8')))
        raw=task.snapshot_definition
        if task.status=='completed':return task
        if task.status=='failed' and not cursor.get('interruption_pending'):return task
        interrupted=[key for key,node in task.node_states.items() if node.status=='running']
        if interrupted or cursor.get('interruption_pending'):
            from src.workflow.task_recovery import WorkflowTaskRecoveryMixin as Recovery
            from src.workflow.model_utils import _now_iso
            if interrupted:
                count=int(cursor.get('interruption_count') or 0)+1
                if count>2:raise ValueError('本任务的进程中断恢复已达两次上限，未重置历史')
                cursor.update(interruption_count=count,interruption_pending=interrupted)
                for key in interrupted:task.node_states[key]=Recovery._interrupted_state(task.node_states[key],completed_at=_now_iso())
                task.status='failed'
                save_state(root,state,cursor,{path.relative_to(root).as_posix():task.to_dict()})
            policy.run_control().observe(root,state,stage,task.to_dict())
            recover_interrupted(task,WorkflowDef.from_dict(raw),sessions,cursor['interruption_pending'])
            cursor['interruption_pending']=None
            save_state(root,state,cursor,{path.relative_to(root).as_posix():task.to_dict()})
            log.event(root,'process_recovered',{'chapter':number,'stage':stage,'task_id':task.task_id,
                'nodes':interrupted or list(task.node_states),'attempt':cursor.get('interruption_count')})
    else:
        raw=json.loads((Path(resources)/f'workflows/{stage}/definition.json').read_text(encoding='utf-8'))
        selection=checkpoint_launch(root,state,stage,raw,policy)
        policy.launch_check(root,state,stage,s)
        overrides=policy.model_overrides(state,raw,stage) or {}
        parameter_overrides=policy.model_params_overrides(state,raw,stage) or {}
        maximum=log.config(root)['config'].get('max_output_tokens',16000)
        for node in raw['nodes']:
            if node.get('node_type')=='agent':
                node['model_override']=overrides.get(node['id']) or state['analysisModel']
                from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY
                node.setdefault('node_params',{})[MODEL_PARAMS_OVERRIDE_KEY]={**parameter_overrides.get(node['id'],{}),'max_tokens':maximum}
        values=task_parameters(state,raw,policy,selection)
        freeze_workflow_runtime_guards(raw,workflow_dir=Path(resources)/'workflows'/stage,
            parameter_values=values,effective_agent_resolver=sessions.get_effective_agent_definition)
        task=WorkflowTask(workflow_id=stage,task_id='longrun-'+str(uuid4()),status='running',
            parameter_values=values,snapshot_definition=raw,workspace_override=str(Path(root).resolve()),
            disabled_node_ids=selection.get('disabled_node_ids',[]))
        cursor['task_id']=task.task_id;task_id=task.task_id;path=tasks/stage/'tasks'/f'{task_id}.json'
        state.setdefault('refs',{})[stage]={'task_id':task_id,'workflow_id':stage}
        save_state(root,state,cursor,{path.relative_to(root).as_posix():task.to_dict()})
    definition=WorkflowDef.from_dict(raw)
    errors=definition.validate()
    if errors:raise ValueError('工作流定义无效：'+str(errors))
    if task.status=='resume_pending':policy.validate_dispatch(root,state,stage,task.to_dict())
    task.run_id=task.run_id or str(uuid4());task.status='running'
    async def persist(_workflow,current):
        s.write(root,path.relative_to(root).as_posix(),current.to_dict())
        log.observe_task(root,state,stage,current.to_dict(),'task_observed')
    engine._save_task_state=persist;engine._push_wf_task_update=lambda *_:None
    original_create=sessions.create_sub_session
    transport=load('transport')
    async def create_session(**kwargs):
        token=transport.CONTEXT.set({'stage':stage,'chapter':number,'task_id':task.task_id,'node_id':kwargs.get('node_id','')})
        try:return await original_create(**kwargs)
        finally:transport.CONTEXT.reset(token)
    sessions.create_sub_session=create_session
    try:
        for attempt in range(24):
            for key,node in list(task.node_states.items()):
                if node.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(node)
            policy.validate_dispatch(root,state,stage,task.to_dict())
            outcome=await engine._execute_plan_segment(definition=definition,task=task,
                execution_plan=definition.get_execution_plan(),disabled_ids=set(task.disabled_node_ids),shared_ws=Path(root),
                parent_id='longrun-copy',on_node_started=lambda n:print(f'NODE {number} {stage} {n.node_id}',flush=True),
                needs_approval=False,run_record=WorkflowRunRecord(workflow_id=stage))
            if outcome!='retry_waiting':break
        task.status='completed' if outcome=='completed' else 'failed'
        await persist(stage,task);return task
    finally:sessions.create_sub_session=original_create


async def run(root,resources,host_root):
    root=Path(root).resolve();resources=Path(resources).resolve();host_root=Path(host_root).resolve()
    os.environ['DETERMINFLOW_CONFIG_DIR']=str(host_root/'config')
    os.environ['DETERMINFLOW_DATA_DIR']=str(root/'observability/runtime-data')
    os.environ['DETERMINFLOW_LOGS_DIR']=str(root/'observability/logs')
    sys.path.insert(0,str(host_root))
    from scripts.start_local import load_startup_environment
    load_startup_environment()
    log=load('ledger');s=log.support();value=log.config(root)['config']
    if value.get('external_run_authorized') is not True:raise ValueError('本次外发运行尚未得到授权')
    if not s.load(root,'observability/source-manifest.json'):raise ValueError('真实长跑只允许在有来源保护的独立副本运行')
    log.check_sources(root);recover_state(root);s.archive_store().recover(root)
    state=s.load(root,'.novel-project.json');cursor=s.load(root,'observability/driver.json',{'stage':'story-plan','phase':'baseline_plan'})
    if cursor.get('finished'):return save_report(root)
    policy=module('longrun_production',resources/'script-library/xs2/console_service/production.py')
    runtime=native_runtime(resources)
    from src.web.novel_automation import NovelAutomation
    automation=NovelAutomation(None,None,None,lambda:policy,None,RLock(),root/'observability/workflows')
    # Native action semantics are retained; the controller's durable intent
    # contains both book state and cursor, including intentional intent changes.
    automation._save=lambda *_args:None
    with run_lock(root),load('transport').metered_models(root):
        start_native_persistence()
        log.event(root,'driver_start',{'id':str(uuid4()),'cursor':cursor,'pid':os.getpid()})
        try:
            while True:
                if cursor.get('paused'):raise ValueError(cursor.get('reason','长跑已暂停'))
                if cursor.get('phase')=='baseline_archive' and cursor['stage']=='post-hoc' and not cursor.get('task_id'):
                    try:policy.reader_report(root,state)
                    except ValueError:
                        cursor.update(phase='baseline_reader',stage='reader-sim',task_id=None)
                        save_state(root,state,cursor)
                number=policy.chapter(state);stage=cursor['stage']
                print(f'STAGE {number} {stage}',flush=True)
                task=await execute_stage(root,resources,runtime,policy,state,cursor)
                if task.status!='completed':
                    action=policy.recovery_action(state,stage,task.to_dict(),root=root)
                    if not action:raise ValueError('工作流失败，内容或执行问题已保留，未绕过验收')
                else:
                    policy.verify_completion(root,state,stage,task.to_dict())
                    state['completed']=list(dict.fromkeys([*state.get('completed',[]),stage]))
                    if stage=='post-hoc':
                        await load('audits').perform(root,number,state['analysisModel'])
                    result=save_report(root)
                    if stage=='export' and result['progress']['target_reached']:
                        policy.run_control().finish(root,state)
                        cursor.update(finished=True,finished_at=log.now(),task_id=None)
                        save_state(root,state,cursor);return result
                    baseline=baseline_action(cursor,state,policy,root)
                    if baseline:action=baseline
                    elif cursor.get('phase')=='baseline_archive':
                        cursor['phase']='continuation'
                        values={**state['values'],'chapter_number':f'{int(number)+1:04d}',
                            'prev_chapter':number,'latest_chapter':number,'planning_mode':'rolling',
                            'human_intent':'','world_intent':'','target_word_count':value.get('chapter_target','3500-4000'),
                            'words_per_chapter':value.get('chapter_target','3500-4000'),'chapter_ending_mode':'continue'}
                        action={'action':'advance','stage':'outline','reset':['outline',*policy.PRODUCTION],
                            'updates':{'values':values,'serialReservation':None}}
                    else:action=policy.next_action(root,state,stage)
                    if action['action']=='repair':action=await repair(root,state,policy,root/'observability/workflows')
                automation._apply_action(root,state,action)
                if action['action'] in ('pause','finish'):raise ValueError(action.get('reason','流程已暂停'))
                cursor.update(stage=action['stage'],task_id=None,interruption_count=0,interruption_pending=None)
                save_state(root,state,cursor)
                result=save_report(root)
                stop=boundary_stop_request(root,cursor,stage,number)
                if stop:
                    cursor.update(paused=True,reason=stop['reason'],last_stop_request_id=stop['id'])
                    save_state(root,state,cursor)
                    log.event(root,'boundary_stop',{'request':stop,'completed_stage':stage,
                        'completed_chapter':number,'next_stage':cursor['stage']})
                    return save_report(root)
                if (stage=='export' and len(result['progress']['accepted_new_chapters'])>=value.get('safe_restart_after_chapters',999999)
                        and not cursor.get('safe_restart_done')):
                    cursor['safe_restart_done']=True;save_state(root,state,cursor)
                    log.event(root,'controlled_restart',{'chapter':number,'reason':'已提交章节边界的安全进程重启验证'})
                    print('CONTROLLED_RESTART_READY',flush=True);return result
        except Exception as exc:
            cursor.update(paused=True,reason=str(exc)[:3000]);save_state(root,state,cursor)
            log.event(root,'driver_pause',{'stage':cursor.get('stage'),'chapter':policy.chapter(state),
                'error_type':type(exc).__name__,'reason':str(exc)[:3000]})
            save_report(root);raise
        finally:
            await runtime['sessions'].shutdown()
            log.check_sources(root)
