import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import pytest
from test_book_contract import PLUGIN


STAGES=('build','character','story-plan','outline','mvp','polish','reader-sim','post-hoc','export')


def test_reference_delivery_is_bound_to_writer_task_context_and_current_body(tmp_path):
    path = PLUGIN/'resources/script-library/xs2/production_guard/production_guard.py'
    spec = importlib.util.spec_from_file_location('reference_delivery_guard', path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    root = tmp_path.resolve()
    context = root/'learning/context/mvp.md'
    context.parent.mkdir(parents=True)
    context.write_text('本场试用一条参考。\n', encoding='utf-8')
    body = root/'story/0001/chapter.md'
    body.parent.mkdir(parents=True)
    body.write_text('窗外的风停了。', encoding='utf-8')
    prepared = root/'learning/receipts/mvp.json'
    prepared.parent.mkdir()
    receipt = {'task_id': 'draft-1', 'chapter': '0001', 'context_path': 'learning/context/mvp.md',
               'context_sha256': hashlib.sha256(context.read_text(encoding='utf-8').encode()).hexdigest(),
               'candidate_ids': ['case-1']}
    prepared.write_text(json.dumps(receipt), encoding='utf-8')
    delivery = root/'learning/receipts/chapters/0001/mvp.json'
    guard.record_reference_delivery(root, 'mvp', '0001', 'draft-1', {})
    assert not delivery.exists()
    written = {'node_states': {'agent_sw': {'status': 'completed'}}}
    guard.record_reference_delivery(root, 'mvp', '0001', 'draft-2', written)
    assert not delivery.exists()
    guard.record_reference_delivery(root, 'mvp', '0001', 'draft-1', written)
    assert json.loads(delivery.read_text(encoding='utf-8'))['candidate_ids'] == ['case-1']


@pytest.mark.parametrize('stage', ('character', 'story-plan', 'outline'))
def test_scoped_reference_is_generated_without_overwriting_frozen_input(tmp_path, stage):
    from src.workflow.definition import WorkflowDef

    graph = json.loads((PLUGIN/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8'))
    assert not WorkflowDef.from_dict(graph).validate()
    variables = {row['key']: row for row in graph['variables']}
    assert variables['learning_context']['source_type'] == 'input'
    scoped = variables['scoped_learning_context']
    assert scoped['source_type'] == 'output' and scoped['default'] == '{{learning_context}}'
    path = PLUGIN/'resources/script-library/xs2/production_guard/production_guard.py'
    spec = importlib.util.spec_from_file_location('reference_scoping_guard', path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    values = {'learning_context': 'learning/active_context.md'}
    assert guard._input_parameters(tmp_path, graph, values) == guard._input_parameters(tmp_path, graph, {
        **values, 'scoped_learning_context': f'learning/context/{stage}.md'})


def test_fragment_review_context_is_generated_by_its_task():
    graph = json.loads((PLUGIN/"resources/workflows/polish/definition.json").read_text(encoding="utf-8"))
    variables = {v["key"]: v for v in graph["variables"]}
    for key in ("fragment_review_input", "fragment_review_report_path", "fragment_review_binding", "fragment_review_binding_sha"):
        assert variables[key]["source_type"] == "output"
        assert variables[key]["source_node_id"] == "script_fragment_review_context"


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
        if stage in {'build', 'character', 'story-plan'} or n['agent_type'] in {
            'novel-single-writer', 'novel-multi-scene-writer',
        }:
            assert '【数字的叙事作用】' not in n['first_message']


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
    assert 'anyOf' not in schema and schema['properties']['protocol']['const']=='local-review-v3'
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
