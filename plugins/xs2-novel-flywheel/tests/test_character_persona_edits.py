"""Bounded persona changes reach production renderers without gaining fact authority."""
import copy
import json
from pathlib import Path

import pytest

from test_character_semantic_review import gate, write, person, apply


DEEP = {
    'core_desire': {'surface_goal': '必须压价来修好屋顶', 'deep_desire': '只能逼人留下'},
    'deep_fear': {'fear': '失信便只能隐瞒', 'source': '曾答应归还蓝伞'},
    'bottom_line': {'condition': '受人帮助', 'reaction_when_crossed': '每次先否认再解释', 'source': '重视承诺'},
    'key_trauma': {'wound': '未确认', 'trigger': '未确认', 'stress_response': '必须沉默', 'impact_on_behavior': '只能拒绝'},
    'internal_contradiction': {'conflicting_elements': '只能靠施压争取信任', 'possible_direction': '先威胁再认错', 'source': '想独立也希望人帮忙'},
    'arc_potential': {'growth_direction': '必须先争吵', 'corruption_direction': '只能撒谎', 'key_choice': '每次逼问'},
    'secret': {'content': '未确认', 'who_knows': [], 'exposure_consequence': '只能逃避'},
}


def setup_persona(gate, root, mode='compact', legacy=False):
    world = root / 'world.md'
    world.write_text('林叶借给顾石一把蓝伞，尚未归还。', encoding='utf-8')
    variables = gate.preflight(root, '结尾归还蓝伞', '保留独立与信任的拉扯，允许协商', '现实世界', world, 'persona-task')
    batch, draft = Path(variables['card_batch_dir']), Path(variables['card_draft_dir'])
    record = person()
    record.update(facts=['林叶借给顾石一把蓝伞，尚未归还。'], personality='想独立也珍惜信任', plot_constraints=['结尾归还蓝伞'])
    record['relationships'][0]['history'] = '曾共同修伞'
    record['knowledge'] = ['只知道借伞']
    if mode == 'compact':
        write(draft / 'cache/short/characters.json', {'characters': [record]})
    else:
        record['relationships'].append({'target': '顾石', 'nature': '曾合作修伞',
                                       'meaning_to_character': '只能靠施压留住熟客',
                                       'hidden_tension': '必须先指责对方', 'default_attitude': '先压价再让步'})
        record['world_position'] = {'social_role': '修伞师', 'stance_on_core_conflict': '只能沉默服从'}
        record['world_anchor'] = {'shaped_by_rule': '手艺靠口碑', 'may_challenge_rule': '必须当面嘲讽'}
        voice = record.pop('voice')
        write(draft / 'cache/character/skeleton.json', {'characters': [record]})
        deep = {**copy.deepcopy(record), **copy.deepcopy(DEEP)}
        if legacy:
            for key in ('card_schema', 'facts', 'personality', 'plot_constraints'):
                deep.pop(key)
        write(draft / 'cache/character/林叶_deep.json', deep)
        write(draft / 'cache/character/voice.json', {'characters': [{'name': '林叶', 'voice_positioning': voice['baseline']}]})
    prepared = gate.prepare(batch)
    request = json.loads(Path(prepared['card_review_input_file']).read_text(encoding='utf-8'))
    original = request['characters'][0]
    review = {'schema': 'xs2.character.semantic-review.v2', 'task_id': request['task_id'],
              'source_sha256': request['source_sha256'], 'status': 'accepted', 'blocking_issues': [],
              'characters': [{'name': '林叶', **{f: copy.deepcopy(record[f]) for f in ('facts', 'personality', 'plot_constraints')},
                              'voice': copy.deepcopy(original['voice']), 'changes': [], 'persona_edits': []}]}
    return variables, prepared, request, review


def edit(entry, after='希望保住独立和信任，可能协商，也可能拒绝'):
    return {'record_path': entry['record_path'], 'field_path': entry['field_path'],
            'before': entry['original'], 'after': after, 'reason': '保留目标与顾虑，去掉必经表演步骤',
            'source_id': 'draft-persona.林叶', 'evidence_quote': entry['original']}


@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_allowed_persona_leaves_reach_rendered_profile_without_mutating_raw(gate, tmp_path, mode):
    variables, prepared, request, review = setup_persona(gate, tmp_path, mode)
    assert request['schema'] == 'xs2.character.semantic-review-input.v2'
    original = request['characters'][0]
    entries = original['editable_persona']
    assert {tuple(e['field_path']) for e in entries} >= {('want',), ('fear',), ('contradiction',), ('relationships', 0, 'dynamic')}
    if mode == 'full':
        assert {tuple(e['field_path']) for e in entries} >= {(k, leaf) for k, value in DEEP.items() for leaf in value if leaf not in {'source', 'condition', 'wound', 'trigger', 'content', 'who_knows'}}
    assert 'draft-persona.林叶' in request['sources']
    locked = json.loads(request['sources']['locked.林叶'])
    assert locked[0]['record']['want'] is None
    assert locked[0]['record']['relationships'][0] == {'with': '顾石', 'dynamic': None, 'history': '曾共同修伞'}
    assert locked[0]['record']['knowledge'] == ['只知道借伞']
    review['characters'][0]['persona_edits'] = [edit(e, '可协商的目标' + str(i)) for i, e in enumerate(entries)]
    raw = {p: p.read_bytes() for p in Path(variables['card_draft_dir']).rglob('*') if p.is_file()}
    apply(gate, variables, prepared, review)
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    assert '可协商的目标' in profile
    for entry in review['characters'][0]['persona_edits']:
        path = tmp_path / entry['record_path']
        data = json.loads(path.read_text(encoding='utf-8'))
        value = next(p for p in data['characters'] if p['name'] == '林叶') if 'characters' in data else data
        for key in entry['field_path']:
            value = value[key]
        assert value == entry['after']
    assert all(p.read_bytes() == before for p, before in raw.items())
    assert '结尾归还蓝伞' in profile


@pytest.mark.parametrize('path', [['name'], ['role'], ['aliases'], ['knowledge', 0], ['relationships', 0, 'with'],
                                 ['relationships', 0, 'history'], ['deep_fear', 'source'], ['bottom_line', 'condition'],
                                 ['key_trauma', 'wound'], ['secret', 'content'], ['secret', 'who_knows', 0], ['unknown'],
                                 ['relationships', True, 'dynamic'], ['relationships', -1, 'dynamic']])
def test_identity_history_knowledge_unknown_and_noncanonical_paths_rejected(gate, tmp_path, path):
    variables, prepared, request, review = setup_persona(gate, tmp_path, 'full')
    item = edit(request['characters'][0]['editable_persona'][0])
    item['field_path'] = path
    review['characters'][0]['persona_edits'] = [item]
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert not (tmp_path / 'meta/character_profiles.md').exists()


@pytest.mark.parametrize('fault', ['before', 'missing_before', 'quote', 'missing_quote', 'source', 'duplicate', 'record_path', 'empty', 'heading', 'v1'])
def test_persona_binding_and_evidence_cannot_be_bypassed(gate, tmp_path, fault):
    variables, prepared, request, review = setup_persona(gate, tmp_path)
    item = edit(request['characters'][0]['editable_persona'][0])
    edits = [item]
    if fault == 'before': item['before'] = '伪造原文'
    elif fault == 'missing_before': item.pop('before')
    elif fault == 'quote': item['evidence_quote'] = '来源没有这句话'
    elif fault == 'missing_quote': item.pop('evidence_quote')
    elif fault == 'source': item['source_id'] = 'draft-persona.别人'
    elif fault == 'duplicate': edits.append(copy.deepcopy(item))
    elif fault == 'record_path': item['record_path'] = 'cache/character/别人_deep.json'
    elif fault == 'empty': item['after'] = ' '
    elif fault == 'heading': item['after'] = '# injected'
    elif fault == 'v1': review['schema'] = 'xs2.character.semantic-review.v1'
    review['characters'][0]['persona_edits'] = edits
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)


@pytest.mark.parametrize('field', ['facts', 'plot_constraints'])
def test_draft_persona_is_not_authority_for_facts_or_author_outcomes(gate, tmp_path, field):
    variables, prepared, request, review = setup_persona(gate, tmp_path)
    reviewed = review['characters'][0]
    reviewed[field] = ['编造事件']
    reviewed['changes'] = [{'field': field, 'reason': '错误地把动机当事实', 'source_id': 'draft-persona.林叶',
                            'evidence_quote': request['characters'][0]['editable_persona'][0]['original']}]
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)


def test_legacy_deep_is_wholly_locked_even_under_v2_skeleton(gate, tmp_path):
    variables, prepared, request, review = setup_persona(gate, tmp_path, 'full', legacy=True)
    entries = request['characters'][0]['editable_persona']
    assert all(not e['record_path'].endswith('_deep.json') for e in entries)
    original = (Path(variables['card_draft_dir']) / 'cache/character/林叶_deep.json').read_bytes()
    apply(gate, variables, prepared, review)
    assert json.loads((tmp_path / 'cache/character/林叶_deep.json').read_text(encoding='utf-8')) == json.loads(original)


def test_personality_and_voice_can_preserve_motives_from_draft_persona(gate, tmp_path):
    variables, prepared, request, review = setup_persona(gate, tmp_path)
    reviewed = review['characters'][0]
    reviewed['personality'] = '珍惜独立也希望得到帮助'
    reviewed['voice']['baseline'] = '愿意讨论实际条件'
    reviewed['changes'] = [{'field': f, 'reason': '保留已经设计的目标与矛盾', 'source_id': 'draft-persona.林叶',
                            'evidence_quote': '想独立也希望人帮忙'} for f in ('personality', 'voice')]
    assert apply(gate, variables, prepared, review)['completed']


def test_full_relationship_and_world_possibilities_are_reviewable_but_targets_history_stay_locked(gate, tmp_path):
    variables, prepared, request, review = setup_persona(gate, tmp_path, 'full')
    skeleton = 'cache/character/skeleton.json'
    entries = {tuple(e['field_path']): e for e in request['characters'][0]['editable_persona'] if e['record_path'] == skeleton}
    paths = [('relationships', 1, key) for key in ('meaning_to_character', 'hidden_tension', 'default_attitude')]
    paths += [('world_position', 'stance_on_core_conflict'), ('world_anchor', 'may_challenge_rule')]
    assert all(path in entries for path in paths)
    review['characters'][0]['persona_edits'] = [edit(entries[path], '有分歧也重视合作，表达随条件变化') for path in paths]
    apply(gate, variables, prepared, review)
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    assert '有分歧也重视合作，表达随条件变化' in profile
    published = json.loads((tmp_path / skeleton).read_text(encoding='utf-8'))['characters'][0]
    assert published['relationships'][1]['target'] == '顾石'
    assert published['relationships'][1]['nature'] == '曾合作修伞'
    assert published['world_position']['social_role'] == '修伞师'
    assert published['world_anchor']['shaped_by_rule'] == '手艺靠口碑'
