import importlib.util
import hashlib
import json
from pathlib import Path


def test_export_keeps_one_chapter_heading_and_never_changes_source(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/manuscript_export/manuscript_export.py'
    spec = importlib.util.spec_from_file_location('test_export_heading_resource', script)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    originals = ['第1章 · 补经痕迹\n\n她挂好了木牌。', '# 第2章 归来\n\n他来了。', '雨落下来了。']
    for index, text in enumerate(originals, 1):
        path = tmp_path / f'story/{index:04d}/chapter.md';path.parent.mkdir(parents=True);path.write_text(text, encoding='utf-8')
    module.build_manuscript('export/manuscript.md', 'export/manifest.json')
    exported = (tmp_path / 'export/manuscript.md').read_text(encoding='utf-8')
    assert exported.count('补经痕迹') == 1
    assert '# 第0001章' not in exported and '# 第0002章' not in exported
    assert '# 第0003章' in exported
    for index, text in enumerate(originals, 1):assert (tmp_path / f'story/{index:04d}/chapter.md').read_text(encoding='utf-8') == text


def test_confirmed_short_layout_skips_only_synthetic_heading(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/manuscript_export/manuscript_export.py'
    spec = importlib.util.spec_from_file_location('test_export_layout_resource', script)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    (tmp_path/'.novel-project.json').write_text('{"mode":"short"}', encoding='utf-8')
    story = tmp_path/'story/0001/chapter.md'
    story.parent.mkdir(parents=True)
    body = '我终于开了口。\n\n——\n\n她把门打开了。'
    story.write_text(body, encoding='utf-8')
    adopted = tmp_path/'learning/blueprints/v0001.json'
    adopted.parent.mkdir(parents=True)
    mechanism = {'candidate_id': 'layout-1', 'dimension': 'layout', 'export_layout': 'short_body_only', 'scopes': ['export']}
    blueprint = {'mechanisms': [mechanism], 'selected_candidate_ids': ['layout-1']}
    canonical = json.dumps(blueprint, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    adopted.write_text(canonical, encoding='utf-8')
    entry = {'blueprint_path': adopted.relative_to(tmp_path).as_posix(),
             'blueprint_sha256': hashlib.sha256(canonical.encode()).hexdigest(), 'version': 1}
    (tmp_path/'learning/active.json').write_text(json.dumps(entry), encoding='utf-8')
    report = module.build_manuscript('export/manuscript.md', 'export/manifest.json')
    assert (tmp_path/'export/manuscript.md').read_text(encoding='utf-8') == body + '\n'
    assert report['layout_reference']['applied_candidate_id'] == 'layout-1'
    assert story.read_text(encoding='utf-8') == body


def test_verified_delivery_reads_back_page_and_submission_and_detects_stale_sources(tmp_path, monkeypatch):
    import os
    script = Path(__file__).resolve().parents[1] / "resources/script-library/xs2/manuscript_export/manuscript_export.py"
    spec = importlib.util.spec_from_file_location("verified_export", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".novel-project.json").write_text('{"mode":"short"}', encoding="utf8")
    chapter = tmp_path / "story/0001/chapter.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_bytes("电话断了。我点开旧照片。\r\n\r\n我差点约他见面。\r\n".encode())
    build = lambda: module.build_manuscript("custom/book.md", "custom/report.json")
    report = build()
    page, txt = tmp_path / "export/manuscript.md", tmp_path / "export/知乎投稿正文.txt"
    assert page.read_bytes() == (tmp_path / "custom/book.md").read_bytes()
    assert txt.read_bytes() == chapter.read_bytes()
    assert module.delivery_matches(tmp_path, report)
    for stale in (chapter, page, txt):
        raw, timestamp = stale.read_bytes(), stale.stat()
        stale.write_bytes("旧稿".encode())
        os.utime(stale, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
        assert not module.delivery_matches(tmp_path, report)
        stale.write_bytes(raw)
    assert module.delivery_matches(tmp_path, build())
    assert module.delivery_matches(tmp_path, {"chapters": []}) is None
