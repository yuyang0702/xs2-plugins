import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_continuity_contract import contract,evidence,SOURCES,PLUGIN


def module():
    path=PLUGIN/'resources/script-library/xs2/draft_guard/draft_guard.py'
    assert path.is_file(),'missing ordered draft guard'
    spec=importlib.util.spec_from_file_location('test_ordered_guard',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def run(m,root,monkeypatch,capsys,action,phase='facts',expression_format='body',inspect_first=False,target='1-500',combined_precheck=False,advisory_length=False):
    monkeypatch.chdir(root);monkeypatch.setenv('TASK_ID','task-guard')
    argv=['guard',action,'--phase',phase,'--multi-dir','cache/multi/task-guard','--target',target,'--pov','third_person','--expression-format',expression_format]
    monkeypatch.setattr('sys.argv',argv+(['--inspect-first'] if inspect_first else [])
                        +(['--combined-precheck'] if combined_precheck else [])
                        +(['--advisory-length'] if advisory_length else []))
    m.main();return capsys.readouterr().out


def prepared(root,monkeypatch,capsys,expression_format='body',source_body='未经修订的原始试稿',inspect_first=False,target='1-500',combined_precheck=False,advisory_length=False):
    m=module();multi=root/'cache/multi/task-guard';save(multi/'plan.json',{'scenes':[{'id':1},{'id':2}],'continuity':contract()})
    (multi/'planning-sources.md').write_text(SOURCES,encoding='utf-8')
    save(root/'cache/si/chapter.json',{'body':source_body})
    run(m,root,monkeypatch,capsys,'prepare',expression_format=expression_format,inspect_first=inspect_first,
        target=target,combined_precheck=combined_precheck,advisory_length=advisory_length)
    return m,root/'cache/draft-guard/task-guard'


@pytest.mark.parametrize('ownership,advisory_length',[('author',False),('planner',False),('author',True)])
def test_combined_precheck_keeps_advice_out_of_hard_length_and_expression_repair(tmp_path,monkeypatch,capsys,ownership,advisory_length):
    body, report = evidence()
    target = '140-500'
    save(tmp_path/'meta/length_policy.json',{'schema':1,'ownership':ownership})
    save(tmp_path/'.novel-project.json',{'values':{'target_word_count':target}})
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True,
                 target=target,combined_precheck=True,advisory_length=advisory_length)
    report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    report['checks']['repetition']=True
    report['issues']=[{'id':'advisory-pacing','category':'repetition','advisory':True,
                       'excerpts':['买方同意。'],'reason':'也可以在这里让节奏稍慢。','goal':'由作者取舍停顿时长。'}]
    save(d/'facts-audit.json',report)
    assert 'guard_facts_needs_repair:no' in run(m,tmp_path,monkeypatch,capsys,'precheck',target=target,advisory_length=advisory_length)
    assert m.read(d/'expression-audit.json')==report
    expression=run(m,tmp_path,monkeypatch,capsys,'precheck','expression',target=target,advisory_length=advisory_length)
    if ownership=='author' and not advisory_length:
        assert 'guard_expression_needs_repair:yes' in expression
        assert not (d/'final-receipt.json').exists()
        assert '也可以在这里让节奏稍慢' not in (d/'expression-feedback.md').read_text(encoding='utf-8')
    else:
        assert 'guard_expression_needs_repair:no' in expression
        assert m.read(d/'final-receipt.json')['body']==body
        assert 'short' in json.dumps(m.read(d/'expression-advice.json'))
    assert [issue['id'] for issue in m.read(d/'expression-advice.json')['issues']]==['advisory-pacing']


def test_combined_precheck_can_return_to_valid_base_when_expression_patch_loses_effect(tmp_path,monkeypatch,capsys):
    main,_=evidence()
    old='他没开口，只把椅子往门前挪了一寸。'
    extra='他这是准备堵门了。'
    body=main+'\n\n'+old+'\n\n'+extra
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True,
                 combined_precheck=True)
    _,report=evidence(body)
    report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    report['checks']['repetition']=True
    report['issues']=[{'id':'already-seen','category':'post_action_restatement','excerpts':[old,extra],
                       'reason':'动作已表现堵门。','goal':'保留挪椅子的动作，删去跟随的说明。',
                       'scene_focus':{'quote':extra,'preserve':[old]}}]
    save(d/'facts-audit.json',report)
    assert 'guard_facts_needs_repair:no' in run(m,tmp_path,monkeypatch,capsys,'precheck')
    assert 'guard_expression_needs_repair:yes' in run(m,tmp_path,monkeypatch,capsys,'precheck','expression')
    goal=m.expression_goals(d)[0]
    edit={'paragraph_id':goal['paragraph_id'],'old':extra,'occurrence':1,'replacement':'椅子让门开不了。','group_id':goal['id']}
    save(d/'expression-draft.json',{'source_sha256':m.body_digest(body),'edits':[edit]})
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    latest=m.read(d/'expression-audit-input.json')
    candidate=latest['candidate_body']
    _,report=evidence(candidate)
    report['checks']['repetition']=True
    report.update(book_contract_sha256=m.read(d/'binding.json')['book_contract_sha256'],edits_sha256=latest['edits_sha256'],
                  change_reviews=[{'edit_index':0,'effect':'equivalent','before_excerpt':extra,
                                   'after_excerpt':edit['replacement'],'reason':'新句仍然解释堵门。'}],
                  added_text_reviews=[{'edit_index':i,'useful':[],'repetitions':[]} for i in latest['growth_edit_indices']],
                  issue_outcomes=[{'id':goal['id'],'status':'remaining','excerpts':[edit['replacement']],
                                   'reason':'已由挪椅子明白的意思仍被说明。'}])
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    receipt=m.read(d/'final-receipt.json')
    assert receipt['body']==body
    assert receipt['retained_original'] is True
    assert [i['id'] for i in m.read(d/'expression-advice.json')['issues'] if i.get('id')]==[goal['id']]
    run(m,tmp_path,monkeypatch,capsys,'finish')


def clean_expression_checks():
    assessments = [
        ('constraint_transcription', 'pass', ['她点收六两。她交清灯。'],
         '人物动作使次序清楚。', '跟着当场行动。'),
        ('dialogue_function', 'not_applicable', [], '现场没有对答。', '无需另添对白。'),
        ('voice_alignment', 'pass', ['她交清灯。'], '用动作直接交代结果。', '简练的旁白。'),
        ('turning_point_payoff', 'pass', ['买方同意。', '她交清灯。'],
         '对方的同意让工具租借得以推进。', '连续交代交易步骤。'),
        ('ending_function', 'pass', ['余四两八钱。'], '新增余额信息。', '保留有用的数目。'),
    ]
    return [{'dimension': dimension, 'status': status, 'excerpts': excerpts, 'reason': reason,
             'style_basis': style_basis, 'issue_ids': []}
            for dimension, status, excerpts, reason, style_basis in assessments]


@pytest.mark.parametrize('legacy_report', [False, True])
def test_inspect_first_publishes_clean_source_without_a_writer_candidate(tmp_path,monkeypatch,capsys,legacy_report):
    body,report=evidence()
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True)
    assert m.read(d/'facts-audit-input.json')['candidate_body']==body
    report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    save(d/'facts-audit.json',report)
    assert 'guard_facts_needs_repair:no' in run(m,tmp_path,monkeypatch,capsys,'precheck')
    assert m.read(d/'expression-audit-input.json')['candidate_body']==body
    report['checks']['repetition']=True
    if not legacy_report:
        report['expression_checks'] = clean_expression_checks()
    save(d/'expression-audit.json',report)
    assert 'guard_expression_needs_repair:no' in run(m,tmp_path,monkeypatch,capsys,'precheck','expression')
    run(m,tmp_path,monkeypatch,capsys,'finish')
    assert m.read(d/'final-receipt.json')['body']==body
    assert not (d/'facts-draft.json').exists()
    assert not (d/'expression-draft.json').exists()


def test_inspect_first_sends_only_grounded_issue_to_writer(tmp_path,monkeypatch,capsys):
    body,report=evidence()
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True)
    report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    report['issues']=[{'category':'convenient_dialogue','excerpts':['没有这句话。'],'reason':'无关', 'goal':'改写'}]
    save(d/'facts-audit.json',report)
    assert 'target="agent_guard_facts_inspect"' in run(m,tmp_path,monkeypatch,capsys,'precheck')
    assert not (d/'facts-approved.json').exists()


def test_short_expression_candidate_is_audited_before_hard_length_publication(tmp_path,monkeypatch,capsys):
    core,_=evidence()
    repeated='同一层说明没有变化。'*15
    body=core+'\n\n'+repeated
    target='140-500'
    save(tmp_path/'meta/length_policy.json',{'schema':1,'ownership':'author'})
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True,target=target)
    def step(action,phase):
        return run(m,tmp_path,monkeypatch,capsys,action,phase,target=target)
    _,report=evidence(body)
    report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    save(d/'facts-audit.json',report)
    assert 'guard_facts_needs_repair:no' in step('precheck','facts')
    paragraph=m.revision.paragraphs(body)[-1]['id']
    save(d/'expression-draft.json',{'source_sha256':m.body_digest(body),'edits':[
        {'paragraph_id':paragraph,'old':repeated,'occurrence':1,'replacement':''}]})
    assert m.length.count_prose(core)<140
    assert 'WF_REJECT' not in step('candidate','expression')
    audit=m.read(d/'expression-audit-input.json')
    assert audit['candidate_body']==core
    _,report=evidence(core)
    report.update(book_contract_sha256=m.read(d/'binding.json')['book_contract_sha256'],
                  edits_sha256=audit['edits_sha256'],expression_checks=clean_expression_checks(),
                  change_reviews=[{'edit_index':0,'effect':'improved','reason':'删除重复说明，保留交易过程。','before_excerpt':repeated,'after_excerpt':''}])
    report['checks']['repetition']=True
    save(d/'expression-audit.json',report)
    assert 'target="agent_guard_expression_repair"' in step('commit','expression')
    assert not (d/'final-receipt.json').exists()


def test_expression_inspection_binds_transcribed_planning_to_both_sources(tmp_path,monkeypatch,capsys):
    core, _ = evidence()
    narration = '约定先收款后交灯是她此刻唯一要满足的场景约束。'
    body = core + '\n\n' + narration
    m, d = prepared(tmp_path, monkeypatch, capsys, expression_format='patches',
                    source_body=body, inspect_first=True)
    _, report = evidence(body)
    report['book_contract_sha256'] = m.read(d/'binding.json')['book_contract_sha256']
    save(d/'facts-audit.json', report)
    assert 'guard_facts_needs_repair:no' in run(m, tmp_path, monkeypatch, capsys, 'precheck')
    report['checks']['repetition'] = True
    report['issues'] = [{'id': 'planning-voice', 'category': 'constraint_transcription',
                         'source_quote': '没有这条资料。', 'excerpts': [narration],
                         'reason': '人物叙述出现提纲的验收口吻。', 'goal': '保留实际收款和交灯的次序。'}]
    report['expression_checks'] = clean_expression_checks()
    report['expression_checks'][0].update(status='issue', excerpts=[narration],
                                          reason='规则直接落进旁白。', issue_ids=['planning-voice'])
    save(d/'expression-audit.json', report)
    assert 'target="agent_guard_expression_inspect"' in run(m, tmp_path, monkeypatch, capsys, 'precheck', 'expression')
    report['issues'][0]['source_quote'] = '收款后交灯'
    save(d/'expression-audit.json', report)
    out = run(m, tmp_path, monkeypatch, capsys, 'precheck', 'expression')
    assert 'guard_expression_needs_repair:yes' in out
    assert narration in (d/'expression-feedback.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('result',['regressed','lost','false-preservation','stale','no-op','improved'])
def test_expression_audit_binds_each_edit_and_requires_a_net_improvement(tmp_path,monkeypatch,capsys,result):
    core,_=evidence()
    body=core+'\n\n椅子在电话那头撞了一下。老唐再开口时，声音已经近了。'
    m,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=body,inspect_first=True)
    _,report=evidence(body);report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256']
    save(d/'facts-audit.json',report)
    assert 'guard_facts_needs_repair:no' in run(m,tmp_path,monkeypatch,capsys,'precheck')
    old='椅子在电话那头撞了一下。'
    replacement={'no-op':old,'improved':'电话那头哐地一声，椅子撞了桌沿。'}.get(result,'')
    edit={'paragraph_id':m.revision.paragraphs(body)[-1]['id'],'old':old,'occurrence':1,'replacement':replacement}
    save(d/'expression-draft.json',{'source_sha256':m.body_digest(body),'edits':[edit]})
    output=run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    if result=='no-op':
        assert 'target="agent_guard_expression_repair"' in output
        assert '应用后正文未变' in output
        return
    packet=m.read(d/'expression-audit-input.json')
    if result=='stale':
        edit['group_id']='different-group'
        save(d/'expression-draft.json',{'source_sha256':m.body_digest(body),'edits':[edit]})
        run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    candidate=body.replace(old,replacement)
    _,report=evidence(candidate);report['book_contract_sha256']=m.read(d/'binding.json')['book_contract_sha256'];report['checks']['repetition']=True
    reason='椅子声保留了听者注意力跟着移动的过程，改后听得出撞击。' if replacement else '原稿用椅子声表现起身靠近，候选只剩结果。'
    change={'edit_index':0,'effect':'regressed' if result=='regressed' else 'improved',
            'reason':reason,'before_excerpt':old,'after_excerpt':replacement}
    if result in ('lost', 'false-preservation', 'improved'):
        change['preservation'] = {
            'status': 'lost' if result == 'lost' else 'preserved',
            'source_excerpt': old,
            'candidate_excerpt': replacement if result != 'false-preservation' else '原稿已经没有这一句。',
            'reason': reason,
        }
    save(d/'expression-audit.json',{**report,'edits_sha256':packet['edits_sha256'],'change_reviews':[change],
         'added_text_reviews':[{'edit_index':i,'useful':[],'repetitions':[]} for i in packet['growth_edit_indices']]})
    output=run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    if result=='improved':
        assert 'WF_REJECT' not in output
        assert m.read(d/'final-receipt.json')['body']==candidate
        return
    assert ('target="agent_guard_expression_audit"' if result in ('stale', 'false-preservation') else
            'target="agent_guard_expression_repair"') in output
    assert old in m.read(tmp_path/'cache/si/chapter.json')['body']


def accepted_facts(root,monkeypatch,capsys):
    m,d=prepared(root,monkeypatch,capsys);body,report=evidence()
    save(d/'facts-draft.json',{'body':body});run(m,root,monkeypatch,capsys,'candidate')
    save(d/'facts-audit.json',report)
    assert 'WF_REJECT' not in run(m,root,monkeypatch,capsys,'commit')
    return m,d,body


def test_only_expression_approval_can_replace_the_assembled_draft(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']=='未经修订的原始试稿'
    assert (d/'facts-approved.json').is_file()
    _,report=evidence(body);report['checks']['repetition']=True
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    guidance=m.read(d/'expression-audit-model.json')['evidence_guidance']
    assert '多个独立问题' in guidance and 'convenient_dialogue' in guidance
    assert '未确认的期限' in guidance and 'facts' in guidance
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']==body


def test_draft_can_publish_when_an_adopted_reference_does_not_fit(tmp_path,monkeypatch,capsys):
    from test_reading_contract import adopt, checks

    adopt(tmp_path)
    save(tmp_path/'planning/chapters/0001.json', {'reference_ids': ['mechanism-opening']})
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    _,report=evidence(body);report['checks']['repetition']=True
    reading=m.read(d/'facts-input.json')['book_contract']['reading_contract']
    report['reading_checks']=checks(reading,'revise')
    report['reading_checks'][0].update(priority='high',excerpts=[body[:8]])
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert m.read(d/'final-receipt.json')['body']==body


def test_unrequested_reference_notes_cannot_block_a_book_without_a_reference(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    _,report=evidence(body);report['checks']['repetition']=True
    report['reading_checks']=[{'goal_id':'invented-reference','status':'revise','priority':'medium',
        'excerpts':['无关引文。'],'reason':'模型误填了参考项。','style_basis':'原稿未采用写法。'}]
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert m.read(d/'final-receipt.json')['body']==body


def test_stilted_dialogue_with_current_evidence_returns_initial_draft_to_writer(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    body+='\n\n“你别刚进门就——”\n\n“我没进门。”'
    _,report=evidence(body);report['checks']['repetition']=True
    issue={'category':'convenient_dialogue','reason':'硬接进门两个字，避开了对方正在抱怨的事。',
           'goal':'接住对方的抱怨，或用动作结束争执。','excerpts':['你别刚进门就——','我没进门。']}
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    report['issues']=[{**issue,'excerpts':['我没进门。','我没进门。']}]
    save(d/'expression-audit.json',report)
    assert 'target="agent_guard_expression_audit"' in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    report['issues']=[issue];save(d/'expression-audit.json',report)
    result=run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert 'target="agent_guard_expression_repair"' in result
    feedback=(d/'expression-feedback.md').read_text(encoding='utf8')
    assert '我没进门。' in feedback and issue['goal'] in feedback
    assert not (d/'final-receipt.json').exists()

    revised=body.replace('我没进门。','你把手里的灯放下再说。')
    _,report=evidence(revised);report['checks']['repetition']=True
    save(d/'expression-draft.json',{'body':revised});run(m,tmp_path,monkeypatch,capsys,'candidate','expression')
    save(d/'expression-audit.json',report)
    assert 'WF_REJECT' not in run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert m.read(d/'final-receipt.json')['body']==revised


def test_candidate_retry_refreshes_completed_auditor_instead_of_reusing_old_proof(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);body,report=evidence()
    save(d/'facts-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate');save(d/'facts-audit.json',report)
    save(d/'facts-draft.json',{'body':body+'她离开。'})
    result=run(m,tmp_path,monkeypatch,capsys,'commit')
    assert 'target="agent_guard_facts_audit"' in result
    audit_input=json.loads((d/'facts-audit-input.json').read_text(encoding='utf-8'))
    model_input=json.loads((d/'facts-audit-model.json').read_text(encoding='utf-8'))
    assert 'source_body' in audit_input and 'source_body' not in model_input
    assert model_input['source_constraints']==audit_input['source_constraints']
    assert audit_input['candidate_body']==body+'她离开。'
    assert audit_input['actual_word_count']==m.length.count_prose(body+'她离开。')
    assert not (d/'facts-approved.json').exists()


def test_expression_cannot_regress_payment_even_when_model_lists_no_issues(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    body=body.replace('她付一两二钱纸债','她付一两整银又二十文纸债');_,report=evidence()
    report['candidate_sha256']=hashlib.sha256(body.encode()).hexdigest();report['checks']['repetition']=True
    report['money_observations'][1]['paid']={'text':'一两整银又二十文','occurrence':1}
    report['event_observations'][4]['quote']={'text':'她付一两整银又二十文纸债','occurrence':1}
    save(d/'expression-draft.json',{'body':body});run(m,tmp_path,monkeypatch,capsys,'candidate','expression');save(d/'expression-audit.json',report)
    output=run(m,tmp_path,monkeypatch,capsys,'commit','expression')
    assert 'target="agent_guard_expression_repair"' in output and '1020' in output
    assert not (d/'final-receipt.json').exists()


@pytest.mark.parametrize('changed', [False, True])
def test_expression_overlap_uses_verified_subquotes_only_for_unchanged_body(tmp_path, monkeypatch, capsys, changed):
    m, directory, body = accepted_facts(tmp_path, monkeypatch, capsys)
    if changed:
        body += '她离开。'
    _, report = evidence()
    report['candidate_sha256'] = m.body_digest(body)
    report['checks']['repetition'] = True
    report['event_observations'][3]['quote'] = {'text': '她点收六两。她交清灯', 'occurrence': 1}
    save(directory/'expression-draft.json', {'body': body})
    run(m, tmp_path, monkeypatch, capsys, 'candidate', 'expression')
    save(directory/'expression-audit.json', report)

    output = run(m, tmp_path, monkeypatch, capsys, 'commit', 'expression')
    if changed:
        assert '前后事件凭据重叠' in output
        assert not (directory/'final-receipt.json').exists()
    else:
        assert 'WF_REJECT' not in output
        assert m.read(directory/'final-receipt.json')['body'] == body
        assert m.read(directory/'expression-audit.json') == report


def test_failed_expression_commit_resumes_with_same_audited_draft(tmp_path, monkeypatch, capsys):
    project = {'values': {'chapter_number': '0001', 'target_word_count': '1-500', 'narrative_pov': 'third_person'}}
    save(tmp_path/'.novel-project.json', project)
    body, facts = evidence()
    m, directory = prepared(tmp_path, monkeypatch, capsys, 'patches', source_body=body)
    save(tmp_path/'cache/se/se_output.json', {})
    save(directory/'facts-draft.json', {'body': body})
    facts['book_contract_sha256'] = m.read(directory/'binding.json')['book_contract_sha256']
    run(m, tmp_path, monkeypatch, capsys, 'candidate', expression_format='patches')
    save(directory/'facts-audit.json', facts)
    assert 'WF_REJECT' not in run(m, tmp_path, monkeypatch, capsys, 'commit', expression_format='patches')
    patch = {'source_sha256': m.body_digest(body), 'edits': []}
    save(directory/'expression-draft.json', patch)
    report = json.loads(json.dumps(facts))
    report['checks']['repetition'] = True
    report['event_observations'][3]['quote'] = {'text': '她点收六两。她交清灯', 'occurrence': 1}
    save(directory/'expression-audit.json', report)
    task = {'workflow_id': 'mvp', 'task_id': 'task-guard', 'status': 'failed', 'workspace_override': str(tmp_path),
            'parameter_values': {'chapter_number': '0001', 'multi_dir': 'cache/multi/task-guard',
                                 'guard_expression_patch_result': json.dumps(patch)},
            'node_states': {name: {'status': 'completed'} for name in
                            ('script_multi_plan', 'script_guard_prepare', 'script_guard_facts_commit',
                             'script_guard_expression_candidate', 'agent_guard_expression_audit')}}
    task['node_states']['agent_guard_expression_audit']['outputs'] = {
        '_json_output_file': str(directory/'expression-audit.json')}
    task['node_states']['script_guard_expression_commit'] = {'status': 'failed', 'error': '前后事件凭据重叠'}
    checkpoint_module = m.load('test_commit_resume', m.BASE/'console_service/draft_review_checkpoint.py')
    checkpoint = checkpoint_module.prepare(tmp_path, project, task, '0001')
    assert 'script_guard_expression_commit' in checkpoint['selected_node_ids']
    assert not any(node.startswith('agent_') for node in checkpoint['selected_node_ids'])
    definition = m.read(PLUGIN/'resources/workflows/mvp/definition.json')
    definition['workflow_id'] = 'xs2-novel-flywheel-mvp'
    for node in definition['nodes']:
        params = node.get('node_params', {})
        if params.get('script_group') in ('xs2', 'nvl'):
            params['script_group'] = 'xs2-novel-flywheel-' + params['script_group']
    state = {**project, 'automaticCheckpoint': checkpoint}
    options = checkpoint_module.options(tmp_path, state, definition, task)
    assert options['selected_node_ids'] == checkpoint['selected_node_ids']
    commit = next(node for node in definition['nodes'] if node['id']=='script_guard_expression_commit')
    commit['node_params']['script_group'] = 'some-other-xs2'
    with pytest.raises(ValueError, match='审稿恢复必须使用'):
        checkpoint_module.options(tmp_path, state, definition, task)

    host = tmp_path/'host'
    (host/'src').mkdir(parents=True)
    save(host/'data/workflows/mvp/tasks/task-guard.json', task)
    monkeypatch.setenv('DETERMINFLOW_PROJECT_DIR', str(host))
    monkeypatch.setenv('WORKFLOW_ID', 'mvp')
    monkeypatch.setenv('TASK_ID', 'task-resume')
    for action in ('prepare', 'commit', 'finish'):
        monkeypatch.setattr('sys.argv', ['guard', action, '--phase', 'expression',
            '--source-file', checkpoint['source_file'], '--multi-dir', checkpoint['multi_dir'],
            '--target', '1-500', '--pov', 'third_person', '--expression-format', 'patches'])
        m.main()
    assert 'WF_REJECT' not in capsys.readouterr().out
    receipt = m.read(tmp_path/'cache/draft-guard/task-resume/final-receipt.json')
    assert receipt['body'] == body
    assert m.read(directory/'expression-audit.json') == report


def test_contract_drift_cannot_reuse_repair_or_audit_files(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);plan=tmp_path/'cache/multi/task-guard/plan.json'
    value=json.loads(plan.read_text(encoding='utf-8'));value['continuity']['facts'][0]['value']='别的铺';save(plan,value)
    with pytest.raises(ValueError,match='变化|新任务|绑定'):
        run(m,tmp_path,monkeypatch,capsys,'candidate')


def test_new_signed_budget_after_draft_freeze_cannot_reuse_old_guard(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys)
    from test_composition_plan import module as composition
    composer=composition();save(tmp_path/'meta/length_policy.json',{'schema':1,'ownership':'planner'})
    request=composer.prepare(tmp_path,'0001','later-budget','1-500')
    plan={'request_digest':request['request_digest'],'status':'ready','reason':'按本书阅读作用分配。','minimum':1,'maximum':500,
        'segments':[{'id':'one','purpose':'关系发展','development':'选择得到回应。','minimum':1,'maximum':500}]}
    review={'request_digest':request['request_digest'],'plan_digest':composer.identity(plan),'verdict':'approve','scope_preserved':True,
        'length_feasible':True,'reason':'作用成立。','checks':[{'segment_id':'one','develops_function':True,'style_basis':'本书声线','reason':'有发展'}]}
    composer.accept(tmp_path,'later-budget',plan,review)
    body,_=evidence();save(d/'facts-draft.json',{'body':body})
    with pytest.raises(ValueError,match='预算|篇幅'):run(m,tmp_path,monkeypatch,capsys,'candidate')


def test_edited_approved_fact_body_cannot_keep_the_old_auditor_approval(tmp_path,monkeypatch,capsys):
    m,d,body=accepted_facts(tmp_path,monkeypatch,capsys)
    approved=json.loads((d/'facts-approved.json').read_text(encoding='utf-8'))
    approved['body']=body+'未经核验的修改。';approved['body_sha256']=hashlib.sha256(approved['body'].encode()).hexdigest();save(d/'facts-approved.json',approved)
    current=json.loads((d/'expression-input.json').read_text(encoding='utf-8'));current['source_body']=approved['body'];save(d/'expression-input.json',current)
    save(d/'expression-draft.json',{'body':approved['body']})
    with pytest.raises(ValueError,match='核验|事实|变化'):
        run(m,tmp_path,monkeypatch,capsys,'candidate','expression')


def test_missing_or_unquoted_report_is_returned_to_the_auditor(tmp_path,monkeypatch,capsys):
    m,d=prepared(tmp_path,monkeypatch,capsys);body,report=evidence();save(d/'facts-draft.json',{'body':body})
    run(m,tmp_path,monkeypatch,capsys,'candidate');report['event_observations'][0]['quote']['text']='没有这句'
    save(d/'facts-audit.json',report)
    assert 'target="agent_guard_facts_audit"' in run(m,tmp_path,monkeypatch,capsys,'commit')
    assert not (d/'facts-approved.json').exists()


def test_hard_fact_repair_uses_analysis_model_and_expression_keeps_body_writer():
    path=PLUGIN/'resources/script-library/xs2/console_service/production.py'
    spec=importlib.util.spec_from_file_location('ordered_repair_models',path);production=importlib.util.module_from_spec(spec);spec.loader.exec_module(production)
    definition=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    selected=production.model_overrides({'analysisModel':'analysis:solver','writerModel':'body:writer','polishModel':'polish:editor'},definition,'mvp')
    assert selected['agent_guard_facts_repair']=='analysis:solver'
    assert selected['agent_guard_expression_repair']=='body:writer'
    assert selected['agent_guard_facts_audit']==selected['agent_guard_expression_audit']=='analysis:solver'


@pytest.mark.parametrize('retry',[False,True])
def test_real_scheduler_orders_fact_then_expression_and_reaudits_replaced_candidate(tmp_path,monkeypatch,capsys,retry):
    import asyncio
    import os
    import subprocess
    import sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.failure_policy import activate_scheduled_retry
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.script import _parse_reject_upstream,_parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    raw=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    wf=WorkflowDef.from_dict(raw)
    assert wf.get_node('script_guard_prepare') is not None
    assert not wf.validate()
    good,_=evidence()
    bad=good.replace('她付一两二钱纸债','她付一两整银又二十文纸债')
    _,d=prepared(tmp_path,monkeypatch,capsys,expression_format='patches',source_body=bad if retry else good,
                 inspect_first=True,combined_precheck=True,advisory_length=True)
    calls=[]
    class Agent(BaseNodePlugin):
        node_type='agent'
        async def execute(self,ctx):
            key=ctx.node_def.id;calls.append(key);phase='expression' if 'expression' in key else 'facts'
            if key.endswith('_repair'):
                text=good
                if retry and phase=='facts' and calls.count(key)==1:text=bad
                save(d/f'{phase}-draft.json',{'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'edits':[]} if phase=='expression' else {'body':text})
            else:
                current=json.loads((d/f'{phase}-audit-input.json').read_text(encoding='utf-8'))['candidate_body']
                _,report=evidence();report['candidate_sha256']=hashlib.sha256(current.encode()).hexdigest()
                report['book_contract_sha256']=json.loads((d/'binding.json').read_text(encoding='utf-8'))['book_contract_sha256']
                if '一两整银又二十文' in current:
                    report['money_observations'][1]['paid']={'text':'一两整银又二十文','occurrence':1}
                    report['event_observations'][4]['quote']={'text':'她付一两整银又二十文纸债','occurrence':1}
                if phase=='expression' or key=='agent_guard_facts_inspect':report['checks']['repetition']=True
                save(d/f'{phase}-audit.json',report)
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            if not ctx.node_def.id.startswith('script_guard_'):return NodeResult(status='completed')
            params=ctx.node_def.node_params
            args=[await resolve_placeholders(x,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for x in params['script_argv']]
            p=subprocess.run([sys.executable,str(PLUGIN/'resources/script-library/xs2/draft_guard/draft_guard.py'),*args],cwd=tmp_path,capture_output=True,
                env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},creationflags=0x08000000 if sys.platform=='win32' else 0)
            reject=_parse_reject_upstream(p.stdout.decode('utf-8'))
            if reject:
                reason,target=reject;assert ctx.on_reject_upstream('fixture',reason,target)['success']
                return NodeResult(status='failed',error=reason)
            return NodeResult(status='completed' if p.returncode==0 else 'failed',outputs=_parse_wf_vars(p.stdout.decode('utf-8')),error=p.stderr.decode('utf-8'))
    monkeypatch.setitem(registry._plugins,'agent',Agent);monkeypatch.setitem(registry._plugins,'script',Script)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(multi_dir='cache/multi/task-guard',target_word_count='1-500',narrative_pov='third_person')
    task=WorkflowTask(task_id='task-guard',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def execute():
        return await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(start_node_id='script_guard_prepare'),disabled_ids=set(),
            shared_ws=tmp_path,parent_id='test',on_node_started=lambda _:None,needs_approval=False,run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    for _ in range(6):
        outcome=asyncio.run(execute())
        if outcome=='completed':break
        assert outcome=='retry_waiting',{k:s.error for k,s in task.node_states.items() if s.error}
        for key,state in list(task.node_states.items()):
            if state.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(state)
    assert outcome=='completed'
    assert calls[0]=='agent_guard_facts_inspect'
    assert calls[-1]==('agent_guard_expression_inspect' if retry else 'agent_guard_facts_inspect')
    assert len(calls)==(6 if retry else 1)
    assert calls.count('agent_guard_facts_repair')==(2 if retry else 0)
    assert calls.count('agent_guard_facts_audit')==(2 if retry else 0)
    assert 'agent_guard_expression_repair' not in calls
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']==good
def test_audit_repairs_only_one_contract_character_for_same_book_and_candidate():
    from pathlib import Path
    import importlib.util

    script = Path(__file__).resolve().parents[1]/'resources/script-library/xs2/draft_guard/draft_guard.py'
    spec = importlib.util.spec_from_file_location('audit_contract_echo_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = {'candidate_sha256': 'c'*64, 'book_contract_sha256': 'b'*64, 'contract_sha256': 'a'*64}
    report = {**context, 'contract_sha256': '0' + 'a'*63, 'event_observations': []}
    assert module.bind_audit_contract_echo(report, context) == {**report, 'contract_sha256': context['contract_sha256']}
    assert report['contract_sha256'].startswith('0')
    stale = {**report, 'candidate_sha256': 'd'*64}
    assert module.bind_audit_contract_echo(stale, context) == stale
    unrelated = {**report, 'contract_sha256': '0'*64}
    assert module.bind_audit_contract_echo(unrelated, context) == unrelated
