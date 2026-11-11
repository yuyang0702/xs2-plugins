import json
import pytest
from test_book_contract import put
from test_local_revision import setup,patch,approved,BODY


def test_independent_equivalent_edit_is_removed_then_freshly_reviewed(tmp_path,monkeypatch):
    m,out=setup(tmp_path);payload=patch(m,out,tmp_path)
    refreshed=[];monkeypatch.setattr(m,'refresh_retry_budget',lambda root,target:refreshed.append(target))
    payload['edits'][0]['independent']=True
    put(tmp_path,out['revision_patch_path'],payload);m.candidate(tmp_path,out['revision_dir'])
    raw=json.loads(approved(m,out,tmp_path));raw['change_reviews'][0]['effect']='equivalent'
    put(tmp_path,out['revision_review_path'],raw)
    with pytest.raises(m.Retry,match='等价') as exc:m.commit(tmp_path,out['revision_dir'],json.dumps(raw,ensure_ascii=False))
    assert exc.value.target=='agent_local_review'
    assert refreshed==['agent_local_review']
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert context['candidate']==BODY and context['edits']==[]
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    fresh=json.loads(approved(m,out,tmp_path));fresh['change_reviews']=[]
    put(tmp_path,out['revision_review_path'],fresh)
    receipt=m.commit(tmp_path,out['revision_dir'],json.dumps(fresh,ensure_ascii=False))
    assert receipt['changed_spans']==0 and receipt['accepted']


def test_atomic_move_cannot_be_partially_pruned(tmp_path):
    m,out=setup(tmp_path)
    edits=[{'paragraph_id':'p0002','old':'第二段重复说明。','occurrence':1,'replacement':'','group_id':'move'},
           {'paragraph_id':'p0003','old':'潮水会回来。','occurrence':1,'replacement':'第二段重复说明。潮水会回来。','group_id':'move'}]
    put(tmp_path,out['revision_patch_path'],{'source_sha256':m.sha(BODY.encode()),'edits':edits})
    m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['change_reviews'][0]['effect']='equivalent'
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as exc:m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert exc.value.target=='agent_pl'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert not (tmp_path/out['revision_dir']/'working.json').exists()


def test_retained_atomic_move_requires_complete_update(tmp_path):
    m,out=setup(tmp_path)
    edits=[{'paragraph_id':'p0002','old':'第二段重复说明。','occurrence':1,'replacement':'','group_id':'move'},
           {'paragraph_id':'p0003','old':'潮水会回来。','occurrence':1,'replacement':'第二段重复说明。潮水会回来。','group_id':'move'}]
    with pytest.raises(ValueError,match='完整更新'):
        m.pending.merge(BODY,edits,[{**edits[1],'replacement':'新说明。潮水会回来。'}],m.patches)


def test_commit_compose_failure_enters_same_logical_retry_boundary(tmp_path,monkeypatch):
    m,out=setup(tmp_path);payload=patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    report=approved(m,out,tmp_path)
    payload['edits'][0]['old']='原文不存在的假句。';put(tmp_path,out['revision_patch_path'],payload)
    seen=[];monkeypatch.setattr(m.guard,'retry',lambda *args:seen.append(args))
    with pytest.raises(m.Retry) as exc:m.commit(tmp_path,out['revision_dir'],report)
    assert exc.value.target=='agent_pl' and len(seen)==1 and seen[0][1]=='local-revision/local-test'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
