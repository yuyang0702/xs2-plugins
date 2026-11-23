import json
import importlib.util
from contextlib import nullcontext

import pytest

from test_book_contract import PLUGIN


@pytest.mark.parametrize("name, upstream, downstream", [
    ("mvp", "script_guard_finish", "script_si_post"),
    ("polish", "script_continuity_stage", "gw_zhuque_whole_text"),
    ("polish", "script_focused_commit", "script_sync_polish"),
])
def test_default_manuscript_path_includes_continuity_gate(name, upstream, downstream):
    path = PLUGIN / "resources/workflows" / name / "definition.json"
    definition = json.loads(path.read_text(encoding="utf8"))
    edges = {(e["source"], e["target"]) for e in definition["edges"]}
    assert (upstream, downstream) not in edges
    assert any(a == upstream and b.startswith("script_continuity_") for a, b in edges)
    assert any(a in ("script_continuity_finish", "gw_continuity_publication", "script_continuity_focused_ready")
               and b == downstream for a, b in edges)
    assert ("gw_continuity_repair", "script_continuity_skip_repair") in edges
    assert ("script_continuity_skip_repair", "script_continuity_finish") in edges
    assert ("agent_continuity_verify", "script_continuity_finish") in edges


@pytest.fixture
def gate(monkeypatch):
    source = PLUGIN / "resources/script-library/xs2/manuscript_continuity/manuscript_continuity.py"
    spec = importlib.util.spec_from_file_location("test_continuity_gate", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.guard, "publication", lambda _: nullcontext())
    return module


@pytest.mark.parametrize("setup, contradiction, correction", [
    ("祁言答应只在满月开门。", "新月当晚，祁言照约打开了门。", "满月当晚，祁言照约打开了门。"),
    ("应急广播切电就停。", "切电后，应急广播依旧通电。", "切电后，应急广播停了。"),
    ("我答应他病好之前不退房。", "他还在住院，我照约退了房。", "他出了院，我才提起退房。"),
])
def test_read_repair_read_requires_bound_exact_evidence_and_preserves_other_paragraphs(
    gate, tmp_path, setup, contradiction, correction
):
    before = f"{setup}\r\n\r\n有人把钥匙留在窗边。\r\n\r\n{contradiction}\r\n"
    path = tmp_path / "cache/si/chapter.json"
    gate.save(path, {"body": before})
    folder = gate.task_folder(tmp_path, "task-test")
    first = gate.prepare(tmp_path, folder, "draft", "0001", "")
    assert setup in (tmp_path / first["continuity_review_input"]).read_text(encoding="utf8")
    binding = gate.read(folder / "binding.json")
    digest = gate.sha(before)
    issue = {"category": "rules", "problem": "和此前约定相冲突", "target": "p0003",
             "evidence": [{"id": "p0001", "quote": setup}, {"id": "p0003", "quote": contradiction}]}
    with pytest.raises(ValueError, match="证据与正文不符"):
        gate.select(tmp_path, folder, binding, before,
                    {"sha256": digest, "redundancy_checked": True, "pair_checks": dict.fromkeys(gate.repeat_pairs(before), "distinct"), "issues": [issue | {
                        "evidence": [issue["evidence"][0], {"id": "p0003", "quote": "不存在"}]}]})
    result = gate.select(tmp_path, folder, binding, before, {"sha256": digest, "redundancy_checked": True, "pair_checks": dict.fromkeys(gate.repeat_pairs(before), "distinct"), "issues": [issue]})
    assert result["continuity_needs_repair"] == "yes"
    with pytest.raises(ValueError, match="只"):
        gate.candidate(tmp_path, folder, binding, before,
                       {"sha256": digest, "edits": [{"id": "p0002", "text": correction}]})
    verify = gate.candidate(tmp_path, folder, binding, before,
                            {"sha256": digest, "edits": [{"id": "p0003", "text": correction}]})
    updated = before.replace(contradiction, correction)
    text = (tmp_path / verify["continuity_verify_input"]).read_text(encoding="utf8")
    assert all(item in text for item in (setup, correction, "有人把钥匙留在窗边。"))
    with pytest.raises(ValueError, match="未绑定当前合稿"):
        gate.finish(tmp_path, folder, binding, before, {"sha256": digest, "redundancy_checked": True, "pair_checks": dict.fromkeys(gate.repeat_pairs(before), "distinct"), "issues": []}, "task-test", "")
    assert gate.read(path)["body"] == before
    args = (tmp_path, folder, binding, before, {"sha256": gate.sha(updated), "redundancy_checked": True, "pair_checks": dict.fromkeys(gate.repeat_pairs(updated), "distinct"), "issues": []}, "task-test", "")
    gate.finish(*args)
    gate.finish(*args)  # Resume a completed publication without rewriting or losing the proof.
    assert gate.read(path)["body"] == updated


def test_clean_polish_keeps_exact_manuscript_and_binds_whole_text_input(gate, tmp_path):
    body = "那封信还没有拆开。\n\n他笑了一下，又笑了一下。\n"
    staged = "cache/polish/staged.json"
    path = tmp_path / staged
    gate.save(path, {"body": body, "source_sha256": gate.sha(body), "enabled": False})
    folder = gate.task_folder(tmp_path, "task-polish")
    gate.prepare(tmp_path, folder, "polish", "0001", staged)
    binding = gate.read(folder / "binding.json")
    assert gate.select(tmp_path, folder, binding, body, {"sha256": gate.sha(body), "redundancy_checked": True, "issues": []}) == {
        "continuity_needs_repair": "no"
    }
    out = gate.finish(tmp_path, folder, binding, body, None, "task-polish", "")
    assert gate.adopt_staged(tmp_path, out["continuity_receipt"], "task-polish", gate.sha(body)) == body
    gate.save(path, {"body": "后来被另外一项任务修改。", "source_sha256": gate.sha(body)})
    with pytest.raises(ValueError, match="未绑定当前"):
        gate.adopt_staged(tmp_path, out["continuity_receipt"], "task-polish", gate.sha(body))


@pytest.mark.parametrize("mode", ["draft", "polish", "focused"])
def test_event_retelling_keeps_revised_sentence_and_drops_only_old_evidence(gate, tmp_path, mode):
    retained = "分手第二天收到照片时，我差点约他见面。"
    old = "分手后的第二天，他把那张照片发给了我。"
    before = retained + "\r\n\r\n" + old + "\r\n\r\n我关了灯。\r\n"
    chapter = tmp_path / "story/0001/chapter.md"
    staged = "cache/staged.json"
    prior = old + "\r\n\r\n我关了灯。\r\n"
    if mode == "polish":
        gate.save(tmp_path / staged, {"body": before, "original_body": prior})
    elif mode == "draft":
        gate.save(tmp_path / "cache/si/chapter.json", {"body": before})
        gate.save(tmp_path / "cache/draft-guard/test/expression-input.json", {"source_body": prior})
    else:
        chapter.parent.mkdir(parents=True)
        chapter.write_bytes(before.encode())
        gate.save(tmp_path / "quality/length/0001-last-attempt.json",
                  {"body_sha256": gate.sha(before), "revised_span_range": [0, len(retained.encode())]})
    folder = gate.task_folder(tmp_path, "test")
    gate.prepare(tmp_path, folder, mode, "0001", staged)
    binding = gate.read(folder / "binding.json")
    with pytest.raises(ValueError, match="缺少本轮语义删重"):
        gate.select(tmp_path, folder, binding, before, {"sha256": gate.sha(before), "issues": []})
    assert gate.repeat_pairs(before) == ["p0001/p0002"]
    with pytest.raises(ValueError, match="逐对核对"):
        gate.select(tmp_path, folder, binding, before,
                    {"sha256": gate.sha(before), "redundancy_checked": True, "issues": []})
    drop, keep = {"id": "p0002", "quote": old}, {"id": "p0001", "quote": retained}
    issue = {"category": "redundancy", "target": "p0002", "problem": "收到的是同一张照片",
             "evidence": [drop, keep]}
    report = {"sha256": gate.sha(before), "redundancy_checked": True, "pair_checks": dict.fromkeys(gate.repeat_pairs(before), "redundant"), "issues": [issue]}
    with pytest.raises(ValueError, match="保留本轮"):
        gate.select(tmp_path, folder, binding, before, dict(report, issues=[
            dict(issue, target="p0001", evidence=[keep, drop])]))
    gate.select(tmp_path, folder, binding, before, report)
    def proposal(text):
        return {"sha256": gate.sha(before), "edits": [{"id": "p0002", "text": text}]}
    with pytest.raises(ValueError, match="只删除"):
        gate.candidate(tmp_path, folder, binding, before, proposal("次日我收到了那张相片。"))
    gate.candidate(tmp_path, folder, binding, before, proposal(""))
    after = retained + "\r\n\r\n我关了灯。\r\n"
    gate.finish(tmp_path, folder, binding, before, {"sha256": gate.sha(after), "redundancy_checked": True, "issues": []}, "test", "")
    assert gate.manuscript(tmp_path, mode, "0001", staged)[1] == after


def test_same_paragraph_retelling_keeps_unique_action_and_deliberate_echo(gate):
    body = "分手第二天收到了旧照。电话断了。我点开照片。分手次日收到照片时，我差点约他见面。"
    issue = {"category": "redundancy", "target": "p0001",
             "evidence": [{"id": "p0001", "quote": "分手第二天收到了旧照。"},
                          {"id": "p0001", "quote": "分手次日收到照片时"}]}
    after = body.split("。", 1)[1]
    assert gate.edited(body, [issue], {"sha256": gate.sha(body),
                       "edits": [{"id": "p0001", "text": after}]}) == after
    echo = "陈导来电邀她参加巡演。\n\n周屿拨给陈导，承认是他擅自替她拒绝。"
    assert gate.edited(echo, [], {"sha256": gate.sha(echo), "edits": []}) == echo
