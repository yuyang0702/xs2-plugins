import copy
import json
import pytest
from test_book_contract import put
from test_reading_contract import adopt,checks
from test_composition_plan import module as composition
from test_reader_review_p0 import review as reader
from test_local_revision import setup,patch,approved


def planned(root):
    adopt(root)
    put(root, 'planning/chapters/0001.json', {'reference_ids': ['mechanism-opening']})
    put(root,'.novel-project.json',{'mode':'short','values':{'chapter_number':'0001','target_word_count':'100-200'}})
    m=composition();r=m.prepare(root,'0001','reading-plan','100-200',ownership='author')
    assert r['enabled']
    p={'request_digest':r['request_digest'],'status':'ready','reason':'安静的开篇也可承载期待。','minimum':100,'maximum':200,
       'segments':[{'id':'s1','purpose':'形成期待','development':'观察与选择','minimum':100,'maximum':200}]}
    return m,r,p


def test_reference_alone_does_not_enable_length_planner(tmp_path):
    adopt(tmp_path)
    assert composition().prepare(tmp_path,'0001','reading-plan','100-200')=={'enabled':False}


def test_independently_enabled_planner_can_skip_reference_goals(tmp_path):
    m,r,p=planned(tmp_path)
    assert r['author_range']==[100,200]
    m.validate_plan(r,p)
    goal=r['book_contract']['reading_contract']['objectives'][0]
    p['goal_plans']=[{'goal_id':goal['id'],'status':'planned','segment_ids':['s1'],'reader_start':'有一个疑问',
        'reader_end':'新的理解','basis':'当前本书允许安静开篇，以选择承载变化。'}]
    m.validate_plan(r,p)
    v={'request_digest':r['request_digest'],'plan_digest':m.identity(p),'verdict':'approve','scope_preserved':True,
       'length_feasible':True,'reason':'作者范围不变。','checks':[{'segment_id':'s1','develops_function':True,'style_basis':'安静开篇','reason':'产生期待'}]}
    m.accept(tmp_path,'reading-plan',p,v)
    v['goal_checks']=[{'goal_id':goal['id'],'supported':False,'reason':'本场可略过范文做法','style_basis':'本书开篇允许安静'}]
    m.accept(tmp_path,'reading-plan',p,v)
    assert m.current(tmp_path,'0001')['plan']['goal_plans']==p['goal_plans']
    from test_reading_contract import definition
    d=definition();d['intent']='改用其他阅读目的。';adopt(tmp_path,[d])
    current=m.current(tmp_path,'0001')
    assert current['minimum']==100 and 'goal_plans' not in current['plan']


def test_blind_reading_reference_does_not_block():
    m=reader();contract={'objectives':[{'id':'r1','dimension':'opening_promise','intent':'阅读期待'}]}
    base={'verdict':'pass','summary':'安静。','issues':[],'decisions':[]}
    assert m.validate_blind(base,'风停了。',contract)==base
    base['reading_checks']=checks(contract,'revise')
    result=m.validate_blind(base,'风停了。',contract)
    assert result['verdict']=='pass' and result['issues'][0]['source']=='reading_contract'
    assert m.validate_blind(result,'风停了。',contract)==result


def test_local_review_can_pass_without_applying_selected_reference(tmp_path):
    adopt(tmp_path)
    put(tmp_path, 'planning/chapters/0001.json', {'reference_ids': ['mechanism-opening']})
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    report=json.loads(approved(m,out,tmp_path))
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert m.review_decision(report,context)==[]
    report['reading_checks']=checks(context['book_contract']['reading_contract'],'revise')
    report['reading_checks'][0]['excerpts']=['第一段保留。']
    assert m.review_decision(report,context)==[]


def test_blind_reference_comment_remains_advisory_on_contextual_reread():
    from test_reader_review_p0 import final
    m=reader();contract={'objectives':[{'id':'r1','dimension':'opening_promise','intent':'阅读期待'}]}
    body='风停了。'
    initial={'verdict':'pass','summary':'阅读期待仍不成立。','issues':[],'decisions':[],
             'reading_checks':checks(contract,'revise')}
    blind=m.validate_blind(initial,body,contract)
    contextual=final();contextual.update(verdict='pass',issues=[],blind_resolutions=[])
    contextual['fact_review']={'verdict':'pass','summary':'无冲突。'}
    contextual['expression_review']={'verdict':'pass','summary':'本书声音成立。','issues':[]}
    contextual['revision_scope']={'mode':'unrestricted','summary':'整篇可改','assessments':[]}
    contextual.pop('expression_checks',None)
    contextual['reading_checks']=checks(contract,'pass')
    merged=m.merge_review(contextual,blind,body,contract)
    assert merged['verdict']=='pass' and merged['issues'][0]['source']=='blind_review'
    assert m.gate_review(merged,body)==merged


def test_workflow_exposes_safe_focus_and_all_gate_schemas():
    from test_book_contract import PLUGIN
    wf=json.loads((PLUGIN/'resources/workflows/reference-distillation/definition.json').read_text(encoding='utf8'))
    split=next(n for n in wf['nodes'] if n['id']=='script_split_reference')['node_params']
    assert '--learning-direction' in split['script_argv'] and 'script_args' not in split
    assert next(v for v in wf['variables'] if v['key']=='learning_direction')['default']=='general'
    options=next(v for v in wf['variables'] if v['key']=='learning_direction')['options']
    assert all(isinstance(row,dict) and row.get('name') and row.get('value') for row in options)
    assert next(row for row in options if row['value']=='zhihu_short')['name']=='知乎短篇'
    for name,ids in [('reader-sim',['agent_blind_reader']),('mvp',['agent_guard_expression_audit'])]:
        wf=json.loads((PLUGIN/f'resources/workflows/{name}/definition.json').read_text(encoding='utf8'))
        for id in ids:
            node=next(n for n in wf['nodes'] if n['id']==id)
            schema=node['node_params']['json_output_schema']
            assert all('reading_checks' in arm['properties'] and 'reading_checks' not in arm.get('required', [])
                       for arm in schema.get('anyOf',[schema]))
            if name == 'reader-sim':
                assert 'reading_checks 可省略' in node['first_message']
    polish = json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    reviewer = next(n for n in polish['nodes'] if n['id']=='agent_local_review')
    assert 'reading_checks' not in reviewer['node_params']['json_output_schema']['properties']


def test_custom_goal_stays_private_and_contextual_comment_is_optional():
    m=reader();contract={'objectives':[{'id':'r1','dimension':'custom','intent':'私有答案不会告知盲读。'}]}
    public=m.book_contract.reading().public(contract)
    assert public['objectives']==[]
    base={'verdict':'pass','summary':'风停了。','issues':[],'decisions':[]}
    m.validate_blind(base,'风停了。',public)
    assert m.book_contract.reading().validate_checks(base,'风停了。',contract)==[]


def test_saved_reference_only_rejection_no_longer_blocks_but_fact_issue_does():
    m=reader();contract={'objectives':[{'id':'r1','dimension':'opening_promise','intent':'阅读期待'}]}
    report=m.validate_blind({'verdict':'pass','summary':'安静。','issues':[],'decisions':[],
        'reading_checks':checks(contract,'revise')},'风停了。',contract)
    report['issues'][0]['priority']='medium'
    report['verdict']='revise'
    assert m.validate_blind(report,'风停了。',contract)['verdict']=='pass'
    report['issues'].append({'id':'fact-1','kind':'fact','priority':'high','excerpts':['风停了。'],
        'location':'开头','impact':'与叙事已知天气事实冲突。','goal':'保留天气事实。'})
    assert m.validate_blind(report,'风停了。',contract)['verdict']=='revise'


def test_author_envelope_and_internal_budgets_are_distinct_without_relaxing_either(tmp_path):
    m,r,p=planned(tmp_path)
    # The hard envelope is unchanged. Internal development estimates can be
    # narrower, rather than allocating the entire permitted slack to prose.
    p['segments']=[{'id':'s1','purpose':'期待','development':'观察','minimum':110,'maximum':170}]
    g=r['book_contract']['reading_contract']['objectives'][0]
    p['goal_plans']=[{'goal_id':g['id'],'status':'planned','segment_ids':['s1'],
        'reader_start':'疑问','reader_end':'理解','basis':'保留本书安静的观察。'}]
    m.validate_plan(r,p)
    p['segments'][0]['minimum']=99
    with pytest.raises(ValueError,match='预算'):m.validate_plan(r,p)
    p['segments'][0].update(minimum=110,maximum=201)
    with pytest.raises(ValueError,match='预算'):m.validate_plan(r,p)
