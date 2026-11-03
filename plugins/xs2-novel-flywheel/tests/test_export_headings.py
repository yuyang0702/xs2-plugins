import importlib.util
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
