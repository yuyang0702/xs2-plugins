"""Parallel independent reading; retain the existing dependent reconciliation."""
import copy
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'resources/workflows/reader-sim/definition.json';raw=path.read_bytes();d=json.loads(raw.decode('utf-8-sig'))
nodes={n['id']:n for n in d['nodes']}
if 'agent_context_reader' not in nodes:
    node=copy.deepcopy(nodes['agent_reader']);node.update(id='agent_context_reader',label='独立资料审稿',output_file_path='{{reader_preflight_raw_path}}')
    text=node['first_message']
    start=text.index('==== 已核验的独立初审')
    end=text.index('【本书世界与文风',start)
    # Preserve all earlier facts/style/whole-book instructions and the same full
    # report schema. Only the dependent blind-resolution instructions differ.
    tail=text[end:].replace('{{reader_context_feedback}}','{{reader_preflight_feedback}}')
    node['first_message']=text[:start]+('【独立资料审稿】本轮与盲读并行，尚未获得盲读结果。请独立完成整章事实、人物认知、跨章连续性、表达六维及作者权限审查，'
        '不能推测盲读问题。blind_resolutions必须为[]，revision_scope仅分类自己实际发现的问题。'
        '后续汇合会保留盲读全部发现，必要时由原有复评阶段结合双方证据处理。\n{{reader_preflight_feedback}}\n')+tail
    node['var_bindings'].pop('reader_context_feedback',None)
    node['var_bindings']['reader_preflight_feedback']={'var_key':'reader_preflight_feedback'}
    schema=node['node_params']['json_output_schema'];schema['properties']['blind_resolutions']['maxItems']=0
    if 'blind_resolutions' not in schema['required']:schema['required'].append('blind_resolutions')
    d['nodes'].append(node)
    for id,action,label in [('script_reader_context_commit','commit-context','验证独立资料审稿'),('script_reader_freeze','freeze-parallel','冻结共同审稿来源'),('script_reader_join','join','核对并行分支及复评需要')]:
        n=copy.deepcopy(nodes['script_reader_blind_commit']);n.update(id=id,label=label)
        n['node_params']['script_argv']=[action,'--binding','{{reader_review_binding}}','--binding-sha','{{reader_review_binding_sha}}']
        if action=='freeze-parallel':n['node_params']['script_argv']+=['--context','{{story_support_context}}']
        if action=='join':n['node_params']['script_argv']+=['--blind-sha','{{reader_blind_report_sha}}','--context-sha','{{reader_preflight_sha}}']
        d['nodes'].append(n)
    for key in ('reader_preflight_raw_path','reader_preflight_path','reader_preflight_feedback','reader_parallel_sources'):
        d['variables'].append({'key':key,'name':key,'type':'file','source_type':'output','hidden':True,'required':False,'default':''})
    for key in ('reader_preflight_sha','reader_reconcile_required'):
        d['variables'].append({'key':key,'name':key,'type':'text','source_type':'output','hidden':True,'required':False,'default':''})
    removed={('script_reader_review_prepare','agent_blind_reader'),('script_reader_blind_commit','script_story_context'),('script_length_context','agent_reader')}
    d['edges']=[e for e in d['edges'] if (e['source'],e['target']) not in removed]
    def edge(a,b,condition=None):
        e={'source':a,'target':b}
        if condition:e['condition']=condition
        d['edges'].append(e)
    for a,b in [('script_reader_review_prepare','script_story_context'),('script_length_context','script_reader_freeze'),
        ('script_reader_freeze','gw_reader_parallel'),('gw_reader_parallel','agent_blind_reader'),('gw_reader_parallel','agent_context_reader'),
        ('script_reader_blind_commit','gw_reader_join'),('agent_context_reader','script_reader_context_commit'),
        ('script_reader_context_commit','gw_reader_join'),('gw_reader_join','script_reader_join'),('script_reader_join','gw_reader_reconcile')]:edge(a,b)
    edge('gw_reader_reconcile','agent_reader',{'expression':'{{reader_reconcile_required}} == yes'})
    edge('gw_reader_reconcile','script_reader_merge',{'is_default':True})
    d['gateways'] += [
        {'id':'gw_reader_parallel','gateway_type':'parallel','label':'并行独立审稿','converge_gateway_id':'gw_reader_join'},
        {'id':'gw_reader_join','gateway_type':'converge','label':'完整汇合'},
        {'id':'gw_reader_reconcile','gateway_type':'condition','label':'有初审发现时依序复评'}]
# Rebuild this one message from the unchanged dependent role, including every
# book contract/style/evidence instruction after its blind-report section.
original=nodes['agent_reader']['first_message'];start=original.index('==== 已核验的独立初审');end=original.index('【本书世界与文风',start)
context=next(n for n in d['nodes'] if n['id']=='agent_context_reader')
context['first_message']=original[:start]+('【独立资料审稿】本轮与盲读并行，尚未获得盲读结果。独立完成全部整章审稿维度、事实、认知边界和作者范围判断。'
    'blind_resolutions必须为[]，不得猜测初审编号；新增问题用context-前缀。汇合后必要时进行依序复评。\n')+original[end:].replace('{{reader_context_feedback}}','{{reader_preflight_feedback}}')
for variable in d['variables']:
    if variable['key'] in ('reader_preflight_raw_path','reader_preflight_path','reader_parallel_sources'):variable['type']='text'
if not any(n['id']=='script_reader_reconcile_bypass' for n in d['nodes']):
    n=copy.deepcopy(nodes['script_reader_blind_commit']);n.update(id='script_reader_reconcile_bypass',label='初审无待复核问题')
    n['node_params']['script_argv']=['bypass','--binding','{{reader_review_binding}}','--binding-sha','{{reader_review_binding_sha}}']
    d['nodes'].append(n)
    for edge in d['edges']:
        if edge['source']=='gw_reader_reconcile' and edge['target']=='script_reader_merge':edge['target']='script_reader_reconcile_bypass'
    d['edges'].append({'source':'script_reader_reconcile_bypass','target':'script_reader_merge'})
if not any(v['key']=='revision_context_path' for v in d['variables']):
    d['variables'].append({'key':'revision_context_path','name':'共同资料路径','type':'text','source_type':'output','hidden':True,'required':False,'default':'cache/story-support/context.md'})
next(n for n in d['nodes'] if n['id']=='script_reader_freeze')['node_params']['script_argv']=[
    'freeze-parallel','--binding','{{reader_review_binding}}','--binding-sha','{{reader_review_binding_sha}}','--context','{{revision_context_path}}','--runtime','{{prose_policy_runtime}}']
argv=nodes['script_reader_merge']['node_params']['script_argv']
if '--context-sha' not in argv:argv+=['--context-sha','{{reader_preflight_sha}}']
argv=nodes['script_reader_review_prepare']['node_params']['script_argv']
if '--parallel' not in argv:argv.append('--parallel')
newline='\r\n' if b'\r\n' in raw else '\n'
path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+(json.dumps(d,ensure_ascii=False,indent=2)+'\n').replace('\n',newline).encode())
spec=importlib.util.spec_from_file_location('sync_p1_schema',ROOT/'tools/sync_output_schemas.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync);sync.sync_file(path,write=True)
