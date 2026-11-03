import json
from test_length_quality import quality,policy,write

def test_large_gap_has_portable_multparagraph_source_and_small_gap_stays_local():
    q=quality();raw=('\n\n'.join('“'+chr(0x4e00+i)*50+'”' for i in range(60))).encode('utf-8')
    result={'status':'short','actual':3000,'lower':4600,'upper':5000}
    spec=q.fragment_anchor(raw,result)
    assert 800<=q.count_prose(raw[spec['start']:spec['end']].decode('utf-8'))<=1350
    short=q.fragment_anchor(raw,{**result,'lower':3100,'upper':3300})
    assert q.count_prose(raw[short['start']:short['end']].decode('utf-8'))==50


def test_scene_and_previous_range_bound_small_window_with_partial_request():
    q=quality();raw=('\n\n'.join('甲'*50 for _ in range(8))+'\n\n***\n\n'+'\n\n'.join('乙'*50 for _ in range(8))).encode('utf-8')
    result={'status':'short','actual':800,'lower':2400,'upper':2600}
    spec=q.fragment_anchor(raw,result);selected=raw[spec['start']:spec['end']].decode('utf-8');count=q.count_prose(selected)
    assert '***' not in selected and count<=360
    assert spec['requested_net_upper']<=2*count
    blocked=[spec['start'],spec['end']]
    following=q.fragment_anchor(raw,result,blocked)
    assert following['end']<=blocked[0] or following['start']>=blocked[1]
    assert '***' not in raw[following['start']:following['end']].decode('utf-8')


def test_v5_contract_migrates_once_preserving_total_and_hard_limit(tmp_path):
    write(tmp_path,'story/0001/chapter.md','衣'*3188)
    state={'readerRepairCount':0,'lengthRepairCycle':0,'lengthRepairCount':3,'lengthRepairTotal':3,'lengthRepairStrategy':'fragment-v5','autoLengthRepairLimit':3,'values':{'chapter_number':'0001','target_word_count':'4800-5200'}}
    state.update(policy().next_action(tmp_path,state,'polish')['updates'])
    assert state['lengthRepairStrategy']==quality().LENGTH_REPAIR_STRATEGY=='fragment-v6'
    assert state['lengthRepairTotal']==4 and state['lengthRepairMigration']['from']=='fragment-v5'
    for _ in range(2):state.update(policy().next_action(tmp_path,state,'polish')['updates'])
    assert policy().next_action(tmp_path,state,'polish')['action']=='pause' and state['lengthRepairTotal']==6


def test_large_window_partial_commit_preserves_every_outside_raw_byte(tmp_path):
    from test_fragment_length import commit
    q=quality();raw=b'\xef\xbb\xbf'+('\r\n\r\n'.join('“'+chr(0x4e00+i)*50+'”' for i in range(60))).encode('utf-8')
    path=write(tmp_path,'story/0001/chapter.md','');path.write_bytes(raw)
    write(tmp_path,'quality/author.md','保留原有交涉事实和结果')
    state={'values':{'chapter_number':'0001','target_word_count':'4800-5200','author_feedback_file':'quality/author.md'}}
    state.update(policy().next_action(tmp_path,state,'polish')['updates']);write(tmp_path,'.novel-project.json',json.dumps(state,ensure_ascii=False))
    outputs=q.prepare_execution(tmp_path,'0001','4800-5200','length_only')
    guard=json.loads((tmp_path/outputs['length_commit_guard']).read_text(encoding='utf-8'));spec=guard['fragment']
    candidate=raw[spec['start']:spec['end']].decode('utf-8')+'丁'*200
    _,receipt=commit(tmp_path,outputs,candidate,'task-window-partial')
    assert receipt['accepted'] and receipt['status']=='accepted_partial' and receipt['actual']==3200
    assert path.read_bytes()==raw[:spec['start']]+candidate.encode('utf-8')+raw[spec['end']:]
