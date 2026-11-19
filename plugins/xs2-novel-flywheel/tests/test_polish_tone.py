from test_local_revision import module, put, scoped_setup, scoped_report


def test_ordinary_polish_freezes_located_hints_and_compares_published_text(tmp_path):
    m = module()
    line = '她把红铅笔放在窗台上。' * 55
    body = line + '\r\n\r\n不是钥匙，而是门闩。\r\n'
    path = tmp_path / 'story/0001/chapter.md'
    path.parent.mkdir(parents=True)
    path.write_bytes(body.encode())
    out = m.prepare(tmp_path, '0001', 'tone-trial', '1-5000', scoped_review=True)
    view = m.read(tmp_path / out['revision_source_model'])
    assert 'tone_review' in view
    hint = next(h for h in view['tone_review']['hints'] if h['rule'] == '翻案腔')
    assert (hint['paragraph'], hint['line']) == ('p0002', 3)
    before = m.read(tmp_path / out['revision_dir'] / 'tone-before.json')
    assert before['sha256'] == m.sha(path.read_bytes())
    assert len(before['metrics']['hits']['翻案腔']) == 1
    put(tmp_path, 'critique.json', {'issues': []})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    edit = {'paragraph_id':'p0002','old':'不是钥匙，而是门闩。','occurrence':1,
            'replacement':'她指了指门闩。','independent':True}
    review = scoped_report(m, tmp_path, out, [edit])
    receipt = m.commit(tmp_path, out['revision_dir'], review)
    after = m.read(tmp_path / out['revision_dir'] / 'tone-after.json')
    assert after['sha256'] == receipt['after_sha256'] == m.sha(path.read_bytes())
    assert not after['metrics']['hits']['翻案腔']
    assert '翻案腔 | 1 | 0' in (tmp_path / receipt['tone_report']).read_text('utf8')
    assert m.commit(tmp_path, out['revision_dir'], review)['tone_report'] == receipt['tone_report']


def test_confirmed_reader_scope_has_no_new_style_hints(tmp_path):
    m, out, _ = scoped_setup(tmp_path)
    assert out['revision_critique_mode'] == 'confirmed'
    assert 'tone_review' not in m.read(tmp_path / out['revision_source_model'])
    assert not (tmp_path / out['revision_dir'] / 'tone-before.json').exists()


def test_grounded_minor_edit_reaches_writer_only_under_new_tone_review(tmp_path):
    m = module()
    body = '她把借条还给我。\n\n她的意思是，这张借条现在属于我了。'
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'tone-handoff', scoped_review=True)
    issue = {'dimension':'收尾再总结', 'severity':'low', 'description':'旁白重复上一句的动作。',
             'evidence':['她把借条还给我。','她的意思是，这张借条现在属于我了。'],
             'impact':'归还借条的动作已经让读者知道易手，再解释拖慢收尾。','suggestion':'收掉第二句，以还借条的动作落笔。'}
    critique = {'issues':[issue, dict(issue, evidence=['并不存在的原文']),
                          dict(issue, impact=''), dict(issue, evidence_status='unverified')]}
    put(tmp_path,'critique.json',critique)
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    writer = m.read(tmp_path / out['revision_editor_model'])
    assert len(writer['goals']) == 1
    goal, = writer['goals']
    assert goal['level'] == 'advisory' and goal['evidence'] == issue['evidence']
    assert issue['impact'] in goal['goal']
    assert not m.scoped_critic_goals({'source_body':body, 'tone_review':{'revision':'old'}}, {'issues':[issue]})


def test_verified_wrapper_and_whitespace_use_actual_source_in_goal():
    from test_humanity_review import polish_post

    m = module()
    body = '灯还亮着。\r\n\r\n“我来关。”'
    issue = {'dimension':'衔接','severity':'low','description':'现场动作缺少照应。',
             'evidence':['“灯还亮着。”', '灯还亮着。 “我来关。”'],
             'impact':'灯的状态前后不明。','suggestion':'接上关灯动作。'}
    critique = polish_post.normalize_critique({'feels_human':True,'issues':[issue]}, body)
    source = {'source_body':body,'tone_review':{'handoff_version':2}}
    goal, = m.scoped_critic_goals(source, critique)
    assert goal['excerpts'] == ['灯还亮着。', body]
    assert critique['issues'][0]['evidence'] == issue['evidence']


def test_deleted_goal_is_reviewable_at_its_surviving_boundary(tmp_path):
    import json
    import pytest

    m = module()
    body = '灯还亮着。\n\n她把借条还给我。\n\n借条现在属于我了。'
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'tone-deletion', scoped_review=True)
    issue = {'dimension':'收尾', 'severity':'low', 'description':'重复解释',
             'evidence':['借条现在属于我了。'], 'impact':'拖慢收尾。', 'suggestion':'以还借条结束。'}
    put(tmp_path, 'critique.json', {'issues':[issue]})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    edit = {'paragraph_id':'p0003','old':issue['evidence'][0],'occurrence':1,'replacement':'','independent':True}
    report = json.loads(scoped_report(m, tmp_path, out, [edit], action='resolved'))
    context = m.read(tmp_path / out['revision_review_input'])
    outcome, = report['issue_outcomes']
    outcome['excerpts'] = ['灯还亮着。']
    with pytest.raises(ValueError, match='原编号'):
        m.scoped_assessment(report, context)
    outcome['excerpts'] = ['她把借条还给我。']
    assert not m.scoped_assessment(report, context)['problems']


def test_unchanged_edit_keeps_independently_reviewed_candidate_intact(tmp_path):
    m=module()
    put(tmp_path, 'story/0001/chapter.md', '她拉开窗帘。\n\n屋里进了光。')
    out=m.prepare(tmp_path, '0001', 'tone-unchanged', scoped_review=True)
    put(tmp_path, 'critique.json', {'issues':[]})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    edits=[
        {'paragraph_id':'p0001','old':'窗帘','replacement':'门帘','occurrence':1,'group_id':'door'},
        {'paragraph_id':'p0002','old':'进了光','replacement':'进了光','occurrence':1,'group_id':'door'},
    ]
    scoped_report(m, tmp_path, out, edits)
    folder=tmp_path/out['revision_dir']
    context=m.read(folder/'review-input.json')
    publication, reasons=m.scoped_publication(context, {'hard':[], 'facts':[], 'blocked':{1}},
                                               m.read(folder/'source-binding.json'))
    assert not reasons
    assert publication['candidate']==context['candidate']
    assert publication['edits']==edits[:1]


def test_scene_goal_validates_frozen_critic_evidence_under_editor_field_name():
    m=module()
    source={'source_body':'她收起借条。\n\n借条已经归她了。'}
    issue={'dimension':'scene_expression','severity':'medium','evidence':['借条已经归她了。','她收起借条。'],
           'scene_focus':{'quote':'借条已经归她了。','preserve':['她收起借条。']},
           'suggestion':'删掉重复解释。'}
    goal,=m.scoped_critic_goals(source,{'issues':[issue]})
    assert goal['scene_anchor']['paragraph_id']=='p0002'


def test_scene_pass_binds_writer_targets_and_respects_keep(tmp_path):
    import pytest
    m=module()
    put(tmp_path,'story/0001/chapter.md','她问了三遍。\n\n他把门打开。')
    out=m.prepare(tmp_path,'0001','scene-pass',scoped_review=True)
    rows=[{'paragraph_id':'p0001','quote':'问了三遍','decision':'revise','impact':'问答停在原地。',
           'action':'让第三次发问引出开门动作。'},
          {'paragraph_id':'p0002','quote':'他把门打开。','decision':'keep','impact':'人物已经回应。','action':'保留。',
           'alternative':'让她听见门锁转动才止住第三声问话。'}]
    put(tmp_path,'critique.json',{'issues':[],'scene_pass':rows})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    writer=m.read(tmp_path/out['revision_editor_model'])
    assert writer['scene_workshop']['scene_pass']==rows
    assert writer['scene_workshop']['assignment']
    goal,trial=writer['goals']
    assert trial['id']=='trial-1' and rows[1]['alternative'] in trial['goal']
    assert goal['paragraph_ids']==['p0001'] and rows[0]['action'] in goal['goal']
    frozen=m.patches.paragraphs('她问了三遍。\n\n他把门打开。')
    assert m.tone.verified_scenes([dict(rows[0],paragraph_id='p0002')],frozen)==rows[:1]
    assert m.tone.verified_scenes([dict(rows[0],quote='不存在'),rows[1]],frozen)==rows[1:]
    windows=writer['scene_workshop']['trial_windows']
    with pytest.raises(ValueError,match='替代稿'):
        m.tone.untried_windows(windows,[])
    with pytest.raises(ValueError,match='仍集中在局部'):
        m.tone.untried_windows(windows,[{'paragraph_id':'p0001','old':'问','replacement':'说'},
                                        {'paragraph_id':'p0002','old':'门','replacement':'门'}])
    assert not m.tone.untried_windows(windows,[{'paragraph_id':'p0001','old':'问','replacement':'说'},
                                               {'paragraph_id':'p0002','old':'门','replacement':'窗'}])
    third={'first':'p0003','last':'p0003','anchor':'p0003'}
    across=[{'paragraph_id':p,'old':'问','replacement':'说'} for p in ('p0001','p0003')]
    assert m.tone.untried_windows([*windows,third],across)==windows[1:]


def test_deletion_distinguishes_redundancy_carried_meaning_and_real_loss(tmp_path):
    import json
    import pytest
    m=module()
    put(tmp_path,'story/0001/chapter.md','她把门推开了。\n\n门现在开着。')
    out=m.prepare(tmp_path,'0001','delete-review',scoped_review=True)
    put(tmp_path,'critique.json',{'issues':[]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    edit={'paragraph_id':'p0002','old':'门现在开着。','replacement':'','occurrence':1,'independent':True}
    report=json.loads(scoped_report(m,tmp_path,out,[edit]))
    context=m.read(tmp_path/out['revision_review_input'])
    decision={'status':'lost','source_excerpt':edit['old'],'candidate_excerpt':'','reason':'原句删了，前文仍交代门已打开。'}
    report['change_reviews'][0]['preservation']=decision
    with pytest.raises(ValueError,match='lost_function'):
        m.scoped_assessment(report,context)
    decision.update(lost_function='人物唯一的发现渠道消失。')
    assert m.scoped_assessment(report,context)['blocked']=={0}
    decision.pop('lost_function')
    decision.update(status='preserved',candidate_excerpt='她把门推开了。')
    assert not m.scoped_assessment(report,context)['blocked']
    decision.update(status='not_applicable',source_excerpt='',candidate_excerpt='')
    assert not m.scoped_assessment(report,context)['blocked']


def test_scene_trial_subset_requires_fresh_independent_review(tmp_path):
    import json
    import pytest
    m=module()
    body='她敲门。\n\n他开门。'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','scene-subset',scoped_review=True)
    scenes=[{'paragraph_id':pid,'quote':q,'action':'保留。','decision':'keep','impact':'这是现场动作。'}
            for pid,q in [('p0001','她敲门。'),('p0002','他开门。')]]
    put(tmp_path,'critique.json',{'issues':[],'scene_pass':scenes})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    edits=[{'paragraph_id':s['paragraph_id'],'old':s['quote'],'replacement':new,'occurrence':1}
           for s,new in zip(scenes,['她叩了两下门。','他推开了门。'])]
    first=scoped_report(m,tmp_path,out,edits)
    with pytest.raises(m.Retry,match='整稿签发'):
        m.commit(tmp_path,out['revision_dir'],first)
    assert (tmp_path/'story/0001/chapter.md').read_text('utf-8')==body
    context=m.read(tmp_path/out['revision_review_input'])
    assert context['edits']==edits[:1] and context['whole_review_phase']=='signoff'
    assert m.scene_trial_prunes(json.loads(first),context)==[]
    goal,=context['goals']
    review={'protocol':'local-review-v3','compatible':True,'issues':[],
            'change_reviews':[],'added_text_reviews':[],
            'issue_outcomes':[{'id':goal['id'],'status':'remaining','excerpts':['她叩了两下门。'],'reason':'相邻场景与次数冲突。'}]}
    assert m.scoped_assessment(review,context)['hard']
    review['issue_outcomes'][0]['status']='resolved'
    review['issue_outcomes'][0]['reason']='门外叩门与室内开门连贯，人物和声音一致。'
    assert m.scoped_assessment({**review,'compatible':False,'issues':[{
        'id':'continuity','category':'continuity','source_quote':'她敲门。',
        'candidate_quote':'她叩了两下门。','reason':'依据有矛盾。'}]},context)['hard']
    with pytest.raises(ValueError,match='须按原编号'):
        m.scoped_assessment({**review,'issue_outcomes':[]},context)
    assert m.read(tmp_path/out['revision_review_model'])['signoff_evidence'][goal['id']]==['她叩了两下门。']
    put(tmp_path,out['revision_review_path'],review)
    raw=json.dumps(review,ensure_ascii=False)
    receipt=m.commit(tmp_path,out['revision_dir'],raw)
    assert receipt['changed_spans']==1 and receipt['after_sha256']==context['candidate_sha256']
    task={'task_id':'scene-subset','parameter_values':{'revision_dir':out['revision_dir'],'revision_review_result':raw}}
    assert m.verify_attempt(tmp_path,task)==receipt
