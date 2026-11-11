import importlib.util
import json
from pathlib import Path

import pytest
from test_story_support import support, commit_chapter


def memory():
    spec = importlib.util.spec_from_file_location('test_memory_p1', support.HERE / 'memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_distant_middle_passage_retrieved_with_exact_provenance(tmp_path):
    body = ('无关的风声。\n\n' * 800) + '青铜匣的机关必须反转三次，随后等待回声。' + ('\n\n无关的雨声。' * 800)
    commit_chapter(tmp_path, '0001', body + '\n\n决定留下救人。')
    support.write(tmp_path, 'outline/near_term_outline.md', '### 第201章\n再次打开青铜匣的机关。')
    result = memory().retrieve(tmp_path, '0201', '青铜匣的机关')
    hit = next(h for h in result['hits'] if '必须反转三次' in h['text'])
    assert hit['source_id'] == 'story/0001/chapter.md'
    text = support.read(tmp_path, hit['source_id'])
    assert text[hit['start']:hit['end']] == hit['text']
    assert hit['source_sha256'] == support.digest(tmp_path, hit['source_id'])
    context = support.context(tmp_path, '0201')
    assert '必须反转三次' in json.dumps(context['memory'], ensure_ascii=False)


def registry(root):
    support.write(root, 'meta/entity_registry.json', {'entities':[
        {'id':'c-lin', 'name':'林照', 'aliases':['阿七','灰衣客']},
        {'id':'c-su', 'name':'苏晚', 'aliases':['掌柜']}]})


def test_alias_retrieval_does_not_make_identity_common_knowledge(tmp_path):
    registry(tmp_path)
    commit_chapter(tmp_path, content='林照将钥匙藏在井沿第三块石砖下。决定留下救人。')
    data = memory().retrieve(tmp_path, '0200', '灰衣客寻找钥匙')
    assert any('第三块石砖' in h['text'] for h in data['hits'])
    assert data['entities'][0]['id'] == 'c-lin'
    assert data['entities'][0]['alias_boundary'] == 'author_only'
    assert data['cognition']['c-lin']['knowledge'] == []


def test_ambiguous_aliases_are_reported_never_silently_merged(tmp_path):
    support.write(tmp_path, 'meta/entity_registry.json', {'entities':[
        {'id':'one','name':'柳甲','aliases':['先生']}, {'id':'two','name':'柳乙','aliases':['先生']}]})
    result = memory().retrieve(tmp_path, '0001', '先生来到门口')
    assert result['ambiguities']['先生'] == ['one','two']


def test_knowledge_belief_fact_and_future_are_separate(tmp_path):
    registry(tmp_path)
    body = '密门实际朝北。林照听苏晚说密门朝南，暂且相信了她。决定留下救人。'
    support.write(tmp_path, 'story/0001/chapter.md', body)
    support.begin_review(tmp_path, '0001')
    support.write(tmp_path, support.review_file('0001','observer.json'), {'confirmed_state':{'characters':[]}})
    support.write(tmp_path, support.review_file('0001','arbiter.json'), {'story_confirmed':{}, 'memory_events':[
        {'id':'f1','kind':'fact','text':'密门实际朝北','evidence':'密门实际朝北。'},
        {'id':'b1','kind':'belief','holder':'c-lin','text':'密门朝南','acquisition':'苏晚的说法','evidence':'林照听苏晚说密门朝南，暂且相信了她。'}]})
    support.commit(tmp_path,'0001')
    current = memory().retrieve(tmp_path,'0002','林照寻找密门')
    assert current['cognition']['c-lin']['knowledge'] == []
    assert current['cognition']['c-lin']['beliefs'][0]['id'] == 'b1'
    assert not memory().retrieve(tmp_path,'0001','密门')['hits']


def test_invalid_event_evidence_rejected_before_any_archive(tmp_path):
    support.write(tmp_path,'story/0001/chapter.md','她留在原地。')
    support.begin_review(tmp_path,'0001')
    support.write(tmp_path,support.review_file('0001','observer.json'),{'confirmed_state':{'characters':[]}})
    support.write(tmp_path,support.review_file('0001','arbiter.json'),{'story_confirmed':{},'memory_events':[
        {'id':'invented','kind':'knowledge','holder':'nobody','text':'密码','evidence':'她知道了密码。'}]})
    with pytest.raises(ValueError):support.commit(tmp_path,'0001')
    assert not (tmp_path/'story/0001/confirmed_state.json').exists()


def test_old_edit_removes_stale_hits_and_reports_affected_plan(tmp_path):
    commit_chapter(tmp_path,'0001','青铜匣必须反转三次。决定留下救人。')
    commit_chapter(tmp_path,'0002')
    support.write(tmp_path,'planning/chapters/0003.json',{'source_hashes':{'story/0001/chapter.md':support.digest(tmp_path,'story/0001/chapter.md')}})
    assert memory().retrieve(tmp_path,'0003','青铜匣')['hits']
    support.write(tmp_path,'story/0001/chapter.md','青铜匣已毁。决定留下救人。')
    result = memory().retrieve(tmp_path,'0003','青铜匣')
    assert not any('反转三次' in h['text'] for h in result['hits'])
    impact = memory().impact(tmp_path)
    assert {'0001','0002'} <= {i['chapter'] for i in impact['chapters']}
    assert '0003' in [p['chapter'] for p in impact['plans']]
    assert impact['automatic_prose_edits'] is False
    assert 'impact' in support.preflight(tmp_path,'0003')


def test_alias_observation_updates_same_character_without_losing_state(tmp_path):
    registry(tmp_path)
    for chapter,name,field in [('0001','林照',{'location':'旧井'}),('0002','阿七',{'goal':'取钥匙'})]:
        support.write(tmp_path,f'story/{chapter}/chapter.md',f'{name}来到井边。')
        support.begin_review(tmp_path,chapter)
        support.write(tmp_path,support.review_file(chapter,'observer.json'),{'confirmed_state':{'characters':[
            {'name':name,'snapshot':field,'evidence':f'{name}来到井边。'}]}})
        support.write(tmp_path,support.review_file(chapter,'arbiter.json'),{'story_confirmed':{}})
        snapshot=support.commit(tmp_path,chapter)
    assert len(snapshot['characters']) == 1
    assert snapshot['characters'][0]['entity_id'] == 'c-lin'
    assert snapshot['characters'][0]['snapshot'] == {'location':'旧井','goal':'取钥匙'}


def test_indirect_dependency_propagates_even_if_parent_file_bytes_unchanged(tmp_path):
    commit_chapter(tmp_path)
    # Simulate an older/minimal archive that records just its actual parent.
    body='第二章。'
    support.write(tmp_path,'story/0002/chapter.md',body)
    parent='story/0001/confirmed_state.json'
    support.write(tmp_path,'story/0002/confirmed_state.json',{'chapter':'0002','version':1,
        'body_sha256':support.digest(tmp_path,'story/0002/chapter.md'),
        'source_hashes':{parent:support.digest(tmp_path,parent)},'characters':[]})
    support.write(tmp_path,'planning/chapters/0003.json',{'source_hashes':{
        'story/0002/confirmed_state.json':support.digest(tmp_path,'story/0002/confirmed_state.json')}})
    support.write(tmp_path,'story/0001/chapter.md','作者改了第一章。')
    valid,stale=support.confirmed(tmp_path)
    assert valid == [] and '0002' in stale
    assert '0003' in [p['chapter'] for p in memory().impact(tmp_path)['plans']]


def test_retrieval_dependencies_frozen_before_review(tmp_path):
    commit_chapter(tmp_path,'0001','井沿第三块石砖藏着钥匙。决定留下救人。')
    support.write(tmp_path,'outline/near_term_outline.md','### 第2章\n取回井沿第三块石砖中的钥匙。')
    support.prepare_context(tmp_path,'0002')
    support.write(tmp_path,'story/0002/chapter.md','她仍决定留下救人。')
    support.begin_review(tmp_path,'0002')
    support.write(tmp_path,'story/0002/planning_context.json',{'memory_dependencies':[]})
    support.write(tmp_path,support.review_file('0002','observer.json'),{'confirmed_state':{'characters':[]}})
    support.write(tmp_path,support.review_file('0002','arbiter.json'),{'story_confirmed':{}})
    state=support.commit(tmp_path,'0002')
    assert any(r['source_id']=='story/0001/chapter.md' for r in state['memory_dependencies'])


def test_knowledge_can_explicitly_replace_a_false_belief(tmp_path):
    registry(tmp_path)
    old={'chapter':'0001','memory_events':[{'id':'b','kind':'belief','holder':'c-lin','text':'门朝南'}]}
    result=memory().validate_events(tmp_path,'0002',[{'id':'k','kind':'knowledge','holder':'c-lin',
        'acquisition':'走到门口核实','text':'门朝北','supersedes':'b','evidence':'林照走到北门。'}],
        [old],memory().entities(tmp_path),'林照走到北门。')
    assert result[0]['supersedes']=='b'


def test_existing_id_cannot_launder_an_unconfirmed_disguise(tmp_path):
    registry(tmp_path)
    with pytest.raises(ValueError,match='身份|别名'):
        memory().canonicalize(tmp_path,[],[{'entity_id':'c-lin','name':'陌生蒙面人'}],[],'陌生蒙面人开锁。')


def event_chapter(root, chapter, events):
    body='林照发现密门朝北，纠正了原先朝南的想法。'
    support.write(root,f'story/{chapter}/chapter.md',body)
    support.begin_review(root,chapter)
    support.write(root,support.review_file(chapter,'observer.json'),{'confirmed_state':{'characters':[]}})
    support.write(root,support.review_file(chapter,'arbiter.json'),{'story_confirmed':{},'memory_events':events})
    return support.commit(root,chapter)


def test_recalled_superseded_fact_includes_correction_chain(tmp_path):
    registry(tmp_path)
    event_chapter(tmp_path,'0001',[{'id':'old','kind':'fact','text':'密门朝南','evidence':'原先朝南的想法。'}])
    event_chapter(tmp_path,'0002',[{'id':'new','kind':'fact','text':'入口朝北','evidence':'林照发现密门朝北，','supersedes':'old'}])
    data=memory().retrieve(tmp_path,'0003','密门朝南')
    hit=next(h for h in data['hits'] if h.get('event',{}).get('id')=='old')
    assert hit['event_status']=='superseded'
    assert hit['replacements'][0]['event']['id']=='new'
    old=memory().retrieve(tmp_path,'0002','密门朝南')
    assert next(h for h in old['hits'] if h.get('event',{}).get('id')=='old')['event_status']=='active'


def test_cognition_is_in_read_set_even_when_event_does_not_match_query(tmp_path):
    registry(tmp_path)
    event_chapter(tmp_path,'0001',[{'id':'secret','kind':'knowledge','holder':'c-lin','text':'AlphaBetaGamma',
        'acquisition':'亲眼看到','evidence':'林照发现密门朝北，'}])
    data=memory().retrieve(tmp_path,'0002','林照')
    assert data['cognition']['c-lin']['knowledge']
    assert any(r['source_id']=='story/0001/confirmed_state.json' for r in data['read_set'])


def test_explicit_flashback_time_does_not_inherit_later_knowledge(tmp_path):
    registry(tmp_path)
    event_chapter(tmp_path,'0001',[{'id':'later','kind':'knowledge','holder':'c-lin','text':'密门朝北',
        'acquisition':'亲眼看到','world_time_key':20,'evidence':'林照发现密门朝北，'}])
    support.write(tmp_path,'story/0002/planned_world_state.json',{'world_time_key':10})
    data=memory().retrieve(tmp_path,'0002','林照回到旧日')
    assert not data['cognition']['c-lin']['knowledge']
    assert data['scene_time_key']==10


def test_fallback_search_and_incremental_reuse(tmp_path,monkeypatch):
    module=memory()
    commit_chapter(tmp_path,content='青铜匣的机关。决定留下救人。')
    real_connect=module.connect
    def fallback(root):
        db,_=real_connect(root)
        return db,False
    monkeypatch.setattr(module,'connect',fallback)
    first=module.retrieve(tmp_path,'0002','青铜匣')
    second=module.retrieve(tmp_path,'0002','青铜匣')
    assert first['hits'] and second['index']['updated_documents']==0


def test_windows_reference_normalization_and_fts_rebuild(tmp_path):
    module=memory()
    support.write(tmp_path,'meta/world_foundation.md','青铜钥匙藏在井底。')
    assert module.retrieve(tmp_path,'0001','青铜钥匙')['hits']
    db,fts=module.connect(tmp_path)
    if fts:
        db.execute('DROP TABLE search');db.commit()
    db.close()
    assert module.retrieve(tmp_path,'0001','青铜钥匙')['hits']


def test_corrupt_disposable_index_does_not_destroy_or_block_book(tmp_path):
    support.write(tmp_path,'meta/world_foundation.md','青铜钥匙藏在井底。')
    file=tmp_path/'archive/memory-index.sqlite3';file.parent.mkdir(exist_ok=True)
    file.write_bytes(b'corrupt disposable cache')
    before=support.digest(tmp_path,'meta/world_foundation.md')
    assert memory().retrieve(tmp_path,'0001','青铜钥匙')['hits']
    assert support.digest(tmp_path,'meta/world_foundation.md')==before
    assert list(file.parent.glob('memory-index.corrupt-*'))


def test_changed_snapshot_during_retrieval_cannot_borrow_new_file_hash(tmp_path):
    commit_chapter(tmp_path)
    old=support.confirmed(tmp_path)[0]
    altered=dict(old[0]);altered['world']={'facts':[{'description':'伪造事实','source_chapter':'0001'}]}
    support.write(tmp_path,'story/0001/confirmed_state.json',altered)
    with pytest.raises(ValueError,match='变化|一致'):
        memory().retrieve(tmp_path,'0002','伪造事实',states=old)


def test_confirmed_alias_survives_without_observer_character_change(tmp_path):
    registry(tmp_path)
    support.write(tmp_path,'story/0001/chapter.md','夜客就是林照。')
    support.begin_review(tmp_path,'0001')
    support.write(tmp_path,support.review_file('0001','observer.json'),{'confirmed_state':{'characters':[]}})
    support.write(tmp_path,support.review_file('0001','arbiter.json'),{'story_confirmed':{},'identity_rulings':[
        {'entity_id':'c-lin','aliases':['夜客'],'verdict':'adopt','evidence':'夜客就是林照。'}]})
    support.commit(tmp_path,'0001')
    assert memory().retrieve(tmp_path,'0002','夜客')['entities'][0]['id']=='c-lin'


def test_flashback_context_does_not_label_future_snapshot_as_current(tmp_path):
    registry(tmp_path)
    support.write(tmp_path,'story/0001/chapter.md','林照知道密码青铜。')
    support.begin_review(tmp_path,'0001')
    support.write(tmp_path,support.review_file('0001','observer.json'),{'confirmed_state':{'characters':[
        {'name':'林照','snapshot':{'knowledge':'密码青铜'},'evidence':'林照知道密码青铜。'}]}})
    support.write(tmp_path,support.review_file('0001','arbiter.json'),{'story_confirmed':{},'memory_events':[
        {'id':'late','kind':'knowledge','holder':'c-lin','acquisition':'亲见','world_time_key':20,'text':'密码青铜','evidence':'林照知道密码青铜。'}]})
    support.commit(tmp_path,'0001')
    support.write(tmp_path,'story/0002/planned_world_state.json',{'world_time_key':10})
    ctx=support.context(tmp_path,'0002','林照')
    assert '密码青铜' not in ctx['state_text']
    assert ctx['world_current']['temporal_status']=='unverified'


def test_scene_time_input_is_in_context_dependency_set(tmp_path):
    registry(tmp_path)
    support.write(tmp_path,'story/0001/planned_world_state.json',{'world_time_key':10})
    ctx=support.context(tmp_path,'0001','林照')
    support.write(tmp_path,'story/0001/planned_world_state.json',{'world_time_key':20})
    with pytest.raises(ValueError,match='变化|过期'):
        support.verify(tmp_path,ctx['source_hashes'])


def test_cognition_accepts_unambiguous_name_and_normalizes_id(tmp_path):
    registry(tmp_path)
    result=memory().validate_events(tmp_path,'0001',[{'id':'k','kind':'knowledge','holder':'林照',
        'acquisition':'亲见','text':'密码','evidence':'林照知道密码。'}],[],memory().entities(tmp_path),'林照知道密码。')
    assert result[0]['holder']=='c-lin'


def test_plan_hash_metadata_does_not_displace_story_retrieval_query(tmp_path):
    commit_chapter(tmp_path,content='青铜匣必须反转三次。决定留下救人。')
    support.write(tmp_path,'planning/chapters/0201.json',{'chapter':'0201',
        'source_hashes':{f'old-{i}':str(i)+'a'*60 for i in range(200)},'goal':'再次打开青铜匣'})
    ctx=support.context(tmp_path,'0201')
    assert any('反转三次' in h['text'] for h in ctx['memory']['hits'])
    assert 'old-199' not in ctx['memory']['query']


def test_routine_world_update_without_time_change_does_not_stale_plan(tmp_path):
    ctx=support.context(tmp_path,'0001')
    support.write(tmp_path,'story/0001/planned_world_state.json',{'world_time':'夜晚','forces':[]})
    support.verify(tmp_path,ctx['source_hashes'])


def test_world_postprocessor_preserves_explicit_scene_time(tmp_path):
    import os,subprocess,sys
    script=support.HERE.parents[1]/'nvl/we_post/we_post.py'
    support.write(tmp_path,'story/0001/planned_world_state.json',{'world_time_key':10})
    support.write(tmp_path,'we-input.json',{'world_time':'夜晚','world_time_key':10,'events':[]})
    result=subprocess.run([sys.executable,str(script),'--chapter','0001','--input','we-input.json'],cwd=tmp_path,
        capture_output=True,text=True,encoding='utf-8',env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    assert result.returncode==0,result.stderr
    assert support.load(tmp_path,'story/0001/planned_world_state.json')['world_time_key']==10


def test_confirmation_batches_ledger_reads_for_long_history(tmp_path,monkeypatch):
    commit_chapter(tmp_path)
    for i in range(2,12):
        chapter=f'{i:04d}';support.write(tmp_path,f'story/{chapter}/chapter.md','离线档案。')
        support.write(tmp_path,f'story/{chapter}/confirmed_state.json',{'chapter':chapter,
            'body_sha256':support.digest(tmp_path,f'story/{chapter}/chapter.md'),'source_hashes':{}})
    journal=support.archive_store();connect=journal.connect;calls=0
    def counted(root):
        nonlocal calls
        calls+=1;return connect(root)
    monkeypatch.setattr(journal,'connect',counted)
    assert len(support.confirmed(tmp_path)[0])==11
    assert calls<=2
