"""Novel production decisions owned by the plugin, independent of browser state."""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
import re

STAGES = ("novel-advisor", "build", "character", "story-plan", "outline", "mvp", "polish", "reader-sim", "post-hoc", "export")
PRODUCTION = ("mvp", "polish", "reader-sim", "post-hoc", "export")
ARTIFACTS = {
    "novel-advisor": "learning/advisor_report.json", "build": "meta/world_foundation.md",
    "character": "meta/character_profiles.md", "story-plan": "meta/story_plan.md",
    "outline": "outline/near_term_outline.md", "mvp": "story/{chapter}/chapter.md",
    "polish": "story/{chapter}/chapter.md", "reader-sim": "story/{chapter}/reader_report.json",
    "post-hoc": "story/{chapter}/diff_story_confirmed.md", "export": "export/manuscript.md",
}


@lru_cache(maxsize=1)
def length_quality():
    path = Path(__file__).with_name('length_quality.py')
    spec = importlib.util.spec_from_file_location(__name__ + '_length_quality', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter(state):
    value = str(state.get("values", {}).get("chapter_number", "0001")).zfill(4)
    if not re.fullmatch(r"[0-9]{4}", value) or value == "0000":
        raise ValueError("自动创作需要有效的章节号。")
    return value


def reader_report(root, state):
    number = chapter(state)
    body = Path(root) / f"story/{number}/chapter.md"
    report = Path(root) / f"story/{number}/reader_report.json"
    scoped = report.is_file()
    if not scoped:
        report = Path(root) / "quality/reader_report.json"
    if not report.is_file() or not body.is_file():
        raise ValueError("缺少本章正文或读者报告，请先完成模拟读者。")
    data = json.loads(report.read_text(encoding="utf-8"))
    bound = str(data.get("chapter_number", number if scoped else "")).zfill(4)
    if bound != number:
        raise ValueError("读者报告不属于当前章节，请重新评估。")
    expected = data.get("body_sha256")
    if (expected and expected != hashlib.sha256(body.read_bytes()).hexdigest()) or (
        not expected and body.stat().st_mtime > report.stat().st_mtime
    ):
        raise ValueError("正文在读者评估后有变化，请重新评估。")
    if data.get("verdict") not in {"pass", "revise", "reject"}:
        raise ValueError("读者报告没有有效结论，请重新评估。")
    return length_quality().gate_report(root, number, state.get('values', {}).get('target_word_count', ''), data)


def verify_completion(root, state, stage, task):
    focused = (task.get('node_states') or {}).get('script_focused_commit') or {}
    if stage == 'polish' and focused.get('status') == 'completed':
        length_quality().verify_focused_attempt(root, chapter(state), task, focused)
        return
    artifact = Path(root) / ARTIFACTS[stage].format(chapter=chapter(state))
    if not artifact.is_file() or not artifact.read_text(encoding="utf-8").strip():
        raise ValueError(f"任务结束但缺少有效产物 {artifact.relative_to(root)}，自动流程已暂停。")
    started = task.get("created_at")
    if started:
        try:
            timestamp = datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            raise ValueError("任务时间记录不完整，无法确认本次产物。")
        if artifact.stat().st_mtime + 2 < timestamp:
            raise ValueError("产物早于本次任务，请检查任务结果后再继续。")
    if stage == "reader-sim":
        reader_report(root, state)


def parameters(state, definition):
    values = dict(state.get("values", {}))
    premise = [values.get("premise", "")]
    for key, label in (("world_direction", "世界观方向（规划草稿）"),
                       ("source_idea", "用户原始设定（保留细节，矛盾处按已采用的顾问建议澄清）"),
                       ("advisor_guidance", "已采用的小说顾问建议")):
        if str(values.get(key) or "").strip():
            premise.append(f"{label}：\n{str(values[key]).strip()}")
    values["premise"] = "\n\n".join(part for part in premise if part)
    values["chapter_number"] = chapter(state)
    if state.get("mode") == "short":
        values.update(conflict_plan_mode="short_full", chapter_ending_mode="book_final")
    elif values.get("conflict_plan_mode") not in {"serial_opening", "serial_chapter", "serial_arc"}:
        values["conflict_plan_mode"] = "serial_chapter"
    if any(variable["key"] == "polish_pass" for variable in definition.get("variables", [])):
        receipt = state.get('lengthRepairFeedback') or {}
        values['polish_pass'] = ('length_only' if isinstance(receipt, dict)
            and receipt.get('path') == str(values.get('author_feedback_file') or '').strip()
            and receipt.get('chapter_number') == chapter(state) and receipt.get('path') else 'content')
    result = {}
    for variable in definition.get("variables", []):
        key = variable["key"]
        if variable.get("source_type") == "output" or (variable.get("type") == "file" and key != "author_feedback_file"):
            continue
        # The workflow's optional feedback path is a conventional location,
        # not an author-approved repair plan for this chapter.
        value = values.get(key, "" if key == "author_feedback_file" else variable.get("default", ""))
        if variable.get("required") and not variable.get("hidden") and variable.get("type") != "file" and not str(value or "").strip():
            raise ValueError(f"请先填写{variable.get('name') or key}。")
        if value is not None:
            result[key] = str(value)
    return result


def launch_check(root, state, stage, support=None):
    if stage not in STAGES or stage == "novel-advisor":
        raise ValueError("请先在小说顾问中确认方向，再启用正文自动创作。")
    if stage == "mvp":
        body = Path(root) / f"story/{chapter(state)}/chapter.md"
        if body.is_file() and body.read_text(encoding="utf-8").strip():
            raise ValueError("本章已有正文，自动创作不会覆盖；请从章节目录选择返修或重新生成。")
        if support is None:
            raise ValueError("故事连续性检查服务不可用，自动创作已暂停。")
        check = support.preflight(root, chapter(state))
        if not check.get("ready"):
            raise ValueError(check.get("message") or "请先完成本章规划与前文审核。")
    if stage in {"post-hoc", "export"} and reader_report(root, state)["verdict"] != "pass":
        raise ValueError("本章读者评估尚未通过，不能自动审核或导出。")


def _length_cycle(state):
    cycle = max(0, int(state.get('readerRepairCount') or 0))
    prior_count = max(0, int(state.get('lengthRepairCount') or 0))
    total = max(prior_count, int(state.get('lengthRepairTotal') or 0))
    tracked = state.get('lengthRepairCycle')
    # Old states used one chapter-wide count. Preserve it in the total while
    # giving an already-started content revision its first tracked budget.
    same = (int(tracked) == cycle) if tracked is not None else cycle == 0
    focused_migration = ((cycle > 0 or state.get('lengthRepairStrategy') in {'fragment-v3', 'fragment-v4', 'fragment-v5'})
                         and state.get('lengthRepairStrategy') != length_quality().LENGTH_REPAIR_STRATEGY)
    # An explicit book-only writer selection is a new execution profile. Track
    # it durably so it receives one bounded budget without erasing history.
    writer_changed = (state.get('writerModel') or '') != (state.get('lengthRepairModel') or '')
    return cycle, prior_count if same and not focused_migration and not writer_changed else 0, total


def next_action(root, state, stage):
    if stage == 'polish':
        result = length_quality().assess(root, chapter(state), state.get('values', {}).get('target_word_count', ''))
        cycle, count, total = _length_cycle(state)
        progress = {'lengthRepairCycle': cycle, 'lengthRepairCount': count, 'lengthRepairTotal': total,
                    'lengthRepairStrategy': length_quality().LENGTH_REPAIR_STRATEGY}
        if state.get('lengthRepairStrategy') == 'fragment-v5' and length_quality().LENGTH_REPAIR_STRATEGY == 'fragment-v6':
            progress['lengthRepairMigration'] = {'from': 'fragment-v5', 'to': 'fragment-v6', 'cycle': cycle,
                                               'total_before': total, 'reason': '按真实缺口冻结连续多段源窗口，替代单句过量扩写契约'}
        if state.get('writerModel') or 'lengthRepairModel' in state:
            progress['lengthRepairModel'] = state.get('writerModel') or ''
        if result['status'] in {'short', 'long'}:
            limit = max(1, min(3, int(state.get('autoLengthRepairLimit') or 2)))
            if count >= limit:
                return {'action': 'pause', 'reason': f"字数自动校正已达上限，实测{result['actual']}实字，目标{result['lower']}—{result['upper']}；未放行审核和导出。",
                        'updates': {**progress, 'lengthCheck': result}}
            feedback = length_quality().correction_feedback(root, {**state, 'lengthRepairCount': count}, result)
            return {'action': 'advance', 'stage': 'polish', 'reset': list(PRODUCTION[1:]),
                    'updates': {**progress, 'lengthRepairCount': count + 1, 'lengthRepairTotal': total + 1, 'lengthCheck': result,
                                'lengthRepairFeedback': feedback,
                                'values': {**state.get('values', {}), 'author_feedback_file': feedback['path']}}}
        length_quality().prepare_guidance(root, chapter(state), state.get('values', {}).get('target_word_count', ''))
        source = length_quality().original_feedback(root, state)
        return {'action': 'advance', 'stage': 'reader-sim', 'updates': {**progress, 'lengthCheck': result,
                'lengthRepairFeedback': {}, 'values': {**state.get('values', {}), 'author_feedback_file': source}}}
    if stage == "reader-sim":
        report = reader_report(root, state)
        if state.get("assessmentOnly"):
            return {"action": "finish", "reason": "本章读者评估已完成。", "updates": {"assessmentOnly": False}}
        if state.get("repairReviewOnly") and report["verdict"] != "pass":
            return {"action": "pause", "reason": "本次返修复评尚未通过，请查看报告后决定后续操作。", "updates": {"repairReviewOnly": False}}
        if report["verdict"] != "pass":
            limit = max(1, min(5, int(state.get("autoRepairLimit") or 2)))
            if int(state.get("readerRepairCount") or 0) >= limit:
                return {"action": "pause", "reason": "已达到本章自动返修次数上限，请查看正文与读者报告。"}
            return {"action": "repair"}
    if stage == "post-hoc" and state.get("repairReviewOnly"):
        return {"action": "finish", "reason": "返修复评通过，故事档案已同步。", "updates": {"repairReviewOnly": False}}
    if stage == "export":
        started = int(state.get("autoChapterStarted") or 1)
        limit = max(1, int(state.get("autoChapterLimit") or 1))
        if (state.get("mode") == "serial" and state.get("autoScope") == "serial_batch" and started < limit
                and state.get("values", {}).get("chapter_ending_mode") != "book_final"):
            next_number = int(chapter(state)) + 1
            if next_number > 9999:
                return {"action": "pause", "reason": "已达到支持的章节号上限。"}
            number = f"{next_number:04d}"
            if (Path(root) / f"story/{number}/chapter.md").exists():
                return {"action": "pause", "reason": f"第 {number} 章已存在，自动创作不会覆盖。"}
            values = {**state.get("values", {}), "chapter_number": number, "prev_chapter": chapter(state),
                      "latest_chapter": chapter(state), "chapter_ending_mode": "continue", "author_feedback_file": "",
                      "human_intent": "", "world_intent": ""}
            return {"action": "advance", "stage": "mvp", "reset": list(PRODUCTION),
                    "updates": {"values": values, "autoChapterStarted": started + 1, "readerRepairCount": 0,
                                "lengthRepairCount": 0, "lengthRepairTotal": 0, "lengthRepairCycle": 0, "lengthRepairStrategy": length_quality().LENGTH_REPAIR_STRATEGY,
                                "lengthCheck": {}, "lengthRepairFeedback": {}}}
        return {"action": "finish", "reason": "本次指定范围已完成并导出。"}
    if stage not in STAGES:
        return {"action": "pause", "reason": "当前步骤不属于自动创作流程。"}
    return {"action": "advance", "stage": STAGES[STAGES.index(stage) + 1]}


def repair_request(state):
    return {"question": "请依据本章正文与完整读者报告制定可执行的返修方案，逐项解决问题，保留既定事实和作者要求。",
            "purpose": "reader_repair", "chapter": chapter(state), "scope": "chapter", "stage": "reader-sim",
            "project": state, "_model_override": state.get("repairModel") or None}


def repair_ready(state, feedback_path):
    cycle = int(state.get("readerRepairCount") or 0) + 1
    _, _, total = _length_cycle(state)
    return {"action": "advance", "stage": "polish", "reset": ["polish", "reader-sim", "post-hoc", "export"],
            "updates": {"values": {**state.get("values", {}), "author_feedback_file": feedback_path},
                        "readerRepairCount": cycle, "lengthRepairCount": 0,
                        "lengthRepairCycle": cycle, "lengthRepairTotal": total, "lengthRepairStrategy": length_quality().LENGTH_REPAIR_STRATEGY,
                        "autoRepairPlanId": "", "lengthRepairFeedback": {}}}


def model_overrides(state, definition, stage):
    eligible = [node for node in definition.get("nodes", [])
                if node.get("node_type", "agent") == "agent" and node["id"] != "agent_fragment_review"
                and not ((node.get("var_bindings") or {}).get("model_override") or {}).get("var_key")
                and "{{" not in node.get("agent_type", "") and "{{" not in (node.get("model_override") or "")]
    selected = {}
    writer = state.get('writerModel')
    body_nodes = {'mvp': {'agent_sw', 'agent_nw', 'agent_dw', 'agent_aw', 'agent_tw', 'agent_iw', 'agent_dsw'},
                  'polish': {'agent_pl', 'agent_pp'}}
    if writer and stage in body_nodes:
        selected.update({node['id']: writer for node in eligible if node['id'] in body_nodes[stage]})
    model = state.get("repairModel")
    if model and stage in {"polish", "reader-sim"} and (state.get("repairReviewOnly") or state.get("readerRepairCount")):
        selected.update({node['id']: model for node in eligible})
    return selected or None


def model_params_overrides(state, definition, stage):
    """Book-only parameters follow the explicitly selected body writer model."""
    from copy import deepcopy
    params = state.get('writerModelParams')
    if params is None:
        return None
    if not isinstance(params, dict):
        raise ValueError('writerModelParams 必须是参数对象')
    writer = state.get('writerModel')
    if not params or not writer:
        return None
    body_nodes = {'mvp': {'agent_sw', 'agent_nw', 'agent_dw', 'agent_aw', 'agent_tw', 'agent_iw', 'agent_dsw'},
                  'polish': {'agent_pl', 'agent_pp'}}
    selected = model_overrides(state, definition, stage) or {}
    result = {node_id: deepcopy(params) for node_id in body_nodes.get(stage, set())
              if selected.get(node_id) == writer}
    return result or None
