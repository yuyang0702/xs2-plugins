import hashlib
import importlib.util
from pathlib import Path

import pytest

PLUGIN=Path(__file__).resolve().parents[1]


def helper():
    path=PLUGIN/'resources/script-library/xs2/multi_scene/audit_evidence.py'
    assert path.is_file(),'missing current-body evidence references'
    spec=importlib.util.spec_from_file_location('audit_evidence_tests',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


BODY='他先同意。她点收六两。她付一两二钱，余四两八钱。'
UNITS={'两':1000,'钱':100,'文':1}


def test_reference_ids_resolve_exact_current_quotes_and_amount_ranges():
    m=helper();rows=m.catalog(BODY,UNITS)
    one=next(r for r in rows if r['kind']=='amount' and r['text']=='一两')
    two=next(r for r in rows if r['kind']=='amount' and r['text']=='二钱')
    report=m.resolve_report({'money_observations':[{'paid':{'start_ref':one['id'],'end_ref':two['id']}}]},BODY,UNITS)
    assert report['money_observations'][0]['paid']=={'text':'一两二钱','occurrence':1}
    clause=next(r for r in rows if r['kind']=='clause' and '点收' in r['text'])
    assert m.resolve_report({'issues':[{'excerpts':[{'ref_id':clause['id']}]}]},BODY,UNITS)['issues'][0]['excerpts']==[clause['text']]


def test_bad_reference_or_literal_quote_reports_its_exact_field_path():
    for quote in [{'ref_id':'c9999'},{'text':'别的稿子','occurrence':1}]:
        with pytest.raises(ValueError,match=r'event_observations\[0\].quote'):
            helper().resolve_report({'event_observations':[{'quote':quote}]},BODY,UNITS)


def test_reference_range_cannot_run_backwards():
    rows=helper().catalog(BODY,UNITS)
    with pytest.raises(ValueError):helper().resolve_report({'quote':{'start_ref':rows[-1]['id'],'end_ref':rows[0]['id']}},BODY,UNITS)


def test_legacy_literal_quotes_remain_compatible():
    assert helper().resolve_report({'quote':{'text':'她点收六两','occurrence':1}},BODY,UNITS)=={'quote':{'text':'她点收六两','occurrence':1}}


def test_references_still_require_matching_candidate_hash():
    from test_continuity_contract import contract,evidence,module
    body,report=evidence();report['event_observations'][0]['quote']={'ref_id':'c0001'}
    with pytest.raises(ValueError,match='不匹配'):module().audit_issues(report,body+'改',contract(),'facts')


def test_amount_reference_keeps_the_ordinal_marker_for_exact_counting():
    rows=helper().catalog('把第二枚电源装上。',{'枚':1})
    assert [r['text'] for r in rows if r['kind']=='amount']==['第二枚']


def test_standalone_zero_gets_a_reference_without_reading_a_name_as_zero():
    rows=helper().catalog('零号基地里，可用模块，零。',{'枚':1})
    assert [r['text'] for r in rows if r['kind']=='amount']==['零']
