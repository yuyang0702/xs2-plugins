import asyncio
import importlib.util
import json
from pathlib import Path


def harness(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'evals'))
    spec=importlib.util.spec_from_file_location('p1_eval_test',root/'evals/compare_performance_p1.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m,root


def test_live_comparison_keeps_dynamic_book_style_system_prompt(tmp_path,monkeypatch):
    from src.workflow.definition import WorkflowDef
    m,root=harness(monkeypatch)
    workflow=json.loads((root/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(workflow);node=next(n for n in workflow['nodes'] if n['id']=='agent_context_reader')
    (tmp_path/'preference.md').write_text('全知与长句是本书作者选择。',encoding='utf8')
    result=asyncio.run(m.system_for(node,{'sections':[{'content':'原有审稿原则'}]},
        {'prose_policy_prompt':'preference.md'},wf.variables,tmp_path))
    assert '原有审稿原则' in result and '全知与长句是本书作者选择。' in result


def test_resumed_cached_calls_are_excluded_from_latency_claims(monkeypatch):
    m,_=harness(monkeypatch)
    resumed=m.arm_timing(4.2,1);fresh=m.arm_timing(65.4,0)
    assert resumed['elapsed_seconds'] is None and resumed['latency_comparable'] is False
    assert fresh['elapsed_seconds']==65.4 and fresh['latency_comparable'] is True


def test_planted_fact_detection_requires_one_matching_factual_issue(monkeypatch):
    m,_=harness(monkeypatch)
    report={'fact_review':{'verdict':'revise'},'issues':[{'impact':'别处t=6存在问题'},{'impact':'重复解释t=10'}]}
    assert not m.detect_planted_fact(report)
    report['issues']=[{'impact':'把站端收到回执由t=10改成t=6，混淆执行与获知时刻。'}]
    assert m.detect_planted_fact(report)


def test_comparison_uses_adopted_style_file_aliases(monkeypatch):
    m,_=harness(monkeypatch)
    values={'character_voice_file':'meta/voice.md','pp_character_voice_file':'{{character_voice_file}}'}
    result=m.apply_runtime_aliases(values,{'aliases':{'meta/voice.md':'learning/runtime/effective-voice.md'}})
    assert result['pp_character_voice_file']=='learning/runtime/effective-voice.md'
    assert values['pp_character_voice_file']=='{{character_voice_file}}'


def test_prior_failed_call_also_invalidates_resumed_latency_comparison(monkeypatch):
    m,_=harness(monkeypatch)
    result=m.arm_timing(9.0,0,previous_calls=1)
    assert result['elapsed_seconds'] is None and result['latency_comparable'] is False
