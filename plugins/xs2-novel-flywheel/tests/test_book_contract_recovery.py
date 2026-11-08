import json
from pathlib import Path

import pytest

from test_book_contract import helper,put,PLUGIN


@pytest.mark.parametrize('consumer',['scene','guard','reader'])
def test_downstream_prepare_cannot_replace_an_existing_task_contract(tmp_path,monkeypatch,capsys,consumer):
    task={'scene':'task-p1','guard':'task-guard','reader':'book-review'}[consumer]
    put(tmp_path,'meta/style_profile.md','旧文风')
    helper().freeze(tmp_path,task)
    put(tmp_path,'meta/style_profile.md','另一文风')
    with pytest.raises(ValueError,match='变化|新建|新任务'):
        if consumer=='scene':
            from test_multi_scene import module
            from test_scene_allocation_p1 import cli
            cli(module(),tmp_path,monkeypatch,capsys,'prepare')
        elif consumer=='guard':
            from test_draft_guard import prepared
            prepared(tmp_path,monkeypatch,capsys)
        else:
            from test_reader_review_p0 import review
            put(tmp_path,'story/0001/chapter.md','正文。')
            review().prepare(tmp_path,'0001',task)


def test_changed_scene_at_assembly_keeps_declared_variable_narration(tmp_path,monkeypatch,capsys):
    from test_multi_scene import module
    from test_scene_allocation_p1 import prepared,cli
    put(tmp_path,'meta/narrative_contract.json',{'schema':1,'narrator_scope':'variable','allow_repeated_passages':True})
    m=module();directory,_,_=prepared(m,tmp_path,monkeypatch,capsys,count=1)
    old='她沿着海岸走。'*100
    (directory/'scene-6.txt').write_text(old,encoding='utf-8');cli(m,tmp_path,monkeypatch,capsys,'scene','--scene','6')
    new='我沿着海岸走。'*100
    (directory/'scene-6.txt').write_text(new,encoding='utf-8')
    assert '[scene_pov]' not in cli(m,tmp_path,monkeypatch,capsys,'assemble')
    assert m.read_json(tmp_path/'cache/si/chapter.json')['body']==new


def test_focused_length_writer_receives_contract_and_rejects_scope_drift(tmp_path):
    from test_fragment_length import setup
    from test_length_quality import quality
    state,_,_=setup(tmp_path)
    state['values'].update(narrator_scope='omniscient',style_intent='独有文风标记：容许技术说明与内心回环')
    put(tmp_path,'.novel-project.json',state)
    q=quality();out=q.prepare_execution(tmp_path,'0001','130-160','length_only')
    text=(tmp_path/out['length_execution_context']).read_text(encoding='utf-8')
    assert 'omniscient' in text and '独有文风标记' in text
    state['values']['narrator_scope']='limited';put(tmp_path,'.novel-project.json',state)
    with pytest.raises(ValueError,match='变化|契约|文风'):
        q.confirm_execution(tmp_path,'0001',out['length_expected_body_sha'],out['length_commit_guard'],out['length_commit_guard_sha'])


def test_blind_and_context_reader_schemas_accept_current_body_references():
    from jsonschema import Draft7Validator
    d=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8'))
    count=0
    def walk(value):
        nonlocal count
        if isinstance(value,dict):
            if 'excerpts' in value.get('properties',{}):
                schema=value['properties']['excerpts'];Draft7Validator(schema).validate([{'ref_id':'c0001'}]);count+=1
            for v in value.values():walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    for node in d['nodes']:
        if node['node_type']=='agent':walk(node['node_params']['json_output_schema'])
    assert count>=3
