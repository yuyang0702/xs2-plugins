import io
import json
from unittest.mock import Mock
import pytest

from test_local_revision import module, put


def test_lieflat_marks_merge_across_a_boundary_and_include_otherwise_passing_text():
    m = module()
    body = '我看见雨伞、胶鞋、帽子。\r\n\r\n房租、押金、中介费得算清。'
    paras = m.patches.paragraphs(body)
    unit = {'id': 'p0001-s1', 'paragraph_id': 'p0001', 'old': '帽子。', 'occurrence': 1}
    packet = {'rewrite_units': [unit], 'reference_paragraphs': ['p0002'], 'reference_excerpts': {}}
    m.tone.annotate_rewrites(packet, paras)
    targets = packet['rewrite_units']
    assert [u['paragraph_id'] for u in targets] == ['p0001', 'p0002']
    assert targets[0]['old'] == paras[0]['text']
    assert all(u['lieflat_review']['mandatory_phrases'] for u in targets)
    rows = [{'id': u['id'], 'reference_id': 'p0002', 'replacement': u['old'] + '呢'} for u in targets]
    with pytest.raises(ValueError, match='仍照录'):
        m.zhuque.compile_rewrites(packet, {'edits': [], 'rewrites': rows})
    rows[0]['replacement'] = '帽子压在胶鞋上，雨伞靠着门。'
    rows[1]['replacement'] = '先算押金。交过中介费，手里才是剩下的房租。'
    edits = m.zhuque.compile_rewrites(packet, {'edits': [], 'rewrites': rows})
    assert len(edits) == 2


def test_overlapping_quote_anchors_keep_the_unmarked_prefix():
    m = module()
    body = '哈哈哈。'
    units = m.zhuque.rewrite_units(body, m.patches.paragraphs, m.patches.paragraphs(body), [(0,1,0),(1,3,2),(3,4,0)])
    assert len(units) == 1 and units[0]['occurrence'] == 2
    edit = {k: v for k, v in units[0].items() if k != 'id'}
    edit['replacement'] = '嘿'
    assert m.patches.apply_patches(body, {'source_sha256':m.patches.digest(body), 'edits':[edit]}) == '哈嘿。'


def test_segments_map_to_frozen_paragraphs_and_exclude_mixed_references(tmp_path, monkeypatch):
    m = module()
    body = '# 小说\r\n\r\n甲乙。\r\n\r\n丙丁。\r\n\r\n戊己。'
    text = '甲乙。\n\n丙丁。\n\n戊己。'
    key = tmp_path / 'key'
    key.write_text('test-key', encoding='utf-8')
    def respond(req, timeout):
        assert json.loads(req.data) == {'text': text, 'is_merge': False}
        data = {'status': 'success', 'labels_ratio': {'0': .5, '1': 0, '2': .5},
                'segment_labels': [{'text': text[:6], 'position': [0,6], 'label': 0},
                                   {'text': text[6:], 'position': [6,len(text)], 'label': 2}]}
        return io.BytesIO(json.dumps(data).encode())
    monkeypatch.setattr(m.zhuque, 'urlopen', respond)
    report = m.zhuque.analyze(body, m.patches.paragraphs, key)
    assert report['reference_paragraphs'] == ['p0002']
    target, = report['attention']
    assert (target['first'],target['last']) == ('p0003','p0004')
    assert target['nearby_references'] == ['p0002']
    assert report['reference_excerpts'] == {'p0002':'甲乙。'}
    assert [(u['paragraph_id'], u['old']) for u in report['rewrite_units']] == [
        ('p0003', '丁。'), ('p0004', '戊己。')]
    assert m.zhuque.analyze(body, m.patches.paragraphs, tmp_path/'missing')['status'] == 'unavailable'


def test_frozen_report_reaches_editors_and_retests_only_the_signed_text(tmp_path, monkeypatch):
    m = module()
    before = '灯灭了。\n\n她等着。'
    after = before.replace('灯灭了。','灯亮了。')
    put(tmp_path, 'story/0001/chapter.md', before)
    (tmp_path/'story/0001/chapter.md').write_bytes(before.encode())
    put(tmp_path,'zhuque-options.json',{'enabled':True,'reference_text':''})
    monkeypatch.setenv('XS2_ZHUQUE_KEY_FILE', str(tmp_path/'key'))
    report = {'status': 'success', 'trial_version': 1, 'attention': [{'first':'p0001','last':'p0001'}],
              'reference_paragraphs':['p0002'], 'labels_ratio':{'0':0,'1':0,'2':1}}
    detect = Mock(return_value=report)
    monkeypatch.setattr(m.zhuque,'analyze',detect)
    def prepare():
        return m.prepare(tmp_path,'0001','zhuque',scoped_review=True,whole_chapter_review=True,blind_scenes=True)
    out = prepare()
    assert prepare() == out and detect.call_count == 1
    put(tmp_path,'critique.json',{'issues':[]})
    folder = out['revision_dir']
    m.writer_input(tmp_path,folder,'critique.json')
    for k in ('revision_source_model','revision_editor_model'):
        assert m.read(tmp_path/out[k])['zhuque_review']['reference_paragraphs'] == ['p0002']
    assert any(g['id']=='trial-zhuque' for g in m.read(tmp_path/out['revision_editor_model'])['goals'])
    put(tmp_path,out['revision_patch_path'],{'source_sha256':m.sha(before.encode()),'edits':[
        {'paragraph_id':'p0001','old':'灯灭了。','replacement':'灯亮了。','occurrence':1}]})
    m.candidate(tmp_path,folder)
    packet = m.read(tmp_path/out['revision_blind_packet'])
    assert set(packet) == {'ballot','scenes'}
    scene, = packet['scenes']
    assert set(scene) == {'id','A','B','choices'}
    vote = {'ballot':packet['ballot'],'scenes':[{'id':scene['id'],'prefer':'A' if '灯亮了' in scene['A'] else 'B',
            'exceptions':[],'voice_quote':'她等着。','redundant_quote':'','reason':'前后呼应。'}]}
    put(tmp_path,out['revision_blind_path'],vote)
    m.accept_blind(tmp_path,folder,json.dumps(vote))
    context = m.read(tmp_path/out['revision_review_input'])
    review = {'protocol':'local-review-v3','compatible':True,'issues':[],'change_reviews':[],
              'added_text_reviews':[],'issue_outcomes':[{'id':i,'status':'resolved','reason':'动作承接。',
              'excerpts':[quotes[0]]} for i,quotes in m.signoff_evidence(context).items()]}
    put(tmp_path,out['revision_review_path'],review)
    receipt = m.commit(tmp_path,folder,json.dumps(review))
    assert [c.args[0] for c in detect.call_args_list] == [before,after]
    assert m.read(tmp_path/receipt['zhuque_report'])['after_sha256'] == m.sha(after.encode())


def test_mandatory_units_preserve_unflagged_text_and_retry_reverted_votes(tmp_path, monkeypatch):
    m = module()
    body = '灯灭了。她等着。\n\n风过门槛。'
    path = tmp_path/'story/0001/chapter.md'
    path.parent.mkdir(parents=True)
    path.write_bytes(body.encode())
    unit = {'id':'p0001-s1','paragraph_id':'p0001','old':'灯灭了。','occurrence':1}
    report = {'trial_version':2,'status':'success','rewrite_units':[unit],
              'attention':[{'first':'p0001','last':'p0001'}],
              'reference_paragraphs':['p0002'],'reference_excerpts':{'p0002':'风过门槛。'}}
    put(tmp_path,'zhuque-options.json',{'enabled':True,'reference_text':''})
    monkeypatch.setenv('XS2_ZHUQUE_KEY_FILE',str(tmp_path/'key'))
    monkeypatch.setattr(m.zhuque,'analyze',Mock(return_value=report))
    out = m.prepare(tmp_path,'0001','required',scoped_review=True,whole_chapter_review=True,blind_scenes=True)
    folder = out['revision_dir']
    put(tmp_path,'critique.json',{'issues':[]})
    m.writer_input(tmp_path,folder,'critique.json')
    assert m.read(tmp_path/out['revision_editor_model'])['zhuque_review']['rewrite_units'] == [unit]
    row = {'id':unit['id'],'reference_id':'p0002','replacement':'灯火熄了。'}
    payload = {'source_sha256':m.sha(body.encode()),'edits':[]}
    for rows in ([], [row,row], [{**row,'reference_id':'p0001'}],
                 [{**row,'replacement':'灯灭了！'}], [{**row,'replacement':''}]):
        with pytest.raises(ValueError):
            m.zhuque.compile_rewrites(report,{**payload,'rewrites':rows})
    put(tmp_path,out['revision_patch_path'],{**payload,'rewrites':[row]})
    m.candidate(tmp_path,folder)
    ballot = m.read(tmp_path/out['revision_blind_packet'])
    assert ballot['reading_task'] == 'meaning_preservation'
    scene, = ballot['scenes']
    vote = {'ballot':ballot['ballot'],'scenes':[{'id':scene['id'],'prefer':'A' if body in scene['A'] else 'B',
            'exceptions':[],'voice_quote':'她等着。','redundant_quote':'','reason':'核对灯火。'}]}
    put(tmp_path,out['revision_blind_path'],vote)
    with pytest.raises(m.Retry,match='p0001-s1'):
        m.accept_blind(tmp_path,folder,json.dumps(vote))
    vote['scenes'][0].update(prefer='tie',reason='两处均写熄灯后等候。')
    put(tmp_path,out['revision_blind_path'],vote)
    m.accept_blind(tmp_path,folder,json.dumps(vote))
    assert m.read(tmp_path/out['revision_review_input'])['candidate'] == body.replace(unit['old'],row['replacement'])


def test_fully_human_automatic_review_has_an_empty_rewrite_scope(tmp_path, monkeypatch):
    m = module()
    put(tmp_path,'story/0001/chapter.md','门开了。')
    put(tmp_path,'zhuque-options.json',{'enabled':True,'reference_text':''})
    monkeypatch.setenv('XS2_ZHUQUE_KEY_FILE',str(tmp_path/'key'))
    monkeypatch.setattr(m.zhuque,'analyze',Mock(return_value={
        'status':'success','trial_version':2,'attention':[],'rewrite_units':[],
        'reference_paragraphs':['p0001'],'reference_excerpts':{}}))
    out = m.prepare(tmp_path,'0001','clear',scoped_review=True,whole_chapter_review=True,blind_scenes=True)
    report = m.read(tmp_path/out['revision_source_input'])['zhuque_review']
    assert report['required'] and m.zhuque.compile_rewrites(report,{'edits':[]}) == []
    with pytest.raises(ValueError):
        m.zhuque.compile_rewrites(report,{'edits':[{'paragraph_id':'p0001'}]})
