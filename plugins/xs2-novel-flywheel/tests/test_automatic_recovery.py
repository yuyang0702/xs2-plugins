import copy
import pytest

from test_length_quality import policy


def test_recovery_relaunches_only_known_operational_failures_with_durable_bound():
    p = policy()
    state={'values':{'chapter_number':'0001'},'writerModel':'volcengine:writer','polishModel':'anthropic:polisher'}
    task={'task_id':'old','status':'failed','node_states':{'script':{'status':'failed','error':'Script Library 已漂移，请创建新任务'}}}
    first=p.recovery_action(state,'polish',task)
    assert first['action']=='advance' and first['stage']=='polish'
    assert set(first['reset'])=={'polish','reader-sim','post-hoc','export'}
    updated=copy.deepcopy(state);updated.update(first['updates'])
    second=p.recovery_action(updated,'polish',{**task,'task_id':'second'})
    assert second is not None
    updated.update(second['updates'])
    assert p.recovery_action(updated,'polish',{**task,'task_id':'third'}) is None
    assert updated['writerModel']=='volcengine:writer' and updated['polishModel']=='anthropic:polisher'


def test_recovery_never_restarts_user_stopped_tasks_or_content_rejections():
    p=policy();state={'values':{'chapter_number':'0001'}}
    assert p.recovery_action(state,'polish',{'task_id':'stop','status':'stopped','error':'connection reset'}) is None
    assert p.recovery_action(state,'mvp',{'task_id':'content','status':'failed','error':'人物提前知道账目；重复片段'}) is None


def test_recovery_does_not_spend_budget_twice_for_same_failed_task():
    p=policy();state={'values':{'chapter_number':'0001'}}
    task={'task_id':'summary','status':'failed','error':'开启了 save_output_to_file，但没有最终 AI 输出可保存'}
    first=p.recovery_action(state,'post-hoc',task);state.update(first['updates'])
    assert p.recovery_action(state,'post-hoc',task) is None


@pytest.mark.parametrize('error',[
    'No streaming chunk received for 120.0s (model=gpt-6.1-sol, chunks_received=6). The connection may be alive at the TCP layer but is not producing content.',
    'StreamChunkTimeoutError: incomplete streaming response',
])
def test_native_stream_inactivity_is_bounded_operational_recovery(error):
    p=policy();state={'values':{'chapter_number':'0002'}}
    task={'task_id':'stream-timeout','status':'failed','node_states':{'agent_pl':{'status':'failed','error':error}}}
    result=p.recovery_action(state,'polish',task)
    assert result and result['stage']=='polish'
    state.update(result['updates'])
    assert p.recovery_action(state,'polish',task) is None
    next_result=p.recovery_action(state,'polish',{**task,'task_id':'stream-timeout-2'})
    assert next_result;state.update(next_result['updates'])
    assert p.recovery_action(state,'polish',{**task,'task_id':'stream-timeout-3'}) is None
