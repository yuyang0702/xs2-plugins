import urllib.request
import json

import pytest

from test_draft_guard import prepared, run, save, evidence
from test_focused_length import managed, cli, quality
from test_local_revision import module, put, scoped_setup


@pytest.mark.parametrize('line', [
    '“你找的不是钥匙，而是门闩。”',
    '“说白了，地府也卡应届生的工龄？”',
    '当潮水漫过旧码头时，他才想起父亲。',
    '她摸了三遍口袋，钥匙、船票、戒指都在。',
])
def test_assembled_draft_sends_lieflat_hits_to_contextual_audit(tmp_path, monkeypatch, capsys, line):
    original, _ = evidence()
    body, report = evidence(original + '\n\n' + line)
    guard, folder = prepared(tmp_path, monkeypatch, capsys, 'patches', body, inspect_first=True, combined_precheck=True)
    report['checks']['repetition'] = True
    report['book_contract_sha256'] = guard.read(folder/'binding.json')['book_contract_sha256']
    save(folder/'facts-audit.json', report)
    assert 'guard_facts_needs_repair:no' in run(guard, tmp_path, monkeypatch, capsys, 'precheck')
    model = guard.read(folder/'expression-audit-model.json')
    assert model['tone_review']['hints']
    assert 'guard_expression_needs_repair:no' in run(guard, tmp_path, monkeypatch, capsys, 'precheck', 'expression')


def test_confirmed_reader_does_not_have_to_rephrase_a_contextual_hit(tmp_path):
    body = '她碰了碰窗框。“还没回来。”不是钥匙，而是门闩。\n\n说白了，邻居还在等。'
    m, out, _ = scoped_setup(tmp_path, raw=body.encode())
    assert out['revision_critique_mode'] == 'confirmed'
    src = m.read(tmp_path/out['revision_source_input'])
    assert src['local_tone']['marks'] == {'p0001':['不是钥匙，而是']}
    m.check_local_tone(src, [])
    edit = {'paragraph_id':'p0001','old':'不是钥匙，而是门闩','replacement':'她指的是门闩','occurrence':1}
    m.check_local_tone(src, [edit])
    m.check_local_tone(src, [], [edit])


def test_plain_single_patch_allows_contextual_phrasing_offline(tmp_path, monkeypatch):
    m = module()
    adapter = m.load('test_local_patch', m.HERE/'local_revision/zhuque_round_adapter.py')
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('单段改写调用了远端检测'))
    old = '不是钥匙，而是门闩。'
    digest = m.sha(old.encode())
    edit = {'paragraph_id':'p0001', 'old':old, 'occurrence':1, 'replacement':'说白了，是门闩。'}
    def check(edits):
        return adapter.run({'action':'local-patch', 'body':'', 'view':{'source_body':m.packet.prose(old)},
                            'patch':{'source_sha256':digest,'edits':edits}})['feedback']
    assert check([]) == ''
    assert check([edit]) == ''
    edit['replacement'] = '门闩。钥匙哪有这么沉？'
    assert check([edit]) == ''


def test_focused_fragment_exposes_style_candidate_to_semantic_review(tmp_path):
    managed(tmp_path)
    out = cli(tmp_path, 'length_only')
    put(tmp_path, 'cache/pp/body.json', {'body':'说白了，我还欠他三块钱。'})
    q = quality()
    reviewed = q.prepare_fragment_review(tmp_path, '0001', out['length_expected_body_sha'], out['length_commit_guard'],
                                         out['length_commit_guard_sha'], 'tone-test')
    context = json.loads((tmp_path/reviewed['fragment_review_input']).read_text(encoding='utf8'))
    assert context['tone_review']['hints']
    assert not (tmp_path/'quality/length-attempts/0001/tone-test/receipt.json').exists()


def test_literal_protection_and_semantic_candidates_remain_available_to_author():
    tone = module().tone
    assert tone.mandatory('# 说白了，标题\n“说白了，”是他的口头禅。', ['说白了，']) == []
    assert tone.fragment_review('她问：“你回家吗？”')['mandatory_phrases'] == []


def test_scoped_edit_checks_rule_at_join_and_leaves_same_phrase_elsewhere():
    m = module()
    old = '不是钥匙，而是门闩。不是钥匙，而是门闩。'
    source = {'paragraphs':m.patches.paragraphs(old), 'book_contract':{'protected_phrases':[]},
              'local_tone':{'marks':{}, 'edited_only':True}}
    edit = {'paragraph_id':'p0001','old':'钥匙','replacement':'那把钥匙','occurrence':1}
    with pytest.raises(ValueError, match='不是那把钥匙，而是'):
        m.check_local_tone(source, [edit])
    corrected = {**edit, 'old':'不是钥匙，而是门闩。', 'replacement':'她指的是门闩。'}
    m.check_local_tone(source, [corrected], [corrected])
    with pytest.raises(ValueError, match='不是钥匙，而是'):
        m.check_local_tone(source, [], [corrected])


def test_blind_tie_allows_the_original_wording_when_only_style_candidates_are_present(tmp_path):
    m = module()
    body = '不是钥匙，而是门闩。\n\n他等在桥上。'
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'local-tie', scoped_review=True, whole_chapter_review=True, blind_scenes=True)
    put(tmp_path, 'critique.json', {'issues':[]})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    src = m.read(tmp_path/out['revision_input'])
    edits = [{'paragraph_id':p['id'], 'old':p['text'], 'occurrence':1, 'replacement':new}
             for p,new in zip(src['paragraphs'], ['她说的是门闩。','他蹲在桥头。'])]
    put(tmp_path, out['revision_patch_path'], {'source_sha256':src['source_sha256'],'edits':edits})
    m.candidate(tmp_path, out['revision_dir'])
    ballot = m.read(tmp_path/out['revision_blind_packet'])
    vote = {'ballot':ballot['ballot'], 'scenes':[{'id':s['id'], 'prefer':'tie','exceptions':[],
            'voice_quote':'','redundant_quote':'','reason':'两版语义相当。'} for s in ballot['scenes']]}
    put(tmp_path, out['revision_blind_path'], vote)
    m.accept_blind(tmp_path, out['revision_dir'], json.dumps(vote, ensure_ascii=False))
    context = m.read(tmp_path/out['revision_review_input'])
    assert context['candidate'] == src['source_body']
    assert not context['edits']
