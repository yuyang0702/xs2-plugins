import copy
import pytest
from test_book_writer_model import MODEL,definition
from test_length_quality import policy


def test_writer_params_only_follow_selected_writer_nodes_and_are_deep_copied():
    p=policy();doc=definition();state={'writerModel':MODEL,'writerModelParams':{'thinking_enabled':True,'reasoning_effort':'high','nested':{'value':[1]}}}
    original=copy.deepcopy((state,doc))
    assert set(p.model_params_overrides(state,doc,'mvp'))=={'agent_sw'}
    actual=p.model_params_overrides(state,doc,'polish')
    assert set(actual)=={'agent_pl','agent_pp'}
    actual['agent_pl']['nested']['value'].append(2)
    assert actual['agent_pp']['nested']['value']==[1] and (state,doc)==original
    for stage in ['build','character','outline','reader-sim','post-hoc']:
        assert p.model_params_overrides(state,doc,stage) is None


def test_writer_params_skip_dynamic_and_legacy_repair_model_replacements():
    p=policy();doc=definition();state={'writerModel':MODEL,'writerModelParams':{'thinking_enabled':True}}
    doc['nodes'][2]['var_bindings']={'model_override':{'var_key':'selected'}}
    assert p.model_params_overrides(state,doc,'polish')=={'agent_pp':{'thinking_enabled':True}}
    state.update(repairModel='other:model',readerRepairCount=1)
    assert p.model_params_overrides(state,doc,'polish') is None
    state.pop('writerModel')
    assert p.model_params_overrides(state,doc,'mvp') is None


@pytest.mark.parametrize('params',[None,{}])
def test_empty_writer_params_are_backward_compatible(params):
    assert policy().model_params_overrides({'writerModel':MODEL,'writerModelParams':params},definition(),'mvp') is None


@pytest.mark.parametrize('params',[[],False,'high',1])
def test_invalid_writer_params_are_rejected(params):
    with pytest.raises(ValueError):policy().model_params_overrides({'writerModel':MODEL,'writerModelParams':params},definition(),'mvp')
