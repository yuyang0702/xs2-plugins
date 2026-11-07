import json
import os
import pytest
from test_fragment_length import setup,commit
from test_length_quality import quality,policy,write


def selected(root,outputs):
    guard=json.loads((root/outputs['length_commit_guard']).read_text(encoding='utf-8'))
    raw=(root/guard['body_path']).read_bytes();spec=guard['fragment']
    return guard,raw[spec['start']:spec['end']].decode('utf-8')


def test_short_expands_frozen_span_preserving_outside_bytes_and_bom(tmp_path):
    raw=b'\xef\xbb\xbf'+('甲'*35+'\r\n\r\n“'+'乙'*35+'”\r\n\r\n'+'丙'*35).encode('utf-8')
    state,outputs,_=setup(tmp_path,raw);guard,old=selected(tmp_path,outputs)
    assert guard['fragment']['kind']=='expand'
    _,receipt=commit(tmp_path,outputs,old+'丁'*10)
    body=(tmp_path/'story/0001/chapter.md').read_bytes();spec=guard['fragment']
    assert body==raw[:spec['start']]+(old+'丁'*10).encode('utf-8')+raw[spec['end']:]
    assert receipt['accepted'] and receipt['status']=='accepted_partial' and receipt['actual']==115
    review=json.loads((tmp_path/'quality/length-attempts/0001/task-fragment-test/review-input.json').read_text(encoding='utf-8'))
    assert review['operation']=='expand' and review['selected_text']==old


@pytest.mark.parametrize('mode',['no_progress','too_big','echo_outside'])
def test_expansion_rejects_unsafe_candidate_without_touching_body(tmp_path,mode):
    _,outputs,raw=setup(tmp_path);guard,old=selected(tmp_path,outputs)
    body=tmp_path/'story/0001/chapter.md';os.utime(body,(1000000000,1000000000));mtime=body.stat().st_mtime_ns
    candidate={'no_progress':old,'too_big':old+'丁'*200,'echo_outside':old+'丁'*10+'甲'*35}[mode]
    _,receipt=commit(tmp_path,outputs,candidate)
    assert not receipt['accepted'] and body.read_bytes()==raw and body.stat().st_mtime_ns==mtime


def test_v4_contract_migration_once_preserves_totals_profile_and_caps(tmp_path):
    write(tmp_path,'story/0001/chapter.md','衣'*3375)
    state={'readerRepairCount':0,'lengthRepairCycle':0,'lengthRepairCount':3,'lengthRepairTotal':9,'lengthRepairStrategy':'fragment-v4','writerModel':'anthropic:existing','lengthRepairModel':'anthropic:existing','autoLengthRepairLimit':3,'values':{'chapter_number':'0001','target_word_count':'4800-5200'}}
    state.update(policy().next_action(tmp_path,state,'polish')['updates'])
    assert state['lengthRepairStrategy']==quality().LENGTH_REPAIR_STRATEGY=='fragment-v6'
    assert state['lengthRepairTotal']==10 and state['lengthRepairCount']==1 and state['lengthRepairModel']=='anthropic:existing'
    for _ in range(2):state.update(policy().next_action(tmp_path,state,'polish')['updates'])
    assert policy().next_action(tmp_path,state,'polish')['stage']=='reader-sim' and state['lengthRepairTotal']==12


def test_next_expansion_avoids_entire_previous_multiline_output_range(tmp_path):
    state,outputs,raw=setup(tmp_path);guard,old=selected(tmp_path,outputs)
    _,receipt=commit(tmp_path,outputs,old+'\n\n'+'丁'*10)
    assert receipt['accepted']
    state.update(policy().next_action(tmp_path,state,'polish')['updates']);write(tmp_path,'.novel-project.json',json.dumps(state,ensure_ascii=False))
    next_outputs=quality().prepare_execution(tmp_path,'0001','130-160','length_only')
    new,_=selected(tmp_path,next_outputs)
    start,end=receipt['expanded_span_range']
    assert new['fragment']['end']<=start or new['fragment']['start']>=end


def test_unbounded_paragraph_uses_bounded_sentence_or_refuses():
    q=quality();raw=('甲'*200+'。'+'乙'*200+'。'+'丙'*200+'。').encode('utf-8')
    spec=q.fragment_anchor(raw,{'status':'short'})
    assert spec['kind']=='expand' and q.count_prose(raw[spec['start']:spec['end']].decode('utf-8'))<=400
    with pytest.raises(ValueError):q.fragment_anchor(('甲'*600).encode('utf-8'),{'status':'short'})


def test_no_fresh_paragraph_never_falls_back_inside_previous_output():
    q=quality();raw=('甲'*600+'\n\n'+'乙'*35+'\n\n'+'丁'*10+'\n\n'+'丙'*600).encode('utf-8')
    previous=[len(('甲'*600+'\n\n').encode('utf-8')),len(('甲'*600+'\n\n'+'乙'*35+'\n\n'+'丁'*10).encode('utf-8'))]
    with pytest.raises(ValueError):q.fragment_anchor(raw,{'status':'short'},previous)


def test_no_fresh_paragraph_uses_safe_sentence_outside_previous_output():
    q=quality();prefix='甲'*200+'。'+'乙'*200+'。'+'丙'*200+'。\n\n';raw=(prefix+'丁'*35).encode('utf-8')
    previous=[len(prefix.encode('utf-8')),len(raw)]
    spec=q.fragment_anchor(raw,{'status':'short'},previous)
    assert spec['end']<=previous[0] and q.count_prose(raw[spec['start']:spec['end']].decode('utf-8'))<=400


def test_actual_reviewer_prompt_distinguishes_retained_span_from_outside_repetition(monkeypatch):
    import copy
    from test_length_quality import PLUGIN
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder
    agents=json.loads((PLUGIN/'resources/agents.json').read_text(encoding='utf-8'))['agents']
    prompts=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf-8'))['agents']
    agent=AgentDefinition(agent_type='xs2-fragment-reviewer',**agents['xs2-fragment-reviewer'])
    monkeypatch.setattr('src.agent.definition.get_agent_definition',lambda key:agent)
    class Manager:
        def get_sections(self,key):return copy.deepcopy(prompts[key]['sections'])
    final=PromptBuilder(Manager()).build(agent.agent_type,is_workflow=True,include_skills=False,include_rules=False)
    assert 'operation=expand' in final and '保留、复用原段原句是正确行为' in final
    assert '遗漏或改变（continuity）' in final and '选定原段以外正文' in final
    assert '隐藏证据' in final and '焦点所知' in final
