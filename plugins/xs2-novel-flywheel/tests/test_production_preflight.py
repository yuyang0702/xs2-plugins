import importlib.util
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_book_contract import PLUGIN


def module():
    path=PLUGIN/'resources/script-library/xs2/production_guard/production_guard.py'
    spec=importlib.util.spec_from_file_location('production_preflight_test',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_shared_resource_locator_matches_prepared_layout(tmp_path):
    m=module();source=PLUGIN/'resources/script-library/xs2'
    prepared=tmp_path/'runtime-resources/xs2-novel-flywheel'
    shutil.copytree(source,prepared/'script-libraries/0/xs2-novel-flywheel-xs2')
    for name in ('prompts','agents'):
        p=prepared/f'json/{name}/0.json';p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(PLUGIN/f'resources/{name}.json',p)
    p=prepared/'workflows/0/xs2-novel-flywheel-polish/definition.json';p.parent.mkdir(parents=True)
    shutil.copy2(PLUGIN/'resources/workflows/polish/definition.json',p)
    keys=['prompts.json','agents.json','workflows/polish/definition.json']
    assert m.resource_hashes(source,keys)==m.resource_hashes(prepared/'script-libraries/0/xs2-novel-flywheel-xs2',keys)
    p.unlink()
    with pytest.raises(FileNotFoundError,match='RESOURCE'):m.resource_hashes(prepared/'script-libraries/0/xs2-novel-flywheel-xs2',keys)


def test_launch_intent_has_one_owner_and_fences_old_epoch(tmp_path):
    m=module()
    def take(owner):
        try:return m.claim(tmp_path,'0001/polish',owner,{'source':'same'})
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(take,['task-a','task-b']))
    assert sum(r is not None for r in results)==1
    lease=next(r for r in results if r)
    assert m.claim(tmp_path,'0001/polish',lease['owner'],{'source':'same'})==lease
    assert m.release(tmp_path,lease)
    newer=m.claim(tmp_path,'0001/polish','task-new',{'source':'same'})
    assert newer['epoch']>lease['epoch']
    with pytest.raises(ValueError,match='LEASE'):m.verify_claim(tmp_path,lease)
    assert not m.release(tmp_path,lease)


def test_retry_budget_is_logical_and_classifies_deterministic_error(tmp_path):
    m=module()
    assert m.classify('RESOURCE: missing installed prompts')=='installation'
    assert m.classify('引用原句不在当前候选')=='evidence'
    assert m.classify('readtimeout')=='transport'
    assert m.classify('这段叙述损害人物语气')=='content'
    m.retry(tmp_path,'same-step','agent_a','引用原句不在当前候选')
    with pytest.raises(ValueError,match='RETRY_STOP'):m.retry(tmp_path,'same-step','agent_b','引用原句不在当前候选')
    assert len(m.retry_history(tmp_path,'same-step'))==2


def test_budget_keeps_complete_input_and_marks_unknowns():
    m=module();parts={'system':'约定','body':'原文。'*100,'schema':json.dumps({'x':1}),'tools':'工具'}
    before=dict(parts);result=m.budget(parts,output_reserve=2048)
    assert parts==before and set(result['components'])==set(parts)
    assert result['provider_usage'] is None and result['context_limit'] is None
    assert result['utf8_token_upper_bound']>=len(parts['body'])
    with pytest.raises(ValueError,match='CONTEXT_BUDGET'):m.budget(parts,output_reserve=2048,context_limit=50)
    segments=m.coverage(parts['body'],max_chars=49)
    assert ''.join(r['text'] for r in segments)==parts['body']
    assert segments[-1]['end']==len(parts['body'])


def test_snapshot_definition_rejects_missing_placeholder_before_paid_call():
    m=module();d={'nodes':[{'id':'writer','node_type':'agent','first_message':'{{body}}'}], 'variables':[]}
    with pytest.raises(ValueError,match='PREFLIGHT'):m.check_definition(d,{})
    d['variables']=[{'key':'body'}]
    assert m.check_definition(d,{'body':'完整原文'})['protocol']=='production-preflight-v1'


def test_all_source_workflows_have_valid_script_and_variable_references():
    m=module()
    for path in sorted((PLUGIN/'resources/workflows').glob('*/definition.json')):
        definition=json.loads(path.read_text(encoding='utf-8-sig'))
        assert m.check_definition(definition,{})['protocol']=='production-preflight-v1', path


def test_character_review_outputs_keep_publication_inputs_stable(tmp_path):
    m = module()
    path = PLUGIN/'resources/workflows/character/definition.json'
    definition = json.loads(path.read_text(encoding='utf-8-sig'))
    review = m.load('preflight_character_review', PLUGIN/'resources/script-library/xs2/character_review/character_review.py')
    batch = tmp_path/'cache/character-review/task-synthetic'
    generated = review._variables(batch)
    generated.update(card_review_binding_sha='a'*64, character_names='["陈满"]', name='陈满')
    source = {'premise': '试营业', 'world_foundation': 'meta/world_foundation.md'}
    frozen = m._input_parameters(tmp_path, definition, source)
    assert m._input_parameters(tmp_path, definition, {**source, **generated}) == frozen
    changed = m._input_parameters(tmp_path, definition, {**source, 'premise':'改动后的设定'})
    assert changed != frozen


@pytest.mark.parametrize('stage', ['mvp', 'polish', 'reader-sim', 'outline', 'story-plan'])
def test_generated_context_and_director_variables_do_not_change_frozen_inputs(tmp_path, stage):
    m = module()
    path = PLUGIN/'resources/workflows'/stage/'definition.json'
    definition = json.loads(path.read_text(encoding='utf-8-sig'))
    generated = {var['key']: 'cache/generated.md' for var in definition['variables']
                 if var['key'].startswith(('pp_', 'prose_policy_')) or var['key'] in {
                     'story_support_context', 'od_intent', 'se_intent'}}
    assert generated
    assert m._input_parameters(tmp_path, definition, generated) == m._input_parameters(tmp_path, definition, {})


def test_definition_checks_system_prompt_script_reference_and_actual_native_override():
    m=module()
    d={'variables':[], 'nodes':[{'id':'role','node_type':'agent','system_prompt_template':'{{undeclared}}'}]}
    with pytest.raises(ValueError,match='undeclared'):m.check_definition(d,{})
    d={'variables':[], 'nodes':[{'id':'script','node_type':'script','node_params':{
        'script_source':'library','script_group':'xs2','script_name':'absent','script_type':'python'}}]}
    with pytest.raises(ValueError,match='missing script'):m.check_definition(d,{})
    d={'variables':[], 'nodes':[{'id':'role','node_type':'agent','model_override':'arbitrary-route:model',
        'node_params':{'_model_params_override':{'thinking':{'type':'adaptive'}}}}]}
    # A provider instance name is not evidence of supported parameters.
    assert m.check_definition(d,{})['model_parameter_compatibility']['role']['status']=='unknown'
    with pytest.raises(ValueError,match='incompatible thinking'):
        m.check_definition(d,{}, {'arbitrary-route:model':{'supported_thinking_types':['enabled','disabled']}})


def test_prepared_profile_covers_sibling_groups_and_non_python_resources(tmp_path):
    m=module();source=PLUGIN/'resources/script-library/xs2'
    prepared=tmp_path/'runtime-resources/xs2-novel-flywheel'
    for group in (PLUGIN/'resources/script-library').iterdir():
        if group.is_dir():shutil.copytree(group,prepared/'script-libraries/0'/('xs2-novel-flywheel-'+group.name))
    runtime=prepared/'script-libraries/0/xs2-novel-flywheel-xs2'
    assert m.profile(source)==m.profile(runtime)
    assert any(k.startswith('script-library/nvl/') for k in m.profile(runtime))
    assert any(k.endswith('.md') for k in m.profile(runtime))
    script=m.resource(runtime,'script-library/nvl/local_archive/local_archive.py')
    assert script.is_file()
    script.write_text('# changed',encoding='utf8')
    assert m.profile(source)!=m.profile(runtime)
