import copy
import json
import pytest
from test_book_contract import put
from test_local_revision import setup,patch,approved,BODY


def test_wrong_goal_id_requires_targeted_reassessment_not_automatic_remapping(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    context['goals']=[{'id':'goal-current','goal':'保留本书回环。'}]
    repair=m.report_repair.request({'issue_outcomes':[{'id':'wrong-id'}],'compatible':True},context,'原有实质问题未逐项复核')
    assert repair['allowed_fields']==['issue_outcomes'] and repair['previous_actual_report']['issue_outcomes'][0]['id']=='wrong-id'
    updated={'issue_outcomes':[{'id':'goal-current'}],'compatible':True}
    m.report_repair.verify(updated,repair,context)
    updated['compatible']=False
    with pytest.raises(ValueError):m.report_repair.verify(updated,repair,context)
    assert m.report_repair.request({},context,'事实结论与问题列表不一致') is None
    assert m.report_repair.request({'reading_checks':[{'goal_id':'wrong'}]},context,'阅读目标编号未知或重复')['allowed_fields']==['reading_checks']


def test_targeted_retry_keeps_real_prior_output_and_still_checks_full_verdict(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    bad=json.loads(approved(m,out,tmp_path));bad['expression_checks']=[]
    put(tmp_path,out['revision_review_path'],bad)
    with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],json.dumps(bad,ensure_ascii=False))
    repair=json.loads((tmp_path/out['revision_review_repair']).read_text(encoding='utf8'))
    assert repair['previous_actual_report']==bad and repair['allowed_fields']==['expression_checks']
    good=json.loads(approved(m,out,tmp_path));put(tmp_path,out['revision_review_path'],good)
    receipt=m.commit(tmp_path,out['revision_dir'],json.dumps(good,ensure_ascii=False))
    assert receipt['accepted']
