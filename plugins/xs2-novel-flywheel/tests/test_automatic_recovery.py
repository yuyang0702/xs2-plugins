import copy

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
