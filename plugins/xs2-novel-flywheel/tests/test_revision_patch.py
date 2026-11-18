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


def test_in_range_local_revision_does_not_suggest_midpoint_padding():
    budget=helper().length_edit_budget(11216,(11200,12800))
    assert budget['net_change_minimum']==-16
    assert budget['suggested_result_word_count']==11216
    assert budget['suggested_net_change']==0


def test_mixed_growth_has_a_stable_sentence_issue_and_preserves_the_useful_addition():
    m = helper()
    heat = '壶口的热气淡了。'
    repeated = '耗去的热气谁也要不回来。'
    choice = '现在分，得看每一碗能泡开多少干粮。'
    reply = '“少泡多少？”'
    source = heat + '\n\n' + reply
    edit = {'paragraph_id': 'p0001', 'old': heat, 'occurrence': 1,
            'replacement': heat + repeated + choice}
    report = [{'edit_index': 0, 'useful': [choice], 'repetitions': [
        {'previous': heat, 'quote': repeated, 'reason': '重新解释已经写出的热气流失'}]}]
    issues = m.review_additions(source, [edit], report)
    issue, = issues
    assert issue['category'] == 'post_action_restatement'
    assert issue['excerpts'] == [heat, repeated]
    assert issue['preserve'] == [choice]
    assert issues == m.review_additions(source, [edit], report)
    repaired = [{**edit, 'replacement': heat + choice}]
    candidate = m.apply_patches(source, {'source_sha256': m.digest(source), 'edits': repaired})
    assert reply in candidate
    outcome = {'id': issue['id'], 'status': 'resolved', 'excerpts': [choice], 'reason': '删去复述，留下分水决定'}
    assert m.review_addition_outcomes(source, repaired, issues, [outcome]) == []
    with pytest.raises(ValueError, match='原编号'):
        m.review_addition_outcomes(source, repaired, issues, [{**outcome, 'id': 'another-id'}])
    assert m.review_addition_outcomes(source, [edit], issues, [outcome])
    assert m.review_addition_outcomes(source, [{**edit, 'replacement': heat}], issues,
                                      [{**outcome, 'excerpts': [heat]}])


def test_growth_review_is_complete_and_cannot_use_an_invented_or_later_quote():
    m = helper()
    edit = {'paragraph_id': 'p0001', 'old': '有风。', 'occurrence': 1,
            'replacement': '有风。风说过了。后面另有一扇门。'}
    with pytest.raises(ValueError, match='增写'):
        m.review_additions('有风。', [edit], None)
    for previous in ('原文没有这句', '后面另有一扇门。'):
        with pytest.raises(ValueError, match='逐字'):
            m.review_additions('有风。', [edit], [{'edit_index': 0, 'useful': [], 'repetitions': [
                {'previous': previous, 'quote': '风说过了。', 'reason': '重复'}]}])


def test_mixed_replacement_with_net_cut_still_reviews_new_restatement():
    m = helper()
    heat = '壶口的热气比揭盖时淡了些。'
    repeated = '谁也不能把耗掉的热气再要回来。'
    choice = '整壶给谁，另一边的事就只能继续等。'
    old = heat + '有一个可以又长又详细地说清楚的理由，在此反复交代也没有什么作用。' * 2
    source = old + '\n\n“少泡多少？”'
    edit = {'paragraph_id': 'p0001', 'old': old, 'occurrence': 1,
            'replacement': heat + repeated + choice}
    assert len(edit['replacement']) < len(old)
    assert m.growth_indices([edit]) == []  # Historical scope stays verifiable.
    assert m.growth_indices([edit], include_mixed=True) == [0]
    review = [{'edit_index': 0, 'useful': [choice], 'repetitions': [
        {'previous': heat, 'quote': repeated, 'reason': '第二句又说明水正在变凉。'}]}]
    issue, = m.review_additions(source, [edit], review, include_mixed=True)
    repair = [{**edit, 'replacement': heat + choice}]
    assert not m.review_addition_outcomes(source, repair, [issue], [{
        'id': issue['id'], 'status': 'resolved', 'excerpts': [choice], 'reason': '留下分水的代价。'}])


def test_mixed_replacement_catches_an_extra_copy_even_after_a_large_cut():
    m = helper()
    retained = '船已经靠岸。'
    old = retained + '他们原本还有许多事情需要在雨停后逐件重新商量。'
    edit = {'paragraph_id': 'p0001', 'old': old, 'occurrence': 1, 'replacement': retained * 2}
    assert m.growth_indices([edit], include_mixed=True) == [0]


def test_scene_line_repair_needs_its_own_change_and_preserves_explicit_keep():
    m = helper()
    speech = '我得先把这项核验停下来。'
    question = '“那留下的人呢？”'
    restatement = '我知道他要明确答复。'
    order = '“十七码先别放，名单对不上。”'
    source = f'“先别走。{speech}”\n\n{question}\n\n{restatement}\n\n{order}他把闸门合上。'
    first = {'id':'line-1','scene_focus':{'quote':speech,'addressee':'等船的人'},'excerpts':['先别走。',speech]}
    second = {'id':'line-2','scene_focus':{'quote':restatement,'preserve':[question]},
              'excerpts':[question,restatement]}
    goals = [m.bind_scene_goal(source, [], source, issue, source.index(issue['scene_focus']['quote']))
             for issue in (first, second)]
    edits = [{'paragraph_id':'p0001','old':speech,'occurrence':1,'replacement':''}]
    edited = m.apply_patches(source, {'source_sha256':m.digest(source),'edits':edits})
    outcome = {'id':'line-1','status':'resolved','reason':'拦下就够了。','excerpts':['“先别走。”']}
    assert not m.scene_outcome_problem(source, edits, edited, goals[0], outcome)
    assert m.scene_outcome_problem(source, edits, edited, goals[1], {**outcome,'id':'line-2'})

    edits += [{'paragraph_id':'p0003','old':restatement,'occurrence':1,'replacement':''}]
    edited = m.apply_patches(source, {'source_sha256':m.digest(source),'edits':edits})
    outcome = {'id':'line-2','status':'resolved','reason':'省去解说，追问直接接下一步动作。','excerpts':[question,order]}
    assert not m.scene_outcome_problem(source, edits, edited, goals[1], outcome)
    edits += [{'paragraph_id':'p0002','old':question,'occurrence':1,'replacement':'他没出声。'}]
    edited = m.apply_patches(source, {'source_sha256':m.digest(source),'edits':edits})
    assert m.scene_outcome_problem(source, edits, edited, goals[1], {**outcome,'excerpts':[order]})


def test_scene_line_can_gain_a_real_addressee_or_be_retained_after_a_recheck():
    m = helper()
    quote = '十七码先别放，名单对不上。'
    witness = '我冲那位等船的人说。'
    source = f'{witness}\n\n“{quote}”'
    issue = {'id':'audience','scene_focus':{'quote':quote},'excerpts':[witness,quote]}
    goal = m.bind_scene_goal(source,[],source,issue,source.index(quote))
    edit = {'paragraph_id':'p0001','old':witness,'occurrence':1,'replacement':'我冲正要开闸的同事说。'}
    candidate = m.apply_patches(source,{'source_sha256':m.digest(source),'edits':[edit]})
    outcome = {'id':'audience','status':'resolved','reason':'同事可立刻暂停放行。',
               'excerpts':[edit['replacement'],quote]}
    assert not m.scene_outcome_problem(source,[edit],candidate,goal,outcome)
    assert m.scene_outcome_problem(source,[],source,goal,{**outcome,'excerpts':[witness,quote]})
    formal = m.bind_scene_goal(candidate,[],candidate,{**issue,'excerpts':outcome['excerpts']},candidate.index(quote))
    assert not m.scene_outcome_problem(candidate,[],candidate,formal,{**outcome,'status':'not_applicable'})


def test_conflict_evidence_binds_label_and_crlf_to_exact_frozen_paragraphs():
    m=helper();source='我把钱收了。\r\n\r\n他还站在那里。\r\n\r\n她转过身。'
    quotes=['p0001—p0002（12实字）：\n我把钱收了。\n\n他还站在那里。','她转过身。']
    assert m.exact_evidence(source,quotes)==['我把钱收了。\r\n\r\n他还站在那里。','她转过身。']
    with pytest.raises(ValueError,match='逐字证据'):
        m.exact_evidence(source,['p0001—p0002：\n我把钱还了。\n\n他还站在那里。'])
    with pytest.raises(ValueError,match='逐字证据'):
        m.exact_evidence(source,['p0002：\n我把钱收了。'])


def payload(*edits):return {'source_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),'edits':list(edits)}
def edit(**patch):return {'paragraph_id':'p0002','old':'那句话','occurrence':2,'replacement':'潮声',**patch}


def test_local_replacement_preserves_every_unedited_character_and_noop_is_valid():
    m=helper();catalog=m.paragraphs(SOURCE)
    assert catalog[1]['id']=='p0002' and catalog[1]['text']=='她又想起那句话。那句话仍在。'
    assert m.apply_patches(SOURCE,payload(edit()))=='雨还没有停。\n\n她又想起那句话。潮声仍在。\n\n潮水会回来。'
    assert m.apply_patches(SOURCE,payload())==SOURCE


def test_patch_rejects_control_characters_without_rejecting_dialogue_and_line_breaks():
    m = helper()
    with pytest.raises(ValueError, match='控制字符 U\\+001C'):
        m.apply_patches(SOURCE, payload(edit(replacement='\x1c潮声\x1d')))
    assert '“潮声。”\n\n' in m.apply_patches(SOURCE, payload(edit(replacement='“潮声。”\n\n')))


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
