"""Wire deterministic model views without altering canonical quality artifacts."""
import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];RES=ROOT/'resources'
spec=importlib.util.spec_from_file_location('wire_model_packet',RES/'script-library/xs2/prose_policy/context_packet.py')
packet=importlib.util.module_from_spec(spec);spec.loader.exec_module(packet)
wire_spec=importlib.util.spec_from_file_location('wire_review_protocol',RES/'script-library/xs2/prose_policy/review_wire.py')
wire=importlib.util.module_from_spec(wire_spec);wire_spec.loader.exec_module(wire)
prompt_path=RES/'prompts.json';prompt_raw=prompt_path.read_bytes();prompts=json.loads(prompt_raw.decode('utf-8-sig'))
for section in prompts['agents']['xs2-local-revision-reviewer']['sections']:
    suffix='；local-review-v2由程序绑定真实输入哈希，change_reviews按edit_index逐项交effect/reason，完整before/after由程序从真实补丁展开'
    section['content']=re.sub(r'(?:v1)*复制当前三个sha字段(?:'+re.escape(suffix)+r')*',lambda _: 'v1复制当前三个sha字段'+suffix,section['content'])
    if 'v2中也须逐项判断' not in section['content']:
        section['content']+='\nv2中也须逐项判断每个edit的净效果，不得漏项；上述after_excerpt规则约束展开后的完整证据，不要求v2重复抄写。候选采用无损段落视图时，引用paragraphs中的id或连续原句，仍核验全部表达维度与既定事实。'
prompt_text=(json.dumps(prompts,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n' if b'\r\n' in prompt_raw else '\n')
prompt_path.write_bytes((b'\xef\xbb\xbf' if prompt_raw.startswith(b'\xef\xbb\xbf') else b'')+prompt_text.encode('utf-8'))
for workflow in ('polish','mvp','reader-sim'):
    path=RES/f'workflows/{workflow}/definition.json';raw=path.read_bytes()
    data=json.loads(raw.decode('utf-8-sig'));keys={v['key'] for v in data['variables']}
    names=('revision_source_model','revision_editor_model','revision_review_model') if workflow=='polish' else ('reader_blind_model',) if workflow=='reader-sim' else ()
    for key in names:
        if key not in keys:data['variables'].append({'key':key,'name':key,'type':'file','source_type':'output','default':'','hidden':True,'required':False})
    if workflow in ('mvp','polish') and 'composition_reused' not in keys:
        data['variables'].append({'key':'composition_reused','name':'composition_reused','type':'text','source_type':'output','default':'no','hidden':True,'required':False})
    for node in data['nodes']:
        replacements={'revision_source_input':'revision_source_model','revision_input':'revision_editor_model',
            'revision_review_input':'revision_review_model'} if node['id'] in ('agent_sc','agent_pl','agent_local_review') else {}
        if node['id'] in ('agent_blind_reader','agent_context_reader','agent_reader'):
            replacements={'reader_blind_input':'reader_blind_model'}
        for old,new in replacements.items():node['first_message']=node['first_message'].replace('{{'+old+'}}','{{'+new+'}}')
        if replacements and '【无损输入视图】' not in node['first_message']:
            node['first_message']='【无损输入视图】全文按source_body/candidate/manuscript的paragraphs依序提供，id就是段落引用，before与suffix保留空白。这不是摘要。逐字补丁的paragraph_id取source_body.paragraphs的id；候选证据取candidate或manuscript段落id，也可用连续原句，不引用未提供的编号。\n'+node['first_message']
        if node['id'] in ('agent_sc','agent_pl','agent_local_review','agent_composition_plan','agent_composition_review'):
            node['first_message']=node['first_message'].replace('{{book_contract_file}}','本书完整契约已在本次冻结输入的book_contract中提供，仅一份；仍须遵守。')
            if node['id'].startswith('agent_composition_') and '【原有契约指导】' not in node['first_message']:
                node['first_message']+='\n【原有契约指导】\n'+packet.book_guidance()
        if node['id']=='agent_local_review':
            node['first_message']=node['first_message'].replace('当前review-input中evidence_catalog的ref_id','当前candidate.paragraphs中的id作为ref_id')
            node['node_params']['json_output_schema']=wire.schema(node['node_params']['json_output_schema'])
            if '【精简传输协议】' not in node['first_message']:
                node['first_message']='【精简传输协议】本轮优先交付protocol:"local-review-v2"。保留所有事实、表达维度、每个改动净效果和每个目标的判断及真实证据；change_reviews只交edit_index/effect/reason，程序从该索引绑定完整old/replacement并展开审查记录。三个哈希由程序绑定真实本次响应，不猜填。不得省略判断或用格式修复改变结论。兼容v1仅为旧客户端保留。\n'+node['first_message']
    newline='\r\n' if b'\r\n' in raw else '\n';text=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').replace('\n',newline)
    path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+text.encode('utf-8'))
sync_spec=importlib.util.spec_from_file_location('sync_performance_schema',ROOT/'tools/sync_output_schemas.py')
sync=importlib.util.module_from_spec(sync_spec);sync_spec.loader.exec_module(sync)
sync.sync_file(RES/'workflows/polish/definition.json',write=True)
