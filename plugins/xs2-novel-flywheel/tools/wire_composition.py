"""Maintain optional native composition planning nodes and exact visible schemas."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];RES=ROOT/'resources'
spec=importlib.util.spec_from_file_location('composition_schemas',RES/'script-library/xs2/composition_plan/composition_plan.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
PLAN,REVIEW=module.schemas()


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


def save(p,value):
    raw=p.read_bytes();bom=raw.startswith(b'\xef\xbb\xbf');newline='\r\n' if b'\r\n' in raw else '\n'
    text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    p.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.replace('\n',newline).encode('utf-8'))


guidance=('输入是本书冻结资料。情节、情绪、关系、氛围、声线、议论或形式探索都可以承载篇幅，例子不是必选项。'
    'author_feedback保留作者意见；automatic_revision_advice仅是旧自动建议，其旧配额不能覆盖本轮policy、author_range或作者原要求。'
    '按本书已有风格、世界规则和作者范围说明每段阅读作用如何发展；有意回环可以成立，不能只复述同一判断或机械增加操作。'
    '不规定事件密度、情绪回响次数、叙述风格或每场字数比例。程序配额可协商，作者硬边界不能改。'
    '全书目标按实际验收正文累计，不能为了固定单章均值灌水；计划不是既成事实。')
agents=read(RES/'agents.json');prompts=read(RES/'prompts.json')
for section in prompts['agents']['xs2-local-revision-writer']['sections']:
    section['content']=section['content'].replace('只交付source_sha256和edits，不交付整篇body。',
        '正常修订交付source_sha256和edits，不交付整篇body。若本轮schema允许且范围与篇幅不能兼顾，交付status:needs_replan、source_sha256、edits:[]、reason和冻结原文evidence，交还规划，不能补字灌水。')
for section in prompts['agents']['xs2-draft-repairer']['sections']:
    if 'needs_replan' not in section['content']:
        section['content']+='\n表达阶段若schema允许且当前范围、篇幅和表达要求不能兼顾，可提交status:needs_replan、source_sha256、edits:[]、reason和冻结原文evidence返回规划；事实阶段仍按该阶段schema交付，不用冲突响应代替事实核验。'
for name,role in [('planner','规划各段阅读作用及相应篇幅；明确承载范围、发展方式及冲突。'),('reviewer','独立核对每段实际作用、本书风格、世界与作者范围，以及预算可行性。不要因为要求了新动作就认为有新作用。')]:
    key='xs2-composition-'+name
    agent=copy.deepcopy(agents['agents']['xs2-local-revision-reviewer']);agent['prompt_template']=key;agent['description']=role
    agents['agents'][key]=agent
    prompts['agents'][key]={'description':role,'preambles':{},'sections':[{'name':'composition_'+name,'enabled':True,'order':0,
        'token_estimate':700,'workflow_only':False,'content':role+guidance}]}
save(RES/'agents.json',agents);save(RES/'prompts.json',prompts)


for wf in ('mvp','polish'):
    path=RES/f'workflows/{wf}/definition.json';data=read(path)
    nodes=data['nodes'];ids={n['id'] for n in nodes}
    template=copy.deepcopy(next(n for n in read(RES/'workflows/polish/definition.json')['nodes'] if n['id']=='agent_local_review'))
    def script(id,action,argv,stdin=None):
        params={'script_source':'library','script_type':'python','script_group':'xs2','script_name':'composition_plan',
            'timeout':30,'script_argv':[action,*argv]}
        if stdin:params['script_stdin_variable']=stdin
        return {'id':id,'node_type':'script','label':id,'position':{'x':80,'y':80},'var_bindings':{},'node_params':params,
            'enable_reject_upstream':True,'max_reject_count':2}
    additions=[script('script_composition_prepare','prepare',['--chapter','{{chapter_number}}','--target','{{target_word_count}}','--ownership','{{chapter_length_ownership}}']),
        script('script_composition_candidate','candidate',['--dir','{{composition_dir}}'],'composition_plan_result'),
        script('script_composition_commit','commit',['--dir','{{composition_dir}}'],'composition_review_result'),
        script('script_composition_ready','emit',['--chapter','{{chapter_number}}']),
        script('script_composition_bypass','bypass',[])]
    for role,schema,file,output,message in [('plan',PLAN,'composition_plan_file','composition_plan_result',
        '制定本章分段阅读作用和篇幅方案。{{composition_request_file}}'),('review',REVIEW,'composition_review_file','composition_review_result',
        '独立核对方案，不替规划者补理由。{{composition_review_input}}')]:
        n=copy.deepcopy(template);n.update(id='agent_composition_'+role,label='内容与篇幅'+('规划' if role=='plan' else '独立复查'),
            agent_type='xs2-composition-'+('planner' if role=='plan' else 'reviewer'),
            first_message=guidance+'\n'+message,system_prompt_template='',output_file_path='{{'+file+'}}',output_variable=output,
            auto_retry_count=2,enable_reject_upstream=False)
        n['node_params']['json_output_schema']=schema;additions.append(n)
    for n in additions:
        if n['id'] not in ids:nodes.append(n)
        elif n['id']=='script_composition_prepare':next(old for old in nodes if old['id']==n['id'])['node_params']=n['node_params']
    for n in nodes:
        if n['id'] in ('agent_composition_plan','agent_composition_review') and '{{composition_feedback_file}}' not in n['first_message']:
            n['first_message']+='\n本轮纠错反馈（不是作者新设定）：{{composition_feedback_file}}'
        if n['id'] in ('agent_composition_plan','agent_composition_review') and '{{book_contract_file}}' not in n['first_message']:
            n['first_message']+='\n本书统一契约（与写作审稿相同）：{{book_contract_file}}'
    gid='gw_composition_enabled'
    if not any(g['id']==gid for g in data.get('gateways',[])):
        data.setdefault('gateways',[]).append({'id':gid,'gateway_type':'condition','label':'是否采用本书篇幅规划','position':{'x':100,'y':100}})
    # A gateway's direct target is part of its branch, not a convergence node.
    # Give the bypass its own node so the shared emitter cannot be skipped.
    edges=data['edges']=[e for e in data['edges'] if e.get('id') not in (
        'composition-__start__-script_composition_prepare','composition-gw_composition_enabled-script_composition_ready')]
    existing={e.get('id') for e in edges}
    for e in edges:
        if e['source']=='script_composition_ready' and e['target']=='script_story_context':e['source']='__start__'
        elif e['source']=='script_story_context' and e['target']!='script_composition_prepare':e['source']='script_composition_ready'
    for a,b,condition in [('script_story_context','script_composition_prepare',None),('script_composition_prepare',gid,None),
        (gid,'agent_composition_plan',{'expression':'{{composition_enabled}} == yes','label':'按每书策略规划'}),
        (gid,'script_composition_bypass',{'is_default':True,'label':'沿用原流程'}),
        ('script_composition_bypass','script_composition_ready',None),
        ('agent_composition_plan','script_composition_candidate',None),('script_composition_candidate','agent_composition_review',None),
        ('agent_composition_review','script_composition_commit',None),('script_composition_commit','script_composition_ready',None)]:
        id='composition-'+a+'-'+b
        if id in existing:continue
        edge={'id':id,'source':a,'target':b}
        if condition:edge['condition']=condition
        edges.append(edge)
    keys={v['key'] for v in data['variables']}
    if 'chapter_length_ownership' not in keys:
        data['variables'].append({'key':'chapter_length_ownership','name':'章节篇幅归属','type':'text','default':'沿用本书',
            'description':'作者硬性范围保持不变；按内容规划允许协商单章分配，全书目标按实际验收正文累计。',
            'options':[{'name':v,'value':v} for v in ('沿用本书','作者硬性范围','按内容规划')],'source_type':'input','hidden':False,'required':False})
    ownership=next(v for v in data['variables'] if v['key']=='chapter_length_ownership')
    ownership['options']=[{'name':v,'value':v} for v in ('沿用本书','作者硬性范围','按内容规划')]
    for key,type in [('composition_enabled','text'),('composition_dir','text'),('composition_request_file','file'),
        ('composition_plan_file','text'),('composition_review_input','file'),('composition_review_file','text'),
        ('composition_plan_result','text'),('composition_review_result','text'),('revision_patch_result','text'),('composition_feedback_file','file')]:
        if key not in keys:data['variables'].append({'key':key,'name':key,'type':type,'default':'','hidden':True,'required':False,'source_type':'output'})
    if wf=='polish':
        writer=next(n for n in nodes if n['id']=='agent_pl');writer['output_variable']='revision_patch_result'
        schema=writer['node_params']['json_output_schema'];schema['properties'].update(status={'enum':['needs_replan']},
            reason={'type':'string','minLength':1},evidence={'type':'array','minItems':1,'items':{'type':'string','minLength':1}})
        schema['allOf']=[{'if':{'required':['status']},'then':{'required':['reason','evidence'],'properties':{'edits':{'maxItems':0}}},
            'else':{'not':{'anyOf':[{'required':['reason']},{'required':['evidence']}]}}}]
        if '【篇幅冲突出口】' not in writer['first_message']:
            writer['first_message']='【篇幅冲突出口】无法在本书授权范围内兼顾表达与篇幅时，提交source_sha256、edits:[]、status:"needs_replan"、reason和evidence(冻结原文连续引句)，不填充重复解释或动作。composition_plan是本轮经独立审核的阅读作用与预算；automatic_revision_advice是较低优先级的旧自动建议，其旧配额不能覆盖当前已批准预算或作者原意见。\n'+writer['first_message']
        if '【上一轮诊断】' not in writer['first_message']:
            writer['first_message']='【上一轮诊断】prior_revision存在时，参考未验收候选中的已有改进并逐项处理仍适用于冻结原稿的剩余诊断，避免重规划后重复遗失修订。它不是事实档案、作者新要求或通过凭据；全部改动仍须按当前本书规则和本轮预算独立复查。\n'+writer['first_message']
    else:
        writer=next(n for n in nodes if n['id']=='agent_guard_expression_repair')
        writer['output_variable']='guard_expression_patch_result'
        if 'guard_expression_patch_result' not in keys:
            data['variables'].append({'key':'guard_expression_patch_result','name':'guard_expression_patch_result','type':'text','default':'',
                'hidden':True,'required':False,'source_type':'output'})
        schema=writer['node_params']['json_output_schema']
        schema['properties'].update(status={'enum':['needs_replan']},reason={'type':'string','minLength':1},
            evidence={'type':'array','minItems':1,'items':{'type':'string','minLength':1}})
        schema['allOf']=[{'if':{'required':['status']},'then':{'required':['reason','evidence'],'properties':{'edits':{'maxItems':0}}},
            'else':{'not':{'anyOf':[{'required':['reason']},{'required':['evidence']}]}}}]
        if '【篇幅冲突出口】' not in writer['first_message']:
            writer['first_message']='【篇幅冲突出口】若在冻结范围内不能兼顾表达与篇幅，提交source_sha256、edits:[]、status:"needs_replan"、reason和evidence(事实核验通过的原文连续引句)，交还分场规划，不能填充重复解释或动作。\n'+writer['first_message']
        writer['first_message']=writer['first_message'].replace('只交付source_sha256与edits局部补丁JSON，禁止输出整篇body。',
            '正常修订只交付source_sha256与edits局部补丁JSON，不能兼顾时按冲突出口返回；禁止输出整篇body。')
        writer['first_message']=writer['first_message'].replace('【必须遵守的输出JSON schema；金额parts/change为字符串，不能改成数组】',
            '【必须遵守的输出JSON schema；正常补丁与有据重规划响应分别按对应结构交付】')
    save(path,data)

sync_spec=importlib.util.spec_from_file_location('sync_composition_schemas',ROOT/'tools/sync_output_schemas.py')
sync=importlib.util.module_from_spec(sync_spec);sync_spec.loader.exec_module(sync)
for wf in ('mvp','polish'):sync.sync_file(RES/f'workflows/{wf}/definition.json',write=True)
