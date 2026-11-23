import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from test_book_contract import put,PLUGIN
from test_expression_evidence import checks

BODY='\ufeff第一段保留。\r\n\r\n第二段重复说明。\r\n\r\n潮水会回来。\r\n'


def module():
    p=PLUGIN/'resources/script-library/xs2/local_revision/local_revision.py'
    s=importlib.util.spec_from_file_location('local_revision_tests',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def setup(root):
    m=module();put(root,'.novel-project.json',{'values':{'narrator_scope':'omniscient','author_feedback_file':'feedback.md'}})
    put(root,'feedback.md','保留全知和回环，仅合并无作用说明。')
    put(root,'meta/narrative_contract.json',{'schema':1,'protected_phrases':['潮水会回来。']})
    p=root/'story/0001/chapter.md';p.parent.mkdir(parents=True);p.write_bytes(BODY.encode())
    out=m.prepare(root,'0001','local-test','1-5000')
    put(root,'cache/sc/critique.json',{'feels_human':True,'issues':[]})
    m.writer_input(root,out['revision_dir'],'cache/sc/critique.json')
    return m,out


def patch(m,out,root,replacement='第二段简明。'):
    source=json.loads((root/out['revision_input']).read_text(encoding='utf-8'))
    edit={'paragraph_id':source['paragraphs'][1]['id'],'old':'第二段重复说明。','occurrence':1,'replacement':replacement}
    data={'source_sha256':source['source_sha256'],'edits':[edit]}
    put(root,out['revision_patch_path'],data);return data


def approved(m,out,root):
    context=json.loads((root/out['revision_review_input']).read_text(encoding='utf-8'))
    report={'candidate_sha256':context['candidate_sha256'],'book_contract_sha256':context['book_contract_sha256'],
        'review_input_sha256':context['review_input_sha256'],'compatible':True,'issues':[],
        'expression_review':{'verdict':'pass','summary':'含义未重复，风格保留。','issues':[]},
        'expression_checks':checks(m.expression),'issue_outcomes':[],
        'added_text_reviews':[{'edit_index':i,'useful':[],'repetitions':[]} for i in context.get('growth_edit_indices',[])],
        'change_reviews':[{'edit_index':i,'effect':'improved','before_excerpt':e['old'],
            'after_excerpt':e['replacement'],'reason':'合并无增量的说明，保留全知声线。'} for i,e in enumerate(context['edits'])]}
    for c in report['expression_checks']:c['excerpts']=['第一段保留。']
    put(root,out['revision_review_path'],report);return json.dumps(report,ensure_ascii=False)


def scoped_setup(root, *, stale=False, authored=False, whole=False, tampered=False, raw=None):
    m = module()
    raw = raw if raw is not None else '“人呢？”\n\n她碰了碰窗框。“还没回来。”\n\n屋里还燃着灯。'.encode()
    path = root/'story/0001/chapter.md'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    if authored:
        put(root, 'author.md', '保留两句对白。必须让她先望向窗外。')
        put(root, '.novel-project.json', {'values': {'author_feedback_file': 'author.md'}})
    elif not (root/'.novel-project.json').exists():
        put(root,'.novel-project.json',{'values':{'human_intent':'创作一个调查旧门窗的故事。'}})
    reader = m.load('test_polish_reader', m.HERE/'reader_review/reader_review.py')
    frozen = m.book.resolve(root)
    readout=reader.prepare(root,'0001','reader-same-body',parallel=True,protocol=2)
    binding=m.read(root/readout['reader_review_binding'])
    if tampered:put(root,readout['reader_blind_input'],{'manuscript':'伪造底稿。'})
    source_sha = 'stale' if stale else m.sha(raw)
    original_row='她碰了碰窗框。' in raw.decode()
    goal={'id':'context-door','source':'expression_review','kind':'expression','priority':'medium',
          'editability':'editable','impact':'可能只是在重报消息。',
          'excerpts':['她碰了碰窗框。','还没回来。'] if original_row else ['第二段重复说明。'],
          'goal':'核对这一拍有无真实回应。','preserve':['还没回来。','她碰了碰窗框。'] if original_row else ['第一段保留。']}
    put(root, 'story/0001/reader_report.json', {
        'reader_review_version': 2, 'chapter_number': '0001', 'body_sha256': source_sha,
        'book_contract_sha256': m.book.digest(frozen), 'verdict': 'revise',
        'review_binding': {key: binding[key] for key in ('task_id','scope_source','body_sha256','input_sha256')},
        'revision_scope': {'mode': 'unrestricted'},
        'issues': [goal],
    })
    out = m.prepare(root, '0001', 'scoped-polish', '1-5000', scoped_review=True, whole_chapter_review=whole)
    return m,out,raw


def scoped_report(m, root, out, edits, *, action='keep'):
    source = m.read(root/out['revision_source_input'])
    put(root, out['revision_patch_path'], {'source_sha256': source['source_sha256'], 'edits': edits})
    m.candidate(root, out['revision_dir'])
    context = m.read(root/out['revision_review_input'])
    report = {'protocol': 'local-review-v3', 'compatible': True, 'issues': [],
              'change_reviews': [{'edit_index': i, 'effect': effect, 'reason': '她的停顿有具体作用。'}
                                 for i,effect in enumerate(('improved','regressed')[:len(edits)])],
              'issue_outcomes': [{'id': goal['id'], 'status': action, 'reason': '动作改变了这句话的语气。',
                                  'excerpts': ['还没回来。']} for goal in context['goals']],
              'added_text_reviews': [{'edit_index': i, 'useful': [], 'repetitions': []}
                                     for i in context.get('growth_edit_indices', [])]}
    put(root, out['revision_review_path'], report)
    return json.dumps(report,ensure_ascii=False)


def test_scoped_polish_reuses_grounded_same_body_goal_without_critic(tmp_path):
    m,out,raw = scoped_setup(tmp_path)
    assert out['revision_critique_mode'] == 'confirmed'
    m.writer_input(tmp_path, out['revision_dir'], 'cache/sc/unused.json')
    editor = m.read(tmp_path/out['revision_editor_model'])
    goal, = editor['goals']
    assert goal['id'] == 'context-door'
    assert goal['paragraph_ids'] == ['p0002']
    assert goal['evidence'] == ['她碰了碰窗框。','还没回来。']
    assert goal['preserve'] == ['还没回来。','她碰了碰窗框。']
    report = scoped_report(m, tmp_path, out, [])
    receipt = m.commit(tmp_path, out['revision_dir'], report)
    assert receipt['changed_spans'] == 0 and receipt['open_issues'] == []
    assert (tmp_path/'story/0001/chapter.md').read_bytes() == raw


@pytest.mark.parametrize('mode',['stale','authored','whole','tampered'])
def test_scoped_polish_uses_critic_for_stale_report_or_manual_scope(tmp_path, mode):
    _,out,_ = scoped_setup(tmp_path, **{mode: True})
    assert out['revision_critique_mode'] == 'critic'


def test_scoped_polish_keeps_safe_independent_patch_and_reports_actual_open_goal(tmp_path):
    m,out,raw = scoped_setup(tmp_path)
    m.writer_input(tmp_path, out['revision_dir'], 'cache/sc/unused.json')
    edits = [
        {'paragraph_id':'p0002','old':'她碰了碰窗框。','occurrence':1,'replacement':'她碰了碰窗框，顿了顿。','independent':True},
        {'paragraph_id':'p0003','old':'屋里还燃着灯。','occurrence':1,'replacement':'灯早灭了。','independent':True},
    ]
    report = scoped_report(m, tmp_path, out, edits, action='remaining')
    receipt = m.commit(tmp_path, out['revision_dir'], report)
    assert receipt['changed_spans'] == 1
    assert [row['id'] for row in receipt['open_issues']] == ['context-door']
    assert (tmp_path/'story/0001/chapter.md').read_bytes() == raw.replace(
        '她碰了碰窗框。'.encode(), '她碰了碰窗框，顿了顿。'.encode())
    task = {'task_id':'scoped-polish','parameter_values':{'revision_dir':out['revision_dir'],'revision_review_result':report}}
    assert m.verify_attempt(tmp_path,task) == receipt


def test_scoped_polish_refuses_to_close_a_mandatory_author_goal_as_keep(tmp_path):
    m,out,raw = scoped_setup(tmp_path, authored=True)
    put(tmp_path, 'critique.json', {'issues': [{'severity':'high','evidence_status':'verified',
        'evidence':['她碰了碰窗框。'], 'suggestion':'让她先望向窗外。', 'required_source':'必须让她先望向窗外。'}]})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    report = scoped_report(m, tmp_path, out, [])
    with pytest.raises(m.Retry,match='原有'):
        m.commit(tmp_path,out['revision_dir'],report)
    assert (tmp_path/'story/0001/chapter.md').read_bytes() == raw


def test_exact_author_deletions_survive_critic_omission_and_blind_vote(tmp_path):
    m = module()
    body = '她推开门。\n\n门现在开着。\n\n天早就黑了。\n\n灯还亮着。'
    put(tmp_path, 'story/0001/chapter.md', body)
    put(tmp_path, 'feedback.md', '删掉 p0002。\n删除「天早就黑了。」\n可以试试改写 p0004。')
    out = m.prepare(tmp_path, '0001', 'explicit-author', feedback_path='feedback.md',
                    scoped_review=True, blind_scenes=True)
    put(tmp_path, 'critique.json', {'issues':[]})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    data = m.read(tmp_path/out['revision_input'])
    assert [(g['level'], g['paragraph_id']) for g in data['goals']] == [
        ('mandatory', 'p0002'), ('mandatory', 'p0003')]
    edits = [{'paragraph_id':p['id'], 'old':p['text'], 'occurrence':1, 'replacement':replacement}
             for p, replacement in zip(data['paragraphs'][1:], ['', '', '灯泡发出白光。'])]
    put(tmp_path, out['revision_patch_path'], {'source_sha256':data['source_sha256'], 'edits':edits[1:]})
    with pytest.raises(m.Retry, match='p0002'):
        m.candidate(tmp_path, out['revision_dir'])
    put(tmp_path, out['revision_patch_path'], {'source_sha256':data['source_sha256'], 'edits':edits})
    m.candidate(tmp_path, out['revision_dir'])
    public = m.read(tmp_path/out['revision_blind_packet'])
    vote = {'ballot':public['ballot'], 'scenes':[
        {'id':s['id'], 'prefer':'A' if '门现在开着。' in s['A'] else 'B', 'exceptions':[],
         'voice_quote':'门现在开着。', 'redundant_quote':'', 'reason':'偏好原稿。'}
        for s in public['scenes']]}
    put(tmp_path, out['revision_blind_path'], vote)
    m.accept_blind(tmp_path, out['revision_dir'], json.dumps(vote, ensure_ascii=False))
    reviewed = m.read(tmp_path/out['revision_review_input'])
    assert reviewed['edits'] == edits[:2]
    assert [p['text'] for p in m.patches.paragraphs(reviewed['candidate'])] == ['她推开门。', '灯还亮着。']
    report = {'protocol':'local-review-v3','compatible':True,'issues':[],
              'change_reviews':[], 'added_text_reviews':[],
              'issue_outcomes':[{'id':key,'status':'resolved','excerpts':[evidence[0]],
                                 'reason':'按作者要求删去该处，邻段保持连贯。'}
                                for key,evidence in m.signoff_evidence(reviewed).items()]}
    put(tmp_path, out['revision_review_path'], report)
    receipt = m.commit(tmp_path, out['revision_dir'], json.dumps(report, ensure_ascii=False))
    assert receipt['changed_spans'] == 2
    assert receipt['after_sha256'] == m.sha((tmp_path/'story/0001/chapter.md').read_bytes())


def test_exact_author_commands_require_the_specified_replacement_and_ignore_options():
    m = module()
    body = '她开门往外看。\n\n他没回头。后面空荡荡的。\n\n天亮了。'
    source = {'source_body':body, 'paragraphs':m.patches.paragraphs(body),
              'author_feedback':('原 p0001 「她开门往外看。」改为「她把门推开。」；'
                                 '原 p0002 整段首句「他没回头。」至「后面空荡荡的。」删掉。\n'
                                 '删掉 p0003 吗？可以试试改写 p0003。')}
    goals = m.explicit_author_goals(source)
    assert [(g['paragraph_id'], g['explicit_delete'], g['explicit_replacement']) for g in goals] == [
        ('p0001', False, '她把门推开。'), ('p0002', True, None)]
    edits = [{'paragraph_id':p['id'], 'occurrence':1, 'old':p['text'], 'replacement':new}
             for p,new in zip(source['paragraphs'], ['她打开了门。', ''])]
    with pytest.raises(ValueError, match='p0001'):
        m.author_edit_indices(source, goals, edits)
    edits[0]['replacement'] = '她把门推开。'
    assert m.author_edit_indices(source, goals, edits) == {0,1}


def test_exact_local_publication_keeps_untouched_bytes_and_recovers_after_publication(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    expected=approved(m,out,tmp_path);m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.replace('第二段重复说明。','第二段简明。').encode()
    m.commit(tmp_path,out['revision_dir'],expected)


def test_checklist_exchange_passes_exact_layout_change_to_independent_review():
    m=module()
    body='“开不开？”\n\n“不开。钥匙不在我手里。”\n\n“钥匙在哪？”'
    source={'paragraphs':m.patches.paragraphs(body)}
    goal={'id':'dialogue-1','focus':'checklist_exchange','goal':'让他顾上对方不肯开门的反应。',
          'target':{'paragraph_id':'p0002','quote':'不开。钥匙不在我手里。'}}
    edit={'paragraph_id':'p0002','old':'不开。钥匙不在我手里。','occurrence':1,'replacement':'不开。\n\n钥匙不在我手里。'}
    m.check_dialogue_goals([edit],[goal],source)
    with pytest.raises(ValueError,match='原句不在'):
        m.check_dialogue_goals([{**edit,'old':'模型补进去的原话'}],[goal],source)
    edit['replacement']='门后头不是你要找的人。'
    m.check_dialogue_goals([edit],[goal],source)


def test_continuous_dialogue_requires_a_scoped_patch_even_with_unchanged_speech():
    m = module()
    body = '“谁来过？”\n\n她停了手。\n\n“送货的。”\n\n“他什么时候走的？”\n\n“刚走。”'
    source = {'source_body': body, 'paragraphs': m.patches.paragraphs(body), 'dialogue_check_version': 6}
    checks = [{'focus': focus, 'status': 'not_applicable', 'reason': '略。', 'goal': '', 'turns': []}
              for focus in ('literal_echo', 'situational_speech', 'checklist_exchange', 'scripted_delivery', 'voice_contrast')]
    with pytest.raises(ValueError, match='连续对白'):
        m.dialogue_goals(source, checks)
    review = checks[2]
    review.update(exchange_id='exchange-1', status='revise', reason='对方停手后仍按顺序盘问。',
                  goal='让接话受对方的犹豫影响。', target_turn=1, preserve=['送货的人刚走'],
                  turns=[{'turn_id': 'd0002'}, {'turn_id': 'd0003'}])
    refs = [row if row is not review else row | {'turns': [{'turn_id': 'd0001'}, {'turn_id': 'd0003'}]}
            for row in checks]
    with pytest.raises(ValueError, match='紧接的话轮'):
        m.dialogue_goals(source, refs)
    expanded, = m.dialogue_goals(source | {'dialogue_check_version':7}, refs)
    assert expanded['turns'][1]['quote'] == '送货的。'
    assert expanded['target']['quote'] == '他什么时候走的？'
    all_turns = [{'turn_id': f'd{number:04d}'} for number in range(1, 5)]
    extended = review | {'turns': all_turns, 'target_turn': 2}
    assert m.dialogue_goals(source, [extended if row is review else row for row in checks])[0]['target']['quote'] == '他什么时候走的？'
    goal, = m.dialogue_goals(source, checks)
    assert goal['paragraph_ids'] == ['p0001', 'p0002', 'p0003', 'p0004', 'p0005']
    assert goal['target']['quote'] == '他什么时候走的？'
    old = source['paragraphs'][3]['text']
    edit = {'paragraph_id': 'p0004', 'old': old, 'occurrence': 1, 'replacement': '“他，什么时候走的？”'}
    m.check_dialogue_goals([edit], [goal], source)
    with pytest.raises(ValueError, match=goal['id']):
        m.check_dialogue_goals([], [goal], source)
    edit['replacement'] = '“你没让他进门吧？”'
    m.check_dialogue_goals([edit], [goal], source)


def test_exchange_opening_requires_its_own_verdict_before_passing_dialogue():
    m = module()
    body = '“谁来过？”\n\n“送货的。”\n\n“他什么时候走的？”\n\n“可他的钥匙还在这儿。”'
    source = {'source_body': body, 'paragraphs': m.patches.paragraphs(body), 'dialogue_check_version': 8}
    checks = [{'focus': focus, 'status': 'not_applicable', 'reason': '无该类问题。', 'goal': '', 'turns': []}
              for focus in ('literal_echo', 'situational_speech', 'scripted_delivery', 'voice_contrast')]
    review = {'focus': 'checklist_exchange', 'exchange_id': 'exchange-1', 'status': 'pass',
              'reason': '后半段因新证据改变。', 'goal': '',
              'turns': [{'turn_id': f'd{number:04d}'} for number in range(1, 5)]}
    with pytest.raises(ValueError, match='开场.*结论'):
        m.dialogue_goals(source, [*checks, review])
    review.update(opening_status='revise', opening_reason='前段只报告情况，语气可以互换。')
    with pytest.raises(ValueError, match='开场.*返修'):
        m.dialogue_goals(source, [*checks, review])
    review.update(status='revise', target_turn=0, goal='让开场更贴合两人的关系。', preserve=['送货人没有带走钥匙'])
    assert m.dialogue_goals(source, [*checks, review])[0]['target']['quote'] == '谁来过？'
    review.update(status='pass', goal='', opening_status='pass', opening_reason='问话让对方认出送货人。')
    assert m.dialogue_goals(source, [*checks, review]) == []


def test_scene_revision_binds_the_exchange_and_reviews_grouped_actions(tmp_path):
    m=module()
    body='“你留一把钥匙。”\n\n他没伸手。\n\n“我给你放窗台。”\n\n他把钥匙拿走了。\n\n院子里还有雨。'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','scene-trial','1-5000',dialogue_check=True,dialogue_check_version=5)
    checks=[{'focus':focus,'status':'not_applicable','reason':'无该类问题。','goal':'','turns':[]}
            for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery','voice_contrast')]
    critique={'issues':[],'dialogue_checks':checks}
    put(tmp_path,'critique.json',critique)
    with pytest.raises(m.Retry,match='scene_review_format'):
        m.writer_input(tmp_path,out['revision_dir'],'critique.json')

    scene={'status':'revise','reason':'答应收钥匙之前缺少能改变他选择的回应。',
           'goal':'让她接住他不肯伸手的反应，他再自己把钥匙拿走。',
           'preserve':['他最后拿走钥匙'],'anchors':[
               {'paragraph_id':'p0001','quote':'你留一把钥匙。'},
               {'paragraph_id':'p0002','quote':'他没伸手。'},
               {'paragraph_id':'p0004','quote':'他把钥匙拿走了。'}]}
    critique['scene_checks']=[scene]
    put(tmp_path,'critique.json',critique)
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    editor=json.loads((tmp_path/out['revision_editor_model']).read_text('utf8'))
    goal=editor['goals'][0]
    assert goal['id']=='scene-1' and goal['paragraph_ids']==['p0001','p0002','p0003','p0004']
    assert goal['anchors']==scene['anchors'] and goal['preserve']==scene['preserve']
    edits=[{'paragraph_id':'p0002','old':'他没伸手。','occurrence':1,'replacement':'他把手往袖子里缩了缩。','group_id':'scene-1'},
           {'paragraph_id':'p0003','old':'我给你放窗台。','occurrence':1,'replacement':'你要不回来，挂门上就是。','group_id':'scene-1'}]
    payload={'source_sha256':editor['source_sha256'],'edits':[]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry,match='scene-1'):
        m.candidate(tmp_path,out['revision_dir'])
    payload['edits']=edits
    put(tmp_path,out['revision_patch_path'],payload)
    m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text('utf8'))
    assert context['candidate'].replace('\r\n','\n').endswith('他把钥匙拿走了。\n\n院子里还有雨。')
    report=json.loads(approved(m,out,tmp_path))
    for check in report['expression_checks']:check['excerpts']=['院子里还有雨。']
    report['issue_outcomes']=[{'id':'scene-1','status':'not_applicable','excerpts':['他把钥匙拿走了。'],'reason':'略过。'}]
    assert any('场景' in reason for reason in m.review_decision(report,context))
    report['issue_outcomes'][0].update(status='resolved',excerpts=['他把钥匙拿走了。'])
    with pytest.raises(ValueError,match='两处'):
        m.review_decision(report,context)
    report['issue_outcomes'][0].update(excerpts=['你要不回来，挂门上就是。','他把钥匙拿走了。'],
                                       reason='她让他可以随时退还，他因此愿意拿走。')
    assert not m.review_decision(report,context)


def test_narration_review_covers_the_scene_and_passes_exact_pause_change_to_review():
    m = module()
    body = '他掀了盖。\n\n又把手擦了擦。\n\n盖底的水是热的。'
    source = {'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':7}
    row = {'status':'revise','focus':'causality','reason':'动作写成了步骤。','goal':'把篇幅留给水温的异常。',
           'anchors':[{'paragraph_id':f'p{index:04d}'} for index in range(1,4)],'preserve':['水是热的']}
    with pytest.raises(ValueError, match='整段叙述'):
        m.scene_goals(source, [row])
    row['focus'] = 'narration'
    goal, = m.scene_goals(source, [row])
    assert goal['focus'] == 'narration'
    assert goal['paragraph_ids'] == ['p0001','p0002','p0003']
    edit = {'paragraph_id':'p0002','old':'又把手擦了擦。','occurrence':1,'replacement':'又，把手擦了擦。','group_id':goal['id']}
    m.check_scene_goals([edit], [goal], source)
    with pytest.raises(ValueError, match='范围'):
        m.check_scene_goals([{**edit,'paragraph_id':'p0004'}], [goal], source)
    edit['replacement'] = '盖底的水淌到指缝，他松了手。'
    m.check_scene_goals([edit], [goal], source)


@pytest.mark.parametrize('kind',['body','feedback','book','patch','review'])
def test_changed_inputs_or_old_audit_cannot_publish(tmp_path,kind):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    original=(tmp_path/'story/0001/chapter.md').read_bytes()
    if kind=='body':(tmp_path/'story/0001/chapter.md').write_bytes(original+'作者新改。'.encode())
    elif kind=='feedback':put(tmp_path,'feedback.md','作者已换意见。')
    elif kind=='book':put(tmp_path,'meta/world_foundation.md','本书规则已经变化。')
    elif kind=='patch':patch(m,out,tmp_path,'未经这份报告复查的新句。')
    else:
        report=json.loads(expected);report['candidate_sha256']='old';put(tmp_path,out['revision_review_path'],report);expected=json.dumps(report,ensure_ascii=False)
    current=(tmp_path/'story/0001/chapter.md').read_bytes()
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==current


def test_empty_edits_are_valid_and_protected_phrase_loss_is_rejected(tmp_path):
    m,out=setup(tmp_path)
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[]})
    m.candidate(tmp_path,out['revision_dir']);m.commit(tmp_path,out['revision_dir'],approved(m,out,tmp_path))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[
        {'paragraph_id':source['paragraphs'][2]['id'],'old':'潮水会回来。','occurrence':1,'replacement':''}]})
    with pytest.raises(ValueError,match='保留'):m.candidate(tmp_path,out['revision_dir'])


def test_fact_pass_cannot_hide_expression_blocker_or_unhelpful_patch(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['change_reviews'][0]['effect']='regressed'
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_candidate_rejects_length_before_expensive_review(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'乙'*5001)
    with pytest.raises(m.Retry) as error:m.candidate(tmp_path,out['revision_dir'])
    assert error.value.target=='agent_pl'
    assert not (tmp_path/out['revision_review_input']).exists()


@pytest.mark.parametrize('kind',['critic','editor'])
def test_changed_editor_evidence_cannot_reuse_a_review(tmp_path,kind):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    if kind=='critic':put(tmp_path,'cache/sc/critique.json',{'issues':[],'new':'other review'})
    else:
        data=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'));data['author_feedback']='new'
        put(tmp_path,out['revision_input'],data)
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_fact_pass_cannot_hide_medium_expression_issue(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['expression_review']={'verdict':'revise','summary':'仍有解释性复述','issues':[
        {'id':'repeat-1','category':'semantic_redundancy','location':'中段','priority':'medium',
         'excerpts':['第二段简明。'],'impact':'再次说明相同结论。','goal':'合并重复结论。'}]}
    report['expression_checks'][0].update(status='issue',issue_ids=['repeat-1'],excerpts=['第二段简明。'])
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as error:m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert error.value.target=='agent_pl'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_partial_deletion_quotes_the_nonempty_replacement_not_an_empty_after(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'第二段。');m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['change_reviews'][0].update(before_excerpt='重复说明。',after_excerpt='')
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as error:m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert error.value.target=='agent_local_review'
    report['change_reviews'][0]['after_excerpt']='第二段。';put(tmp_path,out['revision_review_path'],report)
    m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert '第二段重复说明。'.encode() not in (tmp_path/'story/0001/chapter.md').read_bytes()


def test_writer_retry_receives_actual_rejected_edits_without_rebasing_source(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'上一轮未通过的新句。');m.candidate(tmp_path,out['revision_dir'])
    before=(tmp_path/out['revision_input']).read_bytes()
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],m.Retry('agent_pl','新句仍重复原结论。'))
    assert '上一轮未通过的新句。' in feedback and '第二段重复说明。' in feedback
    assert '未通过补丁' in feedback and '冻结原文' in feedback
    assert (tmp_path/out['revision_input']).read_bytes()==before
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    reviewer=m.retry_feedback(tmp_path,out['revision_dir'],m.Retry('agent_local_review','引文无效。'))
    assert '上一轮未通过的新句。' not in reviewer


def test_crash_after_atomic_publication_recovers_without_rewriting(tmp_path,monkeypatch):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    real_save=m.save
    def interrupted(path,data):
        if path.name=='receipt.json':raise OSError('simulated shutdown after replace')
        return real_save(path,data)
    monkeypatch.setattr(m,'save',interrupted)
    with pytest.raises(OSError):m.commit(tmp_path,out['revision_dir'],expected)
    published=(tmp_path/'story/0001/chapter.md').read_bytes()
    assert published!=BODY.encode()
    monkeypatch.setattr(m,'save',real_save);m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==published


def test_optional_unconfigured_length_does_not_block_content_revision(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','正文保留。')
    out=m.prepare(tmp_path,'0001','no-target')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    assert source['length']['status']=='unconfigured'
    put(tmp_path,'cache/sc/critique.json',{'issues':[]});m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[]})
    m.candidate(tmp_path,out['revision_dir'])


def test_short_candidate_retry_retains_latest_patch_before_review_input_exists(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','甲'*100)
    out=m.prepare(tmp_path,'0001','short-patch','150-200')
    put(tmp_path,'cache/sc/critique.json',{'issues':[]});m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    assert source['length_edit_budget']['source_word_count']==100
    assert source['length_edit_budget']['net_change_minimum']==50
    payload={'source_sha256':source['source_sha256'],'edits':[{
        'paragraph_id':'p0001','old':'甲','occurrence':1,'replacement':'甲'*50}]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry) as failure:m.candidate(tmp_path,out['revision_dir'])
    assert not (tmp_path/out['revision_review_input']).exists()
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],failure.value)
    assert '"net_change_minimum": 50' in feedback and 'rejected_edits' in feedback and '不累计' in feedback
    (tmp_path/out['revision_patch_path']).unlink()
    snapshot=json.loads((tmp_path/out['revision_dir']/'last-rejected-patch.json').read_text(encoding='utf-8'))
    assert snapshot['rejected_edits']==payload['edits'] and snapshot['candidate_length']['actual']==149
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')=='甲'*100


def test_malformed_patch_still_returns_writer_retry_feedback(tmp_path):
    m,out=setup(tmp_path)
    (tmp_path/out['revision_patch_path']).write_text('{"edits":',encoding='utf-8')
    with pytest.raises(m.Retry) as failure:m.candidate(tmp_path,out['revision_dir'])
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],failure.value)
    assert '冻结原文' in feedback and 'source_word_count' in feedback
    assert not (tmp_path/out['revision_dir']/'last-rejected-patch.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_structured_scope_conflict_never_publishes_or_retries_same_writer(tmp_path):
    m,out=setup(tmp_path);source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    payload={'source_sha256':source['source_sha256'],'edits':[],'status':'needs_replan',
        'reason':'在当前范围内压缩复述后不足，不能用同义动作补足。','evidence':['第二段重复说明。']}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.CompositionConflict):m.candidate(tmp_path,out['revision_dir'])
    task={'task_id':'local-test','status':'failed','parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False)},
        'node_states':{'agent_pl':{'status':'completed'},'script_local_candidate':{'status':'failed'}}}
    assert m.verify_conflict(tmp_path,task)['kind']=='content_length_conflict'
    assert not (tmp_path/out['revision_review_input']).exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    task['parameter_values']['revision_patch_result']='{}'
    with pytest.raises(ValueError):m.verify_conflict(tmp_path,task)


def test_repeated_short_content_repair_keeps_length_gate_without_invented_scope_conflict(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','甲'*200)
    put(tmp_path,'story/0001/reader_report.json',{'body_sha256':m.sha(('甲'*200).encode()),
        'issues':[{'id':'repeat','priority':'medium','goal':'合并复述','excerpts':['甲甲']} ]})
    out=m.prepare(tmp_path,'0001','short-content','180-220');put(tmp_path,'cache/sc/critique.json',{'issues':[]})
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    for count in (101,102):
        payload={'source_sha256':m.sha(('甲'*200).encode()),'edits':[{'paragraph_id':'p0001','old':'甲'*200,'occurrence':1,'replacement':'乙'*count}]}
        put(tmp_path,out['revision_patch_path'],payload)
        with pytest.raises(m.Retry):m.candidate(tmp_path,out['revision_dir'])
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')=='甲'*200


def test_complete_reader_report_stays_bound_to_independent_review(tmp_path):
    m,_=setup(tmp_path)
    report={'body_sha256':m.sha(BODY.encode()),'verdict':'pass','issues':[],
            'blind_review':{'summary':'整篇报告原文'},'expression_checks':[{'detail':'复核检查明细'}]}
    put(tmp_path,'story/0001/reader_report.json',report)
    out=m.prepare(tmp_path,'0001','focused-review','1-5000')
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf-8'))
    review=json.loads((tmp_path/out['revision_review_model']).read_text(encoding='utf-8'))
    assert 'reader_report' not in writer and review['reader_report']==report
    assert 'critique' not in writer and review['critique']=={'feels_human':True,'issues':[]}
    assert m.packet.restore(review['source_body'],review['candidate'])==BODY
    assert 'same_as_candidate' in review['source_body']['paragraphs'][0]
    review['reader_report']['blind_review']['summary']='篡改的报告'
    put(tmp_path,out['revision_review_model'],review)
    with pytest.raises(ValueError,match='模型所见输入'):
        m.commit(tmp_path,out['revision_dir'],approved(m,out,tmp_path))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_automatic_advice_is_not_promoted_above_original_author_requirements(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原正文。')
    put(tmp_path,'author.md','保留心理和抒情，不增加无关动作。')
    put(tmp_path,'auto/instructions.md','旧自动建议：用更多操作补到四千字。')
    original=(tmp_path/'author.md').read_text(encoding='utf-8')
    put(tmp_path,'auto/automatic-origin.json',{'origin':'automatic','feedback_sha256':m.sha((tmp_path/'auto/instructions.md').read_bytes()),
        'retained_feedback_sources':[{'source_id':'author.md','sha256':m.sha((tmp_path/'author.md').read_bytes()),'text':original}]})
    out=m.prepare(tmp_path,'0001','layers','1-5000',feedback_path='auto/instructions.md')
    data=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    assert data['author_feedback']==original
    assert '旧自动建议' in data['automatic_revision_advice']
    put(tmp_path,'author.md','作者后来修改了要求。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_exhausted_polish_reuses_verified_review_as_automatic_feedback(tmp_path):
    from test_length_quality import policy
    m,out=setup(tmp_path)
    payload=patch(m,out,tmp_path,'第二段新的说明。');m.candidate(tmp_path,out['revision_dir'])
    report=json.loads(approved(m,out,tmp_path));report['change_reviews'][0]['effect']='regressed'
    put(tmp_path,out['revision_review_path'],report);raw=json.dumps(report,ensure_ascii=False)
    with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],raw)
    task={'task_id':'local-test','status':'failed','workspace_override':str(tmp_path),
          'parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False),'revision_review_result':raw},
          'node_states':{'agent_pl':{'status':'completed'},'agent_local_review':{'status':'completed'},
                         'script_local_commit':{'status':'failed','error':'RETRY_STOP: content：局部改动仍需处理'}}}
    state={'values':{'chapter_number':'0001','target_word_count':'1-5000'}}
    p=policy();action=p.recovery_action(state,'polish',task,root=tmp_path)
    assert action['stage']=='polish' and 'mvp' not in action['reset']
    updates=action['updates'];feedback=updates['values']['author_feedback_file']
    authored, automatic, _=m.feedback_layers(tmp_path,feedback)
    assert authored=='保留全知和回环，仅合并无作用说明。'
    assert report['change_reviews'][0]['reason'] in automatic
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert p.recovery_action({**state,**updates},'polish',task,root=tmp_path) is None


def test_repeated_content_rejection_alone_does_not_prove_scope_conflict(tmp_path):
    m,out=setup(tmp_path)
    for i,text in enumerate(('第二段简明。','第二段新的说明。')):
        payload=patch(m,out,tmp_path,text);m.candidate(tmp_path,out['revision_dir'])
        report=json.loads(approved(m,out,tmp_path));report['change_reviews'][0]['effect']='regressed'
        put(tmp_path,out['revision_review_path'],report);raw=json.dumps(report,ensure_ascii=False)
        with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],raw)
    task={'task_id':'local-test','status':'failed','parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False),
        'revision_review_result':raw},'node_states':{'agent_pl':{'status':'completed'},'agent_local_review':{'status':'completed'},'script_local_commit':{'status':'failed'}}}
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


@pytest.mark.parametrize('changed',['story/0001/chapter.md','story/0001/diff_story_confirmed.md',
    'planning/chapters/0003.json','learning/active_context.md','learning/character_center/preferences.json'])
def test_old_history_and_adopted_planning_are_bound_even_when_context_cache_is_unchanged(tmp_path,changed):
    m=module();put(tmp_path,'story/0001/chapter.md','第一章。');put(tmp_path,'story/0003/chapter.md','第三章。')
    out=m.prepare(tmp_path,'0003','history','1-5000')
    put(tmp_path,changed,'作者更新了此前依据。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_local_editor_uses_current_runtime_context_alias_instead_of_old_legacy_file(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原文。')
    put(tmp_path,'cache/story-support/context.md','旧的继承模式上下文。')
    put(tmp_path,'learning/prose_policy/runtime/task/current/common.md','本次已采用的表达与事实。')
    out=m.prepare(tmp_path,'0001','alias','1-5000','learning/prose_policy/runtime/task/current/common.md')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    assert source['confirmed_context']=='本次已采用的表达与事实。'
    put(tmp_path,'learning/prose_policy/runtime/task/current/common.md','来源被改。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_direct_workflow_feedback_override_is_frozen_and_cannot_drift(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原文。')
    put(tmp_path,'.novel-project.json',{'values':{'author_feedback_file':'old.md'}})
    put(tmp_path,'old.md','旧选择。');put(tmp_path,'new.md','本次作者要求。')
    out=m.prepare(tmp_path,'0001','direct-feedback','1-5000',feedback_path='new.md')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf8'))
    assert source['author_feedback']=='本次作者要求。'
    put(tmp_path,'new.md','本次意见又改变。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_two_bad_length_candidates_do_not_invent_reading_scope_conflict(tmp_path):
    m=module();body=tmp_path/'story/0001/chapter.md';body.parent.mkdir(parents=True);body.write_bytes(BODY.encode())
    out=m.prepare(tmp_path,'0001','length-rejections','1-5000')
    put(tmp_path,'cache/sc/critique.json',{'issues':[{'severity':'medium','description':'说明重复',
        'suggestion':'合并无作用说明','evidence':['第二段重复说明。']}]})
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    for count in (5001,5002):
        patch(m,out,tmp_path,'乙'*count)
        with pytest.raises(m.Retry) as exc:m.candidate(tmp_path,out['revision_dir'])
        assert exc.value.target=='agent_pl'
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert len(json.loads((tmp_path/out['revision_dir']/'length-candidates.json').read_text(encoding='utf8')))==2
    assert body.read_bytes()==BODY.encode()
@pytest.mark.parametrize('body,details,replacement',[
    ('“我接了六十份，七点前送到。”',['六十份','七点'],'“这单得在上工前送过去。”'),
    ('“城门要收三十枚，八点前到。”',['三十枚','八点'],'“天黑前赶到，守门的还肯放人。”'),
])
def test_precision_target_rejects_unmodified_candidate_and_allows_exact_details_with_purpose(tmp_path,body,details,replacement):
    m=module();put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','precision-target','1-100')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    checks=[{'paragraph_id':'p0001','action':'revise','remove':details,'reason':'数量和时间都可用现场条件交代。'}]
    critique={'issues':[],'precision_checks':checks}
    put(tmp_path,'critique.json',critique)
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    editor=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf-8'))
    assert editor['goals'][0]['paragraph_ids']==['p0001']
    payload={'source_sha256':source['source_sha256'],'edits':[]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry,match='确数仍在') as err:m.candidate(tmp_path,out['revision_dir'])
    assert err.value.target=='agent_pl'
    if details[0]=='六十份':
        payload['edits']=[{'paragraph_id':'p0001','old':body,'occurrence':1,'replacement':'“接了60份，07:00要送到。”'}]
        put(tmp_path,out['revision_patch_path'],payload)
        with pytest.raises(m.Retry,match='确数仍在'):m.candidate(tmp_path,out['revision_dir'])
    payload['edits']=[{'paragraph_id':'p0001','old':body,'occurrence':1,'replacement':replacement}]
    put(tmp_path,out['revision_patch_path'],payload)
    m.candidate(tmp_path,out['revision_dir'])
    checks[0].update(action='keep',remove=[],reason='确数用于定量和交付凭证。')
    assert m.precision_goals(source,checks)==[]
    with pytest.raises(ValueError,match='逐项'):m.precision_goals(source,[])


def test_precision_scope_preserves_useful_dose_and_same_number_in_another_paragraph(tmp_path):
    m=module()
    first='“城门要收三十枚，八点前到。”'
    useful='“这药只能吃五毫克，八点前服完才能取血。”'
    put(tmp_path,'story/0001/chapter.md',first+'\n\n'+useful)
    out=m.prepare(tmp_path,'0001','mixed-precision','1-100')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    put(tmp_path,'critique.json',{'issues':[],'precision_checks':[
        {'paragraph_id':'p0001','action':'revise','remove':['三十枚','八点'],'reason':'收费数和具体钟点不改变此处的去留。'},
        {'paragraph_id':'p0002','action':'keep','remove':[],'reason':'剂量和时限决定能否完成后续检查。'},
    ]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[
        {'paragraph_id':'p0001','old':first,'occurrence':1,'replacement':'“关门前还来得及，过门得交钱。”'},
    ]})
    m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    assert context['candidate'].endswith(useful)
    assert [row['id'] for row in context['goals']]==['precision-p0001']


def test_precision_repeated_turns_are_checked_and_rejected_when_moved(tmp_path):
    m = module()
    body = '“六点？”\n\n“六点还得对账。”\n\n她手里的账本还没合上。'
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'repeated-precision', '1-100')
    source = json.loads((tmp_path / out['revision_source_input']).read_text(encoding='utf-8'))
    assert [row['paragraph_id'] for row in source['precision_candidates']] == ['p0001', 'p0002']
    checks = [dict(paragraph_id=key, action='revise', remove=['六点'], reason='只需知道对账以后才能走。')
              for key in ('p0001', 'p0002')]
    m.precision_goals(source, checks)
    with pytest.raises(ValueError, match='范围'):
        m.precision_goals(source, [dict(row, action='outside_scope', remove=[]) for row in checks])
    put(tmp_path, 'critique.json', {'issues': [], 'precision_checks': checks})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    payload = {'source_sha256': source['source_sha256'], 'edits': [
        dict(paragraph_id='p0001', old='六点？', replacement='收摊就走？', occurrence=1),
        dict(paragraph_id='p0002', old='六点还得对账。', replacement='我还得对账。', occurrence=1),
        dict(paragraph_id='p0003', old='她手里的账本', replacement='06:00她手里的账本', occurrence=1),
    ]}
    put(tmp_path, out['revision_patch_path'], payload)
    with pytest.raises(m.Retry, match='确数仍在'):
        m.candidate(tmp_path, out['revision_dir'])
    payload['edits'].pop()
    put(tmp_path, out['revision_patch_path'], payload)
    m.candidate(tmp_path, out['revision_dir'])


def test_dialogue_exchange_is_anchored_and_returns_unfixed_turns_to_writer(tmp_path):
    m=module()
    body='“你替我答应了？”\n\n他手里还提着她的饭盒。\n\n“我已经替你答应了这件事。”\n\n门响了。'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','dialogue-example','1-100',dialogue_check=True)
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf8'))
    assert source['dialogue_check'] is True
    put(tmp_path,'critique.json',{'issues':[]})
    with pytest.raises(m.Retry) as exc:
        m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    assert exc.value.target=='agent_sc'

    turns=[{'paragraph_id':'p0001','quote':'你替我答应了？'},
           {'paragraph_id':'p0003','quote':'我已经替你答应了这件事。'}]
    row={'status':'revise','turns':turns,'reason':'后一轮只重复双方已知的承诺。',
         'goal':'让回应交代他怎么处理承诺。'}
    put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':[row]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf8'))
    assert writer['goals'][0]['paragraph_ids']==['p0001','p0002','p0003']

    payload={'source_sha256':source['source_sha256'],'edits':[]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry,match='对白返修目标') as exc:
        m.candidate(tmp_path,out['revision_dir'])
    assert exc.value.target=='agent_pl'
    payload['edits']=[{'paragraph_id':'p0003','old':turns[1]['quote'],'occurrence':1,'replacement':'我去跟人家说。'}]
    put(tmp_path,out['revision_patch_path'],payload)
    m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert [row['id'] for row in context['goals']]==['dialogue-1']
    report=json.loads(approved(m,out,tmp_path))
    for check in report['expression_checks']:check['excerpts']=['门响了。']
    report['issue_outcomes']=[{'id':'dialogue-1','status':'remaining','reason':'答话仍回避了对方的追问。',
                               'excerpts':['你替我答应了？','我去跟人家说。']}]
    assert any('仍未解决' in reason for reason in m.review_decision(report,context))


def test_dialogue_exchange_rejects_unrelated_or_unordered_quotes():
    m=module();body='“你走吧。”\n\n桌上有碗。\n\n“票在这儿。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body)}
    row={'status':'revise','reason':'接话生硬','goal':'修改接话','turns':[
        {'paragraph_id':'p0003','quote':'票在这儿。'},{'paragraph_id':'p0001','quote':'你走吧。'}]}
    with pytest.raises(ValueError,match='顺序'):
        m.dialogue_goals(source,[row])
    row['turns']=[{'paragraph_id':'p0001','quote':'你走吧。'},{'paragraph_id':'p0002','quote':'桌上有碗。'}]
    with pytest.raises(ValueError,match='对白'):
        m.dialogue_goals(source,[row])


def test_dialogue_review_v2_requires_both_checks_and_an_edit_in_the_target_exchange():
    m=module()
    body='“别揪着这事不——”\n\n“我没揪。”\n\n她把收据递了过去。\n\n“东西能自己走回去？”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':2}
    echo={'focus':'literal_echo','status':'revise','reason':'顺着动词抢白，没接住对方想停下争执的意思。',
          'goal':'让她接住对方想叫停的意思。','target_turn':1,'turns':[
              {'paragraph_id':'p0001','quote':'别揪着这事不——'},
              {'paragraph_id':'p0002','quote':'我没揪。'}]}
    with pytest.raises(ValueError,match='逐项'):
        m.dialogue_goals(source,[echo])
    no_pressure={'focus':'situational_speech','status':'not_applicable','reason':'没有可对照的忙碌说明。','goal':'','turns':[]}
    goals=m.dialogue_goals(source,[echo,no_pressure])
    assert goals[0]['target']==echo['turns'][1]
    unrelated_edit={'paragraph_id':'p0004','old':'东西能自己走回去？','occurrence':1,'replacement':'东西没拿回来。'}
    with pytest.raises(ValueError,match=goals[0]['id']):
        m.check_dialogue_goals([unrelated_edit],goals,source)
    target=echo['turns'][1]['quote']
    edit={'paragraph_id':'p0002','old':target,'occurrence':1,'replacement':'你先把箱子抬下来。'}
    m.check_dialogue_goals([edit],goals,source)
    edit['replacement']='我没揪。你先把箱子抬下来。'
    m.check_dialogue_goals([edit],goals,source)


def test_dialogue_review_v3_anchors_checklist_and_one_sided_speech(tmp_path):
    m=module()
    body='“来过没有？”\n\n“没有。”\n\n“门呢？”\n\n她给房东留了一段语音：“您好。锁坏了。我还在门口。”'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','dialogue-v3','1-100',dialogue_check=True,dialogue_check_version=3)
    absent={'status':'not_applicable','reason':'没有适用情境。','goal':'','turns':[]}
    legacy=[dict(absent,focus=focus) for focus in ('literal_echo','situational_speech')]
    with pytest.raises(m.Retry,match='逐项'):
        put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':legacy})
        m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    checks=legacy+[
        {'focus':'checklist_exchange','status':'revise','reason':'第二问与未等到的人脱节。','target_turn':2,
         'goal':'由没等到人时必须处理的事引出锁。','preserve':['人还没来，门的情况影响下一步'],
         'turns':[{'paragraph_id':key,'quote':quote} for key,quote in
                  [('p0001','来过没有？'),('p0002','没有。'),('p0003','门呢？')]]},
        {'focus':'scripted_delivery','status':'revise','reason':'她急着进屋却逐项宣读现状。','target_turn':0,
         'goal':'先说要房东帮忙的事。','preserve':['锁坏了','还在门口'],
         'turns':[{'paragraph_id':'p0004','quote':'您好。锁坏了。我还在门口。'}]},
    ]
    put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':checks})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf8'))
    assert [(row['focus'],row['preserve']) for row in writer['goals']]==[
        ('checklist_exchange',['人还没来，门的情况影响下一步']),('scripted_delivery',['锁坏了','还在门口'])]
    assert writer['goals'][1]['target']['paragraph_id']=='p0004'


def test_dialogue_v4_turns_voice_flattening_into_a_grounded_repair():
    m=module()
    body='“你先说门怎么坏的。”\n\n“门的确坏了，没约修理时间。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':4}
    checks=[{'focus':focus,'status':'not_applicable','reason':'本处无该类情境。','goal':'','turns':[]}
            for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery')]
    with pytest.raises(ValueError,match='voice_contrast'):
        m.dialogue_goals(source,checks)
    checks.append({'focus':'voice_contrast','status':'revise','reason':'答话在汇报，与对方问的事脱节。',
                   'goal':'让他避开追责，先争取进屋。','target_turn':1,'preserve':['锁坏了，且无人约时间'],
                   'turns':[{'paragraph_id':'p0001','quote':'你先说门怎么坏的。'},
                            {'paragraph_id':'p0002','quote':'门的确坏了，没约修理时间。'}]})
    assert m.dialogue_goals(source,checks)[0]['preserve']==['锁坏了，且无人约时间']


def test_dialogue_v4_accepts_identical_words_at_distinct_source_turns():
    m=module()
    body='“我已经说过了。”\n\n“我已经说过了。你再想想。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':4}
    checks=[{'focus':focus,'status':'not_applicable','reason':'无该类情境。','goal':'','turns':[]}
            for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery')]
    review={'focus':'voice_contrast','status':'revise','reason':'各自用同一句发言开头。','goal':'按各自所求接话。',
            'preserve':['两人先前已说过此事'],'target_turn':1,'turns':[
                {'paragraph_id':'p0001','quote':'我已经说过了。'},
                {'paragraph_id':'p0002','quote':'我已经说过了。你再想想。'}]}
    assert m.dialogue_goals(source,[*checks,review])[0]['target']==review['turns'][1]
    review['turns'][1]=review['turns'][0].copy()
    with pytest.raises(ValueError,match='不可重叠'):
        m.dialogue_goals(source,[*checks,review])


def test_compact_exchange_keeps_frozen_ids_when_quoted_labels_are_not_speech():
    m = module()
    body = ('他盯着屏上的“核验中”。\n\n“那留下的人呢？”\n\n'
            '我记得他用了个“也”。\n\n“按名册办。”\n\n———\n\n'
            '屏幕仍是“核验中”。\n\n他听见了广播：“走。”')
    source = {'source_body': body, 'paragraphs': m.patches.paragraphs(body), 'dialogue_check_version': 9}
    checks = [{'focus': focus, 'status': 'not_applicable', 'reason': '无此类情境。', 'goal': '', 'turns': []}
              for focus in ('literal_echo', 'situational_speech', 'scripted_delivery', 'voice_contrast')]
    revision = {'exchange_id': 'exchange-1', 'phase': 'opening', 'target_turn': 1,
                'reason': '没有接住追问。', 'goal': '让决定回应谁得留下。', 'preserve': ['仍然按名册办。']}
    legacy_review = {'passed': ['exchange-2'], 'revisions': [revision]}
    assert m.dialogue_goals(source, checks, legacy_review)[0]['target']['quote'] == '那留下的人呢？'
    review = {**legacy_review, 'non_turn_ids': ['d0001', 'd0003', 'd0005']}
    goal, = m.dialogue_goals(source, checks, review)
    assert goal['id'] == 'dialogue-exchange-1'
    assert [turn['quote'] for turn in goal['turns']] == ['那留下的人呢？', '按名册办。']
    assert goal['target']['paragraph_id'] == 'p0004'
    with pytest.raises(ValueError, match='非对白'):
        m.dialogue_goals(source, checks, {**review, 'non_turn_ids': ['d0999']})
    reported = {**checks[2], 'status': 'pass', 'turns': [{'turn_id': 'd0003'}]}
    with pytest.raises(ValueError, match='非对白'):
        m.dialogue_goals(source, [*checks[:2], reported, checks[3]], review)
    with pytest.raises(ValueError, match='至少两处'):
        m.dialogue_goals(source, checks, {**review, 'passed': [], 'revisions': [
            revision, {**revision, 'exchange_id': 'exchange-2'}]})


@pytest.mark.parametrize('kind', ['dialogue', 'scene'])
def test_action_only_revision_needs_same_id_and_changed_exchange_evidence(tmp_path, kind):
    m = module()
    body = ('持牌者盯着我：“那留下的人呢？”\n\n'
            '我一时没接上话。\n\n我把手从名册上移开，作了决定：“按现有登记放行，他上船，你留下。”\n\n'
            '持牌者留在雨棚下。')
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'action-only', '1-5000', dialogue_check=True, dialogue_check_version=9)
    checks = [{'focus': focus, 'status': 'not_applicable', 'reason': '无此类情境。', 'goal': '', 'turns': []}
              for focus in ('literal_echo', 'situational_speech', 'scripted_delivery', 'voice_contrast')]
    critique = {'issues': [], 'dialogue_checks': checks,
                'exchange_review': {'passed': ['exchange-1'], 'revisions': []},
                'scene_checks': [{'focus': 'narration', 'status': 'not_applicable', 'reason': '无单独问题。',
                                  'goal': '', 'anchors': []}]}
    goal_id = 'dialogue-exchange-1' if kind == 'dialogue' else 'scene-1'
    goal = '让核验员先面对留下的人，再按名册放行。'
    if kind == 'dialogue':
        critique['exchange_review'] = {'passed': [], 'revisions': [
            {'exchange_id': 'exchange-1', 'phase': 'opening', 'target_turn': 1, 'reason': '没有接住追问。',
             'goal': goal, 'preserve': ['保留追问和逐人告知的结果。']}]}
    else:
        critique['scene_checks'] = [{'focus': 'narration', 'status': 'revise', 'reason': '只交代她停了。',
             'goal': goal, 'preserve': ['保留追问和逐人告知的结果。'],
             'anchors': [{'paragraph_id': f'p{i:04d}'} for i in range(1,4)]}]
    put(tmp_path, 'critique.json', critique)
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    editor = m.read(tmp_path / out['revision_input'])
    assert [row['id'] for row in editor['goals']] == [goal_id]
    edit = {'paragraph_id': 'p0002', 'old': '我一时没接上话。', 'occurrence': 1,
            'replacement': '我望着持牌者，等他抬起眼。', 'group_id': goal_id}
    payload = {'source_sha256': editor['source_sha256'], 'edits': [edit]}
    put(tmp_path, out['revision_patch_path'], payload)
    m.candidate(tmp_path, out['revision_dir'])
    context = m.read(tmp_path / out['revision_review_input'])
    assert m.packet.dialogue_exchanges(m.patches.paragraphs(body)) == m.packet.dialogue_exchanges(
        m.patches.paragraphs(context['candidate']))
    report = json.loads(approved(m, out, tmp_path))
    for check in report['expression_checks']:
        check['excerpts'] = ['持牌者留在雨棚下。']
    outcome = {'id': goal_id, 'status': 'resolved', 'excerpts': [
        '我望着持牌者，等他抬起眼。', '按现有登记放行，他上船，你留下。'],
        'reason': '停下来等持牌者看过来，核验员才当面回答，告知范围和决定仍与名册一致。'}
    report['issue_outcomes'] = [outcome]
    assert m.review_decision(report, context) == []
    outcome['excerpts'] = ['那留下的人呢？', '按现有登记放行，他上船，你留下。']
    assert m.review_decision(report, context) == []
    outcome['excerpts'] = ['按现有登记放行，他上船，你留下。', '持牌者留在雨棚下。']
    assert m.review_decision(report, context)
    outcome['excerpts'] = ['那留下的人呢？', '按现有登记放行，他上船，你留下。']
    report['change_reviews'][0]['preservation'] = {
        'status': 'lost', 'source_excerpt': '那留下的人呢？', 'candidate_excerpt': '按现有登记放行，他上船，你留下。',
        'reason': '问话原有的质疑作用受损。'}
    assert any('质疑作用受损' in reason for reason in m.review_decision(report, context))
    report['change_reviews'][0].pop('preservation')
    report['change_reviews'][0]['effect'] = 'equivalent'
    assert m.review_decision(report, context)
    outcome['id'] = 'renumbered'
    with pytest.raises(ValueError, match='逐项复核'):
        m.review_decision(report, context)
    outcome['id'] = goal_id
    report['change_reviews'][0]['effect'] = 'improved'
    put(tmp_path, out['revision_review_path'], report)
    m.commit(tmp_path, out['revision_dir'], json.dumps(report, ensure_ascii=False))
    assert (tmp_path/'story/0001/chapter.md').read_bytes() == context['candidate'].encode()
