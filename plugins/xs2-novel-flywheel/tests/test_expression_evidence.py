import copy
import importlib.util
from pathlib import Path
import pytest

PLUGIN=Path(__file__).resolve().parents[1]
BODY='她笑了。\n\n“潮水会回来。”\n\n她已约好明日相见。'


def module():
    p=PLUGIN/'resources/script-library/xs2/prose_policy/expression_review.py'
    s=importlib.util.spec_from_file_location('expression_evidence_tests',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def checks(m):
    scene_dimensions=getattr(m,'SCENE_DIMENSIONS',())
    return [{'dimension':key,'status':'not_applicable' if key in scene_dimensions else 'pass',
             'excerpts':[] if key in scene_dimensions else ['她笑了。'],'reason':'此处回应了当下的见面选择，未再次释义。',
             'style_basis':'本书允许抒情与回环。','issue_ids':[]} for key in m.DIMENSIONS]


@pytest.mark.parametrize('dimension, category', [
    ('scene_conflict_progression', 'scene_conflict_stall'),
    ('aftermath_transition', 'aftermath_transition_flat'),
])
def test_scene_review_requires_ordered_evidence_and_gives_legacy_reports_a_read_path(dimension, category):
    m=module()
    previous=[row for row in checks(m) if row['dimension'] not in ('scene_conflict_progression','aftermath_transition')]
    assert m.validate_checks({'expression_checks':previous},BODY)==previous
    rows=checks(m)
    first,middle,last=BODY.split('\n\n')
    target=next(row for row in rows if row['dimension']==dimension)
    target.update(status='pass',excerpts=[first,last])
    report={'expression_checks':rows,'issues':[]}
    m.validate_checks(report,BODY)
    target['excerpts']=[last,first]
    with pytest.raises(ValueError,match='整场'):
        m.validate_checks(report,BODY)
    issue={'category':category,'id':'scene-1','excerpts':[first,middle,last]}
    report['issues']=[issue]
    target.update(status='issue',issue_ids=['scene-1'],excerpts=[first,last])
    with pytest.raises(ValueError,match='整场'):
        m.validate_checks(report,BODY)
    target['excerpts']=[first,middle,last]
    m.validate_checks(report,BODY)
    m.validate_narrative_issue(issue)
    issue['excerpts']=[first,first[:-1],last]
    with pytest.raises(ValueError,match='三处'):
        m.validate_narrative_issue(issue)


def test_expression_checks_require_actual_text_and_book_style_reason():
    m=module();report={'issues':[],'expression_checks':checks(m)}
    assert m.validate_checks(report,BODY,required=True)==report['expression_checks']
    for key,value in [('excerpts',['编造的动作。']),('style_basis',''),('reason','')]:
        wrong=copy.deepcopy(report);wrong['expression_checks'][0][key]=value
        with pytest.raises(ValueError):m.validate_checks(wrong,BODY,required=True)


def test_expression_dimensions_cannot_be_omitted_or_bypassed_with_na():
    m=module();report={'issues':[],'expression_checks':checks(m)}
    report['expression_checks'].pop()
    with pytest.raises(ValueError):m.validate_checks(report,BODY,required=True)
    report['expression_checks']=checks(m)
    row=next(r for r in report['expression_checks'] if r['dimension']=='voice_alignment');row.update(status='not_applicable',excerpts=[])
    with pytest.raises(ValueError):m.validate_checks(report,BODY,required=True)


def test_expression_issue_checks_must_link_a_real_finding():
    m=module();report={'issues':[],'expression_checks':checks(m)}
    report['expression_checks'][0].update(status='issue',issue_ids=['missing'])
    with pytest.raises(ValueError):m.validate_checks(report,BODY,required=True)
    report['issues']=[{'id':'missing'}]
    m.validate_checks(report,BODY,required=True)


def test_legacy_reviews_stay_readable_and_style_is_not_a_word_blacklist():
    m=module();assert m.validate_checks({},BODY)==[]
    report={'issues':[],'expression_checks':checks(m)}
    report['expression_checks'][0]['excerpts']=['“潮水会回来。”']
    m.validate_checks(report,BODY,required=True)
