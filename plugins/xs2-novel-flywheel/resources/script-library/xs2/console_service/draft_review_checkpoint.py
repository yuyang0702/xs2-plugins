"""Replay review gates from a verified draft; never replay authoring nodes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

SCRIPTS={'script_guard_prepare':'draft_guard','script_guard_facts_candidate':'draft_guard',
    'script_guard_facts_commit':'draft_guard','script_guard_expression_candidate':'draft_guard',
    'script_guard_expression_commit':'draft_guard','script_guard_finish':'draft_guard',
    'script_si_post':'si_post','script_render_si':'local_archive','sync_up_si':'local_archive',
    'script_check_originality':'reference_intelligence_helper'}
AGENTS={'agent_guard_facts_repair':'xs2-draft-repairer','agent_guard_facts_audit':'xs2-draft-auditor',
    'agent_guard_expression_repair':'xs2-draft-repairer','agent_guard_expression_audit':'xs2-draft-auditor'}
SELECTED=list(SCRIPTS)+list(AGENTS)
EXPRESSION_COMMIT=['script_guard_prepare','script_guard_expression_commit','script_guard_finish',
                   'script_si_post','script_render_si','sync_up_si','script_check_originality']
EXPRESSION_FILES=('facts-approved.json','facts-audit.json','expression-input.json',
                  'expression-draft.json','expression-audit.json')


def shared():
    spec=importlib.util.spec_from_file_location('draft_review_shared',Path(__file__).with_name('recovery_checkpoint.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def guard():
    spec=importlib.util.spec_from_file_location('draft_review_guard',Path(__file__).parents[1]/'draft_guard/draft_guard.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def read(root,path):return json.loads(shared()._path(root,path).read_text(encoding='utf-8-sig'))


def _resume_expression_commit(g, directory, task, body, source, binding, contract, failed):
    """Carry forward an actual completed audit on the unchanged draft."""
    if failed != {'script_guard_expression_commit'} or body != source['source_body']:
        return False
    auditor=task['node_states'].get('agent_guard_expression_audit',{})
    output=auditor.get('outputs',{}).get('_json_output_file')
    if auditor.get('status')!='completed' or not output or Path(output).resolve()!=directory/'expression-audit.json':
        return False
    try:
        patch=g.read(directory/'expression-draft.json')
        if (binding.get('expression_format')!='patches'
                or patch!=json.loads(task['parameter_values'].get('guard_expression_patch_result','null'))
                or g.candidate(directory,'expression')!=body):
            return False
        report=g.read(directory/'expression-audit.json')
        return (report.get('book_contract_sha256')==binding['book_contract_sha256']
                and not g.audit_candidate(directory,report,body,contract,'expression'))
    except (OSError,ValueError,TypeError,KeyError):
        return False


def prepare(root,state,task,chapter):
    common=shared();g=guard();number=str(chapter).zfill(4)
    if (task.get('status')!='failed' or Path(task.get('workspace_override') or '').resolve()!=Path(root).resolve()
            or task.get('parameter_values',{}).get('chapter_number')!=number
            or common._path(root,f'story/{number}/chapter.md').exists()):
        raise ValueError('审稿恢复需要本书尚未发布正文的失败任务')
    nodes=task.get('node_states',{})
    failed={key for key,node in nodes.items() if node.get('status')=='failed'}
    facts_retry=bool(failed) and failed<={'agent_guard_facts_audit','script_guard_facts_commit'}
    expression_retry=bool(failed) and failed<={'agent_guard_expression_repair','agent_guard_expression_audit',
            'script_guard_expression_candidate','script_guard_expression_commit'}
    required=('agent_guard_facts_repair','script_guard_facts_candidate') if facts_retry else ('script_guard_facts_commit',)
    if not (facts_retry or expression_retry) or not all(nodes.get(key,{}).get('status')=='completed'
            for key in ('script_multi_plan','script_guard_prepare',*required)):
        raise ValueError('该失败范围缺少可继续审核的候选或事实稿')
    directory='cache/draft-guard/'+task['task_id'];multi=task['parameter_values'].get('multi_dir','')
    if not multi:raise ValueError('审稿恢复缺少原计划目录')
    binding=read(root,directory+'/binding.json');source=read(root,directory+'/facts-input.json')
    plan=read(root,multi+'/plan.json');text=common._path(root,multi+'/planning-sources.md').read_text(encoding='utf-8-sig')
    contract=g.policy.validate_contract(plan.get('continuity'),text,len(plan.get('scenes',[])))
    book_sha=g.book_policy.digest(g.book_policy.resolve(root))
    expected_target=state.get('values',{}).get('target_word_count')
    composer=g.load('checkpoint_composition',Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py')
    quota=composer.current(root,number)
    if quota:expected_target=f"{quota['minimum']}-{quota['maximum']}"
    if (binding.get('task_id')!=task['task_id']
            or binding.get('plan_sha256')!=common._digest(common._path(root,multi+'/plan.json'))
            or binding.get('sources_sha256')!=common._digest(common._path(root,multi+'/planning-sources.md'))
            or binding.get('target')!=expected_target
            or binding.get('pov')!=state.get('values',{}).get('narrative_pov')
            or binding.get('book_contract_sha256')!=book_sha
            or g.book_policy.digest(source.get('book_contract'))!=book_sha
            or source.get('source_constraints')!=text or source.get('continuity_contract')!=contract
            or binding.get('source_sha256')!=g.body_digest(source.get('source_body',''))
            or binding.get('contract_sha256')!=g.policy.contract_digest(contract)):
        raise ValueError('候选、原任务或当前本书契约的绑定不完整')
    folder=common._path(root,directory)
    inputs=[directory+'/binding.json',directory+'/facts-input.json']
    if facts_retry:
        output=nodes['agent_guard_facts_repair'].get('outputs',{}).get('_json_output_file')
        if not output or Path(output).resolve()!=folder/'facts-draft.json' or (folder/'facts-approved.json').exists():
            raise ValueError('待审事实候选与原任务的写手交付不一致')
        body=g.candidate(folder,'facts')
        packet=read(root,directory+'/facts-audit-input.json')
        expected=g.audit_value(folder,'facts',body,contract,binding)
        if any(packet.get(key)!=expected[key] for key in expected if key!='evidence_guidance'):
            raise ValueError('待审事实候选与冻结审核输入不一致')
        inputs.extend(directory+'/'+name for name in ('facts-draft.json','facts-audit-input.json'))
    else:
        approved=read(root,directory+'/facts-approved.json');body=approved.get('body')
        audit=read(root,directory+'/facts-audit.json')
        if (not isinstance(body,str) or not body.strip() or approved.get('phase')!='facts'
                or approved.get('body_sha256')!=g.body_digest(body)
                or approved.get('book_contract_sha256')!=book_sha or approved.get('source_sha256')!=binding['source_sha256']
                or approved.get('contract_sha256')!=binding['contract_sha256']
                or approved.get('audit_sha256')!=common._digest(folder/'facts-audit.json')
                or g.policy.audit_issues(audit,body,contract,'facts')):
            raise ValueError('已核验事实稿的原文或审核凭据不一致')
        inputs.extend(directory+'/'+name for name in ('facts-approved.json','facts-audit.json'))
    inputs += [multi+'/plan.json',multi+'/planning-sources.md']
    inputs.append('cache/se/se_output.json')
    if quota:inputs.extend(['meta/length_policy.json',f'planning/length/{number}.json'])
    for name in ('allocation.json','planning-budget.json','book-contract.json'):
        if common._path(root,multi+'/'+name).is_file():inputs.append(multi+'/'+name)
    for key in ('book_contract_file',):
        if task.get('parameter_values',{}).get(key):inputs.append(task['parameter_values'][key])
    identity=[task['task_id'],g.body_digest(body),book_sha]
    seed_data={'body':body}
    resume=_resume_expression_commit(g,common._path(root,directory),task,body,source,binding,contract,failed)
    if resume:
        identity.append('expression-commit')
        seed_data['resume_expression_commit']=task['task_id']
        inputs.extend(f'{directory}/{name}' for name in EXPRESSION_FILES if f'{directory}/{name}' not in inputs)
    seed=f'cache/recovery/draft-review/{common._value_digest(identity)[:24]}/body.json'
    seed_text=json.dumps(seed_data,ensure_ascii=False,indent=2)+'\n';file=common._path(root,seed)
    if file.exists() and file.read_text(encoding='utf-8')!=seed_text:raise ValueError('已有恢复种子被修改，不能覆盖')
    if not file.exists():g.length.atomic_text(file,seed_text)
    return {'kind':'draft_review','stage':'mvp','chapter':number,'source_task_id':task['task_id'],
        'effective_target':expected_target,
        'source_task_sha256':common._value_digest(task),'source_file':seed,'multi_dir':multi,
        'selected_node_ids':EXPRESSION_COMMIT if resume else SELECTED,
        'files':{p:common._digest(common._path(root,p)) for p in [*inputs,seed]},
        'book_contract_sha256':book_sha,'values_sha256':common._value_digest(state.get('values',{})),
        'models':common._profile(state)}


def validate(root,state,checkpoint):
    common=shared()
    if (checkpoint.get('kind')!='draft_review' or checkpoint.get('stage')!='mvp'
            or checkpoint.get('chapter')!=str(state.get('values',{}).get('chapter_number','0001')).zfill(4)
            or checkpoint.get('values_sha256')!=common._value_digest(state.get('values',{}))
            or checkpoint.get('models')!=common._profile(state)
            or set(checkpoint.get('selected_node_ids',[])) not in (set(SELECTED),set(EXPRESSION_COMMIT))
            or not checkpoint.get('files') or checkpoint.get('source_file') not in checkpoint['files']):
        raise ValueError('审稿恢复范围、模型或来源配置已变化')
    if guard().book_policy.digest(guard().book_policy.resolve(root))!=checkpoint['book_contract_sha256']:
        raise ValueError('审稿恢复的本书契约已变化')
    g=guard();composer=g.load('validate_checkpoint_composition',Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py')
    quota=composer.current(root,checkpoint['chapter'])
    expected=f"{quota['minimum']}-{quota['maximum']}" if quota else state.get('values',{}).get('target_word_count')
    if checkpoint.get('effective_target',expected)!=expected or (quota and f"planning/length/{checkpoint['chapter']}.json" not in checkpoint['files']):
        raise ValueError('审稿恢复的生效篇幅预算变化')
    for path,digest in checkpoint['files'].items():
        file=common._path(root,path)
        if not file.is_file() or common._digest(file)!=digest:raise ValueError('审稿恢复依赖或种子已变化')
    if (set(checkpoint['selected_node_ids'])==set(EXPRESSION_COMMIT)) != bool(
            read(root,checkpoint['source_file']).get('resume_expression_commit')):
        raise ValueError('表达审核恢复范围与种子不匹配')


def options(root,state,definition,source):
    checkpoint=state['automaticCheckpoint'];validate(root,state,checkpoint);common=shared()
    if (not source or common._value_digest(source)!=checkpoint['source_task_sha256']
            or common._path(root,f'story/{checkpoint["chapter"]}/chapter.md').exists()):
        raise ValueError('审稿恢复的失败任务或未发布正文条件已变化')
    nodes={n['id']:n for n in definition.get('nodes',[])}
    workflow_id=definition.get('workflow_id','')
    prefix=workflow_id[:-len('mvp')] if workflow_id.endswith('-mvp') else ''
    selected=checkpoint['selected_node_ids']
    for key in (key for key in selected if key in SCRIPTS):
        name=SCRIPTS[key]
        node=nodes.get(key,{});params=node.get('node_params',{})
        if (node.get('node_type')!='script' or params.get('script_source')!='library'
                or params.get('script_type')!='python' or params.get('script_name')!=name
                or params.get('script_group')!=prefix+('nvl' if key in ('script_si_post','script_render_si','sync_up_si') else 'xs2')):
            raise ValueError('审稿恢复必须使用已声明的插件脚本，不能执行替代生成步骤')
    for key in (key for key in selected if key in AGENTS):
        name=AGENTS[key]
        if nodes.get(key,{}).get('node_type')!='agent' or nodes[key].get('agent_type')!=prefix+name:
            raise ValueError('审稿恢复核验者定义无效')
    if '{{guard_source_file}}' not in nodes['script_guard_prepare']['node_params'].get('script_argv',[]):
        raise ValueError('当前工作流不支持冻结事实稿来源')
    declared={v['key'] for v in definition.get('variables',[])}
    parameters={k:v for k,v in source.get('parameter_values',{}).items() if k in declared}
    parameters.update(guard_source_file=checkpoint['source_file'],multi_dir=checkpoint['multi_dir'])
    return {'parameter_values':parameters,'selected_node_ids':selected}


def verify(root,state,task,require_tail=True):
    checkpoint=state['automaticCheckpoint'];validate(root,state,checkpoint);g=guard();common=shared()
    selected=checkpoint['selected_node_ids']
    required=selected if require_tail else [key for key in selected if key not in ('sync_up_si','script_check_originality')]
    if any(task.get('node_states',{}).get(key,{}).get('status')!='completed' for key in required):
        raise ValueError('审稿恢复的全部事实、表达与发布门禁尚未完成')
    directory='cache/draft-guard/'+task['task_id'];receipt=read(root,directory+'/final-receipt.json')
    binding=read(root,directory+'/binding.json');contract=read(root,directory+'/contract.json')
    audit=read(root,directory+'/expression-audit.json');body=receipt.get('body','')
    expected=read(root,checkpoint['multi_dir']+'/plan.json')['continuity'];contract_sha=g.policy.contract_digest(expected)
    if (not body or receipt.get('phase')!='expression' or receipt.get('body_sha256')!=g.body_digest(body)
            or receipt.get('book_contract_sha256')!=checkpoint['book_contract_sha256']
            or binding.get('book_contract_sha256')!=checkpoint['book_contract_sha256']
            or contract!=expected or binding.get('contract_sha256')!=contract_sha or receipt.get('contract_sha256')!=contract_sha
            or binding.get('target')!=checkpoint.get('effective_target',state.get('values',{}).get('target_word_count'))
            or binding.get('pov')!=state.get('values',{}).get('narrative_pov')
            or binding.get('task_id')!=task['task_id'] or binding.get('source_sha256')!=g.body_digest(read(root,checkpoint['source_file'])['body'])
            or receipt.get('audit_sha256')!=common._digest(common._path(root,directory+'/expression-audit.json'))
            or g.audit_candidate(common._path(root,directory),audit,body,contract,'expression')
            or read(root,'cache/si/chapter.json').get('body')!=body or read(root,'cache/si/body.json').get('body')!=body):
        raise ValueError('恢复成稿与新任务最终核验凭据不一致')
    expected=(body.rstrip()+'\n').replace('\n',os.linesep).encode('utf-8')
    if common._path(root,f'story/{checkpoint["chapter"]}/chapter.md').read_bytes()!=expected:
        raise ValueError('恢复渲染正文与新核验稿不一致')
