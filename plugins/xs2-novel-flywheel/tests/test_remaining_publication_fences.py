"""Remaining canonical/derived writers share the native publication lock."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from test_book_contract import PLUGIN
from test_native_preflight import native


def load(relative):
    path=PLUGIN/'resources/script-library'/relative
    spec=importlib.util.spec_from_file_location('remaining_writer_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_style_profile_renders_adopted_reference_provenance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive = load('nvl/local_archive/local_archive.py')
    digest = archive._execution_guard().digest
    raw_path = 'cache/story_plan/style_profile.json'
    final_path = 'meta/style_profile.md'
    raw = {'tone': '早市轻喜剧', 'narrative_persona': '陈满第一人称',
           'references': [{'work': '模型猜测的参考作品'}]}
    blueprint = {'selected_style_ids': ['style-confirmed'], 'selected_candidate_ids': ['mechanism-confirmed'],
                 'styles': [{'choice_id': 'style-confirmed', 'title': '口语叙述', 'guidance': '找零时话会被打断'}],
                 'mechanisms': [{'candidate_id': 'mechanism-confirmed', 'mechanism': '现实任务介入争执'}]}
    blueprint_path = 'learning/blueprints/v0001.json'
    for relative, value in [(raw_path, raw), (blueprint_path, blueprint), ('learning/active.json', {
            'blueprint_path': blueprint_path, 'blueprint_sha256': digest(blueprint)})]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    archive._render_files(raw_path, final_path)
    final = (tmp_path / final_path).read_text(encoding='utf-8')
    assert '模型猜测的参考作品' not in final
    assert all(text in final for text in ['陈满第一人称', 'style-confirmed', '找零时话会被打断', 'mechanism-confirmed'])
    assert json.loads((tmp_path / raw_path).read_text(encoding='utf-8')) == raw


def writer_case(native,monkeypatch,kind):
    guard,root,*_=native;monkeypatch.chdir(root)
    body=root/'story/0001/chapter.md';body.parent.mkdir(parents=True);body.write_bytes('旧正文保留。'.encode())
    if kind=='length':
        module=load('xs2/console_service/length_quality.py')
        action=lambda:module._atomic_body(body,'新正文。'.encode(),lambda:None)
        targets=[body]
    elif kind=='mvp':
        module=load('nvl/local_archive/local_archive.py')
        source=root/'cache/si/body.json';source.parent.mkdir(parents=True);source.write_text(json.dumps({'body':'完整MVP正文。'}),encoding='utf8')
        action=lambda:module._render_files('cache/si/body.json','story/0001/chapter.md')
        targets=[body]
    else:
        module=load('xs2/manuscript_export/manuscript_export.py')
        (root/'export').mkdir()
        targets=[root/'export/manuscript.md',root/'export/manifest.json']
        for p in targets:p.write_bytes(b'old export')
        action=lambda:module.build_manuscript('export/manuscript.md','export/manifest.json')
    record=guard.run(root,'polish','0001','task-a','wf')
    return guard,root,module,action,targets,record


@pytest.mark.parametrize('kind',['length','mvp','export'])
def test_stale_native_owner_cannot_publish_remaining_writer(native,monkeypatch,kind):
    guard,root,module,action,targets,record=writer_case(native,monkeypatch,kind)
    before={p:p.read_bytes() for p in targets}
    guard.release(root,record['lease']);guard.claim(root,'book/manuscript','wf/new-task',{'new':'owner'})
    with pytest.raises(ValueError,match='LEASE'):action()
    assert {p:p.read_bytes() for p in targets}==before


@pytest.mark.parametrize('kind',['length','mvp','export'])
def test_remaining_writer_holds_owner_lock_through_atomic_replacements(native,monkeypatch,kind):
    guard,root,module,action,targets,record=writer_case(native,monkeypatch,kind)
    entered=Event();changed=Event();executor=ThreadPoolExecutor(max_workers=1);future=None;seen=[]
    import os
    replace=os.replace
    def take():
        entered.set();guard.release(root,record['lease'])
        lease=guard.claim(root,'book/manuscript','wf/new-task',{'new':'owner'})
        changed.set();return lease
    def intercepted(src,dst):
        nonlocal future
        if Path(dst) in targets:
            seen.append(Path(dst))
            if future is None:future=executor.submit(take)
            assert entered.wait(2)
            assert not changed.wait(.1), 'owner changed during final file replacement'
        return replace(src,dst)
    monkeypatch.setattr(os,'replace',intercepted)
    try:
        action()
        assert seen==targets
        if kind=='export':
            assert json.loads(targets[1].read_text(encoding='utf8'))['execution_fence']['lease']==record['lease']
        assert future.result(timeout=5)['owner']=='wf/new-task'
    finally:executor.shutdown(wait=True)


@pytest.mark.parametrize('kind',['traversal','absolute'])
def test_export_paths_cannot_leave_workspace(tmp_path,monkeypatch,kind):
    monkeypatch.chdir(tmp_path)
    module=load('xs2/manuscript_export/manuscript_export.py')
    target=tmp_path.parent/(tmp_path.name+'-escaped.md')
    outside='../'+target.name if kind=='traversal' else str(target)
    with pytest.raises(ValueError):module.build_manuscript(outside,'export/manifest.json')
    assert not target.exists()


@pytest.mark.parametrize('kind',['length','mvp','export'])
def test_offline_legacy_writer_does_not_create_archive_database(tmp_path,monkeypatch,kind):
    monkeypatch.chdir(tmp_path);monkeypatch.delenv('TASK_ID',raising=False);monkeypatch.delenv('WORKFLOW_ID',raising=False)
    body=tmp_path/'story/0001/chapter.md';body.parent.mkdir(parents=True);body.write_bytes('原正文。'.encode())
    if kind=='length':load('xs2/console_service/length_quality.py')._atomic_body(body,'修订正文。'.encode(),lambda:None)
    elif kind=='mvp':
        source=tmp_path/'cache/si/body.json';source.parent.mkdir(parents=True);source.write_text(json.dumps({'body':'MVP正文。'}),encoding='utf8')
        load('nvl/local_archive/local_archive.py')._render_files('cache/si/body.json','story/0001/chapter.md')
    else:load('xs2/manuscript_export/manuscript_export.py').build_manuscript('export/manuscript.md','export/manifest.json')
    assert not (tmp_path/'archive/longform.sqlite3').exists()


@pytest.mark.parametrize('group',['xs2','xs2-novel-flywheel-xs2','custom-book-xs2'])
def test_mvp_renderer_loads_guard_from_exact_policy_sibling(tmp_path,monkeypatch,group):
    module=load('nvl/local_archive/local_archive.py')
    entry=tmp_path/group/'production_guard/production_guard.py';entry.parent.mkdir(parents=True)
    entry.write_text('RESOURCE_GROUP='+repr(group),encoding='utf8')
    monkeypatch.setattr(module,'_policy',lambda:SimpleNamespace(__file__=str(tmp_path/group/'prose_policy/prose_policy.py')))
    assert module._execution_guard().RESOURCE_GROUP==group
