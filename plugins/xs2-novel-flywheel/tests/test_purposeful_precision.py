import importlib.util
import json
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/prose_policy/precision_policy.py'


def module():
    assert PATH.is_file(), 'purposeful precision policy must exist'
    spec = importlib.util.spec_from_file_location('purposeful_precision', PATH)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def test_immediate_literal_chinese_quote_mismatch_is_fact_candidate_with_exact_spans():
    m = module(); text = '“下午聊一下”，这四个字让他停住。'
    r = m.analyze(text)
    row = next(x for x in r['findings'] if x['kind'] == 'quoted_character_count')
    assert row['status'] == 'fact_candidate'
    assert (row['claimed_count'], row['actual_count']) == (4, 5)
    assert row['antecedent']['quote'] == '下午聊一下'
    for item in [row, row['antecedent']]:
        assert text[item['start']:item['end']] == item['quote']
    assert r['advisory_only'] is True
    assert 'pass' not in r and 'rewrite' not in r
    json.dumps(r, ensure_ascii=False)


@pytest.mark.parametrize('text', [
    '“下午聊一下”。他走到门边。那四个字仍在心里。',
    '“下午聊一下”“明天见”，这四个字让他停住。',
    '“OK，下午聊一下”，这四个字让他停住。',
    '他重复这四个字。', '“下午，聊一下”，这四个字让他停住。'])
def test_ambiguous_antecedent_or_counting_rule_remains_unknown(text):
    rows = module().analyze(text)['findings']
    assert not any(x['status'] == 'fact_candidate' for x in rows)
    assert any(x['status'] == 'unknown' for x in rows)


def test_correct_literal_count_is_not_a_mismatch():
    assert not any(x['status'] == 'fact_candidate' for x in module().analyze('“下午聊一下”，这五个字。')['findings'])


def test_purpose_less_exact_count_is_review_advice():
    text = '她停了3.72秒，又走了恰好十七步。'
    rows = module().analyze(text)['findings']
    assert rows
    assert all(x['status'] == 'advisory' and text[x['start']:x['end']] == x['quote'] and x['reason'] for x in rows)


@pytest.mark.parametrize('text', ['付款3元，余额2元。', '须在下午3点前交付。', '实验测得温度37.2摄氏度。',
                                  '他有强迫计数的习惯，又数了十七步。', '夸张地说，他等了一万年。'])
def test_useful_quantity_or_intentional_voice_does_not_trigger_generic_count_advice(text):
    assert module().analyze(text)['findings'] == []


def test_contract_can_protect_counting_style_without_fabricating_fact_pass():
    c = {'precision_policy': {'preserve_counting': True, 'reason': '主角强迫计数，保留类型声音'}}
    m = module()
    assert m.analyze('她停了3.72秒。', c)['findings'] == []
    assert any(x['status'] == 'fact_candidate' for x in m.analyze('“下午聊一下”，这四个字。', c)['findings'])
    assert '阅读目的' in m.GUIDANCE and '四→五' in m.GUIDANCE

@pytest.mark.parametrize('claim', ['四五', '三四', '一2', '2一', '二十三四', '十十', '零五'])
def test_ambiguous_or_invalid_claim_numerals_never_become_fact_candidates(claim):
    rows = module().analyze('“下午聊一下”，这' + claim + '个字。')['findings']
    assert rows and all(row['status'] == 'unknown' for row in rows)
    assert rows[0]['claimed_count'] is None


@pytest.mark.parametrize('claim, expected', [('4', 4), ('四', 4), ('十四', 14), ('二十四', 24),
                                           ('一百零四', 104), ('一千零一', 1001)])
def test_valid_exact_claim_numerals_keep_their_values(claim, expected):
    rows = module().analyze('“下午聊一下”，这' + claim + '个字。')['findings']
    assert rows[0]['status'] == 'fact_candidate' and rows[0]['claimed_count'] == expected

@pytest.mark.parametrize('text', ['“他说：「下午聊一下」，这四个字。”',
                                 '「他重复：“下午聊一下”，这四个字。」',
                                 '她说：“他说："下午聊一下"，这四个字。”'])
def test_nested_literal_with_intervening_narration_remains_unknown(text):
    rows = module().analyze(text)['findings']
    assert rows and all(row['status'] == 'unknown' for row in rows)
def test_bundled_business_precision_has_book_independent_anchors_and_normalized_values():
    p=module()
    rows=p.dialogue_details('“我接了六十份，七点前送到。”\n\n“药得五毫克，八点前服。”\n\n“那家有咖啡。”')
    assert [r['paragraph_id'] for r in rows]==['p0001','p0002']
    assert rows[0]['details']==['六十份','七点']
    assert rows[1]['details']==['五毫克','八点']
    assert p.detail_keys('60份、07:00前到')==p.detail_keys('六十份，七点前送到')


def test_precision_scan_spans_narration_and_linked_turns_but_leaves_relative_language():
    text = ('他又数了一遍，盘里还剩一颗。\n\n他接过盘子，没说话。\n\n我把那一颗推过去。\n\n'
            '“六点？”\n\n我把账本翻回来。\n\n“六点要对账。”\n\n“那七点？”\n\n“七点可以。”\n\n'
            '午后又凉了一点。\n\n我摸到三块钱，两张票据。\n\n第二天见。')
    rows = module().review_candidates(text)
    assert {row['paragraph_id']: row['details'] for row in rows} == {
        'p0001': ['一颗'], 'p0003': ['一颗'], 'p0004': ['六点'], 'p0006': ['六点'],
        'p0007': ['七点'], 'p0008': ['七点'], 'p0010': ['三块钱', '两张'],
    }
