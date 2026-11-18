from test_length_quality import policy, quality, write


def test_exhausted_length_budget_is_advisory_and_preserves_source(tmp_path):
    write(tmp_path,'story/0001/chapter.md','甲'*4984)
    state={'lengthRepairCount':2,'lengthRepairTotal':2,'lengthRepairCycle':0,'readerRepairCount':0,
           'lengthRepairStrategy':quality().LENGTH_REPAIR_STRATEGY,
           'values':{'chapter_number':'0001','target_word_count':'5000-5300'}}
    action=policy().next_action(tmp_path,state,'polish')
    assert action['stage']=='post-hoc' and action['updates']['lengthRepairFeedback']=={}
    state.update(action['updates'])
    assert state['lengthCheck']['actual']==4984 and state['lengthCheck']['status']=='short'
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')=='甲'*4984


def test_historical_repair_counts_do_not_trigger_new_length_work(tmp_path):
    write(tmp_path,'story/0001/chapter.md','甲'*4984)
    state={'lengthRepairCount':2,'lengthRepairTotal':6,'lengthRepairCycle':2,'readerRepairCount':2,
           'lengthRepairStrategy':quality().LENGTH_REPAIR_STRATEGY,
           'values':{'chapter_number':'0001','target_word_count':'5000-5300'}}
    action=policy().next_action(tmp_path,state,'polish')
    assert action['stage']=='post-hoc'
    assert 'lengthRepairTotal' not in action['updates']
