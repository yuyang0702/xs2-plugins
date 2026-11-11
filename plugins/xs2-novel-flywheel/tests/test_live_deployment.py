"""Contracts visible at the running UI/API boundary, not only internal CLIs."""
import json
from pathlib import Path
from test_book_contract import PLUGIN
from test_reference_distill import run
import importlib.util


def audit():
    path=PLUGIN/'tools/audit_live_deployment.py'
    spec=importlib.util.spec_from_file_location('deployment_audit_tests',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_every_select_option_has_a_visible_label_and_stable_value():
    for path in (PLUGIN/'resources/workflows').glob('*/definition.json'):
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        for field in data['variables']:
            for option in field.get('options',[]):
                assert isinstance(option,dict),f'{path.parent.name}/{field["key"]}: blank UI option'
                assert option.get('name') and isinstance(option.get('value'),str)


def test_custom_focus_is_optional_and_reaches_analysis_without_book_adoption(tmp_path):
    p=tmp_path/'references/source.txt';p.parent.mkdir(parents=True)
    p.write_text('她把灯放在桌上。来人终于说出了迟到的缘由。',encoding='utf8')
    focus='重点看"开头的疑问"怎样回应；保留抒情与必要解释。\n不要复制原作人物。'
    result=run(tmp_path,'split','--input','references/source.txt','--source-mode','short_full',
        '--learning-direction','zhihu_short','--learning-focus',focus)
    assert result.returncode==0,result.stderr
    meta=json.loads((tmp_path/'learning/dna/metadata.json').read_text(encoding='utf8'))
    assert meta['learning_focus']==focus
    instructions=(tmp_path/'learning/dna/instructions.md').read_text(encoding='utf8')
    assert focus in instructions and '不强制第一人称' in instructions
    assert not (tmp_path/'learning/active.json').exists()
    result=run(tmp_path,'split','--input','references/source.txt','--source-mode','short_full')
    assert result.returncode==0,result.stderr
    meta=json.loads((tmp_path/'learning/dna/metadata.json').read_text(encoding='utf8'))
    assert meta['learning_direction']=='general' and meta['learning_focus']==''


def test_audit_detects_a_masked_contract_and_missing_commit_gate():
    expected={'nodes':[{'id':'prepare','node_type':'script','enable_reject_upstream':True,'auto_retry_count':2,'node_params':{'script_argv':['prepare']}},
        {'id':'review','node_type':'agent','first_message':'{{book_contract_file}}','node_params':{'json_output_schema':{'type':'object'}}},
        {'id':'commit','node_type':'script','node_params':{'script_argv':['commit']}}],'variables':[]}
    current={'nodes':[{'id':'prepare','node_type':'script','node_params':{'script_argv':['prepare']}},
        {'id':'review','node_type':'agent','first_message':'旧版审稿','node_params':{'json_output_schema':{'type':'string'}}}],'variables':[]}
    issues=audit().workflow_gaps(expected,current)
    assert 'missing_node:commit' in issues
    assert 'missing_input:review:book_contract_file' in issues
    assert 'node_param:review:json_output_schema' in issues
    assert 'node_field:prepare:auto_retry_count' in issues


def test_audit_accepts_custom_wording_models_and_visual_positions():
    expected={'nodes':[{'id':'n','node_type':'agent','agent_type':'writer','first_message':'{{book_contract_file}}','node_params':{}}],'variables':[]}
    current=json.loads(json.dumps(expected));current['nodes'][0].update(first_message='保留我的写法。{{book_contract_file}}',model_override='author-model',position={'x':900})
    assert audit().workflow_gaps(expected,current)==[]


def test_prompt_audit_detects_old_whole_agent_override():
    expected={'sections':[{'name':'voice','content':'按本书声音。'},{'name':'memory','content':'区分人物所知与事实。'}]}
    assert audit().prompt_gaps(expected,{'sections':[{'name':'voice','content':'全部限知。'}]})=={
        'missing_sections':['memory'],'changed_sections':['voice']}
