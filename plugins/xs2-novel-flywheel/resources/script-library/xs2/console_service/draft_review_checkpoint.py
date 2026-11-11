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


def shared():
    spec=importlib.util.spec_from_file_location('draft_review_shared',Path(__file__).with_name('recovery_checkpoint.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def guard():
    spec=importlib.util.spec_from_file_location('draft_review_guard',Path(__file__).parents[1]/'draft_guard/draft_guard.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def read(root,path):return json.loads(shared()._path(root,path).read_text(encoding='utf-8-sig'))


def prepare(root,state,task,chapter):
    common=shared();g=guard();number=str(chapter).zfill(4)
    if (task.get('status')!='failed' or Path(task.get('workspace_override') or '').resolve()!=Path(root).resolve()
            or task.get('parameter_values',{}).get('chapter_number')!=number
            or common._path(root,f'story/{number}/chapter.md').exists()):
        raise ValueError('审稿恢复需要本书尚未发布正文的失败任务')
    nodes=task.get('node_states',{})
    if not all(nodes.get(key,{}).get('status')=='completed' for key in
            ('script_multi_plan','script_guard_prepare','script_guard_facts_commit')):
        raise ValueError('审稿恢复缺少已经通过的事实稿')
    failed={key for key,node in nodes.items() if node.get('status')=='failed'}
    if not failed or not failed<={'agent_guard_expression_repair','agent_guard_expression_audit',
            'script_guard_expression_candidate','script_guard_expression_commit'}:
        raise ValueError('该失败范围不能从事实稿恢复')
    directory='cache/draft-guard/'+task['task_id'];multi=task['parameter_values'].get('multi_dir','')
    if not multi:raise ValueError('审稿恢复缺少原计划目录')
    binding=read(root,directory+'/binding.json');approved=read(root,directory+'/facts-approved.json')
    source=read(root,directory+'/facts-input.json');audit=read(root,directory+'/facts-audit.json')
    plan=read(root,multi+'/plan.json');text=common._path(root,multi+'/planning-sources.md').read_text(encoding='utf-8-sig')
    contract=g.policy.validate_contract(plan.get('continuity'),text,len(plan.get('scenes',[])))
    book_sha=g.book_policy.digest(g.book_policy.resolve(root));body=approved.get('body')
    expected_target=state.get('values',{}).get('target_word_count')
    composer=g.load('checkpoint_composition',Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py')
    quota=composer.current(root,number)
    if quota:expected_target=f"{quota['minimum']}-{quota['maximum']}"
    if (not isinstance(body,str) or not body.strip() or approved.get('phase')!='facts'
            or approved.get('body_sha256')!=g.body_digest(body) or binding.get('task_id')!=task['task_id']
            or binding.get('plan_sha256')!=common._digest(common._path(root,multi+'/plan.json'))
            or binding.get('sources_sha256')!=common._digest(common._path(root,multi+'/planning-sources.md'))
            or binding.get('target')!=expected_target
            or binding.get('pov')!=state.get('values',{}).get('narrative_pov')
            or any(row.get('book_contract_sha256')!=book_sha for row in (binding,approved))
            or g.book_policy.digest(source.get('book_contract'))!=book_sha
            or source.get('source_constraints')!=text or source.get('continuity_contract')!=contract
            or binding.get('source_sha256')!=g.body_digest(source.get('source_body',''))
            or approved.get('source_sha256')!=binding['source_sha256']
            or any(row.get('contract_sha256')!=g.policy.contract_digest(contract) for row in (binding,approved))
            or approved.get('audit_sha256')!=common._digest(common._path(root,directory+'/facts-audit.json'))
            or g.policy.audit_issues(audit,body,contract,'facts')):
        raise ValueError('已核验事实稿、原任务或当前本书契约的绑定不完整')
    inputs=[directory+'/'+name for name in ('binding.json','facts-approved.json','facts-input.json','facts-audit.json')]
    inputs += [multi+'/plan.json',multi+'/planning-sources.md']
    inputs.append('cache/se/se_output.json')
    if quota:inputs.extend(['meta/length_policy.json',f'planning/length/{number}.json'])
    for name in ('allocation.json','planning-budget.json','book-contract.json'):
        if common._path(root,multi+'/'+name).is_file():inputs.append(multi+'/'+name)
    for key in ('book_contract_file',):
        if task.get('parameter_values',{}).get(key):inputs.append(task['parameter_values'][key])
    seed=f'cache/recovery/draft-review/{common._value_digest([task["task_id"],approved["body_sha256"],book_sha])[:24]}/body.json'
    seed_text=json.dumps({'body':body},ensure_ascii=False,indent=2)+'\n';file=common._path(root,seed)
    if file.exists() and file.read_text(encoding='utf-8')!=seed_text:raise ValueError('已有恢复种子被修改，不能覆盖')
    if not file.exists():g.length.atomic_text(file,seed_text)
    return {'kind':'draft_review','stage':'mvp','chapter':number,'source_task_id':task['task_id'],
        'effective_target':expected_target,
        'source_task_sha256':common._value_digest(task),'source_file':seed,'multi_dir':multi,
        'selected_node_ids':SELECTED,'files':{p:common._digest(common._path(root,p)) for p in [*inputs,seed]},
        'book_contract_sha256':book_sha,'values_sha256':common._value_digest(state.get('values',{})),
        'models':common._profile(state)}


def validate(root,state,checkpoint):
    common=shared()
    if (checkpoint.get('kind')!='draft_review' or checkpoint.get('stage')!='mvp'
            or checkpoint.get('chapter')!=str(state.get('values',{}).get('chapter_number','0001')).zfill(4)
            or checkpoint.get('values_sha256')!=common._value_digest(state.get('values',{}))
            or checkpoint.get('models')!=common._profile(state)
            or set(checkpoint.get('selected_node_ids',[]))!=set(SELECTED)
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


def options(root,state,definition,source):
    checkpoint=state['automaticCheckpoint'];validate(root,state,checkpoint);common=shared()
    if (not source or common._value_digest(source)!=checkpoint['source_task_sha256']
            or common._path(root,f'story/{checkpoint["chapter"]}/chapter.md').exists()):
        raise ValueError('审稿恢复的失败任务或未发布正文条件已变化')
    nodes={n['id']:n for n in definition.get('nodes',[])}
    for key,name in SCRIPTS.items():
        node=nodes.get(key,{});params=node.get('node_params',{})
        if (node.get('node_type')!='script' or params.get('script_source')!='library'
                or params.get('script_type')!='python' or params.get('script_name')!=name
                or params.get('script_group')!=('nvl' if key in ('script_si_post','script_render_si','sync_up_si') else 'xs2')):
            raise ValueError('审稿恢复必须使用已声明的插件脚本，不能执行替代生成步骤')
    for key,name in AGENTS.items():
        if nodes.get(key,{}).get('node_type')!='agent' or nodes[key].get('agent_type')!=name:
            raise ValueError('审稿恢复核验者定义无效')
    if '{{guard_source_file}}' not in nodes['script_guard_prepare']['node_params'].get('script_argv',[]):
        raise ValueError('当前工作流不支持冻结事实稿来源')
    declared={v['key'] for v in definition.get('variables',[])}
    parameters={k:v for k,v in source.get('parameter_values',{}).items() if k in declared}
    parameters.update(guard_source_file=checkpoint['source_file'],multi_dir=checkpoint['multi_dir'])
    return {'parameter_values':parameters,'selected_node_ids':SELECTED}


def verify(root,state,task,require_tail=True):
    checkpoint=state['automaticCheckpoint'];validate(root,state,checkpoint);g=guard();common=shared()
    required=SELECTED if require_tail else [key for key in SELECTED if key not in ('sync_up_si','script_check_originality')]
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
            or g.policy.audit_issues(audit,body,contract,'expression')
            or read(root,'cache/si/chapter.json').get('body')!=body or read(root,'cache/si/body.json').get('body')!=body):
        raise ValueError('恢复成稿与新任务最终核验凭据不一致')
    expected=(body.rstrip()+'\n').replace('\n',os.linesep).encode('utf-8')
    if common._path(root,f'story/{checkpoint["chapter"]}/chapter.md').read_bytes()!=expected:
        raise ValueError('恢复渲染正文与新核验稿不一致')
