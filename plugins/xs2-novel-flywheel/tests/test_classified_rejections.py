import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_book_contract import PLUGIN


def module():
    p=PLUGIN/'resources/script-library/xs2/production_guard/rejections.py';s=importlib.util.spec_from_file_location('rejection_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_reader_planner_and_scene_retry_routes_share_classification_and_refresh(monkeypatch,capsys):
    m=module();seen=[]
    monkeypatch.setenv('TASK_ID','task-current');monkeypatch.setenv('WORKFLOW_ID','wf')
    monkeypatch.setattr(m,'guard',lambda:SimpleNamespace(retry=lambda *a:seen.append(a)))
    for target in ('agent_context_reader','agent_composition_review','agent_aw'):
        m.emit(f'<WF_REJECT_UPSTREAM target="{target}">凭据&amp;原文需补审</WF_REJECT_UPSTREAM>')
    assert [row[1] for row in seen]==['reader-review/task-current','composition/task-current','scene-writing/task-current']
    assert all(row[-1]=='凭据&原文需补审' for row in seen)
    assert capsys.readouterr().out.count('WF_REJECT_UPSTREAM')==6


def test_repeated_deterministic_failure_stops_before_another_upstream_request(tmp_path,monkeypatch,capsys):
    m=module();monkeypatch.chdir(tmp_path);monkeypatch.setenv('TASK_ID','task-current');monkeypatch.setenv('WORKFLOW_ID','wf')
    from test_production_preflight import module as guard
    g=guard();monkeypatch.setattr(g,'request_budget',lambda *args:None);monkeypatch.setattr(m,'guard',lambda:g)
    message='<WF_REJECT_UPSTREAM target="agent_reader">引用原句不在当前候选</WF_REJECT_UPSTREAM>'
    m.emit(message)
    with pytest.raises(ValueError,match='RETRY_STOP'):m.emit(message)
    assert capsys.readouterr().out.count('<WF_REJECT_UPSTREAM')==1
