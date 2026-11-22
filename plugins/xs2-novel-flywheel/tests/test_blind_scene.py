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


@pytest.mark.parametrize('choice', ['original','new','mix','tie'])
def test_anonymous_scene_selection_signs_only_the_exact_chosen_sentences(tmp_path, choice):
    m = module()
    body = '1\n\n她等了等。她关上了门。\n\n2\n\n他等在桥上。'
    put(tmp_path, 'story/0001/chapter.md', body)
    (tmp_path/'story/0001/chapter.md').write_bytes(body.encode())
    out = m.prepare(tmp_path,'0001','read-test',scoped_review=True,whole_chapter_review=True,blind_scenes=True)
    put(tmp_path,'critique.json',{'issues':[]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    edits = [{'paragraph_id':'p0001','old':'她等了等。她关上了门。','replacement':'她数到三。她锁了门。','occurrence':1},
             {'paragraph_id':'p0002','old':'他等在桥上。','replacement':'他蹲在桥头。','occurrence':1}]
    put(tmp_path,out['revision_patch_path'],{'source_sha256':m.sha(body.encode()),'edits':edits})
    m.candidate(tmp_path,out['revision_dir'])
    packet = m.read(tmp_path/out['revision_blind_packet'])
    assert set(packet)=={'ballot','scenes'}
    assert all(set(s)=={'id','A','B','choices'} for s in packet['scenes'])
    votes, orientations = [], []
    for i,scene in enumerate(packet['scenes']):
        old = 'A' if edits[i]['old'] in scene['A'] else 'B'
        orientations.append(old)
        base = old if choice!='new' else ('A' if old=='B' else 'B')
        votes.append({'id':scene['id'],'prefer':'tie' if choice=='tie' else base,'exceptions':[scene['choices'][0]['id']] if choice=='mix' and i==0 else [],
                      'voice_quote':scene[base].split('\n')[-1][:2],'redundant_quote':'','reason':'这句停得合适。'})
    assert len(set(orientations))==2
    vote={'ballot':packet['ballot'],'scenes':votes}
    put(tmp_path,out['revision_blind_path'],vote)
    raw=json.dumps(vote,ensure_ascii=False)
    m.accept_blind(tmp_path,out['revision_dir'],raw)
    ctx=m.read(tmp_path/out['revision_review_input'])
    expected={'tie':body,'original':body,'mix':body.replace('她等了等。','她数到三。'),
              'new':body.replace(edits[0]['old'],edits[0]['replacement']).replace(edits[1]['old'],edits[1]['replacement'])}[choice]
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
