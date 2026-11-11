"""Idempotently expose optional learning goals in existing plugin workflows."""
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];RES=ROOT/'resources'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


reading=load('wire_reading',RES/'script-library/xs2/prose_policy/reading_contract.py')
composition=load('wire_reading_composition',RES/'script-library/xs2/composition_plan/composition_plan.py')
sync=load('wire_reading_sync',ROOT/'tools/sync_output_schemas.py')
distill=load('wire_distill_shape',RES/'script-library/xs2/reference_distill/distill_schema.py')


def save(path,data):
    raw=path.read_bytes();newline='\r\n' if b'\r\n' in raw else '\n'
    path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+(json.dumps(data,ensure_ascii=False,indent=2)+'\n').replace('\n',newline).encode())


GOAL_PLAN=('【本书阅读目标】有reading_contract时，goal_plans须逐个goal_id填写status(planned/not_applicable)、segment_ids、reader_start、reader_end、basis。'
    'planned说明读者在对应分段前后的期待、理解或感受；not_applicable须给本书和当前章范围的具体依据。'
    '不适用不能只是风格免责；计划与本书事实分开，作者范围、视角和世界规则优先；无目标省略或空数组。')
GOAL_REVIEW=('【阅读目标规划复查】有reading_contract时，goal_checks须逐个goal_id返回supported、reason、style_basis，'
    '独立核对goal_plans的具体依据、分段、信息权限、当前范围和本书风格；不成立就revise，不能仅按模板勾选。无目标省略或空数组。')
BUDGET=('【作者边界与分段建议】author_range非空时，方案顶层minimum/maximum必须原样等于author_range，不得用建议篇幅替换作者边界。'
    'segments的minimum合计及maximum合计只需落在该作者范围内，允许更窄的内容预算；不要为用尽上限增写，也不要把建议下限升级成作者要求。'
    'author_range为空且由规划者决定配额时，分段minimum/maximum合计必须分别等于方案顶层minimum/maximum。'
    '分段编号不可重复，各段须有实际阅读作用，最终正文仍独立核验原有篇幅、事实、风格及阅读目标。')
WRITER=('【本书采用链路】reading_contract仅来自本书显式采用；按已批准composition_plan.plan.goal_plans（分场来源中的已批准计划）及本书目标写作/局部修订，'
    '让阅读作用通过当前正文成立，不把检查项写进小说。作者风格、世界规则和事实优先；有意静景、心理、议论、开放结尾与不可靠叙述均可成立，'
    '不强制知乎短篇、第一人称、反转数量、句长或段长。无目标保持本书原有写法。')
LEGACY_WRITER=WRITER.replace('composition_plan.plan.goal_plans（分场来源中的已批准计划）','composition.plan.goal_plans')
LEARN=('【阅读目标学习】根据dna_instructions_file的学习方向分析；zhihu_short是可选分析侧重点，不能据此假定来源平台或约束其他作品。'
    '有真实证据的机制可附reading_objectives数组（至多8项）：每项{dimension:opening_promise/information_release/relationship_progression/payoff/voice/custom,'
    'intent:抽象作用,planning_question:本书规划要回答的问题,acceptance_question:按正文可检查的问题,limits:[使用条件]}。'
    '分析样本实际开篇期待、信息释放、关系发展、兑现或声音，没体现就省略；不要复制样本的人名、答案、剧情和句子。'
    '目标跟随机制的evidence精确核验，并且只有本书明确选择后才生效。')


def append(node,text):
    if text not in node.get('first_message',''):node['first_message']=node.get('first_message','')+'\n'+text


for path in sorted((RES/'workflows').glob('*/definition.json')):
    data=json.loads(path.read_text(encoding='utf-8-sig'));changed=False
    for node in data['nodes']:
        node['first_message']=node.get('first_message','').replace(LEGACY_WRITER,WRITER)
        id=node['id'];schema=node.get('node_params',{}).get('json_output_schema')
        if id in ('agent_composition_plan','agent_composition_review'):
            node['node_params']['json_output_schema']=composition.schemas()[id=='agent_composition_review']
            append(node,GOAL_REVIEW if id.endswith('review') else GOAL_PLAN);changed=True
            append(node,BUDGET)
        if id in ('agent_local_review','agent_blind_reader','agent_context_reader','agent_reader','agent_context_preflight','agent_guard_expression_audit'):
            if not schema:raise ValueError('Reviewer schema missing: '+id)
            for arm in schema.get('anyOf',[schema]):
                # Existing quote/ref unions are reused, not a second evidence format.
                quote=arm.get('properties',{}).get('expression_checks',{}).get('items',{}).get('properties',{}).get('excerpts',{}).get('items')
                arm['properties']['reading_checks']=reading.schema(quote)
            append(node,reading.GUIDANCE+' 阅读目标问题使用reading_checks，不伪装成事实问题或错误的表达类别。盲读只核对style_contract提供的公开目标。');changed=True
        if node.get('agent_type') in ('xs2-local-revision-writer','xs2-draft-repairer','novel-single-writer','novel-multi-scene-writer','novel-multi-scene-planner') or id in ('agent_sc','agent_single_writer','agent_scene_writer','agent_writer'):
            append(node,WRITER);changed=True
        if path.parent.name=='reference-distillation':
            if id=='script_split_reference':
                params=node['node_params'];params.pop('script_args',None)
                params['script_argv']=['split','--input','{{reference_path}}','--window','{{window_size}}','--overlap','400','--source-mode','{{source_mode}}',
                    '--learning-direction','{{learning_direction}}','--learning-focus','{{learning_focus}}']
            if id=='script_validate_window':
                node.update(enable_reject_upstream=True,max_reject_count=2)
                params=node['node_params'];params.pop('script_args',None)
                params['script_argv']=['validate-window','--input','learning/cache/{{window_id}}.raw.json','--window-id','{{window_id}}']
            if id=='agent_distill_window':
                # Current host shares one finite failure budget across shape
                # errors and downstream rejections; legacy max_reject_count is
                # not serialized into live definitions by that host.
                node.update(auto_retry_count=2,fail_auto_skip=False)
                node['node_params']['json_output_schema']=distill.schema()
                append(node,'【上次本窗口的校验反馈；为空则首次分析】\n{{distill_feedback_file}}\n只依据当前原文和实际编号修正结构或重新分析，不改来源、不猜证据。')
            if node.get('node_type')=='agent' and '当前参考资料窗口' in node.get('first_message',''):append(node,LEARN)
            changed=True
    if path.parent.name=='reference-distillation':
        keys={v['key'] for v in data['variables']}
        for key,name,default,options in [('learning_direction','学习侧重点','general',['general','zhihu_short','custom']),('learning_focus','自定义关注点','',[])]:
            if key not in keys:data['variables'].append({'key':key,'name':name,'type':'text','source_type':'input','default':default,'options':options,
                'hidden':False,'required':False,'description':'general 通用；zhihu_short 知乎短篇阅读体验；custom 使用自定义关注点。仅用于分析，采用前不约束本书。'})
        field=next(v for v in data['variables'] if v['key']=='learning_direction')
        field.update(type='select',options=[{'name':label,'value':value} for value,label in
            [('general','通用'),('zhihu_short','知乎短篇'),('custom','自定义')]])
        if 'distill_feedback_file' not in keys:data['variables'].append({'key':'distill_feedback_file','name':'本窗口校验反馈','type':'file',
            'source_type':'output','hidden':True,'required':False,'default':'learning/cache/{{window_id}}.feedback.md'})
    if changed:save(path,data);sync.sync_file(path,write=True)

path=RES/'prompts.json';data=json.loads(path.read_text(encoding='utf-8-sig'))
for key,agent in data['agents'].items():
    text=GOAL_PLAN if key=='xs2-composition-planner' else GOAL_REVIEW if key=='xs2-composition-reviewer' else reading.GUIDANCE if key in (
        'xs2-local-revision-reviewer','xs2-blind-reader','xs2-reader-sim','xs2-draft-auditor') else WRITER if key in ('xs2-local-revision-writer','xs2-draft-repairer','novel-single-writer','novel-multi-scene-writer','novel-multi-scene-planner') else ''
    if text:
        if key=='xs2-draft-auditor':
            # Fact audit precedes expression audit; only the latter owns these
            # optional semantic checks. Its schema and gate remain unchanged.
            text='仅表达核验阶段执行下列阅读目标验收；事实核验阶段按原schema核对事实，不提交reading_checks。\n'+text
        section=agent['sections'][0]
        section['content']=section['content'].replace(LEGACY_WRITER,WRITER)
        if key=='xs2-draft-auditor':section['content']=section['content'].replace('\n'+text,'').replace('\n'+reading.GUIDANCE,'')
        if text not in section['content']:section['content']+='\n'+text
        if key in ('xs2-composition-planner','xs2-composition-reviewer') and BUDGET not in section['content']:section['content']+='\n'+BUDGET
save(path,data)
