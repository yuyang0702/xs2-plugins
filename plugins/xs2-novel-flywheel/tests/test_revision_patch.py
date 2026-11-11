import hashlib
import json
import importlib.util
from pathlib import Path

import pytest

PLUGIN=Path(__file__).resolve().parents[1]


def helper():
    path=PLUGIN/'resources/script-library/xs2/draft_guard/revision_patch.py'
    assert path.is_file(),'missing exact-source local revision support'
    spec=importlib.util.spec_from_file_location('revision_patch_tests',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


SOURCE='雨还没有停。\n\n她又想起那句话。那句话仍在。\n\n潮水会回来。'


def payload(*edits):return {'source_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),'edits':list(edits)}
def edit(**patch):return {'paragraph_id':'p0002','old':'那句话','occurrence':2,'replacement':'潮声',**patch}


def test_local_replacement_preserves_every_unedited_character_and_noop_is_valid():
    m=helper();catalog=m.paragraphs(SOURCE)
    assert catalog[1]['id']=='p0002' and catalog[1]['text']=='她又想起那句话。那句话仍在。'
    assert m.apply_patches(SOURCE,payload(edit()))=='雨还没有停。\n\n她又想起那句话。潮声仍在。\n\n潮水会回来。'
    assert m.apply_patches(SOURCE,payload())==SOURCE


@pytest.mark.parametrize('patch',[{'paragraph_id':'p9999'},{'old':'别的稿子'},
    {'occurrence':0},{'occurrence':True},{'replacement':3}])
def test_patch_never_guesses_a_stale_or_ambiguous_anchor(patch):
    with pytest.raises(ValueError):helper().apply_patches(SOURCE,payload(edit(**patch)))


def test_bad_anchor_feedback_quotes_actual_frozen_paragraph_without_applying_a_guess():
    source='对林安来说，门还开着。'
    data={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'edits':[{
        'paragraph_id':'p0001','old':'对林安来来说','occurrence':1,'replacement':'对林安来说'}]}
    with pytest.raises(ValueError) as failure:helper().apply_patches(source,data)
    assert source in str(failure.value)
    assert '对林安来来说' in str(failure.value)
    assert '逐字' in str(failure.value)
    assert source=='对林安来说，门还开着。'


def test_source_hash_and_overlapping_edits_are_rejected():
    with pytest.raises(ValueError):helper().apply_patches(SOURCE+'改',payload(edit()))
    with pytest.raises(ValueError,match='重叠'):
        helper().apply_patches(SOURCE,payload(edit(),edit()))


def test_author_protected_refrain_cannot_be_deleted_as_repetition():
    with pytest.raises(ValueError,match='保护|保留'):
        helper().apply_patches(SOURCE,payload(edit(paragraph_id='p0003',old='潮水会回来。',occurrence=1,replacement='')),
                               protected_phrases=['潮水会回来。'])


def test_long_paragraph_style_can_be_edited_without_reformatting_the_whole_book():
    source='她想起潮声，也想起那封信。'*30
    p={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'edits':[{
        'paragraph_id':'p0001','old':'她想起潮声','occurrence':12,'replacement':'她听见潮声'}]}
    result=helper().apply_patches(source,p)
    assert result.count('她听见潮声')==1 and '\n' not in result


def test_expression_candidate_checks_length_before_requesting_an_audit(tmp_path,monkeypatch,capsys):
    from test_draft_guard import accepted_facts,run,save
    m,d,_=accepted_facts(tmp_path,monkeypatch,capsys)
    save(d/'expression-draft.json',{'body':'字'*600})
    output=run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    assert 'agent_guard_expression_repair' in output and '600' in output
    assert not (d/'expression-audit-input.json').exists()


def test_length_feedback_budget_uses_frozen_source_not_previous_candidate(tmp_path,monkeypatch,capsys):
    from test_draft_guard import accepted_facts,save,run
    m,d,_=accepted_facts(tmp_path,monkeypatch,capsys)
    save(d/'expression-input.json',{'source_body':'甲'*100})
    binding=json.loads((d/'binding.json').read_text(encoding='utf-8'));binding['target']='150-200'
    binding['expression_format']='patches'
    prior={'source_sha256':hashlib.sha256(('甲'*100).encode()).hexdigest(),'edits':[{
        'paragraph_id':'p0001','old':'甲','occurrence':1,'replacement':'甲'*50}]}
    save(d/'expression-draft.json',prior)
    m.reject_candidate(d,'expression',binding,'甲'*149,[{'category':'length'}])
    feedback=(d/'expression-feedback.md').read_text(encoding='utf-8')
    assert '"source_word_count": 100' in feedback
    assert '"net_change_minimum": 50' in feedback
    assert '"net_change_maximum": 100' in feedback
    assert '不累计' in feedback
    assert 'previous_patch' in feedback and '"replacement": "'+('甲'*50)+'"' in feedback
    (d/'expression-draft.json').unlink()
    assert json.loads((d/'expression-last-rejected.json').read_text(encoding='utf-8'))['previous_patch']==prior
