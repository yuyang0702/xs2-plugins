from test_quick_adoption import run_job,catalog,decision
from test_reading_contract import definition,module


def test_console_cannot_drop_adopted_reading_goals(tmp_path):
    library=catalog();library['candidates']['candidates'][0]['reading_objectives']=[definition()]
    _,_,_,result=run_job(tmp_path,libraries=[library])
    assert result['status']=='review_required'
    assert not (tmp_path/'learning/active.json').exists()


def test_console_publishes_reviewed_book_specific_goals(tmp_path):
    library=catalog();library['candidates']['candidates'][0]['reading_objectives']=[definition()]
    adapted=definition();adapted['intent']='矿井题材的开篇追问须符合本书知情范围。'
    _,_,_,result=run_job(tmp_path,libraries=[library],response={'decisions':[decision(adapted_reading_objectives=[adapted])],'voice_adaptations':[]})
    assert result['status']=='applied'
    assert module().for_book(tmp_path)['objectives'][0]['intent']==adapted['intent']


def test_compatibility_review_cannot_publish_a_source_quotation_as_goal():
    import json
    import pytest
    from test_quick_adoption import service
    import sys
    m=sys.modules[service().ReferenceAdoptionJobs.__module__];quote='夜里所有的钟都在四点十三分停住，只有母亲的旧怀表继续走着。'
    library=catalog();candidate=library['candidates']['candidates'][0]
    candidate['reading_objectives']=[definition()];candidate['evidence']=[{'excerpt':quote}]
    selected=list(m._catalog_items([library]))
    copied=definition();copied['intent']=quote
    with pytest.raises(m.ReviewRequired,match='20字来源'):
        m._parse_review(json.dumps({'decisions':[decision(adapted_reading_objectives=[copied])],'voice_adaptations':[]},ensure_ascii=False),
            selected,{'values':{}},{})
