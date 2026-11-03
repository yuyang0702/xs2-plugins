import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

RES = Path(__file__).resolve().parents[1] / "resources"
LIB = RES / "script-library"
ENTRY = LIB / "xs2/prose_policy/prose_policy.py"
OLD = "每句对白必须推进情节。"
NEW = "关键对白推动选择，普通回应也可保留个人味。"
FACT = "阿杏必须在落闸前作证。"
KNOWLEDGE = "阿杏不能知道主角私下交易。"
VOICE = "meta/character_voice.md"


def write(root, source, text):
    target = root / source
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target


@pytest.fixture
def book(tmp_path):
    write(tmp_path, VOICE, f"\ufeff## 阿杏\r\n### 表达建议\r\n- {OLD}\r\n")
    write(tmp_path, "meta/character_profiles.md", f"## 阿杏\n### 知情边界\n{KNOWLEDGE}\n")
    write(tmp_path, "meta/story_plan.md", f"## 作者确认事件\n{FACT}\n")
    write(tmp_path, "meta/world_foundation.md", "## 世界规则\n落闸后渡口关闭。\n")
    write(tmp_path, "meta/style_profile.md", f"未标注来源\n每段必须添一个动作。\n")
    write(tmp_path, "outline/volume_outline.md", "### 第1章\n旧坊等待阿杏。\n")
    write(tmp_path, "outline/near_term_outline.md", "### 第1章\n落闸前到渡口。\n")
    write(tmp_path, "story/0001/single_chapter_guide.md", "## 表达建议\n对白后必须解释其用意。\n")
    write(tmp_path, "learning/active_context.md", "## 作者确认\n不得改掉作证的结果。\n")
    return tmp_path


def policy():
    spec = importlib.util.spec_from_file_location("test_prose_policy_service", ENTRY)
    assert ENTRY.is_file(), "plugin has no prose policy service"
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def approve(policy, book, source=VOICE, old=OLD, new=NEW):
    revision = policy.read(book)["revision"]
    preview = policy.preview_override(book, {
        "source_id": source, "quote": old, "replacement": new,
    }, revision)
    assert preview["before"] == old and preview["after"] == new
    return policy.save(book, {"mode": "narrative_led", "overrides": [preview]}, revision)


def test_legacy_audit_is_read_only_and_does_not_call_ordinary_facts_mechanical(book):
    service = policy()
    before = snapshot(book)
    state = service.read(book)
    assert state["mode"] == "inherit" and state["overrides"] == []
    report = service.audit(book, "1")
    assert report["chapter"] == "0001"
    assert {VOICE, "meta/story_plan.md", "outline/volume_outline.md",
            "outline/near_term_outline.md", "story/0001/single_chapter_guide.md",
            "learning/active_context.md"} <= {row["source_id"] for row in report["sources"]}
    by_quote = {item["quote"]: item for item in report["findings"]}
    assert {OLD, "每段必须添一个动作。", "对白后必须解释其用意。"} <= set(by_quote)
    assert FACT not in by_quote and KNOWLEDGE not in by_quote
    assert by_quote[OLD]["line"] == 3 and by_quote[OLD]["review_status"] == "candidate"
    assert by_quote["每段必须添一个动作。"]["source_category"] == "unknown"
    assert not by_quote["每段必须添一个动作。"]["override_eligible"]
    assert snapshot(book) == before


@pytest.mark.parametrize(("source", "quote"), [
    ("meta/story_plan.md", FACT),
    ("meta/character_profiles.md", KNOWLEDGE),
    ("meta/style_profile.md", "每段必须添一个动作。"),
    ("meta/world_foundation.md", "落闸后渡口关闭。"),
    (VOICE, "必须"),
    ("../outside.md", OLD),
])
def test_preview_refuses_non_expression_unknown_and_unbound_fragments(book, source, quote):
    service = policy()
    before = snapshot(book)
    with pytest.raises(ValueError):
        service.preview_override(book, {
            "source_id": source, "quote": quote, "replacement": NEW,
        }, service.read(book)["revision"])
    assert snapshot(book) == before


def test_preview_requires_explicit_confirmation_and_cannot_be_tampered(book):
    service = policy()
    before = snapshot(book)
    state = service.read(book)
    draft = {"source_id": VOICE, "quote": OLD, "replacement": NEW}
    preview = service.preview_override(book, draft, state["revision"])
    assert snapshot(book) == before
    with pytest.raises(ValueError):
        service.save(book, {"mode": "narrative_led", "overrides": [draft]}, state["revision"])
    with pytest.raises(ValueError):
        service.save(book, {"mode": "narrative_led", "overrides": [
            {**preview, "replacement": "擅自改动"}]}, state["revision"])
    saved = service.save(book, {"mode": "narrative_led", "overrides": [preview]}, state["revision"])
    assert saved["revision"] != state["revision"]
    assert service.effective_text(book, VOICE) == before[VOICE].decode("utf-8-sig").replace(OLD, NEW)
    assert {k: v for k, v in snapshot(book).items() if not k.startswith("learning/prose_policy/")} == before
    with pytest.raises(ValueError):
        service.save(book, {"mode": "inherit"}, state["revision"])


def test_changed_source_invalidates_preview_and_never_applies_old_override(book):
    service = policy()
    saved = approve(service, book)
    path = write(book, VOICE, f"## 阿杏\n### 表达建议\n- {OLD}\n补充了一行。\n")
    state = service.read(book)
    assert state["revision"] == saved["revision"]
    assert state["stale_overrides"][0]["source_id"] == VOICE
    assert service.effective_text(book, VOICE) == path.read_text(encoding="utf-8")
    assert "重新核对" in service.effective_context(book)["instructions"]
    with pytest.raises(ValueError):
        service.save(book, {"mode": "narrative_led", "overrides": saved["overrides"]}, saved["revision"])


def test_runtime_aliases_are_task_scoped_and_inherit_creates_nothing(book):
    service = policy()
    before = snapshot(book)
    assert service.prepare_runtime(book, "0001", task_id="legacy-task")["aliases"] == {}
    assert snapshot(book) == before
    approve(service, book)
    one = service.prepare_runtime(book, "0001", task_id="first-task")
    two = service.prepare_runtime(book, "0001", task_id="second-task")
    assert one["aliases"][VOICE] != two["aliases"][VOICE]
    assert NEW in (book / one["aliases"][VOICE]).read_text(encoding="utf-8")
    assert (book / VOICE).read_bytes() == before[VOICE]
    with pytest.raises(ValueError):
        service.prepare_runtime(book, "0001", task_id="../outside")


def test_audit_locates_expression_clause_without_changing_mixed_factual_paragraph(book):
    service = policy()
    source = "meta/story_plan.md"
    quote = "每句对白必须有具体目的"
    original = f"## 章内约束\n{FACT}{quote}；{KNOWLEDGE}\n"
    write(book, source, original)
    report = service.audit(book, "0001")
    finding = next(row for row in report["findings"] if row["source_id"] == source)
    assert finding["quote"].rstrip("；") == quote
    assert original[finding["start"]:finding["end"]] == finding["quote"]
    assert finding["source_category"] == "unknown" and not finding["override_eligible"]
    with pytest.raises(ValueError):
        service.preview_override(book, {"source_id": source, "quote": finding["quote"],
                                       "replacement": NEW}, report["revision"])


def load_workflow(name):
    return json.loads((RES / f"workflows/{name}/definition.json").read_text(encoding="utf-8"))


async def resolve(text, values, definition, root):
    from src.workflow.variable_resolution import resolve_placeholders

    return await resolve_placeholders(text, values, definition["variables"], str(root))


def workflow_context(book, name, task_id):
    definition = load_workflow(name)
    values = {v["key"]: v.get("default", "") for v in definition["variables"]
              if v.get("source_type") != "output"}
    values.update(chapter_number="0001")
    values.update(workflow_script(book, definition, values, "script_story_context", task_id))
    return definition, values


def workflow_script(book, definition, values, node_id, task_id):
    from src.workflow.nodes.script import _parse_wf_vars

    context = next(n for n in definition["nodes"] if n["id"] == node_id)
    params = context["node_params"]
    if "script_argv" in params:
        argv = [asyncio.run(resolve(part, values, definition, book)) for part in params["script_argv"]]
    else:
        import shlex
        argv = shlex.split(asyncio.run(resolve(params["script_args"], values, definition, book)))
    result = subprocess.run(
        [sys.executable, "-X", "utf8",
         str(LIB / params["script_group"] / params["script_name"] / (params["script_name"] + ".py")), *argv],
        cwd=book, env={**os.environ, "TASK_ID": task_id, "WORKFLOW_ID": definition["workflow_id"]},
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return _parse_wf_vars(result.stdout)


@pytest.mark.parametrize(("stage", "node_id"), [
    ("story-plan", "agent_mpvb7xer_1"),
    ("outline", "agent_vo"),
    ("mvp", "agent_od"),
    ("mvp", "agent_sw"),
    ("polish", "agent_pl"),
    ("reader-sim", "agent_reader"),
])
def test_real_prompt_builder_gets_policy_and_no_raw_duplicate_through_direct_and_common_context(
    monkeypatch, book, stage, node_id
):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder

    write(book, "story/0001/chapter.md", f"{FACT}\n{KNOWLEDGE}\n")
    # Profiles appears both in the shared context and under distinct direct
    # file variables in different workflows. Both routes must be effective.
    profile = "meta/character_profiles.md"
    write(book, VOICE, "## 阿杏\n她避开官话。\n")
    write(book, profile, f"## 阿杏\n### 知情边界\n{KNOWLEDGE}\n### 表达建议\n- {OLD}\n")
    approve(policy(), book, profile)
    definition, values = workflow_context(book, stage, f"policy-{stage}")
    node = next(n for n in definition["nodes"] if n["id"] == node_id)
    agent = node["agent_type"]
    definitions = json.loads((RES / "agents.json").read_text(encoding="utf-8"))["agents"]
    templates = json.loads((RES / "prompts.json").read_text(encoding="utf-8"))["agents"]
    monkeypatch.setattr("src.agent.definition.get_agent_definition",
                        lambda kind: AgentDefinition(agent_type=kind, **definitions[kind]))

    class Resources:
        def get_sections(self, template):
            return templates[template]["sections"]

    system = PromptBuilder(Resources()).build(
        agent, is_workflow=True, include_skills=False, include_rules=False,
        custom_append=asyncio.run(resolve(node["system_prompt_template"], values, definition, book)),
    )
    first_message = asyncio.run(resolve(node["first_message"], values, definition, book))
    assert "叙述主导" in system
    assert NEW in first_message and OLD not in first_message
    assert FACT in first_message and KNOWLEDGE in first_message
    assert OLD in (book / profile).read_text(encoding="utf-8")


def test_legacy_workflow_still_reads_canonical_sources_without_runtime_files(book):
    write(book, "story/0001/chapter.md", FACT)
    definition, values = workflow_context(book, "reader-sim", "legacy-workflow")
    reader = next(n for n in definition["nodes"] if n["id"] == "agent_reader")
    assert not asyncio.run(resolve(reader["system_prompt_template"], values, definition, book)).strip()
    assert OLD in asyncio.run(resolve(reader["first_message"], values, definition, book))
    assert not (book / "learning/prose_policy").exists()


def test_opted_in_policy_keeps_a_different_workflow_profile_input(book):
    service = policy()
    canonical = "meta/character_profiles.md"
    write(book, VOICE, "## 阿杏\n她避开官话。\n")
    write(book, canonical, f"## 表达建议\n{OLD}\n")
    custom = "meta/author supplied profile.md"
    write(book, custom, "这次采用的另份档案：阿杏此刻不在场。")
    approve(service, book, canonical)
    definition = load_workflow("outline")
    values = {v["key"]: v.get("default", "") for v in definition["variables"]}
    values.update(chapter_number="0001", character_profiles_file=custom)
    values.update(workflow_script(book, definition, values, "script_story_context", "custom-file"))
    node = next(n for n in definition["nodes"] if n["id"] == "agent_vo")
    text = asyncio.run(resolve(node["first_message"], values, definition, book))
    assert "阿杏此刻不在场" in text
    assert NEW in text and OLD not in text


def test_compact_writer_does_not_read_raw_policy_rule_through_mirrors(book):
    service = policy()
    profile = "meta/character_profiles.md"
    write(book, profile, f"## 表达建议\n{OLD}\n")
    write(book, VOICE, "## 阿杏\n她避开官话。\n")
    (book / "story/0001/single_chapter_guide.md").unlink()
    approve(service, book, profile)
    definition, values = workflow_context(book, "mvp", "short-effective")
    values.update(workflow_script(book, definition, values, "script_short_context", "short-effective"))
    node = next(n for n in definition["nodes"] if n["id"] == "agent_sw")
    text = asyncio.run(resolve(node["first_message"], values, definition, book))
    assert NEW in text and OLD not in text
    assert OLD in (book / "story/0001/character_minor.md").read_text(encoding="utf-8")


def test_length_only_reviewer_freezes_effective_context_instead_of_legacy_cache(book):
    from test_focused_length import managed
    from test_length_quality import quality

    service = policy()
    managed(book)
    write(book, "cache/story-support/context.md", "此前运行生成的缓存：" + OLD)
    approve(service, book)
    task = "length-policy"
    definition, values = workflow_context(book, "polish", task)
    values.update(polish_pass="length_only", target_word_count="4800-5200")
    outputs = workflow_script(book, definition, values, "script_length_context", task)
    write(book, "cache/pp/body.json", json.dumps({"body": "阿杏手腕发酸。"}, ensure_ascii=False))
    review = quality().prepare_fragment_review(
        book, "0001", outputs["length_expected_body_sha"], outputs["length_commit_guard"],
        outputs["length_commit_guard_sha"], task,
    )
    shared = json.loads((book / review["fragment_review_input"]).read_text(encoding="utf-8"))["story_support_context"]
    assert NEW in shared and OLD not in shared
    assert FACT in shared and KNOWLEDGE in shared
    assert OLD in (book / "cache/story-support/context.md").read_text(encoding="utf-8")


def test_mvp_trimmer_reads_effective_voice_in_the_exact_generated_json_mirror(book):
    service = policy()
    write(book, VOICE, f"# 角色声音锚\n\n## 阿杏\n\n### 表达倾向（非固定台词）\n\n- 长短句偏好：{OLD}\n")
    write(book, "cache/character/voice.json", json.dumps({"characters": [
        {"name": "阿杏", "syntax_fingerprint": {"sentence_preference": OLD}}]}, ensure_ascii=False))
    write(book, "cache/character/skeleton.json", json.dumps({"characters": [
        {"name": "阿杏", "identity": "旧坊学徒", "knowledge": KNOWLEDGE}]}, ensure_ascii=False))
    for dimension in ("core_laws", "space_time", "society", "history_culture", "existence", "information"):
        write(book, f"world/{dimension}.json", "{}")
    approve(service, book)
    definition, values = workflow_context(book, "mvp", "structured-voice")
    values.update(workflow_script(book, definition, values, "script_sync_down", "structured-voice"))
    node = next(n for n in definition["nodes"] if n["id"] == "agent_trimmer")
    message = asyncio.run(resolve(node["first_message"], values, definition, book))
    assert NEW in message and OLD not in message
    assert "旧坊学徒" in message and KNOWLEDGE in message
    assert OLD in (book / "cache/sync/characters.json").read_text(encoding="utf-8")


def test_review_reads_adopted_chapter_guide_expression_as_planned_context(book):
    service = policy()
    guide = "story/0001/single_chapter_guide.md"
    write(book, VOICE, "## 阿杏\n她避开官话。\n")
    write(book, guide, f"## 计划场景\n{FACT}\n\n## 表达建议\n{OLD}\n")
    write(book, "story/0001/chapter.md", "阿杏走到渡口。")
    approve(service, book, guide)
    definition, values = workflow_context(book, "reader-sim", "guide-review")
    reader = next(n for n in definition["nodes"] if n["id"] == "agent_reader")
    message = asyncio.run(resolve(reader["first_message"], values, definition, book))
    assert "本章细纲（待写计划，不是已发生事实）" in message
    assert NEW in message and OLD not in message
    assert OLD in (book / guide).read_text(encoding="utf-8")
