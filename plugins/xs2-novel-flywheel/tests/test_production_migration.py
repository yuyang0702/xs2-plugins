import importlib.util
import json
import zipfile
import copy
from test_book_contract import PLUGIN


def module():
    s=importlib.util.spec_from_file_location('migration_test',PLUGIN/'tools/migrate_production_p0.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_message_delta_preserves_custom_tail_and_user_prefix():
    m=module();old='原有开头。正文{{canonical}}。保留原话。';new='新增规则。原有开头。正文{{view}}。保留原话。'
    actual='我的说明。'+old+'作者补充。'
    result=m.merge_message(old,new,actual)
    assert result=='新增规则。我的说明。原有开头。正文{{view}}。保留原话。作者补充。'


def test_field_merge_preserves_user_model_params_variables_and_task_free_graph():
    before={'nodes':[{'id':'a','node_type':'agent','first_message':'旧输入','model_override':'default','position':{'x':1},'node_params':{}}],
        'variables':[{'key':'x','default':'default'}],'edges':[{'source':'__start__','target':'a'},{'source':'a','target':'__end__'}]}
    after=copy.deepcopy(before);after['nodes'][0]['first_message']='新规则。旧输入'
    for key in ('script_production_start','script_production_finish','script_budget_a'):
        after['nodes'].append({'id':key,'node_type':'script','node_params':{}})
    actual=copy.deepcopy(before);actual['nodes'][0].update(model_override='author:model',model_params_override={'temperature':.9},position={'x':42})
    actual['nodes'][0]['first_message']+='作者自己的说明。';actual['variables'][0]['default']='author-value'
    result=module().merge_definition(before,after,actual)
    assert result['nodes'][0]['model_override']=='author:model' and result['nodes'][0]['position']=={'x':42}
    assert result['nodes'][0]['model_params_override']=={'temperature':.9}
    assert result['variables']==actual['variables']
    assert result['nodes'][0]['first_message'].endswith('作者自己的说明。')
    assert {'source':'script_budget_a','target':'a'} in result['edges']


def test_generated_variable_metadata_migrates_without_overwriting_custom_default():
    before={'nodes':[],'variables':[{'key':'feedback','source_type':'input','type':'file','default':''}],'edges':[]}
    after=copy.deepcopy(before);after['variables'][0]['source_type']='output'
    current=copy.deepcopy(before);current['variables'][0]['default']='author-custom-path.md'
    merged=module().merge_definition(before,after,current)
    assert merged['variables'][0]['source_type']=='output' and merged['variables'][0]['default']=='author-custom-path.md'


def test_reader_metadata_migration_retains_saved_node_models_on_real_workflow():
    after=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8-sig'))
    before=copy.deepcopy(after)
    for v in before['variables']:
        if v['key'] in ('reader_context_feedback','reader_blind_feedback'):v['source_type']='input'
    current=copy.deepcopy(before)
    for v in current['variables']:
        if v['key'] in ('reader_context_feedback','reader_blind_feedback'):v.pop('source_type')  # Host omits default input metadata.
    target=next(n for n in current['nodes'] if n['node_type']=='agent')
    target['model_override']='saved:model'
    merged=module().merge_definition(before,after,current)
    assert next(n for n in merged['nodes'] if n['id']==target['id'])['model_override']=='saved:model'
    assert next(v for v in merged['variables'] if v['key']=='reader_blind_feedback')['source_type']=='output'
