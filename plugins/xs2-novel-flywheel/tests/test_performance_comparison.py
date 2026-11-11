import argparse
import importlib.util
import json
from pathlib import Path
import pytest


def harness():
    file=Path(__file__).resolve().parents[1]/'evals/compare_performance_p0.py'
    spec=importlib.util.spec_from_file_location('performance_comparison_test',file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_comparison_freezes_exact_windows_prose_bytes(tmp_path):
    m=harness();path=tmp_path/'source.md';body='\ufeff风\r\n\r\n雨\n\n'
    m.checked_write(path,body);m.checked_write(path,body)
    assert path.read_bytes()==body.encode('utf-8')
    with pytest.raises(ValueError):m.checked_write(path,body+'改')


@pytest.mark.parametrize('protected',['original','baseline'])
def test_comparison_rejects_protected_output_before_any_write(tmp_path,protected):
    m=harness();source=tmp_path/'stopped';original=tmp_path/'original';baseline=tmp_path/'baseline'
    for p in (source/'observability',original,baseline):p.mkdir(parents=True)
    (source/'observability/driver.json').write_text(json.dumps({'paused':True}),encoding='utf-8')
    (source/'.novel-project.json').write_text('{}',encoding='utf-8')
    (original/'chapter.md').write_bytes(b'original')
    (source/'observability/source-manifest.json').write_text(json.dumps({'source':str(original),'files':m.manifest(original)}),encoding='utf-8')
    root=original if protected=='original' else baseline
    before=m.manifest(root);output=root/'must-not-create'
    args=argparse.Namespace(source_book=str(source),baseline=str(baseline),output=str(output))
    with pytest.raises(ValueError):m.prepare(args)
    assert m.manifest(root)==before and not output.exists()
