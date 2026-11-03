import copy
import importlib.util
import json
from test_length_quality import PLUGIN, quality
from test_humanity_review import polish_post


def issue(quote):
    return {'dimension': 'CAUSALITY', 'severity': 'high', 'description': '已批准修复', 'impact': '因果不足', 'evidence': [quote]}


def test_only_one_paired_quote_wrapper_can_restore_exact_evidence_and_is_audited():
    original = {'feels_human': False, 'issues': [issue('“他接受条件。”')]}
    result = polish_post.normalize_critique(original, '他接受条件。随后落笔。')
    assert result['blocking_issues'] == [0]
    assert result['issues'][0]['evidence'] == original['issues'][0]['evidence']
    assert result['issues'][0]['evidence_repairs'] == [{'index': 0, 'repair': 'paired_outer_quote'}]
    assert 'evidence_status' not in original['issues'][0]


def test_ellipses_rewording_and_unpaired_quotes_stay_unverified():
    for quote in ['“他……落笔。”', '“他同意条件。”', '“他接受条件。', '““他接受条件。””']:
        report = polish_post.normalize_critique({'feels_human': False, 'issues': [issue(quote)]}, '他接受条件。随后落笔。')
        assert report['blocking_issues'] == []
        assert report['issues'][0]['evidence_status'] == 'unverified'


def test_actual_writer_prompts_distinguish_approved_plan_from_unverified_critic(monkeypatch):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder
    prompts = json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf-8'))['agents']
    agents = json.loads((PLUGIN/'resources/agents.json').read_text(encoding='utf-8'))['agents']
    for name in ['novel-polisher', 'novel-professional-polisher']:
        agent = AgentDefinition(agent_type=name, **agents[name])
        monkeypatch.setattr('src.agent.definition.get_agent_definition', lambda key, a=agent: a)
        class Manager:
            def get_sections(self, key): return copy.deepcopy(prompts[key]['sections'])
        prompt = PromptBuilder(Manager()).build(name, is_workflow=True, include_skills=False, include_rules=False)
        assert '已批准返修方案独立于审稿证据标签' in prompt
        assert '不能用unverified标签否决' in prompt
        assert '不等于盲信未核实的审稿判断' in prompt


def reviewed(root, body, report, task_id='task-review'):
    from test_fragment_length import setup
    state, outputs, raw = setup(root)
    write(root, 'cache/pp/body.json', json.dumps({'body': body}, ensure_ascii=False))
    binding = quality().prepare_fragment_review(root, '0001', outputs['length_expected_body_sha'], outputs['length_commit_guard'], outputs['length_commit_guard_sha'], task_id)
    binding['fragment_review_result']=json.dumps(report, ensure_ascii=False)
    write(root, binding['fragment_review_report_path'], binding['fragment_review_result'])
    return state, outputs, raw, binding


def write(root, relative, text):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');return path


def test_grounded_hidden_ledger_or_pov_rejected_without_body_change(tmp_path):
    body='她知道木箱里还有未毁的领用记录。'
    report={'compatible':False,'issues':[{'category':'new_fact','candidate_quote':body,'source_quote':'乙'*25,'reason':'原文只给可见场景，片段增加未展示记录'}]}
    state, outputs, raw, binding=reviewed(tmp_path,body,report)
    result=quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    receipt=json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf-8'))
    assert not receipt['accepted'] and 'new_fact' in receipt['rejection_reason']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_compatible_visible_action_passes_and_candidate_change_is_not_reviewed(tmp_path):
    body='丁'*30
    state,outputs,raw,binding=reviewed(tmp_path,body,{'compatible':True,'issues':[]})
    write(tmp_path,'cache/pp/body.json',json.dumps({'body':'ALTERED'},ensure_ascii=False))
    import pytest
    with pytest.raises(ValueError):quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_ungrounded_review_is_terminal_not_relabelled_compatible(tmp_path):
    report={'compatible':False,'issues':[{'category':'pov','candidate_quote':'NOT IN CANDIDATE','source_quote':'乙'*25,'reason':'不可靠引用'}]}
    state,outputs,raw,binding=reviewed(tmp_path,'丁'*30,report)
    import pytest
    with pytest.raises(ValueError):quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_reprepare_changed_candidate_keeps_original_review_input_bytes_and_mtime(tmp_path):
    state, outputs, raw, binding=reviewed(tmp_path,'丁'*30,{'compatible':True,'issues':[]})
    file=tmp_path/binding['fragment_review_input']; before=file.read_bytes(); stamp=file.stat().st_mtime_ns
    write(tmp_path,'cache/pp/body.json',json.dumps({'body':'NEW CANDIDATE'}))
    import pytest
    with pytest.raises(ValueError):quality().prepare_fragment_review(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review')
    assert file.read_bytes()==before and file.stat().st_mtime_ns==stamp


def test_changing_pov_after_review_refuses_commit(tmp_path):
    state,outputs,raw,binding=reviewed(tmp_path,'丁'*30,{'compatible':True,'issues':[]})
    state['values']['narrative_pov']='first_person'
    write(tmp_path,'.novel-project.json',json.dumps(state,ensure_ascii=False))
    import pytest
    with pytest.raises(ValueError):quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_legitimate_focus_sensation_passes_compatible_review(tmp_path):
    body='“'+'乙'*35+'”她指腹微微发酸，吸了口气，又把注意放回眼前。'
    state,outputs,raw,binding=reviewed(tmp_path,body,{'compatible':True,'issues':[]})
    result=quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    receipt=json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf-8'))
    assert receipt['accepted'] and receipt['actual']>quality().count_prose(raw.decode('utf-8'))


def test_review_source_edit_and_review_edit_are_never_published(tmp_path):
    state,outputs,raw,binding=reviewed(tmp_path,'丁'*30,{'compatible':True,'issues':[]})
    file=tmp_path/binding['fragment_review_input'];file.write_text(file.read_text(encoding='utf-8')+' ',encoding='utf-8')
    import pytest
    with pytest.raises(ValueError):quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_new_reviewer_inherits_default_and_is_not_repair_model_override():
    from test_focused_length import definition
    raw=definition();node=next(n for n in raw['nodes'] if n['id']=='agent_fragment_review')
    agents=json.loads((PLUGIN/'resources/agents.json').read_text(encoding='utf-8'))['agents']
    assert not node.get('model_override') and not agents[node['agent_type']].get('model')
    assert not agents[node['agent_type']].get('model_params')
    from test_length_quality import policy
    overrides=policy().model_overrides({'repairModel':'existing:model','readerRepairCount':1},raw,'polish')
    assert 'agent_fragment_review' not in overrides
    assert overrides['agent_pp']=='existing:model'


def test_shared_context_is_frozen_before_pp_and_reviewer_can_cite_it(tmp_path):
    from test_fragment_length import setup
    shared='已确认事实：焦点人物不曾打开木箱。计划：将来可查箱内记录，尚未发生。'
    write(tmp_path,'cache/story-support/context.md',shared)
    state,outputs,raw=setup(tmp_path)
    write(tmp_path,'cache/pp/body.json',json.dumps({'body':'她知道箱内有账册。'},ensure_ascii=False))
    binding=quality().prepare_fragment_review(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review')
    context=json.loads((tmp_path/binding['fragment_review_input']).read_text(encoding='utf-8'))
    assert context['story_support_context']==shared
    guard=json.loads((tmp_path/outputs['length_commit_guard']).read_text(encoding='utf-8'))
    assert 'cache/story-support/context.md' in guard['files']
    report={'compatible':False,'issues':[{'category':'pov','candidate_quote':'她知道箱内有账册。','source_quote':'焦点人物不曾打开木箱','reason':'焦点信息未取得，未来计划不能当现有知识'}]}
    binding['fragment_review_result']=json.dumps(report,ensure_ascii=False)
    write(tmp_path,binding['fragment_review_report_path'],binding['fragment_review_result'])
    result=quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert not json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf-8'))['accepted']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_editing_shared_context_after_snapshot_refuses_review(tmp_path):
    from test_fragment_length import setup
    write(tmp_path,'cache/story-support/context.md','已确认人物与世界事实')
    state,outputs,raw=setup(tmp_path)
    write(tmp_path,'cache/story-support/context.md','NEW SHARED CONTEXT')
    write(tmp_path,'cache/pp/body.json',json.dumps({'body':'丁'*30}))
    import pytest
    with pytest.raises(ValueError):quality().prepare_fragment_review(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review')
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_review_file_cannot_be_changed_to_compatible_after_model_completed(tmp_path):
    report={'compatible':False,'issues':[{'category':'new_fact','candidate_quote':'丁'*30,'source_quote':'乙'*25,'reason':'独立审查发现新增事实'}]}
    state,outputs,raw,binding=reviewed(tmp_path,'丁'*30,report)
    write(tmp_path,binding['fragment_review_report_path'],json.dumps({'compatible':True,'issues':[]}))
    import pytest
    with pytest.raises(ValueError):quality().focused_commit(tmp_path,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review',binding['fragment_review_binding'],binding['fragment_review_binding_sha'],binding['fragment_review_result'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw
