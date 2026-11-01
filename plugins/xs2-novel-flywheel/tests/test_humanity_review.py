from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "resources/script-library/nvl/polish_post/polish_post.py"
SPEC = importlib.util.spec_from_file_location("humanity_polish_post", SCRIPT)
assert SPEC and SPEC.loader
polish_post = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(polish_post)

CHAPTER = """## 二
我把工作记录逐项核对，依次写下文件编号、版本和收件日期。
她问我明天还来不来。我说等核完再说，把同一张清单重新抄了一遍。

## 六
退款到账后，我又核一遍金额，又核一遍账户，没有回答她关于搬走的话。
"""


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )


def test_minor_surface_notes_cannot_make_a_chapter_fail_humanity() -> None:
    original = {
        "feels_human": False,
        "issues": [{"dimension": "EXPOSITORY_SYNTAX", "severity": "low", "description": "用了依次。"}],
    }
    snapshot = copy.deepcopy(original)

    review = polish_post.normalize_critique(original, CHAPTER)

    assert review["feels_human"] is True
    assert review["review_status"] == "pass_with_notes"
    assert review["blocking_issues"] == []
    assert review["issues"][0]["description"] == "用了依次。"
    assert original == snapshot


@pytest.mark.parametrize("assessment", [None, "主要场景只写手续，人物的选择和情绪没有落地。"])
def test_negative_empty_review_remains_an_unsupported_assessment(assessment: str | None) -> None:
    original = {"feels_human": False, "issues": []}
    if assessment is not None:
        original["scene_assessment"] = assessment

    review = polish_post.normalize_critique(original, CHAPTER)

    assert review["feels_human"] is False
    assert review["review_status"] == "needs_review"
    assert review["blocking_issues"] == []
    assert review["issues"] == []
    assert review["review_warnings"]
    if assessment is not None:
        assert review["scene_assessment"] == assessment


def test_negative_scene_assessment_is_not_erased_by_only_low_notes() -> None:
    assessment = "第二节和第六节以核对流程替代人物对关系选择的回应。"
    issue = {"dimension": "LOCAL_EXPRESSION", "severity": "low", "description": "这处重复用词可精简。"}

    review = polish_post.normalize_critique(
        {"feels_human": False, "scene_assessment": assessment, "issues": [issue]}, CHAPTER
    )

    assert review["feels_human"] is False
    assert review["review_status"] == "needs_review"
    assert review["blocking_issues"] == []
    assert review["scene_assessment"] == assessment
    assert review["issues"][0]["severity"] == "low"
    assert review["review_warnings"]


def test_positive_review_without_issues_remains_a_clean_pass() -> None:
    review = polish_post.normalize_critique(
        {"feels_human": True, "scene_assessment": "人物的处境、选择与后果已经成立。", "issues": []},
        CHAPTER,
    )

    assert review["feels_human"] is True
    assert review["review_status"] == "pass"
    assert review["blocking_issues"] == []
    assert review["review_warnings"] == []


def test_scene_issue_keeps_grounded_evidence_and_material_impact_for_editors() -> None:
    quote = "她问我明天还来不来。我说等核完再说，把同一张清单重新抄了一遍。"
    review = polish_post.normalize_critique(
        {
            "feels_human": True,
            "issues": [{
                "dimension": "PROCEDURE_REPLACES_SCENE",
                "severity": "major",
                "scope": "scene",
                "location": "第二节",
                "description": "人物面临关系选择，正文却用重复核对越过回答。",
                "evidence": [quote],
                "impact": "对方的追问没有改变主角的行动或关系，清单重复占据关键回应。",
                "repair": "保留必要核验，合并重复清单，在已有追问中写出拒答的代价。",
            }],
        },
        CHAPTER,
    )

    assert review["review_status"] == "revise"
    assert review["feels_human"] is False
    assert review["blocking_issues"] == [0]
    assert review["issues"][0]["severity"] == "high"
    assert review["issues"][0]["evidence_status"] == "verified"
    assert review["issues"][0]["evidence"] == [quote]
    assert "合并重复清单" in review["issues"][0]["repair"]


@pytest.mark.parametrize("missing", ["quote", "impact"])
def test_unsupported_major_issue_remains_visible_and_unverified(missing: str) -> None:
    issue = {
        "dimension": "UNMOTIVATED_CHOICE",
        "severity": "high",
        "description": "主角突然同意搬走，需要作者核查。",
        "evidence": ["她突然答应搬走。" if missing == "quote" else "她问我明天还来不来。"],
        "impact": "" if missing == "impact" else "缺少从拒绝到同意的经历。",
        "repair": "核实场景中的选择是否发生，勿凭报告新增搬走情节。",
    }
    review = polish_post.normalize_critique({"feels_human": False, "issues": [issue]}, CHAPTER)

    assert review["review_status"] == "needs_review"
    assert review["feels_human"] is False
    assert review["blocking_issues"] == []
    assert review["issues"][0]["severity"] == "high"
    assert review["issues"][0]["description"] == issue["description"]
    assert review["issues"][0]["evidence"] == issue["evidence"]
    assert review["issues"][0]["evidence_status"] == "unverified"
    assert review["review_warnings"]


def test_legacy_or_unknown_major_review_is_not_silently_converted_to_clean() -> None:
    review = polish_post.normalize_critique(
        {"feels_human": False, "issues": [
            {"dimension": "CONVERSATION_REALITY", "severity": "high", "description": "所有人像工具。"},
            {"dimension": "VOICE", "severity": "urgent", "description": "声线需要核查。"},
        ]},
        CHAPTER,
    )

    assert review["review_status"] == "needs_review"
    assert review["feels_human"] is False
    assert review["blocking_issues"] == []
    assert review["issues"][0]["description"] == "所有人像工具。"
    assert review["issues"][1]["severity"] == "urgent"
    assert len(review["review_warnings"]) >= 2


def test_normalize_cli_updates_only_review_and_preserves_scene_advice(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text(CHAPTER, encoding="utf-8")
    critique = tmp_path / "critique.json"
    critique.write_text(json.dumps({"feels_human": False, "issues": [{
        "dimension": "PROCEDURE_REPLACES_SCENE", "severity": "moderate",
        "description": "反复核对挤掉人物回应。", "location": "第六节",
        "evidence": ["退款到账后，我又核一遍金额，又核一遍账户，没有回答她关于搬走的话。"],
        "impact": "退款的后果和关系回应被重复操作遮住。", "repair": "合并核对，保留原有人物追问。",
    }]}), encoding="utf-8")

    result = _run("--normalize-critique", str(critique), "--source-chapter", str(chapter), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    review = json.loads(critique.read_text(encoding="utf-8"))
    assert review["blocking_issues"] == [0]
    assert review["issues"][0]["severity"] == "medium"
    assert review["issues"][0]["repair"] == "合并核对，保留原有人物追问。"
    assert chapter.read_text(encoding="utf-8") == CHAPTER


def test_invalid_review_cli_fails_without_overwriting_review_or_chapter(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text(CHAPTER, encoding="utf-8")
    critique = tmp_path / "critique.json"
    bad_json = '{"feels_human":false,"issues":"not an array"}'
    critique.write_text(bad_json, encoding="utf-8")

    result = _run("--normalize-critique", str(critique), "--source-chapter", str(chapter), cwd=tmp_path)

    assert result.returncode != 0
    assert critique.read_text(encoding="utf-8") == bad_json
    assert chapter.read_text(encoding="utf-8") == CHAPTER


@pytest.mark.parametrize("body", [None, "", "  ", [], {"paragraph": "计划"}])
def test_polish_converter_rejects_missing_or_nontext_body_before_overwrite(tmp_path: Path, body: object) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text(CHAPTER, encoding="utf-8")
    source = tmp_path / "body.json"
    source.write_text(json.dumps({"body": body}), encoding="utf-8")

    result = _run("--body-json", str(source), "--output", str(chapter), cwd=tmp_path)

    assert result.returncode != 0
    assert chapter.read_text(encoding="utf-8") == CHAPTER


def test_polish_converter_preserves_full_body_and_quotes(tmp_path: Path) -> None:
    body = '# 第一章\n\n“我先看一眼。”她说。\n\n玻璃映着招牌。'
    source = tmp_path / "body.json"
    source.write_text(json.dumps({"body": body}, ensure_ascii=False), encoding="utf-8")
    chapter = tmp_path / "story/chapter.md"

    result = _run("--body-json", str(source), "--output", str(chapter), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert chapter.read_text(encoding="utf-8") == body
