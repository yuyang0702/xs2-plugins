"""Deterministic boundary races for native lease-backed canonical writes."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
from threading import Event

import pytest
from test_native_preflight import native, armed_state
from test_book_contract import PLUGIN
from test_length_quality import policy
from test_local_revision import setup, patch, approved, BODY


def archive():
    path=PLUGIN/'resources/script-library/xs2/story_support/archive_store.py'
    spec=importlib.util.spec_from_file_location('fenced_archive_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_launch_parameter_error_then_fixed_retry_has_no_orphan_reservation(native):
    guard,root,*_=native;p=policy();state=armed_state();state['stageId']='build'
    definition={'workflow_id':'build','variables':[{'key':'premise','required':True}]}
    p.launch_check(root,state,'build')
    assert guard._active(root,'book/manuscript') is None
    with pytest.raises(ValueError,match='premise'):
        p.parameters(state,definition)
    assert guard._active(root,'book/manuscript') is None
    state['values']['premise']='修复后的完整设定'
    assert p.parameters(state,definition)['premise']=='修复后的完整设定'
    guard.verify_claim(root,state['productionLaunchLease']['lease'])


def test_missing_feedback_fails_before_reservation_then_retry_succeeds(native):
    guard,root,*_=native;p=policy();state=armed_state();state['stageId']='build'
    state['values']['author_feedback_file']='selected.md'
    definition={'workflow_id':'build','variables':[{'key':'author_feedback_file','type':'file'}]}
    p.launch_check(root,state,'build')
    with pytest.raises(ValueError,match='意见|反馈|feedback'):
        p.parameters(state,definition)
    assert guard._active(root,'book/manuscript') is None
    (root/'selected.md').write_bytes('完整作者意见。\r\n'.encode('utf8'))
    result=p.parameters(state,definition)
    assert (root/result['author_feedback_file']).read_bytes()==(root/'selected.md').read_bytes()
    (root/'selected.md').unlink()
    assert (root/result['author_feedback_file']).is_file()
    guard.verify_claim(root,state['productionLaunchLease']['lease'])


@pytest.mark.parametrize('change',['none','removed','content','selection','snapshot','origin','receipt'])
def test_pending_feedback_reuses_exact_frozen_parameter_and_revalidates_selection(native,change):
    guard,root,*_=native;p=policy();state=armed_state();state['stageId']='build'
    state['values']['author_feedback_file']='selected.md'
    definition={'workflow_id':'build','variables':[{'key':'author_feedback_file','type':'file'}]}
    original='完整作者意见。\r\n'.encode('utf8')
    (root/'selected.md').write_bytes(original)
    p.launch_check(root,state,'build');first=p.parameters(state,definition)
    lease=dict(state['productionLaunchLease']['lease'])
    state['autoPending']={'id':'pending-feedback','stage':'build','workflow_id':'build',
                          'parameters':dict(first),'before_task_ids':[]}
    project=root/'.novel-project.json';project.write_text(json.dumps(state),encoding='utf8')
    state=json.loads(project.read_text(encoding='utf8'))
    if change=='removed':(root/'selected.md').unlink()
    elif change=='content':(root/'selected.md').write_bytes('新的作者意见。'.encode('utf8'))
    elif change=='selection':
        (root/'other.md').write_bytes(original);state['values']['author_feedback_file']='other.md'
    elif change=='snapshot':(root/first['author_feedback_file']).write_bytes('被改动的快照。'.encode('utf8'))
    elif change=='origin':(root/'automatic-origin.json').write_text('{}',encoding='utf8')
    elif change=='receipt':
        path=(root/first['author_feedback_file']).parent/'selection.json'
        receipt=json.loads(path.read_text(encoding='utf8'));receipt['feedback_sha256']='0'*64
        path.write_text(json.dumps(receipt),encoding='utf8')
    p.launch_check(root,state,'build')
    if change in ('none','removed'):
        assert p.parameters(state,definition)==first
        assert state['productionLaunchLease']['lease']==lease
    else:
        with pytest.raises(ValueError,match='意见|参数|反馈|feedback'):
            p.parameters(state,definition)
    assert state['autoPending']['parameters']==first
    guard.verify_claim(root,lease)


@pytest.mark.parametrize('changed',[False,True])
def test_missing_token_handoff_requires_durable_ref_and_exact_reservation_inputs(native,changed):
    guard,root,task,*_=native;state=armed_state()
    state['productionLaunchContext']={'effective_parameters':task['parameter_values'],'workflow_id':'wf'}
    guard.reserve_launch(root,state,'polish')
    state.pop('productionLaunchLease')
    state['autoPending']={'id':'durable-intent','stage':'polish','workflow_id':'wf',
                          'task_id':'task-a','parameters':task['parameter_values'],'before_task_ids':[]}
    state['refs']={'polish':{'workflow_id':'wf','task_id':'task-a'}}
    if changed:state['values']['chapter_number']='0002'
    (root/'.novel-project.json').write_text(json.dumps(state),encoding='utf8')
    if changed:
        with pytest.raises(ValueError,match='LEASE'):guard.run(root,'polish','0001','task-a','wf')
    else:
        record=guard.run(root,'polish','0001','task-a','wf')
        assert record['lease']['owner']=='wf/task-a'


def prepared_local(native):
    guard,root,*_=native
    module,out=setup(root);patch(module,out,root);module.candidate(root,out['revision_dir'])
    expected=approved(module,out,root)
    record=guard.run(root,'polish','0001','task-a','wf')
    return guard,root,module,out,expected,record


def test_local_commit_rechecks_owner_after_unlocked_review_work(native,monkeypatch):
    guard,root,module,out,expected,record=prepared_local(native)
    compose=module.compose
    def replace_owner(*args,**kwargs):
        context=compose(*args,**kwargs)
        guard.release(root,record['lease'])
        guard.claim(root,'book/manuscript','wf/task-new',{'new':'owner'})
        return context
    monkeypatch.setattr(module,'compose',replace_owner)
    with pytest.raises(ValueError,match='LEASE'):
        module.commit(root,out['revision_dir'],expected)
    assert (root/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_local_canonical_replace_holds_same_sqlite_owner_lock(native,monkeypatch):
    guard,root,module,out,expected,record=prepared_local(native)
    entered=Event();changed=Event();executor=ThreadPoolExecutor(max_workers=1);future=None
    replace=module.os.replace
    def take():
        entered.set();guard.release(root,record['lease'])
        lease=guard.claim(root,'book/manuscript','wf/task-new',{'new':'owner'})
        changed.set();return lease
    def intercepted(src,dst):
        nonlocal future
        if Path(dst)==root/'story/0001/chapter.md':
            future=executor.submit(take)
            assert entered.wait(2)
            assert not changed.wait(.15), 'owner changed inside canonical replacement'
        return replace(src,dst)
    monkeypatch.setattr(module.os,'replace',intercepted)
    try:
        module.commit(root,out['revision_dir'],expected)
        assert future.result(timeout=5)['owner']=='wf/task-new'
    finally:executor.shutdown(wait=True)


@pytest.mark.parametrize('views',[False,True])
def test_archive_replay_rejects_old_epoch_after_durable_prepare(native,monkeypatch,views):
    guard,root,*_=native;journal=archive()
    record=guard.run(root,'polish','0001','task-a','wf')
    recover=journal.recover;calls=0
    def before_replay(root):
        nonlocal calls
        calls+=1
        # publish_views calls recover once before preparing its own intent.
        if not views or calls==2:
            guard.release(root,record['lease'])
            guard.claim(root,'book/manuscript','wf/new-task',{'new':'owner'})
        return recover(root)
    monkeypatch.setattr(journal,'recover',before_replay)
    with pytest.raises(ValueError,match='LEASE'):
        if views:
            journal.publish_views(root,lambda write:write(root,'archive/view.md','reviewed output'),lambda:{})
        else:
            journal.publish(root,{'archive_commit_id':'commit-a','chapter':'0001'},
                            {'archive/output.md':'reviewed output'},{},{'source':{}},0)
    target=root/('archive/view.md' if views else 'archive/output.md')
    assert not target.exists()
    assert journal.publications(root)[0]['status']=='pending'
    with journal.connect(root) as db:
        stored=json.loads(db.execute('SELECT content FROM publications').fetchone()[0])
    assert stored['execution_fence']['lease']==record['lease']
    with pytest.raises(ValueError,match='LEASE'):recover(root)
    assert not target.exists()
