import json

from test_length_quality import policy, quality, write


def test_rejected_length_budget_escalates_to_reader_and_planner_without_exporting(tmp_path):
    write(tmp_path,'story/0001/chapter.md','甲'*4984)
    state={'lengthRepairCount':2,'lengthRepairTotal':2,'lengthRepairCycle':0,'readerRepairCount':0,
           'lengthRepairStrategy':quality().LENGTH_REPAIR_STRATEGY,
           'values':{'chapter_number':'0001','target_word_count':'5000-5300'}}
    action=policy().next_action(tmp_path,state,'polish')
    assert action['action']=='advance' and action['stage']=='reader-sim'
    state.update(action['updates'])
    assert state['lengthCheck']['actual']==4984 and state['lengthCheck']['status']=='short'
    write(tmp_path,'story/0001/reader_report.json',json.dumps({'verdict':'pass','continue_reading_score':90,'issues':[]}))
    next_step=policy().next_action(tmp_path,state,'reader-sim')
    assert next_step['action']=='repair'


def test_exhausted_content_repair_budget_still_pauses_without_unbounded_restart(tmp_path):
    write(tmp_path,'story/0001/chapter.md','甲'*4984)
    state={'lengthRepairCount':2,'lengthRepairTotal':6,'lengthRepairCycle':2,'readerRepairCount':2,
           'lengthRepairStrategy':quality().LENGTH_REPAIR_STRATEGY,
           'values':{'chapter_number':'0001','target_word_count':'5000-5300'}}
    assert policy().next_action(tmp_path,state,'polish')['action']=='pause'
