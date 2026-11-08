from __future__ import annotations

import json
import tomllib
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WORKFLOWS = {
    "novel-advisor",
    "reader-sim",
    "export",
    "market-ranking",
    "build",
    "character",
    "mvp",
    "outline",
    "polish",
    "post-hoc",
    "story-plan",
    "reference-distillation",
    "adopt-reference",
    "style-compatibility-advisor",
}
EXPECTED_SCRIPT_LIBRARIES = {
    "book_context",
    "local_revision",
    "draft_guard",
    "reader_review",
    "multi_scene",
    "character_review",
    "manuscript_quality",
    "story_support",
    "manuscript_export",
    "market_rankings",
    "cm_post",
    "json_to_md",
    "local_archive",
    "no_post",
    "od_post",
    "parse_intent",
    "polish_post",
    "se_post",
    "si_post",
    "trimmer_post",
    "vo_post",
    "reference_distill",
    "reference_intelligence_helper",
    "we_post",
    "short_preparation",
}
EXPECTED_SKILLS = {"writing-assistant"}
EXPECTED_WORKBENCH_SERVICES = {"character_center", "console_service", "prose_policy", "story_support", "voice_support"}


def test_workbench_services_are_packaged_with_the_plugin():
    extension = tomllib.loads((PLUGIN_ROOT / 'extension.toml').read_text(encoding='utf-8'))
    scripts = PLUGIN_ROOT / extension['resources']['script_libraries'] / 'xs2'
    for service in EXPECTED_WORKBENCH_SERVICES:
        assert (scripts / service / 'SCRIPT.md').is_file()
        assert (scripts / service / f'{service}.py').is_file()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_polish_target_word_count_is_a_bound_input_instead_of_an_empty_template(tmp_path):
    import asyncio
    import importlib.util
    from src.workflow.variable_resolution import resolve_placeholders
    workflow = _json(PLUGIN_ROOT / 'resources/workflows/polish/definition.json')
    assert any('{{target_word_count}}' in node.get('first_message', '') for node in workflow['nodes'])
    fields = {field['key']: field for field in workflow['variables']}
    assert fields['target_word_count']['source_type'] == 'input'
    assert fields['target_word_count']['type'] == 'text'
    path = PLUGIN_ROOT / 'resources/script-library/xs2/console_service/production.py'
    spec = importlib.util.spec_from_file_location('polish_target_parameters', path)
    production = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(production)
    state = {'mode':'short', 'values':{'chapter_number':'0001', 'target_word_count':'4800-5200'}}
    parameters = production.parameters(state, workflow)
    node = next(node for node in workflow['nodes'] if node['id'] == 'agent_pl')
    message = asyncio.run(resolve_placeholders(node['first_message'], parameters, workflow['variables'], str(tmp_path)))
    assert '本章目标字数：4800-5200' in message


def test_manifest_is_resource_only() -> None:
    manifest = tomllib.loads(
        (PLUGIN_ROOT / "extension.toml").read_text(encoding="utf-8")
    )
    assert manifest["extension"]["id"] == "xs2-novel-flywheel"
    assert manifest["extension"]["version"] == "0.1.13"
    assert "backend" not in manifest["extension"]
    assert "installation" not in manifest
    assert "lifecycle" not in manifest
    assert "settings" not in manifest
    assert manifest["resource_namespace"]["prefix"] == "xs2-novel-flywheel"
    assert set(manifest["resources"]) == {
        "agents",
        "prompts",
        "skills",
        "skill_bundles",
        "workflows",
        "script_libraries",
    }
    assert "resources.skills" in manifest["extension"]["capabilities"]


def test_writing_assistant_is_auto_injected_for_main() -> None:
    resources = PLUGIN_ROOT / "resources"
    skills = _json(resources / "skills.json")

    assert skills["skills"] == {
        "writing-assistant": {
            "group_ids": ["default"],
            "auto_inject": True,
        }
    }
    assert skills["skill_configs"] == {
        "writing-assistant": {
            "enabled": True,
            "priority": 70,
            "auto_inject": True,
            "workflow_only": False,
        }
    }
    assert skills["groups"] == []


def test_writing_assistant_skill_covers_public_workflow_contract() -> None:
    skill_root = (
        PLUGIN_ROOT
        / "resources"
        / "skill-bundles"
        / "writing-assistant"
    )
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    workflow_reference = (
        skill_root / "references" / "workflows.md"
    ).read_text(encoding="utf-8")
    workspace_reference = (
        skill_root / "references" / "workspace.md"
    ).read_text(encoding="utf-8")

    assert "name: writing-assistant" in skill
    assert "写作助手" in skill
    assert "写作工作流主管" in skill
    assert "workspace_mode=named_shared" in skill
    assert "list_workflows" in skill
    assert "get_workflow" in skill
    assert "get_task_result" in skill
    assert EXPECTED_WORKFLOWS <= set(workflow_reference.split("`"))
    assert "task_isolated" in workspace_reference
    assert "workspace_override" in workspace_reference

    evals = _json(PLUGIN_ROOT / "evals" / "evals.json")
    assert evals["skill_name"] == "writing-assistant"
    assert len(evals["evals"]) == 3
    assert all(case["expectations"] for case in evals["evals"])


def test_resource_graph_contains_only_referenced_production_resources() -> None:
    resources = PLUGIN_ROOT / "resources"
    agents = _json(resources / "agents.json")["agents"]
    prompts = _json(resources / "prompts.json")["agents"]
    definitions = sorted((resources / "workflows").glob("*/definition.json"))

    assert {path.parent.name for path in definitions} == EXPECTED_WORKFLOWS
    assert set(prompts) == set(agents)

    referenced_agents: set[str] = set()
    referenced_libraries: set[str] = set()
    for definition_path in definitions:
        definition = _json(definition_path)
        assert definition["workflow_id"] == definition_path.parent.name
        assert isinstance(definition['version'], int) and definition['version'] >= 1
        if definition["workflow_id"] == "mvp":
            assert not definition.get("execution_schemes")
        for node in definition.get("nodes", []):
            if node.get("node_type") == "agent":
                referenced_agents.add(node["agent_type"])
            params = node.get("node_params", {})
            if (
                node.get("node_type") == "script"
                and params.get("script_source") == "library"
            ):
                assert params["script_group"] in {"nvl", "xs2"}
                referenced_libraries.add(params["script_name"])

    # Saved task snapshots still resolve these original multi-writer agents.
    legacy_writers = {
        "novel-writer", "novel-dialogue-writer", "novel-action-writer", "novel-internal-writer",
        "novel-description-writer", "novel-transition-writer", "novel-storyboard-integrator",
        "novel-self-critic", "novel-polisher",
    }
    assert set(agents) - referenced_agents == legacy_writers
    assert referenced_agents <= set(agents)
    assert referenced_libraries == EXPECTED_SCRIPT_LIBRARIES
    # Resolve each workflow identity to its actual executable. Host-loaded
    # service libraries (voice/console support) may legitimately be unreferenced.
    library_root = resources / "script-library"
    for definition_path in definitions:
        for node in _json(definition_path).get("nodes", []):
            params = node.get("node_params", {})
            if node.get("node_type") != "script" or params.get("script_source") != "library":
                continue
            name = params["script_name"]
            entrypoint = library_root / params["script_group"] / name / (name + ".py")
            assert entrypoint.is_file(), f"Unresolved script: {definition_path}:{node['id']}: {entrypoint}"


def test_workflows_do_not_require_database_or_book_ids() -> None:
    for definition_path in (
        PLUGIN_ROOT / "resources" / "workflows"
    ).glob("*/definition.json"):
        content = definition_path.read_text(encoding="utf-8").lower()
        assert "book_id" not in content
        assert "uuid" not in content
        assert "db_sync" not in content
        assert "json_to_db" not in content


def test_polish_has_no_hidden_external_detection_dependency() -> None:
    resources = PLUGIN_ROOT / "resources"
    polish = _json(resources / "workflows" / "polish" / "definition.json")

    assert "script_ai_detect" not in {
        node["id"] for node in polish["nodes"]
    }
    assert "ai_detect" not in {
        node.get("node_params", {}).get("script_name")
        for node in polish["nodes"]
    }
    assert "ai_issues_file" not in {
        variable["key"] for variable in polish["variables"]
    }
    assert not (
        resources / "script-library" / "nvl" / "ai_detect"
    ).exists()

    public_polish_text = json.dumps(polish, ensure_ascii=False).lower()
    script_library_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (resources / "script-library").rglob("*.py")
    )
    for marker in {
        "".join(("ai_detect_", "gateway_url")),
        ".".join(("host", "docker", "internal")),
        "-".join(("humanize", "chinese")),
    }:
        assert marker not in public_polish_text
        assert marker not in script_library_text


def test_agents_inherit_core_main_model() -> None:
    resources = PLUGIN_ROOT / "resources"
    agents = _json(resources / "agents.json")["agents"]

    assert all("model" not in definition for definition in agents.values())
    for definition_path in (resources / "workflows").glob("*/definition.json"):
        definition = _json(definition_path)
        for node in definition.get("nodes", []):
            if node.get("node_type") == "agent":
                assert not node.get("model_override")


def test_workflow_agents_do_not_define_model_budgets() -> None:
    """小说工作流只选择模型与常规参数，不携带独立的模型预算。"""
    resources = PLUGIN_ROOT / "resources"
    agents = _json(resources / "agents.json")["agents"]
    forbidden = {
        "thinking_budget",
        "token_budget",
        "max_tokens",
        "max_completion_tokens",
        "output_budget",
    }

    for agent_name, definition in agents.items():
        params = definition.get("model_params", {})
        assert forbidden.isdisjoint(params), (
            f"工作流 Agent {agent_name} 不应配置模型预算字段: "
            f"{forbidden.intersection(params)}"
        )


def test_public_package_has_no_private_pipeline_markers() -> None:
    forbidden = {
        "-".join(("nov" + "el", "tear" + "down")),
        "-".join(("hind" + "sight", "mem" + "ory")),
        "".join(("field_", "rewrite")),
        "".join(("pattern_", "usage_", "receipt")),
        "".join(("tear" + "down_", "pat" + "tern")),
        "拆" + "书",
    }
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        try:
            content = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for marker in forbidden:
            assert marker not in content, f"private marker in {path}"

    resources = PLUGIN_ROOT / "resources"
    assert not (PLUGIN_ROOT / "integration").exists()
    assert (resources / "skills.json").is_file()
    assert not (resources / "rules.json").exists()
    assert not (resources / "preset-phrases.json").exists()
    assert {
        path.name
        for path in (resources / "skill-bundles").iterdir()
        if path.is_dir()
    } == EXPECTED_SKILLS


