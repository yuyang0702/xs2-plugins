import copy
import json

import pytest
from jsonschema import Draft202012Validator

from test_short_preparation import PLUGIN, cast, helper


def test_compact_character_schema_accepts_text_list_boundaries():
    doc=json.loads((PLUGIN/'resources/workflows/character/definition.json').read_text(encoding='utf-8'))
    node=next(n for n in doc['nodes'] if n['id']=='agent_short_character')
    data=cast()
    for person in data['characters']:
        person['voice']['avoid']=[]
        person['boundary']=['不替别人作证','不接受未确认的条件']
    Draft202012Validator(node['node_params']['json_output_schema']).validate(data)


def test_boundary_list_renders_all_entries_without_mutating_source(tmp_path):
    data=cast();data['characters'][0]['boundary']=['不替别人作证','可求助但不替人认账']
    before=copy.deepcopy(data)
    helper().render_characters(tmp_path,data)
    text=(tmp_path/'meta/character_profiles.md').read_text(encoding='utf-8')
    assert all(item in text for item in data['characters'][0]['boundary'])
    assert "['不替别人作证'" not in text
    assert data==before


@pytest.mark.parametrize('bad',[[],[1],[''],[{'rule':'不能猜测'}]])
def test_invalid_boundary_lists_do_not_publish_archives(tmp_path,bad):
    data=cast();data['characters'][0]['boundary']=bad
    with pytest.raises(ValueError):helper().render_characters(tmp_path,data)
    assert not (tmp_path/'meta/character_profiles.md').exists()
