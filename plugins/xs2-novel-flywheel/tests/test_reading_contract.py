import copy
import importlib.util
import json
import pytest
from test_book_contract import PLUGIN,helper,put


def module():
    path=PLUGIN/'resources/script-library/xs2/prose_policy/reading_contract.py'
    assert path.is_file(),'Missing adopted reading goals contract'
    spec=importlib.util.spec_from_file_location('reading_contract_test',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def definition():
    return {'dimension':'opening_promise','intent':'让开篇的异常形成值得追问的问题。',
        'planning_question':'本书开篇让读者想知道什么？','acceptance_question':'前文疑问是否由真实叙事发展回应？','limits':['允许安静和抒情的开篇。']}


def adopt(root,definitions=None):
    m=helper();defs=definitions if definitions is not None else [definition()]
    blueprint={'schema':'xs2.project.learning.blueprint.v1','version':1,'selected_candidate_ids':['mechanism-opening'],
        'mechanisms':[{'candidate_id':'mechanism-opening','mechanism':'异常带动选择','transfer_guidance':'以本书自己的异常影响选择。',
            'scopes':['mvp','polish'],'application_scope':['general'],'reading_objectives':defs}]}
    put(root,'learning/blueprints/v0001.json',blueprint)
    put(root,'learning/active.json',{'version':1,'blueprint_path':'learning/blueprints/v0001.json','blueprint_sha256':m.digest(blueprint)})
    return blueprint


def checks(contract,status='pass'):
    return [{'goal_id':g['id'],'status':status,'priority':'medium','excerpts':['风停了。'],
        'reason':'本段提出的变化有阅读作用。','style_basis':'保留本书安静的叙述方式。'} for g in contract['objectives']]


def test_unselected_candidates_do_not_create_requirements_or_change_book_style(tmp_path):
    put(tmp_path,'learning/candidates.json',{'candidates':[{'reading_objectives':[definition()]}]})
    put(tmp_path,'.novel-project.json',{'values':{'genre':'玄幻','narrator_scope':'omniscient','style_intent':'缓慢抒情'}})
    assert module().for_book(tmp_path) is None
    contract=helper().resolve(tmp_path)
    assert 'reading_contract' not in contract and contract['style_intent']=='缓慢抒情'


def test_selected_goals_are_frozen_but_blind_reader_gets_no_private_answers(tmp_path):
    item=definition();item['planning_question']='私密答案：丢失的信其实被主角烧毁。';adopt(tmp_path,[item])
    m=module();contract=m.for_book(tmp_path)
    assert len(contract['objectives'])==1
    book=helper().resolve(tmp_path)
    assert book['reading_contract']==contract
    public=helper().public_style(book)['reading_contract']
    assert '私密答案' not in json.dumps(public,ensure_ascii=False)
    assert public['objectives'][0]['id']==contract['objectives'][0]['id']
    frozen=helper().freeze(tmp_path,'goal-frozen')
    adopt(tmp_path,[{**definition(),'intent':'改为另一种阅读期待。'}])
    with pytest.raises(ValueError):helper().freeze(tmp_path,'goal-frozen')


def test_goal_adoption_does_not_revoke_historical_fact_archive_identity(tmp_path):
    from test_composition_plan import module as composition
    archive=composition().support.archive_store()
    before=archive.contract(tmp_path,persistent=True)
    adopt(tmp_path)
    assert archive.contract(tmp_path,persistent=True)==before


@pytest.mark.parametrize('defect',['missing','unknown','fake_quote','duplicate'])
def test_every_selected_goal_requires_current_prose_and_real_identity(tmp_path,defect):
    adopt(tmp_path);m=module();contract=m.for_book(tmp_path);rows=checks(contract)
    if defect=='missing':rows=[]
    elif defect=='unknown':rows[0]['goal_id']='invented'
    elif defect=='fake_quote':rows[0]['excerpts']=['正文不存在这句话。']
    else:rows*=2
    with pytest.raises(ValueError):m.validate_checks({'reading_checks':rows},'风停了。',contract)


def test_reading_failure_stays_blocking_when_facts_and_expression_pass(tmp_path):
    adopt(tmp_path);m=module();contract=m.for_book(tmp_path)
    report={'verdict':'pass','issues':[],'reading_checks':checks(contract,'revise')}
    issues=m.validate_checks(report,'风停了。',contract)
    assert len(issues)==1 and issues[0]['priority']=='medium'
    assert issues[0]['source']=='reading_contract'


def test_tampered_blueprint_and_unselected_goal_are_not_silently_adopted(tmp_path):
    m=module();blueprint=adopt(tmp_path);blueprint['mechanisms'][0]['reading_objectives'][0]['intent']='未经采用的新目标'
    put(tmp_path,'learning/blueprints/v0001.json',blueprint)
    with pytest.raises(ValueError):m.for_book(tmp_path)


@pytest.mark.parametrize('genre,scope',[('古风','variable'),('言情','limited'),('末日','omniscient'),('科幻','unreliable'),('玄幻','preserve')])
def test_selected_goal_does_not_replace_genre_or_narration(tmp_path,genre,scope):
    adopt(tmp_path);put(tmp_path,'.novel-project.json',{'values':{'genre':genre,'narrator_scope':scope,'style_intent':'保留议论与有意复沓。'}})
    c=helper().resolve(tmp_path)
    assert c['genre']==genre and c['narrator_scope']==scope and c['style_intent']=='保留议论与有意复沓。'
    assert c['reading_contract']['objectives']
