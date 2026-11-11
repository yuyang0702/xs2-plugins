import importlib.util
import json
from pathlib import Path
import re

PLUGIN=Path(__file__).resolve().parents[1]
BLOCK=re.compile(r'<OUTPUT_SCHEMA>\s*([\s\S]*?)\s*</OUTPUT_SCHEMA>')


def test_every_agent_validator_contract_is_visible_and_matches_its_prompt():
    failures=[]
    for file in (PLUGIN/'resources/workflows').glob('*/definition.json'):
        for node in json.loads(file.read_text(encoding='utf-8'))['nodes']:
            schema=node.get('node_params',{}).get('json_output_schema')
            if node.get('node_type')!='agent' or not schema:continue
            blocks=BLOCK.findall(node.get('first_message',''))
            if len(blocks)!=1 or json.loads(blocks[0])!=schema:failures.append((file.parent.name,node['id']))
    assert not failures,failures


def test_schema_sync_preserves_prose_context_and_is_idempotent(tmp_path):
    path=PLUGIN/'tools/sync_output_schemas.py'
    spec=importlib.util.spec_from_file_location('schema_sync_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    schema={'type':'object','properties':{'notes':{'type':'string'}},'required':['notes']}
    value={'untouched':'保留原样：{{file}}','nodes':[{'id':'critic','node_type':'agent',
        'first_message':'按本书文风判断。\n{{input_file}}','node_params':{'json_output_schema':schema}}]}
    file=tmp_path/'definition.json';original=json.dumps(value,ensure_ascii=False,indent=2)
    file.write_text(original,encoding='utf-8')
    assert module.sync_file(file,write=True)==1
    after=file.read_text(encoding='utf-8');parsed=json.loads(after)
    assert parsed['untouched']==value['untouched'] and parsed['nodes'][0]['first_message'].startswith(value['nodes'][0]['first_message'])
    assert module.sync_file(file,write=True)==0 and file.read_text(encoding='utf-8')==after
