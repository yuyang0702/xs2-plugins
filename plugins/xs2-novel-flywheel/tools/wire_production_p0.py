"""Idempotent plugin-owned preflight, role budgets and purposeful prose policy."""
import copy
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1];RES=ROOT/'resources'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def save(path,value):
    raw=path.read_bytes();text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if b'\r\n' in raw:text=text.replace('\n','\r\n')
    path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+text.encode())


def script(id,stage,command,chapter,node=None):
    argv=[command,'--stage',stage,'--chapter',chapter]
    if node:argv+=['--node',node]
    return {'id':id,'label':'运行版本与输入预算' if command!='finish' else '核对执行凭据',
        'node_type':'script','agent_type':'default','position':{'x':0,'y':0},
        'first_message':'','system_prompt_template':'','var_bindings':{},'auto_flow':False,
        'enable_complete_node_task':True,'enable_reject_upstream':False,'fail_auto_skip':False,
        'node_params':{'script_source':'library','script_group':'xs2','script_name':'production_guard',
                       'script_type':'python','script_argv':argv,'timeout':30}}


def edit_schema(schema):
    if isinstance(schema,dict):
        props=schema.get('properties',{})
        if {'units','unit_equations','accounts','transfers'}<=set(props):
            quote={'type':'string','minLength':1}
            props['currency_scope']={'type':'object','properties':{'code':{'const':'CNY'},'source_quote':quote},'required':['code','source_quote'],'additionalProperties':False}
            props['unit_aliases']={'type':'array','items':{'type':'object','properties':{'alias':quote,'unit':quote,'source_quote':quote},'required':['alias','unit','source_quote'],'additionalProperties':False}}
        if {'paragraph_id','old','occurrence','replacement'}<=set(props):
            props.update(group_id={'type':'string','pattern':'^[A-Za-z0-9_-]{1,80}$'},independent={'type':'boolean'})
        if props.get('category',{}).get('enum') and 'voice_flattening' in props['category']['enum']:
            if 'unnecessary_precision' not in props['category']['enum']:props['category']['enum'].append('unnecessary_precision')
        for value in schema.values():edit_schema(value)
    elif isinstance(schema,list):
        for item in schema:edit_schema(item)


def wire():
    precision=module('wire_precision',RES/'script-library/xs2/prose_policy/precision_policy.py')
    report=module('wire_report',RES/'script-library/xs2/prose_policy/review_wire.py')
    sync=module('wire_p0_sync',ROOT/'tools/sync_output_schemas.py')
    guidance='【数字的叙事作用】\n'+precision.GUIDANCE
    patch_guidance=('【完整阅读作用与补丁依赖】移动、删后补入等相关补丁使用同一group_id，按整组净作用审查；'
        '确实不依赖其他补丁的改动可标independent:true。未确认独立就不要标；组内不得标独立。'
        'change_reviews仍逐项填写，但理由须结合整组净作用，不将移动的删除单项误判。'
        '无依赖的equivalent可撤回并重新组装、独立复核；不得把equivalent改为improved。'
        '仅重复拒稿不证明篇幅与阅读作用冲突；needs_replan须有具体冻结原文与真实冲突证据。')
    currency=('【账本作用域】现代人民币账本须明确currency_scope:{code:"CNY",source_quote:"本账使用人民币计价，收款三块。"}（示例主单位为块，实际引文须含本账主单位），'
        'source_quote须逐字来自本书已有资料、且仅支持该账本；不要添加书中没有的声明。'
        '已证实人民币作用域允许元/块等同；其他单位用unit_aliases:[{alias:"别名",unit:"主单位",source_quote:"一主单位等于一别名"}]声明。'
        '不同币种、资源品阶、未知兑换率不能猜测等同，不要求小说用词迎合解析器。')
    path=RES/'prompts.json';prompts=json.loads(path.read_text(encoding='utf-8-sig'))
    for agent,config in prompts['agents'].items():
        if any(token in agent for token in ('writer','polish','revision','reader','review','auditor','scene','composition')):
            sections=config.get('sections',[])
            for section in sections:section['content']=section['content'].replace('\n'+guidance,'')
            target=next((s for s in sections if '{{custom_append}}' not in s['content']),None)
            if target is not None:target['content']+='\n'+guidance
        if agent=='xs2-local-revision-reviewer':
            for section in config.get('sections',[]):
                section['content']=section['content'].replace('v1复制当前三个sha字段','当前仅提交local-review-v2，三个sha字段由程序绑定，不由模型复制')
    save(path,prompts)
    stages=('build','character','story-plan','outline','mvp','polish','reader-sim','post-hoc','export')
    for stage in stages:
        path=RES/f'workflows/{stage}/definition.json';data=json.loads(path.read_text(encoding='utf-8-sig'))
        chapter='{{chapter_number}}' if any(v['key']=='chapter_number' for v in data['variables']) else '0001'
        defaults={'conflict_ledger_file':('file','meta/conflict_ledger.md'),
                  'conflict_point_count':('text',''), 'foreshadowing_count':('text',''),
                  'conflict_plan_mode':('text','')}
        supplied={v['key'] for v in data['variables']}
        if stage=='reader-sim':
            for variable in data['variables']:
                if variable['key'] in ('reader_context_feedback','reader_blind_feedback'):
                    variable['source_type']='output'  # Generated by script_reader_review_prepare, never an author input.
        if stage=='polish' and 'revision_review_repair' not in supplied:
            data['variables'].append({'key':'revision_review_repair','name':'revision_review_repair','type':'file','source_type':'output','default':'','hidden':True,'required':False});supplied.add('revision_review_repair')
        if stage in ('mvp','polish'):
            for key in ('composition_request_model','composition_review_model'):
                if key not in supplied:
                    data['variables'].append({'key':key,'name':key,'type':'file','source_type':'output','default':'','hidden':True,'required':False});supplied.add(key)
        refs=set(re.findall(r'\{\{([\w_]+)\}\}',json.dumps(data,ensure_ascii=False)))
        for key in sorted(refs-supplied):
            if key in defaults:
                kind,default=defaults[key]
                data['variables'].append({'key':key,'name':key,'type':kind,'source_type':'input','default':default,'hidden':True,'required':False})
        ids={n['id'] for n in data['nodes']}
        if 'script_production_start' not in ids:
            for edge in data['edges']:
                if edge['source']=='__start__':edge['source']='script_production_start'
                if edge['target']=='__end__':edge['target']='script_production_finish'
            data['nodes']=[script('script_production_start',stage,'start',chapter),*data['nodes'],script('script_production_finish',stage,'finish',chapter)]
            data['edges']+=[{'source':'__start__','target':'script_production_start'},{'source':'script_production_finish','target':'__end__'}]
        for node in list(data['nodes']):
            if node['node_type']!='agent':continue
            if '【数字的叙事作用】' not in node.get('first_message',''):node['first_message']=guidance+'\n'+node.get('first_message','')
            if node['id'] in ('agent_composition_plan','agent_composition_review'):
                node['first_message']=node['first_message'].replace('{{composition_request_file}}','{{composition_request_model}}').replace('{{composition_review_input}}','{{composition_review_model}}')
                if '【规划无损视图】' not in node['first_message']:
                    node['first_message']='【规划无损视图】body保留完整原文字符串，保留本书全部规则、作者要求与有效审稿语义。机器来源清单留本地核对；与当前稿哈希不匹配的旧报告/旧冲突标stale_not_authoritative，不能当作当前问题，也不是缺少当前正文。request_digest/plan_digest仍取本次输入明示字段。\n'+node['first_message']
                node['first_message']=node['first_message'].replace('body按paragraphs完整提供','body保留完整原文字符串')
            if node['id'] in ('agent_pl','agent_local_review','agent_guard_expression_repair','agent_guard_expression_audit') and '【完整阅读作用与补丁依赖】' not in node['first_message']:
                node['first_message']=patch_guidance+'\n'+node['first_message']
            if node['id'].startswith('agent_guard_'):
                node['first_message']=node['first_message'].replace('{{book_contract_file}}','本书完整契约已在冻结输入的book_contract中提供；仍须遵守，仅一份。')
                for phase in ('facts','expression'):
                    for old,new in ((f'guard_{phase}_input',f'guard_{phase}_model'),(f'guard_{phase}_audit_input',f'guard_{phase}_audit_model')):
                        node['first_message']=node['first_message'].replace('{{'+old+'}}','{{'+new+'}}')
                        if new not in supplied:
                            data['variables'].append({'key':new,'name':new,'type':'file','source_type':'output','default':'','hidden':True,'required':False});supplied.add(new)
                if '【核验无损视图】' not in node['first_message']:
                    node['first_message']='【核验无损视图】source_body/candidate_body按paragraphs完整提供，before和suffix保留空白。大型证据目录仅留本地，当前可引用paragraphs的p编号或连续逐字原句；未提供的a/c编号不可猜测。\n'+node['first_message']
            if stage=='mvp' and any(t in node['id'] for t in ('allocation','plan','fact')) and '【账本作用域】' not in node['first_message']:
                node['first_message']=currency+'\n'+node['first_message']
            if '【账本作用域】' in node['first_message']:
                node['first_message']=re.sub(r'^【账本作用域】[^\n]*\n',lambda _:currency+'\n',node['first_message'],flags=re.M)
            node['first_message']=node['first_message'].replace('本账使用人民币计价，金额为三元','本账使用人民币计价，收款三块。').replace('本账使用人民币计价，收款三元。','本账使用人民币计价，收款三块。')
            schema=node.get('node_params',{}).get('json_output_schema')
            if node['id']=='agent_local_review':
                node['node_params']['json_output_schema']=report.schema(schema)
                node['first_message']=node['first_message'].replace('兼容v1仅为旧客户端保留。','本轮仅输出local-review-v2，旧版兼容只在程序读取端。')
                if '【定点补审】' not in node['first_message']:
                    node['first_message']='【定点补审】\n{{revision_review_repair}}\n若为空对象，执行完整独立复查；有targeted-report-repair-v1时，只重新判断allowed_fields并完整返回同一协议，其余字段逐字保留。不得自动改目标ID、编证据或把失败改通过；发现其他字段有实质错误时明确提出完整复审，程序会取消局部复用。\n'+node['first_message']
            if schema:edit_schema(node['node_params']['json_output_schema'])
            budget_id='script_budget_'+node['id']
            if budget_id not in ids:
                for edge in data['edges']:
                    if edge['target']==node['id']:edge['target']=budget_id
                data['nodes'].append(script(budget_id,stage,'budget',chapter,node['id']))
                data['edges'].append({'source':budget_id,'target':node['id']})
        agent_ids={n['id'] for n in data['nodes'] if n['node_type']=='agent'}
        for scheme in data.get('execution_schemes',[]):
            selected=scheme.get('selected_node_ids',[])
            if selected:
                required=['script_production_start','script_production_finish',*['script_budget_'+n for n in selected if n in agent_ids]]
                scheme['selected_node_ids']=list(dict.fromkeys([*required,*selected]))
        save(path,data);sync.sync_file(path,write=True)


if __name__=='__main__':wire()
