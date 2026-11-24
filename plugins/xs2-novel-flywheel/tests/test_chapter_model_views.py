import asyncio
import json
from pathlib import Path

from test_prose_policy import load_workflow, resolve, workflow_script
from test_story_support import commit_chapter, support


def fixture_context():
    return {
        "chapter": "0080",
        "chapter_characters": [
            {"entity_id": "li", "name": "李明", "snapshot": {"location": "旧屋"}},
            {"entity_id": "companion", "name": "石七", "snapshot": {"location": "陪同他坐在屋外"}},
        ],
        "sources": [
            {"source_id": "story/0079/chapter.md", "content": "他在门外等了一夜。"},
            {"source_id": "story/0079/diff_story_confirmed.md", "content": "李明确认旧屋仍空着。"},
            {"source_id": "story/0080/chapter.md", "content": "本章正文只由本章原稿字段提供。"},
        ],
        "chapter_drafts": [],
        "world_current": {"facts": [
            {"description": "旧屋的后门从外面锁住", "source_chapter": "0015", "evidence": "后门上锁了"},
            *[{"description": f"远方账本第{i}条与本章无关" * 12, "source_chapter": "0060"}
              for i in range(400)],
        ]},
        "serial": {"enabled": True, "volume": {"title": "归乡"}, "entry": {
            "body_sha256": "FULL_SNAPSHOT_HASH", "characters": [{"name": "整份人物档案"}],
            "world": {"facts": ["第二份世界事实"]}, "indexes": {"hooks": ["第二份伏笔账本"]}}},
        "indexes_before": {"hooks": [
            {"id": "h20", "status": "open", "description": "李明在旧屋藏起铜钥匙", "source_chapter": "0020"},
            {"id": "h21", "status": "resolved", "description": "李明在旧屋已结清的误会"},
            {"id": "h99", "status": "open", "description": "作者要求保留的线索", "pinned": True},
            *[{"id": f"h{i}", "status": "open", "description": f"边境狼群线索{i}" * 9,
               "source_chapter": "0060"} for i in range(100, 500)],
            {"id": "h15", "status": "open", "description": "久未提及的天文台线索",
             "source_chapter": "0015", "expected_payoff": "第78章至第80章"},
        ], "debts": [{"id":"d001", "status":"near_payoff", "description":"和船夫约定的报酬"}]},
        "memory": {"query": "李明回到旧屋", "entities": [{"id": "li", "name": "李明"}],
                   "cognition": {"li": {"knowledge": [
                       {"id": "e20", "text": "李明知道旧屋还有备用钥匙", "source_sha256": "HASH"},
                   ], "beliefs": [{"id": "e21", "text": "李明误以为旧屋无人"}], "rumors": [],
                       "time_unverified": [{"id": "e90", "text": "更晚才获知的旧屋秘密"}]}},
                   "hits": [{"source_id": "story/0020/chapter.md", "source_sha256": "HISTORICAL_HASH",
                             "kind": "confirmed_world_fact", "chapter": "0020",
                             "evidence": "钥匙压在门砖下。"},
                            {"kind": "confirmed_world_fact", "chapter": "0015",
                             "text": "旧屋的后门从外面锁住", "evidence": "后门上锁了"}],
                   "read_set": [{"source_id": "secret/local/path", "source_sha256": "VERIFY_ONLY"}]},
    }


def test_serial_views_bound_growth_without_losing_old_relevant_hooks():
    ctx = fixture_context()
    v = support.chapter_views().render(ctx, "李明回到旧屋", "")
    assert "h20" in v["director"] and "0020" in v["director"]
    assert "h99" in v["director"] and "h99" in v["writer"]
    assert "h21" not in v["director"]
    assert all("h15" in text and "d001" in text for text in v.values())
    assert "陪同他坐在屋外" in v["writer"]
    assert "藏起铜钥匙" not in v["writer"]
    assert "李明误以为旧屋无人" in v["writer"] and "信念" in v["writer"]
    assert "更晚才获知的旧屋秘密" not in v["writer"]
    assert "钥匙压在门砖下" in v["audit"]
    assert v["audit"].count("后门上锁了") == 1
    assert "h500" in v["audit"]
    assert "本章正文只由本章原稿字段提供" not in "\n".join(v.values())
    assert all(len(text) < 15000 for text in v.values())
    for forbidden in ("secret/local/path", "VERIFY_ONLY", "FULL_SNAPSHOT_HASH", "HISTORICAL_HASH",
                      "第二份世界事实", "第二份伏笔账本", "整份人物档案"):
        assert forbidden not in "\n".join(v.values())
    assert ctx["memory"]["read_set"][0]["source_sha256"] == "VERIFY_ONLY"
    rolling = support.chapter_views().memory_view(ctx, "钥匙", "director", cite_sources=True)
    quote = next(row for row in rolling["可核对的原文依据"] if row.get("evidence") == "钥匙压在门砖下。")
    assert quote["source_id"] == "story/0020/chapter.md"
    assert "source_sha256" not in quote


def test_workflows_route_longform_context_to_each_role():
    plugin = Path(__file__).resolve().parents[1]
    nodes = {
        "mvp": {"agent_od": "story_director_context", "agent_se": "story_director_context", "agent_aw":"story_writer_context"},
        "polish": {"agent_pp": "story_audit_context"},
        "post-hoc": {"agent_obs": "story_audit_context", "agent_arb": "story_audit_context"},
        "outline": {"agent_no": "story_director_context"},
        "reader-sim": {"agent_context_reader": "story_audit_context"},
    }
    for stage, mapping in nodes.items():
        definition = json.loads((plugin / "resources/workflows" / stage / "definition.json").read_text(encoding="utf8"))
        variables = {v["key"]: v for v in definition["variables"]}
        indexed = {node["id"]: node for node in definition["nodes"]}
        for node, variable in mapping.items():
            assert variables[variable]["type"] == "file"
            assert "{{" + variable + "}}" in indexed[node]["first_message"]
        command = indexed["script_story_context"]["node_params"]["script_argv"]
        assert "--context-mode={{conflict_plan_mode}}" in command
    mvp = json.loads((plugin / "resources/workflows/mvp/definition.json").read_text(encoding="utf8"))
    writer = next(v["default"] for v in mvp["variables"] if v["key"] == "single_writer_context")
    assert "{{story_writer_context}}" in writer


def test_resolved_workflow_keeps_short_overrides_and_long_verification_local(tmp_path):
    definition = load_workflow("post-hoc")
    defaults = {item["key"]: item.get("default", "") for item in definition["variables"]}
    support.write(tmp_path, "meta/author_hooks.txt", "作者自定义伏笔文件")
    support.write(tmp_path, "story/0002/chapter.md", "阿杏拿着铜钥匙走到渡口。")
    defaults.update(chapter_number="0002", hooks_file="meta/author_hooks.txt", conflict_plan_mode="short_full")
    observer = next(node for node in definition["nodes"] if node["id"] == "agent_obs")

    short = {**defaults, **workflow_script(tmp_path, definition, defaults, "script_story_context", "short-observer")}
    short_prompt = asyncio.run(resolve(observer["first_message"], short, definition, tmp_path))
    assert short["story_audit_context"] == "cache/story-support/context.md"
    assert short["chapter_hooks_context_file"] == "meta/author_hooks.txt"
    assert "作者自定义伏笔文件" in short_prompt

    support.safe(tmp_path, "story/0002/chapter.md").unlink()
    commit_chapter(tmp_path)
    support.write(tmp_path, "story/0002/chapter.md", "阿杏拿着铜钥匙走到渡口。")
    support.write(tmp_path, "meta/serial_contract.json", {
        "schema": 1, "volumes": [{"id": "v1", "title": "渡口", "start": 1, "end": None}],
    })
    defaults["conflict_plan_mode"] = ""
    unclear = workflow_script(tmp_path, definition, defaults, "script_story_context", "unplanned-observer")
    assert unclear["story_audit_context"] == "cache/story-support/context.md"
    assert unclear["chapter_hooks_context_file"] == "meta/author_hooks.txt"
    fallback = support.read(tmp_path, unclear["story_audit_context"])
    assert "决定留下救人" in fallback
    assert "read_set" not in fallback and "body_sha256" not in fallback

    support.write(tmp_path, "outline/near_term_outline.md", "## 第2章 渡口\n赵磊带钥匙回去核对旧事。")
    long = {**defaults, **workflow_script(tmp_path, definition, defaults, "script_story_context", "long-observer")}
    long_prompt = asyncio.run(resolve(observer["first_message"], long, definition, tmp_path))
    assert long["story_audit_context"].endswith("long-observer-audit.md")
    assert long["chapter_hooks_context_file"] == "meta/author_hooks.txt"
    assert "本章相关故事资料" in long_prompt and "作者自定义伏笔文件" in long_prompt
    verification = support.load(tmp_path, "story/0002/planning_context.json")
    assert "meta/serial_contract.json" in verification["source_hashes"]
    assert "meta/author_hooks.txt" in verification["source_hashes"]
    assert long["chapter_debts_context_file"] == ""
    assert verification["source_hashes"]["meta/serial_contract.json"] not in long_prompt


def test_author_plan_and_active_character_state_survive_selection(tmp_path):
    old = "story/0001/chapter.md"
    commit_chapter(tmp_path)
    support.write(tmp_path, "planning/chapters/0002.json", {
        "chapter": "0002", "title": "留下来的人", "choice": "必须保留作者安排的决定",
        "setup": [{"source_id": old, "quote": "决定留下救人", "use": "回收旧章中留下的承诺"}],
        "source_hashes": {old: support.digest(tmp_path, old)},
    })
    result = support.prepare_context(tmp_path, "0002", task_id="protected-plan", context_mode="serial_chapter")
    for path in result["model_context_files"].values():
        role_context = support.read(tmp_path, path)
        assert "必须保留作者安排的决定" in role_context
        assert "决定留下救人：回收旧章中留下的承诺" in role_context

    ctx = fixture_context()
    state = ctx["chapter_characters"][0]["snapshot"]
    state.update(goal="保护" * 2000 + "绝不能暴露妹妹", knowledge="两人约好用红灯发信号")
    view = support.chapter_views().render(ctx, "李明回到旧屋", "")["writer"]
    assert "绝不能暴露妹妹" in view
    assert "两人约好用红灯发信号" in view


def test_unverified_flashback_keeps_previous_narration_out_of_writer_context():
    ctx = fixture_context()
    ctx["world_current"] = {"temporal_status": "unverified", "scene_time_key": 1}
    ctx["memory"]["hits"].append({
        "source_id": "story/0079/chapter.md", "kind": "prose", "text": "旧屋的谜底已经揭晓。",
    })
    views = support.chapter_views().render(ctx, "李明回忆多年前的旧屋", "")
    assert "旧屋的谜底已经揭晓" not in views["writer"]
    assert "他在门外等了一夜" not in views["writer"]
    assert "旧屋的谜底已经揭晓" in views["audit"]
