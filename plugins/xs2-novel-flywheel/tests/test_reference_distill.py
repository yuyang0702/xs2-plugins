from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PLUGIN_ROOT=Path(__file__).resolve().parents[1]
SCRIPT=PLUGIN_ROOT/'resources'/'script-library'/'xs2'/'reference_distill'/'reference_distill.py'

def run(tmp_path, *args):
    return subprocess.run([sys.executable,str(SCRIPT),*args],cwd=tmp_path,capture_output=True,text=True)

def test_reference_selection_creates_versioned_context(tmp_path):
    source=tmp_path/'references'/'source.txt'; source.parent.mkdir()
    source.write_text('主角发现一处异常。这个异常迫使他重新选择。结尾兑现问题并留下代价。',encoding='utf-8')
    result=run(tmp_path,'split','--input','references/source.txt','--window','4200','--overlap','400')
    assert result.returncode==0,result.stderr
    manifest=json.loads((tmp_path/'learning/cache/windows.json').read_text(encoding='utf-8'))
    window=manifest['windows'][0]
    raw={'window_id':window['window_id'],'source_sha256':manifest['source']['text_sha256'],'candidates':[{'mechanism':'异常选择机制','transfer_guidance':'用新的可观察异常改变角色的选择空间','constraints':['不得复制来源情节'],'scopes':['story-plan','outline','mvp','polish','post-hoc'],'confidence':'high','evidence':[{'window_id':window['window_id'],'source_start':0,'source_end':8,'excerpt':window['text'][:8],'reason':'异常制造继续阅读问题'}]}]}
    raw_path=tmp_path/'learning/cache/window-0001.raw.json'; raw_path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
    assert run(tmp_path,'normalize','--input','learning/cache/window-0001.raw.json','--window-id','window-0001').returncode==0
    assert run(tmp_path,'merge').returncode==0
    candidates=json.loads((tmp_path/'learning/candidates.json').read_text(encoding='utf-8'))
    selection={'candidates_sha256':candidates['candidates_sha256'],'selected_candidate_ids':[candidates['candidates'][0]['candidate_id']]}
    (tmp_path/'learning/selection.json').write_text(json.dumps(selection),encoding='utf-8')
    assert run(tmp_path,'adopt').returncode==0
    context=(tmp_path/'learning/active_context.md').read_text(encoding='utf-8')
    assert '异常选择机制' in context
    assert '主角发现一处异常' not in context
