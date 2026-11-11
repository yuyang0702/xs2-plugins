import importlib.util
import json
from pathlib import Path

import pytest
from test_story_support import support, commit_chapter
from test_length_quality import policy


def store():
    spec = importlib.util.spec_from_file_location('archive_p0_test', support.HERE / 'archive_store.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_duplicate_archive_has_same_receipt_and_timestamp(tmp_path):
    first = commit_chapter(tmp_path)
    second = support.commit(tmp_path, '0001')
    assert first == second
    assert first['archive_commit_id']
    assert len(store().publications(tmp_path)) == 1


def test_interrupted_archive_is_not_consumed_and_replays_after_restart(tmp_path, monkeypatch):
    journal = support.archive_store()
    original = journal.atomic
    count = 0
    def crash(root, relative, content):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError('simulated power loss')
        original(root, relative, content)
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', crash)
        with pytest.raises(OSError, match='power loss'):
            commit_chapter(tmp_path)
    assert support.confirmed(tmp_path)[0] == []
    restarted = store()
    restarted.recover(tmp_path)
    states, stale = support.confirmed(tmp_path)
    assert len(states) == 1 and stale == []
    assert support.load(tmp_path, 'archive/current_status.json')['updated_chapter'] == '0001'
    assert restarted.publications(tmp_path)[0]['status'] == 'complete'
    assert len(restarted.events(tmp_path)) >= 2


@pytest.mark.parametrize('changed', ['story/0001/chapter.md', 'meta/world_foundation.md', 'meta/narrative_contract.json', 'archive/hooks.json'])
def test_pending_recovery_refuses_source_or_destination_drift(tmp_path, monkeypatch, changed):
    journal = support.archive_store()
    original = journal.atomic
    def crash(root, relative, content):
        original(root, relative, content)
        raise OSError('interrupted')
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', crash)
        with pytest.raises(OSError):
            commit_chapter(tmp_path)
    value = '{"style_intent":"新风格"}' if changed.endswith('contract.json') else '作者另有修改'
    support.write(tmp_path, changed, value)
    before = (tmp_path / changed).read_bytes()
    with pytest.raises(ValueError, match='变化|冲突'):
        store().recover(tmp_path)
    assert (tmp_path / changed).read_bytes() == before


def test_snapshot_tampering_is_stale(tmp_path):
    state = commit_chapter(tmp_path)
    state['world']['facts'] = [{'description':'凭空增加的事实'}]
    support.write(tmp_path, 'story/0001/confirmed_state.json', state)
    assert support.confirmed(tmp_path)[0] == []
    assert support.preflight(tmp_path, '0002')['ready'] is False


def test_contract_change_invalidates_new_archive(tmp_path):
    commit_chapter(tmp_path)
    support.write(tmp_path, 'meta/narrative_contract.json', {'narrator_scope':'unreliable'})
    assert support.confirmed(tmp_path)[0] == []


def test_next_chapter_local_intent_does_not_invalidate_completed_history(tmp_path):
    support.write(tmp_path, '.novel-project.json', {'values':{'human_intent':'本章犹豫','world_intent':'本章下雨'}})
    commit_chapter(tmp_path)
    support.write(tmp_path, '.novel-project.json', {'values':{'human_intent':'','world_intent':''}})
    assert len(support.confirmed(tmp_path)[0]) == 1


def test_managed_snapshot_cannot_remove_receipt_to_become_legacy(tmp_path):
    state = commit_chapter(tmp_path)
    state.pop('archive_commit_id')
    support.write(tmp_path, 'story/0001/confirmed_state.json', state)
    assert support.confirmed(tmp_path)[0] == []


@pytest.mark.parametrize('relative', ['planned_world_state.json', 'planned_hooks.json', 'planned_debts.json'])
def test_planning_inputs_changed_after_review_cannot_enter_archive(tmp_path, relative):
    commit_chapter(tmp_path)
    support.begin_review(tmp_path, '0001')
    support.write(tmp_path, f'story/0001/{relative}', {})
    with pytest.raises(ValueError, match='变化|过期'):
        support.commit(tmp_path, '0001')


def test_run_ledger_records_launch_dispatch_completion_idempotently(tmp_path):
    p = policy()
    state = {'values':{'chapter_number':'0001'}}
    p.launch_check(tmp_path, state, 'build')
    task = {'task_id':'task-1', 'status':'completed'}
    support.write(tmp_path, 'meta/world_foundation.md', '梦中规则由本书自行决定。')
    p.validate_dispatch(tmp_path, state, 'build', task)
    p.verify_completion(tmp_path, state, 'build', task)
    p.verify_completion(tmp_path, state, 'build', task)
    events = store().events(tmp_path)
    assert [e['kind'] for e in events].count('stage_complete') == 1
    assert {'stage_launch', 'stage_dispatch', 'stage_complete'} <= {e['kind'] for e in events}


def test_changed_parent_archive_invalidates_descendants_even_with_same_body(tmp_path):
    first = commit_chapter(tmp_path)
    commit_chapter(tmp_path, '0002')
    arb = support.load(tmp_path, 'cache/arbiter/arb_output.json')
    support.begin_review(tmp_path, '0001')
    arb['story_confirmed'] = {'note':'同一正文的审核结论有修正'}
    support.write(tmp_path, 'cache/arbiter/arb_output.json', arb)
    support.commit(tmp_path, '0001')
    states, stale = support.confirmed(tmp_path)
    assert [s['chapter'] for s in states] == ['0001']
    assert '0002' in stale


def test_stale_precomputed_publication_cannot_overtake_another_commit(tmp_path):
    journal = store()
    version = journal.revision(tmp_path)
    commit_chapter(tmp_path)
    state = {'chapter':'0002','archive_commit_id':'another'}
    with pytest.raises(ValueError, match='版本已有变化'):
        journal.publish(tmp_path, state, {}, {}, {}, version)


def test_explicit_abandon_retains_diagnostics_and_allows_fresh_review(tmp_path, monkeypatch):
    journal = support.archive_store()
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', lambda *args: (_ for _ in ()).throw(OSError('crash')))
        with pytest.raises(OSError):
            commit_chapter(tmp_path)
    support.write(tmp_path, 'story/0001/chapter.md', '作者改稿，决定留下救人。')
    journal.abandon(tmp_path, '0001')
    support.begin_review(tmp_path, '0001')
    support.commit(tmp_path, '0001')
    assert [p['status'] for p in journal.publications(tmp_path)] == ['abandoned', 'complete']


def test_forged_historical_indexes_cannot_be_laundered(tmp_path):
    snapshot = commit_chapter(tmp_path)
    snapshot['indexes_before'] = {'hooks':[{'id':'forged', 'description':'无依据'}]}
    support.write(tmp_path, 'story/0001/confirmed_state.json', snapshot)
    with pytest.raises(ValueError, match='凭据'):
        support.begin_review(tmp_path, '0001')


def test_posthoc_completion_must_belong_to_this_task(tmp_path):
    commit_chapter(tmp_path)
    support.write(tmp_path, 'story/0001/diff_story_confirmed.md', '新的任务写出的报告')
    with pytest.raises(ValueError, match='任务|凭据'):
        policy().verify_completion(tmp_path, {'values':{'chapter_number':'0001'}}, 'post-hoc', {'task_id':'different-task', 'status':'completed'})


def test_abandon_after_snapshot_replace_allows_fresh_review(tmp_path, monkeypatch):
    journal = support.archive_store()
    atomic = journal.atomic
    def crash(root, relative, content):
        atomic(root, relative, content)
        if relative == 'story/0001/confirmed_state.json':
            raise OSError('after snapshot replace')
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', crash)
        with pytest.raises(OSError):
            commit_chapter(tmp_path)
    support.write(tmp_path, 'story/0001/chapter.md', '作者改稿，决定留下救人。')
    journal.abandon(tmp_path, '0001')
    support.begin_review(tmp_path, '0001')
    support.commit(tmp_path, '0001')
    assert len(support.confirmed(tmp_path)[0]) == 1


def test_completed_archive_survives_disposable_review_cache_cleanup(tmp_path):
    commit_chapter(tmp_path)
    (tmp_path / 'cache/story-support/0001/indexes-before.json').unlink()
    assert len(support.confirmed(tmp_path)[0]) == 1


def test_task_review_cannot_consume_shared_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv('TASK_ID', 'isolated-review')
    support.write(tmp_path, 'story/0001/chapter.md', '她决定留下救人。')
    support.begin_review(tmp_path, '0001')
    support.write(tmp_path, 'cache/observer/obs_output.json', {'confirmed_state':{'characters':[]}})
    support.write(tmp_path, 'cache/arbiter/arb_output.json', {'story_confirmed':{}})
    with pytest.raises(ValueError, match='不完整'):
        support.commit(tmp_path, '0001')


def test_workflow_scoped_paths_resolve_as_paths_before_and_after_output(tmp_path):
    import asyncio
    from src.workflow.variable_resolution import resolve_placeholders
    definition = json.loads((support.HERE.parents[2] / 'workflows/post-hoc/definition.json').read_text(encoding='utf-8'))
    nodes = {n['id']: n for n in definition['nodes']}
    observer = 'cache/story-support/reviews/task/0001/observer.json'
    arbiter = 'cache/story-support/reviews/task/0001/arbiter.json'
    values = {'chapter_number':'0001', 'obs_output_file':observer,
              'archive_observer_path':observer, 'archive_arbiter_path':arbiter,
              'archive_arbiter_file':arbiter}
    def resolve(text):
        return asyncio.run(resolve_placeholders(text, values, definition['variables'], str(tmp_path)))
    assert resolve(nodes['agent_obs']['output_file_path']) == observer
    assert resolve(nodes['agent_arb']['output_file_path']) == arbiter
    support.write(tmp_path, observer, {'confirmed_state':{}})
    args = resolve(nodes['script_sync_up']['node_params']['script_args'])
    assert '--observer ' + observer in args and '--arbiter ' + arbiter in args
    assert 'confirmed_state' in resolve('{{obs_output_file}}')


def test_abandon_interrupted_views_by_id(tmp_path, monkeypatch):
    commit_chapter(tmp_path)
    support.write(tmp_path, 'archive/hooks.json', [])
    journal = support.archive_store()
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', lambda *args: (_ for _ in ()).throw(OSError('views crash')))
        with pytest.raises(OSError):
            support.refresh_archive(tmp_path)
    support.write(tmp_path, 'meta/world_foundation.md', '作者更新规则')
    pending = next(p for p in journal.publications(tmp_path) if p['status'] == 'pending')
    assert pending['chapter'] == ''
    journal.abandon(tmp_path, commit_id=pending['id'])
    support.begin_review(tmp_path, '0001')
    assert not any(p['status'] == 'pending' for p in journal.publications(tmp_path))


@pytest.mark.parametrize('review_only', [False, True])
def test_automatic_posthoc_tail_recovery_uses_receipt_without_model_rerun(tmp_path, monkeypatch, review_only):
    monkeypatch.setenv('TASK_ID', 'interrupted-task')
    journal = support.archive_store()
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', lambda *args: (_ for _ in ()).throw(OSError('power loss')))
        with pytest.raises(OSError):
            commit_chapter(tmp_path)
    support.write(tmp_path, 'story/0001/diff_story_confirmed.md', '真实归档阶段报告')
    nodes = {key:{'status':'completed'} for key in (
        'script_story_context','script_sync_down','script_review_source','agent_obs',
        'script_validate_observation','agent_arb','script_sync_up','script_sync_down_final')}
    nodes['script_confirm_archive'] = {'status':'failed','error':'power loss'}
    task = {'task_id':'interrupted-task','status':'failed','node_states':nodes}
    result = policy().recovery_action({'values':{'chapter_number':'0001'}, 'repairReviewOnly':review_only}, 'post-hoc', task, root=tmp_path)
    if review_only:
        assert result['action'] == 'finish' and result['updates']['repairReviewOnly'] is False
    else:
        assert result['action'] == 'advance' and result['stage'] == 'export'
    assert 'post-hoc' in result['updates']['completed']
    assert len(support.confirmed(tmp_path)[0]) == 1


@pytest.mark.parametrize('boundary', range(1, 10))
def test_every_file_replacement_boundary_is_recoverable(tmp_path, monkeypatch, boundary):
    journal = support.archive_store()
    atomic = journal.atomic
    count = 0
    def crash(root, relative, content):
        nonlocal count
        atomic(root, relative, content)
        count += 1
        if count == boundary:
            raise OSError('boundary interruption')
    with monkeypatch.context() as patch:
        patch.setattr(journal, 'atomic', crash)
        with pytest.raises(OSError):
            commit_chapter(tmp_path)
    store().recover(tmp_path)
    assert len(support.confirmed(tmp_path)[0]) == 1
    assert support.load(tmp_path, 'archive/current_status.json')['updated_chapter'] == '0001'
