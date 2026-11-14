import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN=Path(__file__).resolve().parents[1]
SOURCES='铺名青石铺，店主白榆。书中一两等于十钱，一钱等于一百文。买方同意后验收，再点付六两，收款后交灯。白榆清偿纸债一两二钱后取工具，租屋一两，买灯二十文，付一钱找八十文。'


def module():
    path=PLUGIN/'resources/script-library/xs2/multi_scene/continuity_contract.py'
    assert path.is_file(),'missing grounded continuity contract implementation'
    spec=importlib.util.spec_from_file_location('test_continuity_policy',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def contract():
    return {'schema':1,'focus':'白榆','facts':[{'id':'shop','value':'青石铺','aliases':[],
        'required':True,'source_quote':'铺名青石铺'}],
        'units':{'文':1,'钱':100,'两':1000},'unit_equations':[
            {'left':'一两','right':'十钱','source_quote':'一两等于十钱'},
            {'left':'一钱','right':'一百文','source_quote':'一钱等于一百文'}],
        'accounts':[{'id':'hero','opening':0}],
        'transfers':[
            {'id':'income','scene':1,'account':'hero','direction':'in','parts':'六两','change':'',
             'amount':6000,'balance':6000,'event_id':'receive','source_quote':'再点付六两'},
            {'id':'paper','scene':2,'account':'hero','direction':'out','parts':'一两二钱','change':'',
             'amount':1200,'balance':4800,'event_id':'paper_paid','source_quote':'清偿纸债一两二钱后取工具'}],
        'events':[
            {'id':'agree','scene':1,'after':[],'description':'同意分付','source_quote':'买方同意后验收'},
            {'id':'accept','scene':1,'after':['agree'],'description':'整批验收','source_quote':'验收，再点付六两'},
            {'id':'receive','scene':1,'after':['accept'],'description':'收款','source_quote':'再点付六两'},
            {'id':'handover','scene':1,'after':['receive'],'description':'交清灯','source_quote':'收款后交灯'},
            {'id':'paper_paid','scene':2,'after':['receive'],'description':'付纸债','source_quote':'清偿纸债一两二钱后取工具'},
            {'id':'tools','scene':2,'after':['paper_paid'],'description':'取工具','source_quote':'清偿纸债一两二钱后取工具'}]}


def span(text):return {'text':text,'occurrence':1}


def evidence(body=None):
    body=body or '青石铺门前。买方同意。整批验收合格。她点收六两。她交清灯。她付一两二钱纸债。她取回工具。余四两八钱。'
    c=contract();m=module()
    return body,{'schema':1,'candidate_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'contract_sha256':m.contract_digest(c),'checks':{k:True for k in ['money','facts','pov','handoff']},
        'money_observations':[{'id':'income','paid':span('六两'),'change':None},
                              {'id':'paper','paid':span('一两二钱'),'change':None}],
        'balance_observations':[{'after':'paper','quote':span('四两八钱')}],
        'fact_observations':[{'id':'shop','occurrences':[{'value':'青石铺','quote':span('青石铺门前')}]}],
        'event_observations':[{'id':key,'quote':span(text)} for key,text in [
            ('agree','买方同意'),('accept','整批验收合格'),('receive','她点收六两'),
            ('handover','她交清灯'),('paper_paid','她付一两二钱纸债'),('tools','她取回工具')]],'issues':[]}


def test_book_defined_units_and_ledger_close_without_float_rounding():
    m=module();c=contract();assert m.validate_contract(c,SOURCES,2)==c
    assert m.amount('一两整银，又摸出二十文',c['units'])==1020
    assert m.amount('1两2钱',c['units'])==1200
    body,report=evidence();assert m.audit_issues(report,body,c,'facts')==[]


def test_scene_quote_labels_bind_frozen_evidence_without_relaxing_arithmetic():
    m = module()
    source = '铺名青石铺，店主白榆。\n买方同意后验收，再点付六两。\n' + SOURCES
    c = contract()
    c['facts'][0]['source_quote'] = '@Q0001'
    c['events'][0]['source_quote'] = '@Q0002'
    c['transfers'][0]['source_quote'] = '@Q0002'
    bound = m.bind_planning_quotes(c, source)
    assert '[@Q0002] 买方同意后验收，再点付六两。' in m.planning_quote_view(source)
    assert bound['facts'][0]['source_quote'] == '铺名青石铺，店主白榆。'
    assert bound['transfers'][0]['source_quote'] == '买方同意后验收，再点付六两。'
    assert c['facts'][0]['source_quote'] == '@Q0001'
    assert m.validate_contract(bound, source, 2) == bound
    bound['transfers'][0]['parts'] = '再点付'
    with pytest.raises(ValueError, match='没有可复算金额或数量'):
        m.validate_contract(bound, source, 2)
    c['facts'][0]['source_quote'] = '@Q9999'
    c['events'][0]['source_quote'] = '买方答应了再验货'
    with pytest.raises(ValueError, match=r'facts\[shop\].*events\[agree\]'):
        m.bind_planning_quotes(c, source)


@pytest.mark.parametrize('wide_report_quote', [True, False])
def test_completed_event_report_keeps_actual_order_when_text_citations_overlap(wide_report_quote):
    m = module()
    earlier = '六十份已经另找店补齐，交付也解决了'
    telling = '告诉我' + earlier if wide_report_quote else '告诉我'
    body = '中午收摊前，周叙回来过一趟。他站在门口，告诉我' + earlier + '。'
    c = {'schema': 1, 'focus': '陈满', 'facts': [], 'units': {}, 'unit_equations': [], 'accounts': [],
         'transfers': [], 'events': [
             {'id': 'remedy', 'scene': 1, 'after': [], 'description': '另店补齐', 'source_quote': earlier},
             {'id': 'telling', 'scene': 1, 'after': ['remedy'], 'description': '事后告知', 'source_quote': telling}]}
    report = {'schema': 1, 'candidate_sha256': hashlib.sha256(body.encode()).hexdigest(),
              'contract_sha256': m.contract_digest(c), 'checks': {k: True for k in ('money','facts','pov','handoff')},
              'event_observations': [{'id': 'remedy', 'quote': span(earlier)}, {'id': 'telling', 'quote': span(telling)}],
              'fact_observations': [], 'money_observations': [], 'balance_observations': [], 'issues': []}
    assert m.audit_issues(report, body, c, 'facts') == []
    for replacement in ['六十份已经打算另找店补齐', '六十份已经等店家确认之后再交付']:
        changed = body.replace(earlier, replacement)
        rejected = {**report, 'candidate_sha256': hashlib.sha256(changed.encode()).hexdigest(),
                    'event_observations': [{'id': 'remedy', 'quote': span(replacement)},
                                           {'id': 'telling', 'quote': span(telling.replace(earlier, replacement))}]}
        with pytest.raises(ValueError, match='事件凭据'):
            m.audit_issues(rejected, changed, c, 'facts')


def test_reuse_exact_arithmetic_still_checks_new_body_event_order():
    m=module();c=contract();body,report=evidence()
    first=m.Arithmetic(m.amount)
    assert m.audit_issues(report,body,c,'facts',arithmetic=first)==[]
    revised='风过河面。'+body
    report['candidate_sha256']=hashlib.sha256(revised.encode()).hexdigest()
    def unexpected_parse(*args):
        pytest.fail('unchanged arithmetic should use the validated exact quote')
    second=m.Arithmetic(unexpected_parse,first.values)
    assert m.audit_issues(report,revised,c,'facts',arithmetic=second)==[]
    assert second.hits and not second.misses
    wrong=revised.replace('她点收六两。她交清灯','她交清灯。她点收六两')
    report['candidate_sha256']=hashlib.sha256(wrong.encode()).hexdigest()
    with pytest.raises(ValueError,match='事件凭据位置反向'):
        m.audit_issues(report,wrong,c,'facts',arithmetic=second)


@pytest.mark.parametrize('patch',[{'amount':1020},{'balance':4980},{'amount':True},{'scene':3}])
def test_invalid_planned_transfer_never_becomes_the_shared_truth(patch):
    c=contract();c['transfers'][1].update(patch)
    with pytest.raises(ValueError):module().validate_contract(c,SOURCES,2)


def test_invented_alias_and_unit_ratio_require_real_source_support():
    m=module();c=contract();c['facts'][0]['aliases']=['别的铺']
    with pytest.raises(ValueError):m.validate_contract(c,SOURCES,2)
    c=contract();c['units']['钱']=10
    with pytest.raises(ValueError):m.validate_contract(c,SOURCES,2)


def test_wrong_actual_payment_is_computed_from_the_quote_not_the_model_claim():
    body,report=evidence();body=body.replace('她付一两二钱纸债','她付一两整银又二十文纸债')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['money_observations'][1]['paid']=span('一两整银又二十文')
    report['event_observations'][4]['quote']=span('她付一两整银又二十文纸债')
    issues=module().audit_issues(report,body,contract(),'facts')
    assert any(x['category']=='money' and '1020' in x['reason'] and '1200' in x['reason'] for x in issues)


def test_missing_payment_observation_cannot_hide_an_underpayment():
    body,report=evidence();report['money_observations'].pop()
    with pytest.raises(ValueError):module().audit_issues(report,body,contract(),'facts')


def test_goods_handover_before_receipt_is_rejected_from_text_positions():
    body,report=evidence();body=body.replace('她点收六两。她交清灯','她交清灯。她点收六两')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    with pytest.raises(ValueError,match='首次|复述|凭据'):module().audit_issues(report,body,contract(),'facts')
    report['issues']=[{'category':'handoff','reason':'receive 必须先于 handover，但实际交付反序',
        'excerpts':['她交清灯','她点收六两'],'goal':'按本书已有承接条件修正实际履行顺序'}]
    assert any(i['category']=='handoff' for i in module().audit_issues(report,body,contract(),'facts'))


def test_late_restatement_is_not_automatically_a_body_order_error():
    body,report=evidence();body+='她又想起她点收六两时的迟疑。'
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['event_observations'][2]['quote']={'text':'她点收六两','occurrence':2}
    with pytest.raises(ValueError,match='首次|复述'):module().audit_issues(report,body,contract(),'facts')
    report['event_observations'][2]['quote']['occurrence']=1
    assert module().audit_issues(report,body,contract(),'facts')==[]


def test_wrong_shop_observation_cannot_claim_canonical_value():
    body,report=evidence();body=body.replace('青石铺门前','新铺门前');report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['fact_observations'][0]['occurrences']=[{'value':'新铺','quote':span('新铺门前')}]
    assert any(i['category']=='facts' for i in module().audit_issues(report,body,contract(),'facts'))
    report['fact_observations'][0]['occurrences'][0]['value']='青石铺'
    with pytest.raises(ValueError):module().audit_issues(report,body,contract(),'facts')


def test_private_thought_and_repetition_are_grounded_and_ordered():
    body,report=evidence();report['issues']=[{'category':'pov','excerpts':['买方同意'],
        'reason':'错误地直接确定他人内心','goal':'改为可观察的回应'}]
    assert module().audit_issues(report,body,contract(),'facts')[0]['category']=='pov'
    report['issues'].append({'category':'repetition','excerpts':['青石铺门前','她取回工具'],
        'reason':'同义解释','goal':'保留行动与后果'})
    with pytest.raises(ValueError):module().audit_issues(report,body,contract(),'facts')
    report['checks']['repetition']=True
    assert [i['category'] for i in module().audit_issues(report,body,contract(),'expression')]==['pov','repetition']


def test_stale_or_unquoted_audit_never_passes_expression_repair():
    body,report=evidence();report['checks']['repetition']=True
    with pytest.raises(ValueError):module().audit_issues(report,body+'改稿',contract(),'expression')
    report['candidate_sha256']=hashlib.sha256((body+'改稿').encode()).hexdigest()
    report['issues']=[{'category':'repetition','excerpts':['根本不存在'], 'reason':'重复','goal':'删掉'}]
    with pytest.raises(ValueError):module().audit_issues(report,body+'改稿',contract(),'expression')


def test_nonfinancial_story_can_explicitly_have_no_money_or_handoffs():
    c={'schema':1,'focus':'主角','facts':[],'units':{},'unit_equations':[],
       'accounts':[],'transfers':[],'events':[]}
    assert module().validate_contract(c,'没有经济交易',1)==c


@pytest.mark.parametrize('text,expected',[('1万2千文',12000),('1.2万文',12000),('十二两',12000),('一百零二文',102)])
def test_written_amounts_support_explicit_mixed_numeral_scales(text,expected):
    assert module().amount(text,contract()['units'])==expected


@pytest.mark.parametrize('text',['-1两','负一两'])
def test_negative_quote_cannot_be_read_as_a_positive_cash_payment(text):
    with pytest.raises(ValueError):module().amount(text,contract()['units'])


def test_invented_opening_cash_cannot_make_false_balances_authoritative():
    c=contract();c['accounts'][0]['opening']=900000
    for row in c['transfers']:row['balance']+=900000
    with pytest.raises(ValueError):module().validate_contract(c,SOURCES,2)
    c['accounts'][0]['opening_quote']='现有九百两'
    with pytest.raises(ValueError):module().validate_contract(c,SOURCES,2)


def test_omitted_unit_equation_cannot_hide_a_tenfold_currency_error():
    c=contract();c['units'].update(钱=1000,两=10000);c['unit_equations']=c['unit_equations'][:1]
    for row in c['transfers']:row['amount']*=10;row['balance']*=10
    with pytest.raises(ValueError):module().validate_contract(c,SOURCES,2)


def test_unrelated_change_cannot_cancel_a_wrong_actual_payment():
    body,report=evidence();body=body.replace('她付一两二钱纸债','她付一两五钱纸债')+'另一个客人退回三钱。'
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['money_observations'][1].update(paid=span('一两五钱'),change=span('三钱'))
    report['event_observations'][4]['quote']=span('她付一两五钱纸债')
    assert any(i['category']=='money' for i in module().audit_issues(report,body,contract(),'facts'))


def test_paid_and_change_quotes_cannot_overlap_to_hide_net_underpayment():
    body,report=evidence();body=body.replace('她付一两二钱纸债','她付一两二钱并找回二钱纸债')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['money_observations'][1].update(paid=span('一两二钱并找回二钱'),change={'text':'二钱','occurrence':2})
    report['event_observations'][4]['quote']=span('她付一两二钱并找回二钱纸债')
    assert any(i['category']=='money' for i in module().audit_issues(report,body,contract(),'facts'))


def test_balance_quote_must_follow_the_transaction_it_claims_to_follow():
    body,report=evidence();body=body.replace('余四两八钱。','');body='余四两八钱。'+body
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    assert any(i['category']=='money' for i in module().audit_issues(report,body,contract(),'facts'))


def test_common_trailing_half_unit_is_not_silently_discarded():
    assert module().amount('一两半',contract()['units'])==1500


def test_same_object_description_does_not_require_identical_words():
    c=contract();c['facts'][0].update(value='对账页',match_mode='referent',source_quote='陆押认的对账页')
    body,report=evidence();body=body.replace('青石铺门前','毛边纸账页在案头')
    report.update(candidate_sha256=hashlib.sha256(body.encode()).hexdigest(),contract_sha256=module().contract_digest(c))
    report['fact_observations'][0]['occurrences']=[{'value':'毛边纸账页','quote':span('毛边纸账页在案头'),'same_referent':True}]
    assert module().audit_issues(report,body,c,'facts')==[]
    report['fact_observations'][0]['occurrences'][0]['same_referent']=False
    assert any(i['category']=='facts' for i in module().audit_issues(report,body,c,'facts'))


def test_balance_inside_a_long_event_quote_is_still_after_actual_payment():
    body,report=evidence();body=body.replace('她付一两二钱纸债。她取回工具。余四两八钱。','她付一两二钱纸债，余四两八钱。她取回工具。')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['event_observations'][4]['quote']=span('她付一两二钱纸债，余四两八钱')
    assert module().audit_issues(report,body,contract(),'facts')==[]


def test_describing_a_named_entity_is_not_renaming_it():
    body,report=evidence();body=body.replace('青石铺门前','旧铺门前');report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['fact_observations'][0]['occurrences']=[{'value':'旧铺','quote':span('旧铺门前'),'is_name':False,'same_referent':True}]
    assert module().audit_issues(report,body,contract(),'facts')==[]
    report['fact_observations'][0]['occurrences'][0]['is_name']=True
    assert any(i['category']=='facts' for i in module().audit_issues(report,body,contract(),'facts'))


def test_overlapping_event_evidence_requests_narrower_proof_instead_of_inventing_reversed_actions():
    body,report=evidence();report['event_observations'][1]['quote']=span('整批验收合格。她点收六两')
    with pytest.raises(ValueError,match='重叠|分句|凭据'):
        module().audit_issues(report,body,contract(),'facts')


def test_balance_evidence_including_payment_requests_narrower_proof_not_a_rewrite():
    body,report=evidence();body=body.replace('她付一两二钱纸债。她取回工具。余四两八钱。',
        '她付一两二钱纸债，余四两八钱。她取回工具。')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['balance_observations'][0]['quote']=span('她付一两二钱纸债，余四两八钱')
    with pytest.raises(ValueError,match='余额凭据|最小分句'):
        module().audit_issues(report,body,contract(),'facts')


def test_mixed_cash_balance_can_include_retained_change_without_double_counting():
    c=contract();c['transfers'][1].update(parts='一两五钱',change='三钱',source_quote='付一两五钱找三钱')
    body,report=evidence();body=body.replace('她付一两二钱纸债','她付一两五钱纸债，找回三钱铜钱').replace('余四两八钱','余四两五钱银子，铜钱收好')
    report.update(candidate_sha256=hashlib.sha256(body.encode()).hexdigest(),contract_sha256=module().contract_digest(c))
    report['money_observations'][1].update(paid=span('一两五钱'),change=span('三钱'))
    report['event_observations'][4]['quote']=span('她付一两五钱纸债，找回三钱铜钱')
    report['balance_observations'][0]['quote']=span('余四两五钱银子，铜钱收好')
    report['balance_observations'][0]['components']=[span('四两五钱'),span('三钱')]
    assert module().audit_issues(report,body,c,'facts')==[]
    report['balance_observations'][0]['components'].append(span('三钱'))
    with pytest.raises(ValueError,match='重复|重叠'):
        module().audit_issues(report,body,c,'facts')


def test_balance_components_cannot_borrow_unrelated_money():
    body,report=evidence();body=body.replace('余四两八钱','余四两五钱')+'另一个客人有三钱。'
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['balance_observations'][0].update(quote=span('四两五钱'),components=[span('四两五钱'),span('三钱')])
    with pytest.raises(ValueError,match='分项|找零'):
        module().audit_issues(report,body,contract(),'facts')


def test_change_returned_to_a_payer_is_not_the_receivers_retained_cash():
    c=contract();c['transfers'][0].update(parts='七两',change='一两')
    body,report=evidence();body=body.replace('她点收六两','她点收七两，找出一两给买方。余五两银子')
    report.update(candidate_sha256=hashlib.sha256(body.encode()).hexdigest(),contract_sha256=module().contract_digest(c))
    report['money_observations'][0].update(paid=span('七两'),change=span('一两'))
    report['event_observations'][2]['quote']=span('她点收七两，找出一两给买方')
    report['balance_observations'].append({'after':'income','quote':span('五两银子'),'components':[span('五两'),span('一两')]})
    with pytest.raises(ValueError,match='分项|找零'):
        module().audit_issues(report,body,c,'facts')


def resource_case():
    c=contract();c['events'].append({'id':'water_given','scene':2,'after':['receive'],
        'description':'分水','source_quote':'分给孩子两瓶水'})
    c['resource_ledgers']=[{'id':'water','units':{'瓶':1},'unit_equations':[],
        'accounts':[{'id':'bag','opening':3,'opening_quote':'现有三瓶水'}],
        'transfers':[{'id':'share_water','scene':2,'account':'bag','direction':'out','parts':'两瓶','change':'',
            'amount':2,'balance':1,'event_id':'water_given','source_quote':'分给孩子两瓶水'}]}]
    body,report=evidence();body+='她分给孩子两瓶水，剩下一瓶水。'
    report.update(candidate_sha256=hashlib.sha256(body.encode()).hexdigest(),contract_sha256=module().contract_digest(c))
    report['checks']['resources']=True
    report['event_observations'].append({'id':'water_given','quote':span('她分给孩子两瓶水')})
    report['resource_observations']=[{'id':'water','money_observations':[{'id':'share_water','paid':span('两瓶'),'change':None}],
        'balance_observations':[{'after':'share_water','quote':span('一瓶')}]}]
    return c,body,report


def test_nonfinancial_resources_have_independent_units_and_exact_balances():
    c,body,report=resource_case();m=module()
    assert m.validate_contract(c,SOURCES+'现有三瓶水，分给孩子两瓶水。',2)==c
    assert m.audit_issues(report,body,c,'facts')==[]
    body=body.replace('她分给孩子两瓶水','她分给孩子一瓶水')
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest()
    report['event_observations'][-1]['quote']=span('她分给孩子一瓶水')
    report['resource_observations'][0]['money_observations'][0]['paid']=span('一瓶')
    report['resource_observations'][0]['balance_observations'][0]['quote']={'text':'一瓶','occurrence':2}
    assert any(i['category']=='resources' for i in m.audit_issues(report,body,c,'facts'))


def test_omitted_resource_proof_or_invalid_resource_plan_cannot_pass():
    c,body,report=resource_case();report.pop('resource_observations')
    with pytest.raises(ValueError):module().audit_issues(report,body,c,'facts')
    c['resource_ledgers'][0]['transfers'][0]['balance']=2
    with pytest.raises(ValueError):module().validate_contract(c,SOURCES+'现有三瓶水，分给孩子两瓶水。',2)


def test_resource_ordinals_identify_one_item_not_the_ordinal_quantity():
    m=module()
    assert m.amount('第二枚',{'枚':1})==1
    assert m.amount('第一枚和第二枚',{'枚':1})==2
    assert m.amount('十二枚',{'枚':1})==12


def test_explicit_zero_balance_does_not_require_a_repeated_unit():
    m=module()
    assert m.amount('可用模块，零。',{'枚':1})==0
    assert m.amount('零',{'瓶':1})==0
    with pytest.raises(ValueError):m.amount('零号基地',{'枚':1})
