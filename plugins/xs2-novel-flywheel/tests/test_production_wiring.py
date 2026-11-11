import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import pytest
from test_book_contract import PLUGIN


STAGES=('build','character','story-plan','outline','mvp','polish','reader-sim','post-hoc','export')


@pytest.mark.parametrize('stage',STAGES)
def test_every_paid_role_is_downstream_of_preflight_and_its_budget(stage):
    from src.workflow.definition import WorkflowDef
    d=json.loads((PLUGIN/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8-sig'))
    assert not WorkflowDef.from_dict(d).validate()
    assert all(e['target']=='script_production_start' for e in d['edges'] if e['source']=='__start__')
    assert all(e['source']=='script_production_finish' for e in d['edges'] if e['target']=='__end__')
    for n in d['nodes']:
        if n['node_type']!='agent':continue
        incoming=[e['source'] for e in d['edges'] if e['target']==n['id']]
        if stage == 'post-hoc' and n['id'] == 'agent_obs':
            assert [e['source'] for e in d['edges'] if e['target']=='script_budget_agent_obs'] == ['gw_archive_observation_reused']
            assert [e['source'] for e in d['edges'] if e['target']=='gw_archive_observation_reused'] == ['script_reuse_observation']
            assert [e['source'] for e in d['edges'] if e['target']=='script_reuse_observation'] == ['script_review_source']
            assert {'script_validate_observation','script_validate_cached_observation'} == {
                e['source'] for e in d['edges'] if e['target']=='script_budget_agent_arb'}
        assert incoming==['script_budget_'+n['id']]
        assert '【数字的叙事作用】' in n['first_message']


@pytest.mark.parametrize('stage', ('mvp', 'post-hoc'))
def test_story_context_generated_paths_are_declared_outputs(stage):
    d = json.loads((PLUGIN/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8-sig'))
    variables = {item['key']: item for item in d['variables']}
    producer = next(node for node in d['nodes'] if node['id'] == 'script_story_context')
    argv = producer['node_params']['script_argv']
    outputs = {'story_support_context', 'prose_policy_runtime', 'prose_policy_prompt'}
    outputs.update(argv[i+1].split('=', 1)[0] for i, option in enumerate(argv) if option == '--policy-alias')
    assert all(variables[name]['source_type'] == 'output' for name in outputs)


def test_single_new_review_protocol_and_source_bound_ledger_alias_schema():
    d=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf-8-sig'))
    reviewer=next(n for n in d['nodes'] if n['id']=='agent_local_review')
    schema=reviewer['node_params']['json_output_schema']
    assert 'anyOf' not in schema and schema['properties']['protocol']['const']=='local-review-v2'
    writer=next(n for n in d['nodes'] if n['id']=='agent_pl')
    def find(value):
        if isinstance(value,dict):
            if {'paragraph_id','old','occurrence','replacement'}<=set(value.get('properties',{})):return value
            for v in value.values():
                if (r:=find(v)) is not None:return r
        elif isinstance(value,list):
            for v in value:
                if (r:=find(v)) is not None:return r
    assert {'group_id','independent'}<=set(find(writer['node_params']['json_output_schema'])['properties'])


def test_generated_currency_example_is_accepted_by_its_evidence_grammar():
    import re
    from test_ledger_aliases import module,ledger
    d=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8-sig'))
    examples=[quote for n in d['nodes'] for quote in re.findall(r'currency_scope:\{code:"CNY",source_quote:"([^"]+)"\}',n.get('first_message',''))]
    assert examples
    for quote in examples:assert module().enrich_unit_aliases(ledger(),quote)['currency_scope']['source_quote']==quote


def test_generated_reader_feedback_paths_are_not_frozen_as_author_inputs():
    d=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8-sig'))
    variables={v['key']:v for v in d['variables']}
    for name in ('reader_context_feedback','reader_blind_feedback'):
        assert variables[name]['source_type']=='output'


def test_production_wiring_idempotent_and_preserves_models(tmp_path):
    target=tmp_path/'plugin';shutil.copytree(PLUGIN,target,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','data','vendor'))
    paths=[target/'resources/prompts.json',*[target/f'resources/workflows/{s}/definition.json' for s in STAGES]]
    models={str(p):{n['id']:n.get('model_override') for n in json.loads(p.read_text(encoding='utf-8-sig')).get('nodes',[])} for p in paths[1:]}
    command=[sys.executable,str(target/'tools/wire_production_p0.py')]
    subprocess.run(command,check=True,capture_output=True);first={str(p):p.read_bytes() for p in paths}
    subprocess.run(command,check=True,capture_output=True)
    assert first=={str(p):p.read_bytes() for p in paths}
    assert models=={str(p):{n['id']:n.get('model_override') for n in json.loads(p.read_text(encoding='utf-8-sig'))['nodes']} for p in paths[1:]}
