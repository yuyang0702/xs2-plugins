import asyncio
import json
from pathlib import Path

import pytest

from test_multi_scene import module
from test_scene_allocation_p1 import plan,cli
from test_continuity_contract import contract,SOURCES


def set_planning_sources(m, directory):
    (directory / 'planning-sources.md').write_text(SOURCES, encoding='utf-8')
    (directory / 'planning-sources-model.md').write_text(
        m.continuity_policy.planning_quote_view(SOURCES), encoding='utf-8')


def test_next_writer_message_contains_only_the_adjacent_accepted_ending(tmp_path):
    from src.workflow.variable_resolution import resolve_placeholders

    m = module()
    allocation = {'scenes': [{'slot': 1, 'scene_id': 1}, {'slot': 2, 'scene_id': 2},
                             {'slot': 6, 'scene_id': 3}]}
    directory = tmp_path / 'cache/multi/task-handoff'
    directory.mkdir(parents=True)
    m.save_json(directory / 'allocation.json', allocation)
    allocation_sha = m.allocation_policy.digest(directory / 'allocation.json')
    for slot, body in [(1, '巷口风大。'), (2, '箱子里的东西。' * 300 + '\n\n她把收据反扣在桌上。')]:
        raw = directory / f'scene-{slot}.txt'
        raw.write_text(body, encoding='utf-8')
        m.save_json(directory / f'validated-{slot}.json',
                    {'allocation_sha256': allocation_sha, 'source_sha256': m.allocation_policy.digest(raw),
                     'body': body})
    (directory / 'scene-6.txt').write_text('三天后她又来了。', encoding='utf-8')
    writer_files = m.write_handoffs(directory, {'continuity': {}}, allocation, writer_inputs=True)
    assert set(writer_files) == {6}
    definition_path = Path(__file__).resolve().parents[1] / 'resources/workflows/mvp/definition.json'
    definition = json.loads(definition_path.read_text(encoding='utf-8'))
    variables = definition['variables']
    values = {item['key']: '' for item in variables}
    values['multi_previous_6'] = (directory / writer_files[6]).relative_to(tmp_path).as_posix()
    message = next(node['first_message'] for node in definition['nodes'] if node['id'] == 'agent_si')
    rendered = asyncio.run(resolve_placeholders(message, values, variables, str(tmp_path)))
    assert '她把收据反扣在桌上。' in rendered
    assert '箱子里的东西。' not in rendered
    assert '巷口风大。' not in rendered
    assert '三天后她又来了。' not in rendered


def test_planning_sources_include_the_confirmed_prior_story_context(tmp_path):
    path=tmp_path/'cache/story-support/context.md';path.parent.mkdir(parents=True);path.write_text('上章已经付清押金，不得重复支付。',encoding='utf-8')
    assert '上章已经付清押金，不得重复支付。' in module().planning_sources(tmp_path,'0002')


def test_every_writer_receives_the_same_contract_and_only_preceding_accepted_prose(tmp_path,monkeypatch,capsys):
    m=module();cli(m,tmp_path,monkeypatch,capsys,'prepare');d=tmp_path/'cache/multi/task-p1'
    p=plan(2);p['continuity']=contract();m.save_json(d/'plan.json',p)
    set_planning_sources(m, d)
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
    m.save_json(d/'plan.json',p);set_planning_sources(m, d)
    output=cli(m,tmp_path,monkeypatch,capsys,'plan')
    assert 'target="agent_nw"' in output
    assert not (d/'allocation.json').exists()


def test_changed_planning_sources_cannot_be_rebound_to_existing_scenes(tmp_path,monkeypatch,capsys):
    m=module();cli(m,tmp_path,monkeypatch,capsys,'prepare');d=tmp_path/'cache/multi/task-p1'
    p=plan(2);p['continuity']=contract();m.save_json(d/'plan.json',p)
    set_planning_sources(m, d);cli(m,tmp_path,monkeypatch,capsys,'plan')
    (d/'planning-sources.md').write_text(SOURCES+'新依据',encoding='utf-8')
    with pytest.raises(ValueError,match='变化|新任务'):
        cli(m,tmp_path,monkeypatch,capsys,'check-plan')
