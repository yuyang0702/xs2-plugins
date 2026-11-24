import argparse
import copy
import json

from test_reference_distill import _load_module, PLUGIN_ROOT


def test_batch_split_limits_and_chapter_coverage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    text = "".join(f"第{n}章 行程\n主角带着第{n}份卷宗去补齐线索。\n" for n in range(1, 13))
    ref.save("references/source.txt", text)
    args = argparse.Namespace(input="references/source.txt", window=800, overlap=40,
                              source_mode="serial_full", batch_max_chapters=10, batch_max_chars=40000)
    ref.split(args)
    manifest, raw = ref.manifest()
    assert [len(entry["chapter_ids"]) for entry in manifest["windows"]] == [10, 2]
    entry = manifest["windows"][0]
    packet = ref.read_packet(entry)
    segments = packet["chapter_segments"]
    assert [entry["chapter_id"] for entry in segments] == entry["chapter_ids"]
    model = ref.load("learning/cache/window-0001.input.json")
    assert all(raw[seg["source_start"]:seg["source_end"]] == row["text"]
               for seg, row in zip(segments, model["chapters"], strict=True))
    assert "evidence_catalog" not in model
    reply = {**{key: packet[key] for key in ("window_id", "source_sha256")}, "chapter_rows": [
        {"segment_id": s["segment_id"], "event": "出发寻找线索", "state": "", "lead": "", "cue": "",
         "quote": model["chapters"][i]["text"].splitlines()[1]} for i, s in enumerate(segments)
    ]}
    valid_reply = copy.deepcopy(reply)
    reply["chapter_rows"][-1]["quote"] = reply["chapter_rows"][0]["quote"]
    location = "learning/cache/window-0001.raw.json"
    ref.save(location, reply)
    ref.validate_window(argparse.Namespace(window_id="window-0001", input=location))
    assert "WF_REJECT_UPSTREAM" in capsys.readouterr().out
    assert not ref.path("learning/cache/window-0001.validated.json").exists()
    narrowed = ref.load("learning/cache/window-0001.input.json")
    assert len(narrowed["chapters"]) == 1
    valid_reply["chapter_rows"] = valid_reply["chapter_rows"][-1:]
    ref.save(location, valid_reply)
    ref.validate_window(argparse.Namespace(window_id="window-0001", input=location))
    checked = ref.load("learning/cache/window-0001.validated.json")
    assert len(checked["chapter_readings"]) == 10
    assert len(ref.load(ref.PROGRESS)["source_coverage"]["analyzed_chapters"]) == 10
    ref.split(args)
    assert ref.load(ref.MANIFEST)["run_id"] == manifest["run_id"]
    assert '"window-0002"' in capsys.readouterr().out


def test_batch_chars_split_an_oversized_chapter_without_gaps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    ref.save("references/source.txt", "第1章 行程\n" + "他前往巷子调查。"*250 + "\n第2章 新谋\n新情报。")
    ref.split(argparse.Namespace(input="references/source.txt", window=800, overlap=40,
                                 source_mode="serial_full", batch_max_chapters=10, batch_max_chars=1200))
    manifest, raw = ref.manifest()
    assert len(manifest["windows"]) == 3
    segments = [segment for window in manifest["windows"] for segment in ref.read_packet(window)["chapter_segments"]]
    assert all(s["source_end"] - s["source_start"] <= 1200 for s in segments)
    for chapter in manifest["chapters"]:
        parts = [s for s in segments if s["chapter_id"] == chapter["id"]]
        assert parts[0]["source_start"] == chapter["start"]
        assert parts[-1]["source_end"] == chapter["end"]
        assert all(a["source_end"] >= b["source_start"] for a, b in zip(parts, parts[1:]))


def test_workflow_exposes_batch_defaults():
    definition = json.loads((PLUGIN_ROOT / "resources/workflows/reference-distillation/definition.json").read_text(encoding="utf8"))
    variables = {row["key"]: row["default"] for row in definition["variables"]}
    assert variables["batch_max_chapters"] == "10"
    assert variables["batch_max_chars"] == "40000"


def test_batch_cross_read_recalls_a_distant_literal_and_keeps_every_chapter(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    from cross_chapter import PLAN, ROOT, REPORT, prepare, validate, finalize

    ref.save("references/source.txt", "".join(
        f"第{n}章 行程\n这回出现了青铜钥匙。\n" if n in (1, 37) else f"第{n}章 行程\n主角带着卷宗走向第{n}处。\n"
        for n in range(1, 41)))
    ref.split(argparse.Namespace(input="references/source.txt", window=800, overlap=40,
                                 source_mode="serial_full", batch_max_chapters=10, batch_max_chars=40000))
    data, raw = ref.manifest()
    for e in data["windows"]:
        rows = []
        for seg in e["chapter_segments"]:
            cue = seg["chapter_id"] == "chapter-0001"
            rows.append({"segment_id": seg["segment_id"], "event": "某件事发生", "quote":
                         raw[seg["source_start"]:seg["source_end"]].splitlines()[1],
                         "lead": "钥匙的来历" if cue else "", "cue": "青铜钥匙" if cue else ""})
        dest = f"learning/cache/{e['window_id']}.raw.json"
        ref.save(dest, {"window_id": e["window_id"], "source_sha256": e["source_sha256"], "chapter_rows": rows})
        ref.validate_window(argparse.Namespace(window_id=e["window_id"], input=dest))
    ref.merge(None)
    prepare()
    plan = ref.load(PLAN)
    assert len(plan["batches"]) == 1
    batch = next(iter(plan["batches"]))
    prefix = f"{ROOT}/{batch}"
    packet = ref.load(prefix + ".packet.json")
    picked = {chapter["chapter_id"]: chapter["passages"][0] for chapter in packet["chapters"]}
    assert list(picked) == ["chapter-0001", "chapter-0037"]
    evidence = {"passage_id": picked["chapter-0001"]["passage_id"], "excerpt": "这回出现了青铜钥匙。"}
    reply = {key: packet[key] for key in ("batch_id", "source_sha256", "packet_sha256")}
    ref.save(prefix + ".reply.json", {**reply, "findings": [], "chapter_observations": [
        {"chapter_id": "chapter-0001", "observations": [{"dimension": "plot", "statement": "获得线索", "evidence": [evidence]}]}
    ]})
    validate(batch)
    finalize()
    report = ref.load(REPORT)
    assert report["coverage"]["first_pass_chapter_count"] == 40
    assert report["coverage"]["reviewed_chapter_count"] == 1
    assert len(report["chapter_observations"]) == 40


def test_targeted_search_skips_cue_in_import_marker_gap():
    _load_module()
    from cross_chapter import _targeted_packets

    before, gap, after = "她发现青铜钥匙。", "===== SOURCE CHAPTER 2: 青铜钥匙 =====", "她用青铜钥匙开门。"
    start = len(before) + len(gap)
    chapters = [
        {"chapter_id": "a", "title": "一", "passages": [
            {"passage_id": "a1", "source_start": 0, "source_end": len(before), "text": before}]},
        {"chapter_id": "b", "title": "二", "passages": []},
    ]
    bindings = {"a": {"start": 0, "end": len(before)}, "b": {"start": start, "end": start+len(after)}}
    notes = {"a": [{"cue": "青铜钥匙", "lead": "钥匙用途"}], "b": []}
    packet, = _targeted_packets(chapters, bindings, notes, before+gap+after, {})
    assert packet["research_targets"][0]["later_chapter"] == "b"
    assert packet["chapters"][1]["passages"][0]["text"] == after
