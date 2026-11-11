import copy
import hashlib
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2'


def module():
    spec = importlib.util.spec_from_file_location('ledger_alias_policy', ROOT / 'multi_scene/continuity_contract.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def ledger():
    return {'schema': 1, 'focus': '小林', 'facts': [], 'units': {'块': 1}, 'unit_equations': [],
            'accounts': [{'id': 'cash', 'opening': 0}],
            'events': [{'id': 'receive', 'scene': 1, 'after': [], 'description': '收款', 'source_quote': '收款三块'}],
            'transfers': [{'id': 'income', 'scene': 1, 'account': 'cash', 'direction': 'in',
                           'parts': '三块', 'change': '', 'amount': 3, 'balance': 3,
                           'event_id': 'receive', 'source_quote': '收款三块'}]}


def report(m, c, body='收款三元整。余三元。'):
    span = lambda s: {'text': s, 'occurrence': 1}
    return {'schema': 1, 'candidate_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'contract_sha256': m.contract_digest(c), 'checks': {k: True for k in m.HARD}, 'issues': [],
            'fact_observations': [], 'event_observations': [{'id': 'receive', 'quote': span('收款三元整')}],
            'money_observations': [{'id': 'income', 'paid': span('三元整'), 'change': None}],
            'balance_observations': [{'after': 'income', 'quote': span('余三元')}]}


def test_modern_cny_alias_audits_raw_payment_and_balance():
    m = module(); original = ledger()
    c = m.enrich_unit_aliases(original, '本账使用现代人民币，收款三块。')
    assert original == ledger()
    assert c['units'] == {'块': 1}
    assert m.validate_contract(c, '本账使用现代人民币，收款三块。', 1) == c
    body = '收款三元整。余三元。'
    r = report(m, c, body); before = copy.deepcopy(r)
    assert m.audit_issues(r, body, c, 'facts') == []
    assert r == before
    wrong = body.replace('余三元', '余二元')
    r = report(m, c, wrong); r['balance_observations'][0]['quote']['text'] = '余二元'
    assert any(i['category'] == 'money' for i in m.audit_issues(r, wrong, c, 'facts'))


def test_aliases_are_not_global_or_inferred_from_generic_money_words():
    m = module()
    for source in ['收款三块', '虚构灵元与晶块', '美元付款', '人民币和晶块的汇率未知',
                   '本账使用美元，另记人民币。收款三块', '本账不使用人民币，收款三块',
                   '人民币与灵石各记一账，买三块灵石']:
        with pytest.raises(ValueError): m.enrich_unit_aliases(ledger(), source)
    with pytest.raises(ValueError): m.audit_issues(report(m, ledger()), '收款三元整。余三元。', ledger(), 'facts')


def test_explicit_alias_needs_literal_equal_unit_source():
    m = module(); c = ledger()
    c['unit_aliases'] = [{'alias': '元', 'unit': '块', 'source_quote': '一块等于一元'}]
    assert m.validate_contract(c, '收款三块。一块等于一元', 1) == c
    assert m.audit_issues(report(m, c), '收款三元整。余三元。', c, 'facts') == []
    for quote in ['一块等于二元', '块与元汇率未知', '一块等于一美元']:
        wrong = copy.deepcopy(c); wrong['unit_aliases'][0]['source_quote'] = quote
        with pytest.raises(ValueError): m.validate_contract(wrong, '收款三块。' + quote, 1)
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块', 1)


def test_alias_is_not_new_independent_unit_or_rate_conversion():
    m = module(); c = ledger()
    c['unit_aliases'] = [{'alias': '元', 'unit': '块', 'source_quote': '一块等于一元'}]
    c['units']['元'] = 2
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块。一块等于一元', 1)
    c = ledger(); c['units']['钱'] = 10
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块', 1)


def test_resource_child_keeps_its_own_aliases_only():
    m = module(); parent = ledger()
    child = m.enrich_unit_aliases(ledger(), '本账以人民币计价，一块钱。')
    child['id'] = 'cash'
    result = m.resource_contract(parent, child)
    assert result['currency_scope'] == child['currency_scope']
    assert m.effective_units(result)['元'] == 1
    assert '元' not in m.effective_units(parent)


def test_alias_vocabulary_is_available_for_exact_evidence_refs():
    m = module(); c = m.enrich_unit_aliases(ledger(), '本账使用现代人民币，收款三块。')
    body = '收款三元整。余三元。'
    rows = m.audit_evidence.catalog(body, m.evidence_unit_names(c))
    paid = next(row for row in rows if row['kind'] == 'amount' and row['text'] == '三元')
    r = report(m, c); r['money_observations'][0]['paid'] = {'ref_id': paid['id']}
    assert m.audit_issues(r, body, c, 'facts') == []


def test_forged_currency_scope_and_duplicate_alias_are_rejected():
    m = module(); c = ledger()
    c['currency_scope'] = {'code': 'CNY', 'source_quote': '本账使用现代人民币，收款三块。'}
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块', 1)
    c['currency_scope']['code'] = 'USD'
    with pytest.raises(ValueError): m.effective_units(c)
    c = ledger(); row = {'alias': '元', 'unit': '块', 'source_quote': '一块等于一元'}
    c['unit_aliases'] = [row, row]
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块。一块等于一元', 1)

@pytest.mark.parametrize('quote', ['十一块等于一元', '二十一块等于一元', '不是一块等于一元',
                                  '并非一块等于一元', '假如一块等于一元', '一块不等于一元',
                                  '一块等于十一元', '一块等于一元吗？'])
def test_alias_evidence_must_be_complete_affirmative_one_to_one(quote):
    m = module(); c = ledger()
    c['unit_aliases'] = [{'alias': '元', 'unit': '块', 'source_quote': quote}]
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块。' + quote, 1)


@pytest.mark.parametrize('quote', ['本账使用美元，价格不是人民币三块。',
                                  '本账不使用人民币三块。', '假如本账使用人民币，收款三块。',
                                  '本账使用人民币吗，收款三块。', '本账使用美元，人民币三块。'])
def test_currency_scope_does_not_accept_negated_hypothetical_or_mixed_claims(quote):
    with pytest.raises(ValueError): module().enrich_unit_aliases(ledger(), quote)

@pytest.mark.parametrize('quote', ['11块等于1元', '1块等于11元', '十一元等于一块',
                                  '-1块等于1元', '负一块等于一元', '一块等于负一元',
                                  '据说一块等于一元', '有人声称一块等于一元'])
def test_alias_rejects_multidigit_signed_or_reported_equalities(quote):
    m = module(); c = ledger()
    c['unit_aliases'] = [{'alias': '元', 'unit': '块', 'source_quote': quote}]
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块。' + quote, 1)

@pytest.mark.parametrize('quote', ['本账使用人民币，收款三块，以上记载有误。',
                                  '本账使用卢布，人民币三块。',
                                  '人民币三元，本账使用卢布，收款三块。',
                                  '本账使用人民币，收款三块，后来撤回上述记载。',
                                  '本账使用人民币，收款三块，另账采用火星币。',
                                  '人民币三块，上述只是他人的猜测。'])
def test_every_scope_evidence_clause_must_have_supported_affirmative_structure(quote):
    m = module()
    with pytest.raises(ValueError): m.enrich_unit_aliases(ledger(), quote)
    c = ledger(); c['currency_scope'] = {'code': 'CNY', 'source_quote': quote}
    with pytest.raises(ValueError): m.validate_contract(c, '收款三块。' + quote, 1)


@pytest.mark.parametrize('quote', ['本账使用人民币，收款三块。', '本账以人民币计价，一块钱。',
                                  '人民币三块。', '本账采用现代人民币结算；期初三块；余额三元。'])
def test_complete_affirmative_scope_and_amount_clauses_remain_supported(quote):
    m = module(); c = m.enrich_unit_aliases(ledger(), quote)
    assert m.validate_contract(c, '收款三块。' + quote, 1) == c
    assert m.effective_units(c) == {'块': 1, '元': 1}
