"""Generation boundaries and production prompt routing, not prose quality scoring."""
from __future__ import annotations

import copy
import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
EXAMPLE_FACT = "甲曾替乙修好一把伞；乙已经取走。"
EXAMPLE_OUTCOME = "作者指定：结尾甲搬到新摊位；此前不能让乙代甲作决定。"


def document(name):
    return json.loads((RESOURCES / name).read_text(encoding="utf-8"))


def schema(node_id):
    node = next(n for n in document("workflows/character/definition.json")["nodes"] if n["id"] == node_id)
    return Draft202012Validator(node["node_params"].get("json_output_schema", {}))


def compact(versioned=True):
    person = {"name": "角色甲", "role": "技师", "want": "保住成果", "fear": "失去工作",
              "contradiction": "信任与顾虑并存", "relationships": [],
              "voice": {"baseline": "熟人面前比较直接", "by_relationship": []}}
    if versioned:
        person.update(card_schema="xs2.character.v2", facts=["角色甲是技师"],
                      personality="重视信誉，愿意听取熟人的解释", plot_constraints=[])
    else:
        person["boundary"] = "不冒领他人成果"
    return {"characters": [person]}


def test_compact_generation_accepts_v2_without_legacy_boundary():
    schema("agent_short_character").validate(compact())


@pytest.mark.parametrize("boundary", ["保留原值", ["保留第一项", "保留第二项"]])
def test_compact_schema_still_accepts_unversioned_legacy_boundary(boundary):
    data = compact(False)
    data["characters"][0]["boundary"] = boundary
    schema("agent_short_character").validate(data)


@pytest.mark.parametrize("change", [
    {"card_schema": "xs2.character.v99"}, {"card_schema": None},
    {"facts": "不是数组"}, {"facts": [1]}, {"personality": "   "},
    {"personality": ["不是字符串"]}, {"plot_constraints": [False]},
    {"boundary": "与v2混用的旧字段"},
])
def test_compact_v2_rejects_invalid_or_ambiguous_fields(change):
    data = compact()
    data["characters"][0].update(change)
    with pytest.raises(ValidationError):
        schema("agent_short_character").validate(data)


@pytest.mark.parametrize("field", ["facts", "personality", "plot_constraints"])
def test_version_marker_requires_all_v2_semantics(field):
    data = compact()
    del data["characters"][0][field]
    with pytest.raises(ValidationError):
        schema("agent_short_character").validate(data)


@pytest.mark.parametrize("value", ["错误类型", [{}], [{"with": "角色乙"}],
                                    [{"with": "角色乙", "guidance": 3}],
                                    [{"with": " ", "guidance": "说明已知情况"}]])
def test_actual_voice_relationship_property_rejects_malformed_shapes(value):
    data = compact(False)
    data["characters"][0]["voice"]["by_relationship"] = value
    with pytest.raises(ValidationError):
        schema("agent_short_character").validate(data)


def test_relationship_and_adaptability_extensions_keep_supported_shape():
    data = compact()
    data["characters"][0]["voice"].update(
        by_relationship=[{"with": "角色乙", "guidance": "有分歧时也愿意解释"}],
        when_adaptable=["疲惫时可以求助", {"condition": "信任恢复", "reaction": "愿意多说明"}],
        boundaries=["不泄露明确保密的身份"], preferences=[])
    schema("agent_short_character").validate(data)


def test_production_agent_mapping_delivers_current_generation_and_use_contracts(monkeypatch):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder

    agents = document("agents.json")["agents"]
    prompts = document("prompts.json")["agents"]
    targets = ("novel-short-character", "novel-character-skeleton", "novel-character-deep",
               "novel-character-voice", "novel-single-writer", "novel-dialogue-writer",
               "novel-storyboard-integrator", "novel-polisher", "novel-professional-polisher",
               "novel-self-critic", "xs2-reader-sim")
    definitions = {key: AgentDefinition(agent_type=key, **agents[key]) for key in targets}
    monkeypatch.setattr("src.agent.definition.get_agent_definition", definitions.get)

    class Resources:
        def get_sections(self, template):
            return copy.deepcopy(prompts[template]["sections"])

    for key in targets:
        final = PromptBuilder(Resources()).build(key, is_workflow=True, include_skills=False, include_rules=False)
        template = definitions[key].prompt_template
        assert template == key
        sections = prompts[template]["sections"]
        for section in sections:
            content = section["content"]
            if section.get("enabled", True) and content.strip() and "{{" not in content:
                assert content in final, (key, section["name"])
                if section["name"] in {"novel-short-character-contract", "ncs_role", "ncd_role",
                                       "cv_role", "sw_dialogue", "ndw_rules", "dialogue_learning_contract"}:
                    assert final.count(content) == 1, (key, section["name"])
        if key in ("novel-short-character", "novel-character-skeleton", "novel-character-deep"):
            # This is schema vocabulary propagation, not a claim about generated style.
            assert all(field in final for field in ("xs2.character.v2", "facts", "personality", "plot_constraints"))


@pytest.mark.parametrize("node_id,custom_fields", [
    ("agent_skeleton", "essence gender age world_position relationships"),
    ("agent_deep", "core_desire deep_fear bottom_line internal_contradiction"),
])
def test_full_node_invocation_keeps_v2_contract_with_legacy_custom_template(node_id, custom_fields, monkeypatch):
    """An effective user template can replace all bundled sections independently."""
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder
    from src.workflow.variable_resolution import resolve_placeholders

    workflow = document("workflows/character/definition.json")
    node = next(n for n in workflow["nodes"] if n["id"] == node_id)
    key = node["agent_type"]
    definition = AgentDefinition(agent_type=key, **document("agents.json")["agents"][key])
    monkeypatch.setattr("src.agent.definition.get_agent_definition", lambda _: definition)
    custom = "作者自定义的旧格式：" + custom_fields

    class CustomResources:
        def get_sections(self, template):
            assert template == definition.prompt_template
            return [{"name": "custom_legacy", "content": custom}]

    system = PromptBuilder(CustomResources()).build(key, is_workflow=True, include_skills=False, include_rules=False)
    task = asyncio.run(resolve_placeholders(node["first_message"],
        {"premise": "角色甲在已有关系中作出选择", "name": "角色甲", "genre": "现实",
         "language": "中文", "narrative_pov": "third_person", "learning_context": "",
         "world_foundation": "已确认背景", "skeleton_json": "已确认人物", "beliefs_json": "已有信念"}))
    assert custom in system
    assert "xs2.character.v2" not in system
    assert "角色甲" in task and "{{premise}}" not in task
    assert all(field in task for field in ("card_schema", "xs2.character.v2", "facts", "personality", "plot_constraints"))
    # Full nodes keep the historical tool/file completion protocol; no new response validator.
    assert "json_output_schema" not in node["node_params"]


def separated_example(content):
    """Read the explicit instructional fixture; this is not generated-prose scoring."""
    marker = "【字段分区正例】"
    assert marker in content, "generation invocation lacks its field-separation example"
    return json.JSONDecoder().raw_decode(content.split(marker, 1)[1].lstrip())[0]


def assert_example_partition(example):
    # These hand-authored event directions and author outcomes define the example's input.
    assert example["facts"] == [EXAMPLE_FACT]
    assert example["plot_constraints"] == [EXAMPLE_OUTCOME]
    assert EXAMPLE_OUTCOME not in example["facts"]
    payload = compact()
    payload["characters"][0].update(example)
    schema("agent_short_character").validate(payload)


@pytest.mark.parametrize("agent,section_name", [
    ("novel-short-character", "novel-short-character-contract"),
    ("novel-character-skeleton", "ncs_role"),
    ("novel-character-deep", "ncd_role"),
    ("novel-character-voice", "cv_role"),
])
def test_generation_classification_example_preserves_fact_and_outcome_directions(agent, section_name):
    sections = document("prompts.json")["agents"][agent]["sections"]
    content = next(s["content"] for s in sections if s["name"] == section_name)
    assert_example_partition(separated_example(content))


@pytest.mark.parametrize("node_id", ["agent_skeleton", "agent_deep", "agent_voice"])
def test_field_separation_example_survives_legacy_custom_prompt_override(node_id):
    from src.workflow.variable_resolution import resolve_placeholders

    node = next(n for n in document("workflows/character/definition.json")["nodes"] if n["id"] == node_id)
    # The user can fully replace system sections. Only the separately resolved invocation is relied on.
    task = asyncio.run(resolve_placeholders(node["first_message"], {"name": "角色甲", "premise": "已有前提"}))
    assert_example_partition(separated_example(task))


@pytest.mark.parametrize('node_id', ['agent_skeleton', 'agent_deep', 'agent_voice', 'agent_short_character'])
def test_new_persona_strategy_contract_survives_full_system_override(node_id):
    node = next(n for n in document('workflows/character/definition.json')['nodes'] if n['id'] == node_id)
    invocation = node['first_message']
    for term in ('want', 'fear', 'contradiction', 'relationships', '不复制全局', '固定策略', '未确认'):
        assert term in invocation


def test_semantic_review_production_contract_separates_draft_provenance_and_authority():
    sections = document('prompts.json')['agents']['novel-character-semantic-review']['sections']
    content = '\n'.join(s['content'] for s in sections)
    for term in ('semantic-review.v2', 'editable_persona', 'persona_edits', 'record_path', 'field_path', 'before', 'after', 'draft-persona.', '不具备事实权威'):
        assert term in content


@pytest.mark.parametrize('agent', ['novel-single-writer', 'novel-dialogue-writer', 'novel-storyboard-integrator',
                                  'novel-polisher', 'novel-professional-polisher', 'novel-self-critic', 'xs2-reader-sim'])
def test_dialogue_contract_preserves_required_speech_and_local_repair_evidence(agent):
    sections = document('prompts.json')['agents'][agent]['sections']
    contract = next(s['content'] for s in sections if s['name'] == 'dialogue_learning_contract')
    for term in ('必要的公开要求', '有限证词', '上一句话', '自我诊断', '字数范围'):
        assert term in contract
    if agent in ('novel-polisher', 'novel-professional-polisher', 'novel-self-critic', 'xs2-reader-sim'):
        assert '具体原句' in contract and '已经成立的信息' in contract and '场景终点' in contract


def test_belief_generation_and_custom_override_invocation_do_not_force_behavior_or_history():
    sections = document('prompts.json')['agents']['novel-character-belief']['sections']
    prompt = '\n'.join(s['content'] for s in sections)
    node = next(n for n in document('workflows/character/definition.json')['nodes'] if n['id'] == 'agent_belief')
    for content in (prompt, node['first_message']):
        for term in ('信念不是作者事实', '固定反应', 'belief_source', '未确认'):
            assert term in content
