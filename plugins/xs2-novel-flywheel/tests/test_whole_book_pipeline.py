import argparse
import json
import re
from pathlib import Path

import pytest

from test_reference_distill import _load_module, PLUGIN_ROOT


def split(ref, mode="auto", source="references/source.txt"):
    ref.split(argparse.Namespace(input=source, window=800, overlap=40, source_mode=mode,
                                learning_direction="custom", learning_focus="只看结尾"))


def write_source(root, text, name="source.txt"):
    path = root / "references" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")


def accepted(ref, entry):
    key = entry["window_id"]
    location = f"learning/cache/{key}.raw.json"
    ref.save(location, {"window_id": key, "source_sha256": entry["source_sha256"], "candidates": []})
    ref.validate_window(argparse.Namespace(window_id=key, input=location))


def pending(output):
    return json.loads(re.search(r"<WF_VAR>window_ids:(.*?)</WF_VAR>", output)[1])


def test_automatic_complete_book_runs_both_model_passes_and_recovers_exact_windows(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    text = "===== SOURCE FILE: 全文.txt =====\n" + "".join(
        f"第{n}章 行程\n卷宗记录了第{n}个地点。\n" for n in range(1, 103)) + "全书完"
    write_source(tmp_path, text)
    split(ref)
    assert len(pending(capsys.readouterr().out)) == 102
    data, raw = ref.manifest()
    assert data["source_mode"] == "serial_full"
    assert data["source_coverage"]["completeness_basis"] == "end_marker"
    assert ref.load("learning/dna/metadata.json")["learning_focus"] == ""
    for entry in data["windows"]:
        packet = ref.read_packet(entry)
        assert raw[entry["source_start"]:entry["source_end"]] == packet["text"]
        assert not packet["dialogue_context"]["after"] and not packet["dialogue_context"]["before"]
    accepted(ref, data["windows"][0])
    assert ref.load(ref.PROGRESS)["source_coverage"]["analyzed_chapters"] == ["chapter-0001"]
    split(ref)
    assert len(pending(capsys.readouterr().out)) == 101
    assert ref.load(ref.MANIFEST)["run_id"] == data["run_id"]
    # A corrupted receipt payload must return to the queue.
    ref.save("learning/cache/window-0001.validated.json", {})
    split(ref)
    assert len(pending(capsys.readouterr().out)) == 102
    with pytest.raises(ValueError, match="窗口"):
        ref.merge(None)
    for entry in data["windows"]:
        accepted(ref, entry)
    ref.merge(None)
    result = ref.load(ref.CANDIDATES)
    scope = result["source_coverage"]
    assert scope["complete"] and len(scope["analyzed_chapters"]) == 102 and scope["missing_chapters"] == []
    assert ref.load("learning/cache/progress.json")["batches"]["batch-0004"] == {"total": 6, "validated": 6}
    assert ref.load("learning/dna/bundle.json")["source_coverage"] == scope

    import cross_chapter as cross
    cross.prepare()
    for batch in cross.load(cross.PLAN)["batches"]:
        prefix = f"{cross.ROOT}/{batch}"
        packet = cross.load(prefix + ".packet.json")
        observations = []
        for chapter in packet["chapters"]:
            if chapter["chapter_id"] in packet["focus_chapter_ids"]:
                p = chapter["passages"][0]
                observations.append({"chapter_id": chapter["chapter_id"], "observations": [
                    {"dimension": "plot", "statement": "行动改变所在地点", "evidence": [
                        {"passage_id": p["passage_id"], "excerpt": p["text"]}]}]})
        reply = {key: packet[key] for key in ("batch_id", "source_sha256", "packet_sha256")}
        cross.save(prefix + ".reply.json", {**reply, "chapter_observations": observations, "findings": []})
        cross.validate(batch)
    cross.finalize()
    docs = {name: "记录本次可观察的行动压力和叙事选择。"*4 for name in ref.writing_dna.DOCUMENTS}
    ref.save("model.json", {"source_sha256": ref.digest(raw), "documents": docs})
    ref.writing_dna.finalize(argparse.Namespace(input="model.json"), ref.load, ref.save, ref.digest)
    profile = ref.load("learning/dna/profile.json")
    assert profile["source_coverage"] == scope
    assert profile["cross_chapter_analysis"]["coverage"]["reviewed_chapter_count"] == 102
    assert not Path(ref.ACTIVE).exists()


def test_auto_never_promotes_chapter_samples_or_known_gaps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    for ending, second in [("", 2), ("全文完", 3)]:
        write_source(tmp_path, f"第一章 回家\n她回去了。\n第{second}章 归途\n她启程了。\n{ending}")
        split(ref)
        assert ref.load(ref.MANIFEST)["source_mode"] == "serial_chapters"
    with pytest.raises(ValueError, match="第 2～2 章"):
        split(ref, "serial_full")
    text = "第一章 开端\n甲。\n第二章 结束\n乙。\n（全文完）"
    write_source(tmp_path, text, "url-imported-corpus.txt")
    ref.save("references/url-import.json", {"source_mode": "serial_chapters", "catalog_complete": False,
                                            "corpus_sha256": ref.digest(text)})
    split(ref, source="references/url-imported-corpus.txt")
    assert ref.load(ref.MANIFEST)["source_mode"] == "serial_chapters"
    with pytest.raises(ValueError, match="章节样本"):
        split(ref, "serial_full", "references/url-imported-corpus.txt")


def test_long_chapter_is_complete_only_after_its_last_window(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    raw = "第一章 早班\n" + "车窗外的灯逐渐熄灭。" * 240 + "\n第二章 归途\n她走下了最后一级台阶。"
    write_source(tmp_path, raw)
    split(ref, "serial_full")
    data, _ = ref.manifest()
    first = [ref.read_packet(w) for w in data["windows"] if w["chapter_id"] == "chapter-0001"]
    assert len(first) >= 3
    assert first[0]["source_start"] == 0 and first[-1]["source_end"] == raw.index("第二章")
    for left, right in zip(first, first[1:]):
        assert left["source_end"] - right["source_start"] == 40
    for packet in first[:-1]:
        accepted(ref, packet)
    assert ref.load(ref.PROGRESS)["source_coverage"]["analyzed_chapters"] == []
    accepted(ref, first[-1])
    scope = ref.load(ref.PROGRESS)["source_coverage"]
    assert scope["analyzed_chapters"] == ["chapter-0001"] and scope["missing_chapters"] == ["chapter-0002"]


def test_native_workflow_schedules_both_agent_passes():
    from src.workflow.definition import WorkflowDef
    data = json.loads((PLUGIN_ROOT / "resources/workflows/reference-distillation/definition.json").read_text(encoding="utf-8"))
    wf = WorkflowDef.from_dict(data)
    assert not wf.validate()
    loops = [step["loop_body_nodes"] for step in wf.get_execution_plan() if step["type"] == "loop_gateway"]
    assert set(loops[0]) == {"agent_distill_window", "agent_distill_batch", "script_validate_window"}
    assert loops[1] == ["agent_cross_chapter", "script_cross_validate"]
    assert all(gateway["max_list_iterations"] >= 102 for gateway in data["gateways"]
               if gateway["gateway_type"] == "loop")


def test_model_inputs_do_not_grow_with_the_full_chapter_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    sizes = []
    for count in (100, 1000):
        raw = "".join(f"第{n}章 归来\n车停了。\n" for n in range(1, count + 1))
        source = {"text_sha256": ref.digest(raw), "characters": len(raw)}
        mode, chapters = ref.source_units(raw, "serial_full")
        ref.writing_dna.prepare(raw, source, mode, ref.save, units_info=(mode, chapters))
        ids = [c["id"] for c in chapters]
        scope = {"chapters": chapters, "analyzed_chapters": ids, "missing_chapters": [], "complete": True,
                 "completeness_basis": "user_declared"}
        data = {"covered_window_ids": [f"window-{n:04d}" for n in range(count)], "source_coverage": scope}
        ref.writing_dna.bundle(data, [], [], [], ref.load, ref.save)
        sizes.append([Path(f"learning/dna/{name}.json").stat().st_size for name in ("window-metadata", "summary-input")])
        assert len(ref.load("learning/dna/bundle.json")["source_coverage"]["chapters"]) == count
    assert all(abs(large - small) < 300 for small, large in zip(*sizes))
