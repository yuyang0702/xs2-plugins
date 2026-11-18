import copy
import json

from test_length_quality import install_legacy_length_feedback, policy, quality, write


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


def test_model_budget_does_not_overwrite_previous_attempt_feedback(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '衣' * 3206)
    state = exhausted()
    state['lengthRepairCount'] = 0
    install_legacy_length_feedback(tmp_path, state)
    first_receipt = state['lengthRepairFeedback']
    original = tmp_path / state['lengthRepairFeedback']['path']
    content, stamp = original.read_bytes(), original.stat().st_mtime_ns
    state['lengthRepairCount'] = 3
    state['writerModel'] = MODEL
    install_legacy_length_feedback(tmp_path, state)
    assert state['lengthRepairFeedback']['path'] != first_receipt['path']
    assert original.read_bytes() == content and original.stat().st_mtime_ns == stamp

def test_explicit_book_roles_separate_writer_planner_polisher_and_assessor():
    p = policy()
    book = {'writerModel': 'volcengine:writer', 'analysisModel': 'system:model', 'polishModel': MODEL}
    mvp = {'nodes': [{'id': key, 'node_type': 'agent', 'agent_type': agent}
                     for key, agent in [('agent_nw', 'novel-multi-scene-planner'),
                                        ('agent_aw', 'novel-multi-scene-writer'),
                                        ('agent_si', 'novel-multi-scene-writer'),
                                        ('agent_trimmer', 'existing')]]}
    assert p.model_overrides(book, mvp, 'mvp') == {
        'agent_nw': 'system:model', 'agent_aw': 'volcengine:writer',
        'agent_si': 'volcengine:writer', 'agent_trimmer': 'system:model'}
    assert p.model_overrides(book, definition(), 'polish')['agent_pp'] == MODEL
    assert p.model_overrides(book, definition(), 'polish')['agent_fragment_review'] == 'system:model'
