import json

import pytest

from test_multi_scene import module
from test_scene_allocation_p1 import plan,cli
from test_continuity_contract import contract,SOURCES


def test_planning_sources_include_the_confirmed_prior_story_context(tmp_path):
    path=tmp_path/'cache/story-support/context.md';path.parent.mkdir(parents=True);path.write_text('上章已经付清押金，不得重复支付。',encoding='utf-8')
    assert '上章已经付清押金，不得重复支付。' in module().planning_sources(tmp_path,'0002')


def test_every_writer_receives_the_same_contract_and_only_preceding_accepted_prose(tmp_path,monkeypatch,capsys):
    m=module();cli(m,tmp_path,monkeypatch,capsys,'prepare');d=tmp_path/'cache/multi/task-p1'
    p=plan(2);p['continuity']=contract();m.save_json(d/'plan.json',p)
    (d/'planning-sources.md').write_text(SOURCES,encoding='utf-8')
    cli(m,tmp_path,monkeypatch,capsys,'plan')
    assert m.read_json(d/'brief-1.json')['continuity']==m.read_json(d/'brief-6.json')['continuity']==contract()
    for slot,body in [(1,'已收款尚未交灯'),(6,'后场不能倒灌进前场')]:
        (d/f'scene-{slot}.txt').write_text(body,encoding='utf-8')
        cli(m,tmp_path,monkeypatch,capsys,'scene','--scene',str(slot))
    cli(m,tmp_path,monkeypatch,capsys,'check-plan')
    first=m.read_json(d/'handoff-1.json');last=m.read_json(d/'handoff-6.json')
    assert first['previous_scenes']==[]
    assert last['previous_scenes']==[{'scene_id':1,'body':'已收款尚未交灯'}]
    assert last['continuity']==contract()
    (d/'scene-1.txt').write_text('已变更未校验的前场',encoding='utf-8')
    with pytest.raises(ValueError,match='前场|变化|校验'):
        cli(m,tmp_path,monkeypatch,capsys,'check-plan')


def test_current_plan_rejects_a_ledger_not_supported_by_frozen_book_sources(tmp_path,monkeypatch,capsys):
    m=module();cli(m,tmp_path,monkeypatch,capsys,'prepare');d=tmp_path/'cache/multi/task-p1'
    p=plan(2);p['continuity']=contract();p['continuity']['transfers'][1]['amount']=1020
    m.save_json(d/'plan.json',p);(d/'planning-sources.md').write_text(SOURCES,encoding='utf-8')
    output=cli(m,tmp_path,monkeypatch,capsys,'plan')
    assert 'target="agent_nw"' in output
    assert not (d/'allocation.json').exists()


def test_changed_planning_sources_cannot_be_rebound_to_existing_scenes(tmp_path,monkeypatch,capsys):
    m=module();cli(m,tmp_path,monkeypatch,capsys,'prepare');d=tmp_path/'cache/multi/task-p1'
    p=plan(2);p['continuity']=contract();m.save_json(d/'plan.json',p)
    (d/'planning-sources.md').write_text(SOURCES,encoding='utf-8');cli(m,tmp_path,monkeypatch,capsys,'plan')
    (d/'planning-sources.md').write_text(SOURCES+'新依据',encoding='utf-8')
    with pytest.raises(ValueError,match='变化|新任务'):
        cli(m,tmp_path,monkeypatch,capsys,'check-plan')
