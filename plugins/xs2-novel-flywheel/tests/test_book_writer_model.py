import copy
import json

from test_length_quality import policy, quality, write


MODEL = 'anthropic:claude-opus-5-5'


def definition():
    return {'nodes': [{'id': key, 'node_type': 'agent', 'agent_type': 'existing', 'node_params': {}}
                      for key in ['agent_sw', 'agent_id', 'agent_pl', 'agent_pp', 'agent_sc', 'agent_reader', 'agent_fragment_review']]}


def test_book_writer_model_only_selects_body_agents_without_mutating_templates():
    doc = definition()
    before = copy.deepcopy(doc)
    p = policy()
    assert p.model_overrides({'writerModel': MODEL}, doc, 'mvp') == {'agent_sw': MODEL}
    assert p.model_overrides({'writerModel': MODEL}, doc, 'polish') == {'agent_pl': MODEL, 'agent_pp': MODEL}
    for stage in ['character', 'outline', 'reader-sim', 'post-hoc', 'export']:
        assert p.model_overrides({'writerModel': MODEL}, doc, stage) is None
    assert doc == before
    assert p.model_overrides({}, doc, 'polish') is None


def test_explicit_dynamic_model_bindings_keep_precedence_and_legacy_repair_works():
    p = policy()
    doc = definition()
    doc['nodes'][2]['var_bindings'] = {'model_override': {'var_key': 'selected'}}
    assert p.model_overrides({'writerModel': MODEL}, doc, 'polish') == {'agent_pp': MODEL}
    old = p.model_overrides({'repairModel': MODEL, 'readerRepairCount': 1}, doc, 'reader-sim')
    assert 'agent_reader' in old and 'agent_fragment_review' not in old


def exhausted():
    return {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'},
            'autoLengthRepairLimit': 3, 'readerRepairCount': 0, 'lengthRepairCount': 3,
            'lengthRepairTotal': 6, 'lengthRepairCycle': 0,
            'lengthRepairStrategy': quality().LENGTH_REPAIR_STRATEGY}


def test_author_selected_model_starts_one_bounded_budget_keeps_total_and_originals(tmp_path):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3206)
    before = body.read_bytes()
    state = exhausted()
    assert p.next_action(tmp_path, state, 'polish')['action'] == 'pause'
    state['writerModel'] = MODEL
    for expected in [1, 2, 3]:
        action = p.next_action(tmp_path, state, 'polish')
        assert action['action'] == 'advance'
        state.update(action['updates'])
        assert state['lengthRepairCount'] == expected
        assert state['lengthRepairTotal'] == 6 + expected
        assert state['lengthRepairModel'] == MODEL
        assert state['autoLengthRepairLimit'] == 3
    assert p.next_action(tmp_path, state, 'polish')['action'] == 'pause'
    assert body.read_bytes() == before


def test_model_budget_does_not_overwrite_previous_attempt_feedback(tmp_path):
    p = policy()
    q = quality()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 3206)
    state = exhausted()
    state['lengthRepairCount'] = 0
    first = p.next_action(tmp_path, state, 'polish')
    state.update(first['updates'])
    original = tmp_path / state['lengthRepairFeedback']['path']
    content, stamp = original.read_bytes(), original.stat().st_mtime_ns
    state['lengthRepairCount'] = 3
    state['writerModel'] = MODEL
    second = p.next_action(tmp_path, state, 'polish')
    assert second['action'] == 'advance'
    assert second['updates']['lengthRepairFeedback']['path'] != state['lengthRepairFeedback']['path']
    assert original.read_bytes() == content and original.stat().st_mtime_ns == stamp
