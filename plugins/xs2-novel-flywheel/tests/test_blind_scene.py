import json
import pytest

from test_local_revision import module, put


@pytest.mark.parametrize('trial', [False, True])
def test_keep_allows_an_empty_patch_or_an_independent_trial(tmp_path, trial):
    m = module()
    lines = ['泵压正常。', '第二盏灯还亮着。', '值班员在记录上签了字。']
    body = '\n\n'.join(lines)
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'optional-scene', scoped_review=True,
                    whole_chapter_review=True, blind_scenes=True)
    scenes = [{'paragraph_id': f'p{i:04d}', 'quote': line, 'decision': 'keep',
               'impact': '这是值班记录的原有语体。', 'action': '保留。'}
              for i, line in enumerate(lines, start=1)]
    put(tmp_path, 'critique.json', {'issues': [], 'scene_pass': scenes})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    edits = [{'paragraph_id': 'p0001', 'old': lines[0], 'replacement': '泵压已复原。',
              'occurrence': 1}] if trial else []
    source = m.read(tmp_path/out['revision_input'])
    put(tmp_path, out['revision_patch_path'], {'source_sha256': source['source_sha256'], 'edits': edits})
    m.candidate(tmp_path, out['revision_dir'])
    ballot = m.read(tmp_path/out['revision_blind_packet'])
    vote = {'ballot': ballot['ballot'], 'scenes': [
        {'id': s['id'], 'prefer': 'tie', 'exceptions': [], 'voice_quote': s['A'][:2],
         'redundant_quote': '', 'reason': '两版的阅读作用相当。'} for s in ballot['scenes']]}
    put(tmp_path, out['revision_blind_path'], vote)
    m.accept_blind(tmp_path, out['revision_dir'], json.dumps(vote, ensure_ascii=False))
    assert m.read(tmp_path/out['revision_review_input'])['candidate'] == source['source_body']


@pytest.mark.parametrize('choice,feedback,meaning,voice', [
    ('original','',True,True), ('new','',True,True), ('mix','',True,True), ('tie','',True,True),
    ('tie','请换一种表达，加强情绪。',True,True), ('tie','只校错和删重，尽量少动。',True,True),
    ('tie','重写这两场。',False,True), ('tie','重写这两场。',True,False),
])
def test_anonymous_scene_selection_signs_only_the_exact_chosen_sentences(tmp_path, choice, feedback, meaning, voice):
    m = module()
    body = '1\n\n她等了等。她关上了门。\n\n2\n\n他等在桥上。'
    put(tmp_path, 'story/0001/chapter.md', body)
    (tmp_path/'story/0001/chapter.md').write_bytes(body.encode())
    put(tmp_path,'feedback.md',feedback)
    out = m.prepare(tmp_path,'0001','read-test',feedback_path='feedback.md',scoped_review=True,whole_chapter_review=True,blind_scenes=True)
    put(tmp_path,'critique.json',{'issues':[]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    edits = [{'paragraph_id':'p0001','old':'她等了等。她关上了门。','replacement':'她等了一会儿。她把门关上了。','occurrence':1},
             {'paragraph_id':'p0002','old':'他等在桥上。','replacement':'他在桥上等着。','occurrence':1}]
    if not meaning:
        edits[0]['replacement'] = '她没等。她推开了门。'
        edits[1]['replacement'] = '他已经离开了桥。'
    elif not voice:
        edits[0]['replacement'] = '其人稍候，旋即闭户。'
        edits[1]['replacement'] = '彼候于桥上。'
    put(tmp_path,out['revision_patch_path'],{'source_sha256':m.sha(body.encode()),'edits':edits})
    m.candidate(tmp_path,out['revision_dir'])
    packet = m.read(tmp_path/out['revision_blind_packet'])
    creative = feedback.startswith(('请换','重写'))
    assert packet.get('reading_task') == ('creative_equivalence' if creative else None)
    assert all(set(s)=={'id','A','B','choices'} for s in packet['scenes'])
    votes, orientations = [], []
    for i,scene in enumerate(packet['scenes']):
        old = 'A' if edits[i]['old'] in scene['A'] else 'B'
        orientations.append(old)
        base = old if choice!='new' else ('A' if old=='B' else 'B')
        votes.append({'id':scene['id'],'prefer':'tie' if choice=='tie' else base,'exceptions':[scene['choices'][0]['id']] if choice=='mix' and i==0 else [],
                      'same_meaning':meaning,'same_voice':voice,'voice_quote':scene[base].split('\n')[-1][:2],'redundant_quote':'','reason':'这句停得合适。'})
    assert len(set(orientations))==2
    vote={'ballot':packet['ballot'],'scenes':votes}
    put(tmp_path,out['revision_blind_path'],vote)
    raw=json.dumps(vote,ensure_ascii=False)
    m.accept_blind(tmp_path,out['revision_dir'],raw)
    ctx=m.read(tmp_path/out['revision_review_input'])
    expected={'tie':body,'original':body,'mix':body.replace('她等了等。','她等了一会儿。'),
              'new':body.replace(edits[0]['old'],edits[0]['replacement']).replace(edits[1]['old'],edits[1]['replacement'])}['new' if choice=='tie' and creative and meaning and voice else choice]
    assert ctx['candidate']==expected and ctx['whole_review_phase']=='signoff'
    assert (tmp_path/'story/0001/chapter.md').read_text('utf8')==body
    report={'protocol':'local-review-v3','compatible':True,'issues':[],'change_reviews':[],'added_text_reviews':[],
            'issue_outcomes':[{'id':k,'status':'resolved','reason':'两句话接得上。','excerpts':[v[0]]}
                              for k,v in m.signoff_evidence(ctx).items()]}
    put(tmp_path,out['revision_review_path'],report)
    final=json.dumps(report,ensure_ascii=False)
    receipt=m.commit(tmp_path,out['revision_dir'],final)
    task={'task_id':'read-test','parameter_values':{**out,'revision_review_result':final,'revision_blind_result':raw}}
    assert m.verify_attempt(tmp_path,task)==receipt
    assert (tmp_path/'story/0001/chapter.md').read_text('utf8')==expected
    with pytest.raises(ValueError,match='匿名对读'):
        m.verify_attempt(tmp_path,{**task,'parameter_values':{**task['parameter_values'],'revision_blind_result':'{}'}})


def test_mixed_directives_use_local_scope_and_ignore_words_inside_story_quotes():
    blind = module().blind
    rows = [{'id': f'p{i:04}', 'text': line} for i, line in enumerate(
        ('请进。', '他说，重写。', '重写旧条例。', '请回。'), 1)]
    policy = blind.tie_policy('其余尽量少动，p0001 到 p0003 换个说法；“他说，重写。”只校错；p0003 不要改写。', rows)
    assert policy == {'default': 'original', 'paragraphs': {
        'p0001': 'creative', 'p0002': 'original', 'p0003': 'original'}}
    assert blind.tie_policy('全文加强情绪，最后一段尽量少动。', rows) == {
        'default': 'creative', 'paragraphs': {'p0004': 'original'}}
