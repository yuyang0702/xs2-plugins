"""Regression contracts for the prompts that actually reach novel writers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
PROSE_AGENTS = (
    "novel-writer", "novel-single-writer", "novel-dialogue-writer",
    "novel-action-writer", "novel-internal-writer", "novel-description-writer",
    "novel-storyboard-integrator", "novel-transition-writer",
    "novel-polisher", "novel-professional-polisher",
    "novel-multi-scene-planner", "novel-multi-scene-writer",
)
# These are obsolete imperatives, not banned words in the novel itself.
# Fact, schema, information-access and author-specified constraints are retained.
MECHANICAL = re.compile(
    r"永远执行|长短句交替|禁止(?:使用)?破折号|禁止被动语态|禁止省略主谓语"
    r"|禁止情绪副词|禁止对偶排比|禁止悖论句|感知必须有(?:后果|即刻)"
    r"|(?<!不是)(?:每句|每段|每轮对话|每槽|每次内心活动|每千字|每三千字|每\s*200\s*字)[^\n]{0,35}(?:≤|不超过|至少|必须)"
    r"|连续三(?:句|段)[^\n]{0,45}(?:打碎|打散|切开|合并)"
    r"|超过\s*5\s*句[^\n]{0,15}必须拆"
    r"|最多\s*\d+\s*字/处|\d+-\d+句，至少.{0,5}感官|一句一个感官细节"
    r"|情绪不命名|连续\s*150\s*字[^\n]{0,20}插"
    r"|日常场景\s*\d+-\d+\s*句|不超过\s*1\s*句|60-200\s*字"
    r"|每个场景至少.{0,8}感官|每个段落里至少|哪怕配角也得有一个小动作"
    r"|不写「他心想」「他意识到」|第一个偏即时反应（短）"
)


def test_quota_audit_distinguishes_a_ban_from_an_instruction_rejecting_quotas():
    assert MECHANICAL.search("每段必须增加一个动作。")
    assert not MECHANICAL.search("写法不是每段必须执行的清单。")


@pytest.fixture
def prompt_manager(tmp_path):
    from src.prompts.manager import PromptManager
    document = json.loads((RESOURCES / "prompts.json").read_text(encoding="utf-8"))
    document["agents"]["main"] = {"sections": [{"name": "main", "content": "test"}]}
    config = tmp_path / "prompts.json"
    config.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "cache.json").write_text('{"prompt":"test","version":1}', encoding="utf-8")
    (tmp_path / "history.json").write_text('[]', encoding="utf-8")
    return PromptManager(config_file=config, cache_file=tmp_path / "cache.json",
                         history_file=tmp_path / "history.json")


@pytest.mark.parametrize("agent", PROSE_AGENTS)
def test_enabled_writer_paths_do_not_reintroduce_mechanical_expression_rules(prompt_manager, agent):
    prompt = prompt_manager.get_prompt_text(agent)
    hits = MECHANICAL.findall(prompt)
    assert not hits, f"{agent} still receives contradictory expression rules: {hits}"


def test_workflow_messages_do_not_restore_removed_expression_quotas(prompt_manager):
    count = 0
    for name in ("mvp", "polish"):
        workflow = json.loads((RESOURCES / "workflows" / name / "definition.json").read_text(encoding="utf-8"))
        for node in workflow["nodes"]:
            if node.get("agent_type") not in PROSE_AGENTS:
                continue
            # First messages are combined with this selected agent's enabled
            # sections in production; a later instruction cannot undo a ban.
            assembled = prompt_manager.get_prompt_text(node["agent_type"]) + "\n" + node.get("first_message", "")
            assert not MECHANICAL.search(assembled), f"{name}/{node['id']} restores a removed quota"
            count += 1
    assert count >= 10


def test_character_voice_examples_are_not_frequency_or_catchphrase_quotas(prompt_manager):
    prompt = prompt_manager.get_prompt_text("novel-character-voice")
    assert not re.search(r"每[一二三四五六七八九十\d]+句[^\n]{0,25}(?:至少|必须|不超过)", prompt)
    # Keep the existing character extraction contract and incomplete-data path.
    for field in ("syntax_fingerprint", "emotion_patterns", "cognitive_bias"):
        assert field in prompt
    assert "待补充" in prompt


def test_style_profiler_examples_cannot_regenerate_prose_sentence_quotas(prompt_manager):
    prompt = prompt_manager.get_prompt_text("novel-style-profiler")
    assert "不得有超过三句" not in prompt


@pytest.mark.parametrize("agent", ("novel-director", "novel-outliner"))
def test_planning_does_not_reintroduce_forced_prose_or_plot_cycles(prompt_manager, agent):
    prompt = prompt_manager.get_prompt_text(agent)
    assert not re.search(
        r"不许连续3章|连续 3 章不同节奏|连续3章同一节奏|强制交替"
        r"|高潮前3-5章|每 10 章 ≥1|每 3 章 ≥1|占70%|占20%|占10%"
        r"|留\s*20%\s*给下一章|每次获得必须有代价|每章必须有对抗力量"
        r"|重要秘密分3-5层释放|蓄力章只能有一个事件",
        prompt,
    ), f"{agent} restores fixed plot or expression quotas"
    # Numerical fields and summaries remain available to downstream code.
    assert "纯 JSON" in prompt
    assert "「情节密度约束」表" not in prompt
    if agent == "novel-director":
        assert "填空字符串并保留该键" in prompt


@pytest.mark.parametrize("agent", ("novel-settler", "novel-volume-outliner", "novel-story-planner"))
def test_scene_and_volume_planning_respect_existing_events_instead_of_filling_quotas(prompt_manager, agent):
    prompt = prompt_manager.get_prompt_text(agent)
    assert not re.search(
        r"至少 3 条，至多 5 条|至少各 1 条|第3个状态转换节点"
        r"|章数必须落在|数量对齐篇幅约束表|每次升级后麻烦一定变大"
        r"|每轮的代价如何递增",
        prompt,
    )
    assert "JSON" in prompt
    if agent == "novel-settler":
        assert "空数组" in prompt
        assert "≤60" in prompt  # renderer field limits are still required


def test_polish_messages_do_not_import_an_unrelated_books_repair_case():
    workflow = json.loads((RESOURCES / "workflows/polish/definition.json").read_text(encoding="utf-8"))
    for node in workflow["nodes"]:
        if node["id"] in {"agent_sc", "agent_pl", "agent_pp"}:
            message = node["first_message"]
            assert not re.search(r"感染观察|现场管控|倒计时提示|每项必要规则说明一次即可", message)
            assert "{{target_word_count}}" in message
            assert "{{author_feedback_file}}" in message


def _normalizer():
    path = RESOURCES / "script-library/nvl/polish_post/polish_post.py"
    spec = importlib.util.spec_from_file_location("natural_prose_review_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_critique


def test_naturalness_review_still_requires_textual_evidence_and_reading_impact():
    normalize = _normalizer()
    body = "她问工钱何时结。我解释了规矩。她又问。我又解释一遍。"
    review = normalize({"feels_human": False, "issues": [{
        "dimension": "MECHANICAL_RHYTHM", "severity": "medium", "scope": "passage",
        "location": "工钱交涉", "description": "同样的解释轮次取代了对对方追问的回应。",
        "evidence": [body], "impact": "两次追问没有带来新的回答，人物的急迫被同一节拍抹平。",
        "repair": "合并重复说明，在已有追问中保留这次是否结钱的实际回应。",
    }]}, body)
    assert review["blocking_issues"] == [0]
    assert review["issues"][0]["evidence_status"] == "verified"
    assert review["issues"][0]["evidence"] == [body]


def test_rhythm_statistic_alone_cannot_become_an_automatic_rewrite_order():
    body = "她说：‘好。’\n\n我把账合上。"
    review = _normalizer()({"feels_human": False, "issues": [{
        "dimension": "MECHANICAL_RHYTHM", "severity": "medium",
        "description": "句长方差太低。", "evidence": [], "impact": "",
    }]}, body)
    assert review["blocking_issues"] == []
    assert review["issues"][0]["evidence_status"] == "unverified"


@pytest.mark.parametrize('agent,section_name', [
    ('novel-single-writer', 'sw_self_edit'),
    ('novel-dialogue-writer', 'natural_prose_contract'),
    ('novel-storyboard-integrator', 'niw_polish'),
    ('novel-self-critic', 'nsc_dimensions'),
    ('xs2-reader-sim', 'payoff_and_naturalness'),
    ('novel-polisher', 'natural_prose_contract'),
    ('novel-professional-polisher', 'natural_prose_contract'),
])
def test_cross_paragraph_semantic_audit_reaches_each_production_role_once(monkeypatch, agent, section_name):
    """Check effective role/self-edit delivery, not the literary score of any sample."""
    import copy
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder

    agents = json.loads((RESOURCES / 'agents.json').read_text(encoding='utf-8'))['agents']
    prompts = json.loads((RESOURCES / 'prompts.json').read_text(encoding='utf-8'))['agents']
    definition = AgentDefinition(agent_type=agent, **agents[agent])
    monkeypatch.setattr('src.agent.definition.get_agent_definition', lambda _: definition)
    sections = prompts[definition.prompt_template]['sections']
    section = next(s for s in sections if s['name'] == section_name)
    marker = '## 跨段语义回读'
    assert marker in section['content'], (agent, section_name)
    assert section.get('enabled', True)

    class Resources:
        def get_sections(self, template):
            assert template == definition.prompt_template
            return copy.deepcopy(sections)

    actual = PromptBuilder(Resources()).build(agent, is_workflow=True, include_skills=False, include_rules=False)
    assert section['content'] in actual
    assert actual.count(marker) == 1
