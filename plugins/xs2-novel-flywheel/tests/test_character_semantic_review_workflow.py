"""Character workflow contracts at the real resolver and CLI boundaries."""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from src.workflow.definition import WorkflowDef
from src.workflow.variable_resolution import resolve_placeholders, resolve_workspace_file_path


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def document(name):
    return json.loads((RESOURCES / name).read_text(encoding="utf-8"))


def workflow():
    from runtime_graph import literary_graph
    return literary_graph(document("workflows/character/definition.json"))


def node_map():
    return {node["id"]: node for node in workflow()["nodes"]}


def resolve(text, values, workspace):
    return asyncio.run(resolve_placeholders(text, values, workflow()["variables"], str(workspace)))


def values(workspace):
    result = {var["key"]: var.get("default", "") for var in workflow()["variables"]}
    batch = workspace / "cache/character-review/task-synthetic"
    draft = batch / "draft"
    result.update(card_batch_dir=str(batch), card_draft_dir=str(draft),
                  card_draft_relative="cache/character-review/task-synthetic/draft",
                  card_draft_skeleton=str(draft / "cache/character/skeleton.json"),
                  card_draft_beliefs=str(draft / "cache/character/beliefs.json"),
                  card_draft_voice_json=str(draft / "cache/character/voice.json"),
                  card_draft_profiles=str(draft / "meta/character_profiles.md"),
                  card_draft_voice=str(draft / "meta/character_voice.md"),
                  card_draft_short_characters=str(draft / "cache/short/characters.json"),
                  card_review_input_file=str(batch / "review_input.json"),
                  card_review_result_file=str(batch / "review_result.json"),
                  card_review_binding_sha="a" * 64, name="人物甲")
    return result


def test_full_and_compact_cannot_finish_without_shared_review_tail():
    data = workflow()
    assert data["version"] == 12
    edges = data["edges"]
    assert [e["target"] for e in edges if e["source"] == "__start__"] == ["script_card_preflight"]
    assert [e["target"] for e in edges if e["source"] == "script_card_preflight"] == ["script_sync_down"]
    for origin in ("script_voice_to_md", "script_short_character"):
        current = origin
        for expected in ("script_prepare_card_review", "agent_card_semantic_review", "script_apply_card_review", "__end__"):
            assert [e["target"] for e in edges if e["source"] == current] == [expected]
            current = expected
    assert {e["source"] for e in edges if e["target"] == "__end__"} == {"script_apply_card_review"}


def test_preflight_passes_author_text_as_single_arguments_and_raw_world_path_on_stdin(tmp_path):
    nodes = node_map()
    preflight = nodes["script_card_preflight"]["node_params"]
    assert preflight["script_stdin_variable"] == "world_foundation"
    assert preflight["script_name"] == "character_review"
    assert preflight["script_group"] == "xs2"
    assert "script_args" not in preflight
    pv = values(tmp_path)
    author = '作者“原话” "quoted"\n第二行; $(does_not_run)'
    pv.update(premise=author, human_intent=author, world_intent=author)
    rendered = [resolve(arg, pv, tmp_path) for arg in preflight["script_argv"]]
    assert rendered == ["preflight", "--premise", author, "--human-intent", author,
                        "--world-intent", author, "--world-file-stdin"]
    # The transport selects pv directly: a file placeholder would read these bytes.
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta/world_foundation.md").write_text("世界正文", encoding="utf-8")
    assert pv[preflight["script_stdin_variable"]] == "meta/world_foundation.md"
    assert resolve("{{world_foundation}}", pv, tmp_path) == "世界正文"


def test_first_preflight_resolves_without_any_draft_variables_yet(tmp_path):
    pv = {var["key"]: var.get("default", "") for var in workflow()["variables"]}
    pv.update(premise="合成人物资料", human_intent="", world_intent="")
    args = node_map()["script_card_preflight"]["node_params"]["script_argv"]
    assert [resolve(arg, pv, tmp_path) for arg in args] == [
        "preflight", "--premise", "合成人物资料", "--human-intent", "", "--world-intent", "", "--world-file-stdin"]


def test_draft_file_bindings_read_generated_contents_with_real_resolver(tmp_path):
    pv = values(tmp_path)
    for key, content in (("card_draft_skeleton", '{"characters":[{"name":"人物甲"}]}'),
                         ("card_draft_beliefs", '{"beliefs":"信任"}'),
                         ("card_draft_profiles", "# 草稿人物档案\n仅草稿"),
                         ("card_review_input_file", '{"task_id":"task-synthetic","sources":{"world":"世界"}}')):
        path = Path(pv[key]); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for node_id, expected in (("agent_belief", '"name":"人物甲"'),
                              ("agent_deep", '"beliefs":"信任"'),
                              ("agent_voice", "# 草稿人物档案"),
                              ("agent_card_semantic_review", '"task_id":"task-synthetic"')):
        assert expected in resolve(node_map()[node_id]["first_message"], pv, tmp_path)
    assert not (tmp_path / "meta/character_profiles.md").exists()


@pytest.mark.parametrize("node_id,key,suffix", [
    ("agent_skeleton", "card_draft_skeleton", ""),
    ("agent_belief", "card_draft_beliefs", ""),
    ("agent_deep", "card_draft_dir", "/cache/character/人物甲_deep.json"),
    ("agent_voice", "card_draft_voice_json", ""),
    ("agent_short_character", "card_draft_short_characters", ""),
])
def test_original_model_output_paths_are_draft_paths(tmp_path, node_id, key, suffix):
    pv = values(tmp_path)
    output = resolve(node_map()[node_id]["output_file_path"], pv, tmp_path)
    assert output == pv[key] + suffix
    assert Path(output).is_relative_to(Path(pv["card_draft_dir"]))


@pytest.mark.parametrize("node_id,expected", [
    ("script_merge", ["--mode", "character"]),
    ("script_voice_to_md", ["--mode", "voice"]),
])
def test_full_renderers_receive_draft_book_and_output(tmp_path, node_id, expected):
    pv = values(tmp_path); params = node_map()[node_id]["node_params"]
    assert "script_args" not in params
    args = [resolve(arg, pv, tmp_path) for arg in params["script_argv"]]
    assert args[:2] == expected
    assert args[args.index("--book-dir") + 1] == pv["card_draft_dir"]
    output = args[args.index("--output") + 1]
    assert Path(output).is_relative_to(Path(pv["card_draft_dir"]) / "meta")


@pytest.mark.parametrize("node_id,key,suffix", [
    ("script_persist_skeleton", "card_draft_skeleton", "skeleton.json"),
    ("script_persist_belief", "card_draft_beliefs", "beliefs.json"),
    ("script_persist_deep", "card_draft_dir", "人物甲_deep.json"),
    ("script_persist_voice", "card_draft_voice_json", "voice.json"),
])
def test_existing_checkpoint_cli_checks_draft_only(tmp_path, node_id, key, suffix):
    pv = values(tmp_path)
    target = Path(pv["card_draft_dir"]) / "cache/character" / suffix
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    params = node_map()[node_id]["node_params"]
    args = [resolve(arg, pv, tmp_path) for arg in params["script_argv"]]
    script = RESOURCES / "script-library/nvl/local_archive/local_archive.py"
    result = subprocess.run([sys.executable, str(script), *args], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "cache/character").exists()


def test_extractor_reads_draft_without_mutating_canonical_book(tmp_path):
    pv = values(tmp_path)
    target = Path(pv["card_draft_skeleton"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"characters":[{"card_schema":"xs2.character.v2","name":"人物甲"}]}', encoding="utf-8")
    params = node_map()["script_extract"]["node_params"]
    args = [resolve(arg, pv, tmp_path) for arg in params["script_argv"]]
    script = RESOURCES / "workflows/character/script/extract_names.py"
    result = subprocess.run([sys.executable, str(script), *args], cwd=tmp_path,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert '<WF_VAR>character_names:["人物甲"]</WF_VAR>' in result.stdout
    assert not (tmp_path / "cache/character").exists()


def test_review_selected_output_is_saved_then_sent_directly_to_apply(tmp_path):
    nodes = node_map(); agent = nodes["agent_card_semantic_review"]
    assert agent["agent_type"] == "novel-character-semantic-review"
    assert agent["output_variable"] == "card_semantic_review_result"
    assert agent["save_output_to_file"] is True
    assert agent["output_file_path"] == "{{card_review_result_file}}"
    assert agent["auto_flow"] is True
    assert agent["enable_complete_node_task"] is False
    assert agent["node_params"]["output_selection"] == "completion_tool_message"
    apply = nodes["script_apply_card_review"]["node_params"]
    assert apply["script_stdin_variable"] == "card_semantic_review_result"
    assert apply["script_argv"] == ["apply", "--batch-dir", "{{card_batch_dir}}", "--binding-sha", "{{card_review_binding_sha}}", "--retry-review"]
    assert nodes["script_short_character"]["node_params"]["script_argv"] == ["render-compact", "--batch-dir", "{{card_batch_dir}}"]
    assert nodes["script_prepare_card_review"]["node_params"]["script_argv"] == ["prepare", "--batch-dir", "{{card_batch_dir}}"]


def test_model_choices_stay_legacy_and_analysis_inherits_system_default():
    agents = document("agents.json")["agents"]
    expected = {
        "agent_skeleton": ("novel-character-skeleton", "high", 0.7),
        "agent_belief": ("novel-character-belief", "high", 0.7),
        "agent_deep": ("novel-character-deep", "high", 0.7),
        "agent_voice": ("novel-character-voice", "high", 0.3),
        "agent_short_character": ("novel-short-character", "medium", 0.7),
    }
    for node_id, (agent_type, effort, temperature) in expected.items():
        node = node_map()[node_id]
        assert node["agent_type"] == agent_type
        assert not node.get("model_override")
        assert not node["node_params"].get("model_params_override")
        params = copy.deepcopy(agents[agent_type]["model_params"])
        assert params.pop("thinking_enabled") is True
        assert params.pop("reasoning_effort") == effort
        assert params.pop("temperature") == temperature
        assert params.pop("top_p") == 1
        assert params.pop("response_format") == {"type": "json_object"}
        assert params == ({"presence_penalty": 0} if node_id == "agent_voice" else {})
    review = agents["novel-character-semantic-review"]
    assert not set(review) & {"model", "model_override", "model_params"}
    assert review.get("tools") == []
    assert not node_map()["agent_card_semantic_review"].get("model_override")
    # Production loader can consume all new nodes and variable definitions.
    assert WorkflowDef.from_dict(workflow()).workflow_id == "character"


def test_loop_file_default_rebinding_retains_paths_then_reads_draft(tmp_path):
    """Mirror execution_loop's actual default reassignment, including later iterations."""
    pv = values(tmp_path)
    for key, payload in (("card_draft_skeleton", '{"name":"人物甲"}'),
                         ("card_draft_beliefs", '{"beliefs":"信任"}')):
        path = Path(pv[key]); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    for name in ("人物甲", "人物乙"):
        pv["name"] = name
        for variable in workflow()["variables"]:
            default = variable.get("default", "")
            if variable["type"] == "file" and "{{" in default:
                pv[variable["key"]] = default
                pv[variable["key"]] = resolve(default, pv, tmp_path)
        assert pv["skeleton_json"] == pv["card_draft_skeleton"]
        assert pv["beliefs_json"] == pv["card_draft_beliefs"]
        assert Path(pv["deep_json"]).name == name + "_deep.json"
        assert '"beliefs":"信任"' in resolve(node_map()["agent_deep"]["first_message"], pv, tmp_path)


def test_full_render_node_arguments_really_render_only_inside_draft(tmp_path):
    pv = values(tmp_path)
    record = {"card_schema": "xs2.character.v2", "name": "人物甲", "role": "修伞师",
              "facts": ["人物甲修过伞"], "personality": "看重手艺也愿意协商", "plot_constraints": []}
    for key, data in (("card_draft_skeleton", {"characters": [record]}),
                      ("card_draft_voice_json", {"characters": [{"name": "人物甲", "voice_positioning": "熟人前愿意解释"}]})):
        path = Path(pv[key]); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = RESOURCES / "script-library/nvl/json_to_md/json_to_md.py"
    for node_id in ("script_merge", "script_voice_to_md"):
        args = [resolve(arg, pv, tmp_path) for arg in node_map()[node_id]["node_params"]["script_argv"]]
        result = subprocess.run([sys.executable, str(script), *args], cwd=tmp_path,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
    assert "人物甲修过伞" in Path(pv["card_draft_profiles"]).read_text(encoding="utf-8")
    assert "熟人前愿意解释" in Path(pv["card_draft_voice"]).read_text(encoding="utf-8")
    assert not (tmp_path / "meta/character_profiles.md").exists()
    assert not (tmp_path / "meta/character_voice.md").exists()


def test_review_policy_selects_plain_json_and_rejects_duplicate_keys():
    from src.workflow.output_selection import select_agent_output

    params = node_map()["agent_card_semantic_review"]["node_params"]
    output = {"schema": "xs2.character.semantic-review.v2", "task_id": "synthetic",
              "source_sha256": "a" * 64, "status": "blocked", "characters": [],
              "blocking_issues": ["锁定来源有矛盾"]}
    selected, error = select_agent_output([
        {"type": "user", "content": "冻结审核输入"},
        {"type": "assistant", "content": json.dumps(output, ensure_ascii=False)},
    ], params)
    assert not error
    assert json.loads(selected) == output
    _, error = select_agent_output([
        {"type": "user", "content": "冻结审核输入"},
        {"type": "assistant", "content": '{"status":"accepted","status":"blocked"}'},
    ], params)
    assert "duplicate JSON key" in error


def test_production_prompt_builder_routes_the_complete_review_contract(monkeypatch):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder

    key = "novel-character-semantic-review"
    agent = AgentDefinition(agent_type=key, **document("agents.json")["agents"][key])
    monkeypatch.setattr("src.agent.definition.get_agent_definition", lambda _: agent)
    sections = document("prompts.json")["agents"][key]["sections"]

    class Resources:
        def get_sections(self, template):
            assert template == key
            return copy.deepcopy(sections)

    actual = PromptBuilder(Resources()).build(key, is_workflow=True, include_skills=False, include_rules=False)
    for section in sections:
        assert section["content"] in actual


def extract_synthetic(tmp_path, characters, *, legacy_cli=False, pv_overrides=None, raw_json=None):
    pv = values(tmp_path)
    pv.update(pv_overrides or {})
    path = Path(pv["card_draft_skeleton"])
    path.parent.mkdir(parents=True, exist_ok=True)
    source = raw_json if raw_json is not None else json.dumps({"characters": characters}, ensure_ascii=False)
    path.write_bytes(source.encode("utf-8"))
    args = [resolve(arg, pv, tmp_path) for arg in node_map()["script_extract"]["node_params"]["script_argv"]]
    if legacy_cli:
        args = ["--file", str(path)]
    result = subprocess.run([sys.executable, str(RESOURCES / "workflows/character/script/extract_names.py"), *args],
                            cwd=tmp_path, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                            capture_output=True, text=True, encoding="utf-8")
    emitted = re.findall(r"<WF_VAR>character_names:(.*?)</WF_VAR>", result.stdout)
    # Exercise the real downstream interpolation/path policy if extraction permits it.
    # Never write the resulting model output; the canonical destination must remain absent.
    targets = []
    for payload in emitted:
        for name in json.loads(payload):
            pv["name"] = name
            output = resolve(node_map()["agent_deep"]["output_file_path"], pv, tmp_path)
            targets.append(resolve_workspace_file_path(tmp_path, output))
    return result, emitted, targets


def test_v2_traversal_is_rejected_before_deep_loop_can_target_canonical_cache(tmp_path):
    result, emitted, targets = extract_synthetic(tmp_path, [
        {"card_schema": "xs2.character.v2", "name": "人物甲"},
        {"card_schema": "xs2.character.v2", "name": "../../../../../character/escaped"},
    ])
    assert result.returncode != 0, {"stdout": result.stdout, "resolved_deep_targets": targets}
    assert not emitted
    assert not targets
    assert not (tmp_path / "cache/character/escaped_deep.json").exists()
    assert not (tmp_path / "cache/character").exists()


def test_v10_workflow_rejects_omitted_v2_marker_before_traversal_can_enter_loop(tmp_path):
    result, emitted, targets = extract_synthetic(tmp_path, [
        {"name": "../../../../../character/escaped"},
    ])
    assert result.returncode != 0, {"stdout": result.stdout, "resolved_deep_targets": targets}
    assert not emitted
    assert not targets
    assert not (tmp_path / "cache/character").exists()


def test_v10_workflow_rejects_even_safe_names_without_explicit_v2_marker(tmp_path):
    result, emitted, targets = extract_synthetic(tmp_path, [{"name": "人物甲"}])
    assert result.returncode != 0, result.stdout
    assert not emitted
    assert not targets


@pytest.mark.parametrize("field", ["name", "true_name", "aliases"])
@pytest.mark.parametrize("template", ["{{premise}}", "{{", "}}"])
def test_v10_rejects_identity_template_delimiters_before_nested_expansion(tmp_path, field, template):
    record = {"card_schema": "xs2.character.v2", "name": "人物甲"}
    record[field] = [template] if field == "aliases" else template
    result, emitted, targets = extract_synthetic(tmp_path, [record],
        pv_overrides={"premise": "../../../../../character/escaped"})
    assert result.returncode != 0, {"stdout": result.stdout, "resolved_deep_targets": targets}
    assert not emitted
    assert not targets
    assert not (tmp_path / "cache/character").exists()


@pytest.mark.parametrize("change", [
    {"name": "..\\..\\character\\escaped"}, {"name": "C:\\absolute"}, {"name": "/absolute"},
    {"name": "../outside"}, {"name": "# 标题"}, {"name": "```json"}, {"name": "~~~"},
    {"name": "人物\n甲"}, {"name": "人物\u2028甲"}, {"name": "人物\x00甲"},
    {"name": ""}, {"name": " "}, {"name": 3}, {"name": ".."}, {"name": "甲" * 61},
    {"true_name": None}, {"true_name": ["人物甲"]}, {"true_name": "真名\n另一行"},
    {"true_name": "## 标题"}, {"true_name": "```json"},
    {"aliases": "别称"}, {"aliases": [1]}, {"aliases": [""]}, {"aliases": ["别称\n第二行"]},
    {"aliases": ["# 标题"]}, {"aliases": ["~~~"]},
    {"card_schema": None}, {"card_schema": "xs2.character.v99"},
])
def test_v2_invalid_identity_or_marker_emits_no_loop_names(tmp_path, change):
    invalid = {"card_schema": "xs2.character.v2", "name": "人物乙"}
    invalid.update(change)
    result, emitted, targets = extract_synthetic(tmp_path, [
        {"card_schema": "xs2.character.v2", "name": "人物甲"}, invalid])
    assert result.returncode != 0, result.stdout
    assert not emitted
    assert not targets
    assert not (tmp_path / "cache/character").exists()


@pytest.mark.parametrize("other", [
    {"card_schema": "xs2.character.v2", "name": "人物甲"},
    {"card_schema": "xs2.character.v2", "name": " 人物甲 "},
    {"name": "人物甲"},
])
def test_v2_duplicate_identity_is_rejected_for_entire_batch(tmp_path, other):
    result, emitted, targets = extract_synthetic(tmp_path, [
        {"card_schema": "xs2.character.v2", "name": "人物甲"}, other])
    assert result.returncode != 0, result.stdout
    assert not emitted
    assert not targets


def test_v2_unicode_identities_emit_only_confined_deep_targets(tmp_path):
    result, emitted, targets = extract_synthetic(tmp_path, [
        {"card_schema": "xs2.character.v2", "name": "顾青·林", "true_name": "", "aliases": ["阿青", "青先生"]},
        {"card_schema": "xs2.character.v2", "name": "Élodie-2", "true_name": "Élodie", "aliases": []},
        {"card_schema": "xs2.character.v2", "name": "顾青[林]{甲}", "aliases": ["{小顾}"]},
    ])
    assert result.returncode == 0, result.stderr
    assert len(emitted) == 1
    assert json.loads(emitted[0]) == ["顾青·林", "Élodie-2", "顾青[林]{甲}"]
    draft = Path(values(tmp_path)["card_draft_dir"])
    assert [target.name for target in targets] == ["顾青·林_deep.json", "Élodie-2_deep.json", "顾青[林]{甲}_deep.json"]
    assert all(target.is_relative_to(draft) for target in targets)
    assert not (tmp_path / "cache/character").exists()


def test_require_v2_preserves_valid_json_smart_quotes_and_bytes(tmp_path):
    raw = '''{
  "characters": [{
    "card_schema": "xs2.character.v2", "name": "人物甲",
    "true_name": "阿甲", "aliases": ["小甲"],
    "facts": ["人物甲说过“等雨停了再走”，原话不能被改写。"],
    "personality": "珍惜他人所说的“愿意”，也在意自己的选择。",
    "plot_constraints": ["结尾保留“自己决定”的作者要求。"]
  }]
}
'''
    result, emitted, targets = extract_synthetic(tmp_path, None, raw_json=raw)
    assert result.returncode == 0, result.stderr
    assert json.loads(emitted[0]) == ["人物甲"]
    pv = values(tmp_path)
    assert Path(pv["card_draft_skeleton"]).read_bytes() == raw.encode("utf-8")
    assert len(targets) == 1
    assert targets[0].is_relative_to(Path(pv["card_draft_dir"]))
    assert not (tmp_path / "cache/character").exists()


@pytest.mark.parametrize("raw", [
    '[]', '{}', '{"characters":null}', '{"characters":{}}',
    '{"characters":"人物甲"}', '{"characters":[3]}',
    '{"characters":[{"card_schema":"xs2.character.v2","name":"人物甲",}]}',
    '```json\n{"characters":[{"card_schema":"xs2.character.v2","name":"人物甲"}]}\n```',
    '{\n"characters":[{\n"card_schema":"xs2.character.v2",\n"name":"人物甲",\n孤立文本",\n"facts":[]\n}]\n}',
])
def test_require_v2_rejects_invalid_json_or_shape_without_repairing_source(tmp_path, raw):
    result, emitted, targets = extract_synthetic(tmp_path, None, raw_json=raw)
    assert result.returncode != 0, result.stdout
    assert not emitted
    assert not targets
    assert Path(values(tmp_path)["card_draft_skeleton"]).read_bytes() == raw.encode("utf-8")
    assert not (tmp_path / "cache/character").exists()


def test_unversioned_legacy_extraction_keeps_its_existing_name_behavior(tmp_path):
    result, emitted, _ = extract_synthetic(tmp_path, [
        {"name": "旧档甲", "aliases": "旧格式不在此迁移"}, {"name": "旧档甲"},
    ], legacy_cli=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(emitted[0]) == ["旧档甲", "旧档甲"]
