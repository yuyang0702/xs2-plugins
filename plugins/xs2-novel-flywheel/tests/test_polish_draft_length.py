import json
import re
import subprocess
import sys
import pytest
from test_length_quality import PLUGIN,policy,quality,write


def test_final_editor_budget_measures_its_draft_not_the_pre_polish_body(tmp_path):
    q=quality();body=write(tmp_path,'story/0001/chapter.md','甲'*5068)
    report=write(tmp_path,'quality/length/0001.json','original evidence')
    write(tmp_path,'cache/pl/body.json',json.dumps({'body':'乙'*4749},ensure_ascii=False))
    path=q.prepare_draft_guidance(tmp_path,'0001','5000-5300','cache/pl/body.json')
    text=(tmp_path/path).read_text(encoding='utf8')
    assert '4749' in text and '251' in text and '尚未提交' in text
    assert body.read_text(encoding='utf8')=='甲'*5068
    assert report.read_text(encoding='utf8')=='original evidence'


@pytest.mark.parametrize('payload',[{}, {'body':None}, {'body':''}])
def test_missing_or_invalid_polish_draft_cannot_reuse_old_length_evidence(tmp_path,payload):
    write(tmp_path,'cache/pl/body.json',json.dumps(payload))
    with pytest.raises(ValueError):quality().prepare_draft_guidance(tmp_path,'0001','5000-5300','cache/pl/body.json')


def test_content_polish_refreshes_draft_budget_but_length_only_keeps_frozen_contract():
    data=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    edges={(e['source'],e['target']) for e in data['edges']}
    assert ('agent_pl','script_draft_length_context') in edges
    assert ('script_draft_length_context','agent_pp') in edges
    assert ('script_focused_execution','agent_pp') in edges
    assert ('agent_pl','agent_pp') not in edges


def test_actual_cli_output_reaches_final_editor_without_competing_with_original_budget(tmp_path):
    from src.workflow.definition import WorkflowDef
    from src.workflow.engine import WorkflowEngine
    from src.workflow.runtime_models import NodeExecutionState
    write(tmp_path,'cache/pl/body.json',json.dumps({'body':'乙'*4749},ensure_ascii=False))
    entry=PLUGIN/'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    result=subprocess.run([sys.executable,str(entry),'draft-guidance','--chapter','0001','--target','5000-5300','--candidate','cache/pl/body.json'],
                          cwd=tmp_path,capture_output=True,text=True,encoding='utf8',check=True)
    path=re.search(r'<WF_VAR>pp_length_context_file:(.*?)</WF_VAR>',result.stdout)[1]
    raw=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(raw)
    states={'script_length_context':NodeExecutionState(node_id='script_length_context',status='completed',outputs={'length_context_file':'old.md'}),
            'script_draft_length_context':NodeExecutionState(node_id='script_draft_length_context',status='completed',outputs={'pp_length_context_file':path})}
    values=WorkflowEngine._enrich_parameter_values({},wf,'agent_pp',states)
    assert values['pp_length_context_file']==path and values['length_context_file']=='old.md'
    node=next(n for n in raw['nodes'] if n['id']=='agent_pp')
    assert '{{pp_length_context_file}}' in node['first_message'] and '{{length_context_file}}' not in node['first_message']
    assert node['var_bindings']['pp_length_context_file']['var_key']=='pp_length_context_file'


def test_script_argument_resolves_to_draft_path_instead_of_entire_json(tmp_path):
    import asyncio
    from src.workflow.definition import WorkflowDef,resolve_placeholders
    write(tmp_path,'cache/pl/body.json',json.dumps({'body':'乙'*4749},ensure_ascii=False))
    raw=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(raw);node=next(n for n in wf.nodes if n.id=='script_draft_length_context')
    values={v.key:v.default for v in wf.variables};values.update(chapter_number='0001',target_word_count='5000-5300')
    argv=[asyncio.run(resolve_placeholders(part,values,wf.variables,str(tmp_path))) for part in node.node_params['script_argv']]
    assert argv[argv.index('--candidate')+1]=='cache/pl/body.json'


def test_book_values_cannot_redirect_internal_polish_output_into_published_chapter():
    raw=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    values={v['key']:v.get('default','') for v in raw['variables']}
    values.update(chapter_number='0001',pl_draft_path='story/0001/chapter.md',pl_body_file='quality/author.md')
    parameters=policy().parameters({'values':values},raw)
    assert 'pl_draft_path' not in parameters and 'pl_body_file' not in parameters
    assert next(n for n in raw['nodes'] if n['id']=='agent_pl')['output_file_path']=='cache/pl/body.json'
