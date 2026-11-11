"""Keep contextual reading separate from automatic revision suggestions."""
import json
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'resources/workflows/reader-sim/definition.json'
raw=path.read_bytes();bom=raw.startswith(b'\xef\xbb\xbf');newline='\r\n' if b'\r\n' in raw else '\n'
data=json.loads(raw.decode('utf-8-sig'))
node=next(n for n in data['nodes'] if n['id']=='agent_reader')
node['first_message']=node['first_message'].replace('{{author_feedback_file}}','{{reader_revision_context}}').replace(
    '==== 作者本次返修意见 ====','==== 作者范围与自动建议的来源分层 ====')
if '【修改权限的来源】' not in node['first_message']:
    node['first_message']='【修改权限的来源】reader_revision_context中author_feedback及human_intent才是作者要求；automatic_revision_advice是旧自动建议，其段落锚点和停止条款不能创建作者禁改范围。没有作者局部限制时revision_scope按整章权限分类，同时维护本书规则、事实和风格；质量问题仍须如实保留。\n'+node['first_message']
if not any(v['key']=='reader_revision_context' for v in data['variables']):
    data['variables'].append({'key':'reader_revision_context','name':'作者范围与自动建议','type':'file','source_type':'output',
        'default':'','hidden':True,'required':False})
text=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').replace('\n',newline)
path.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.encode('utf-8'))
