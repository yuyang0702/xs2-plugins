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
    reply = {**{key: packet[key] for key in ("window_id", "source_sha256")}, "style_observations": [], "conflict_patterns": [], "chapter_rows": [
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
        ref.save(dest, {"window_id": e["window_id"], "source_sha256": e["source_sha256"], "chapter_rows": rows, "style_observations": [], "conflict_patterns": []})
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


def test_batch_checks_extras_against_source_and_keeps_accepted_readings(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    args = argparse.Namespace(input="references/source.txt", window=800, overlap=40,
                              source_mode="serial_full", batch_max_chapters=10, batch_max_chars=40000)
    ref.save(args.input, "第1章 来访\n她在桌上摊开一封信。\n第2章 回答\n他用一声咳嗽打断了沉默。")
    ref.split(args)
    data, _ = ref.manifest()
    entry = data["windows"][0]
    stem = "learning/cache/" + entry["window_id"]
    request = ref.load(stem + ".input.json")
    assert "style_observations" in request["extras_request"]
    identity = {key: request[key] for key in ("window_id", "source_sha256")}
    rows = [{"segment_id": s["segment_id"], "event": "一件事发生", "quote": s["text"].splitlines()[1]}
            for s in request["chapters"]]
    validate = argparse.Namespace(window_id=entry["window_id"], input=stem + ".raw.json")

    def submit(**fields):
        ref.save(validate.input, {**identity, **fields})
        ref.validate_window(validate)

    submit(chapter_rows=rows)
    assert "WF_REJECT_UPSTREAM" in capsys.readouterr().out
    assert len(ref.load(stem + ".input.json")["chapters"]) == 2
    style = {"layer": "dialogue", "confidence": "medium", "rule": "用动作接住沉默",
             "transfer_guidance": "等待回答时用一个动作表现犹豫", "limits": ["需要对话出现停顿"],
             "evidence": [{"excerpt": "原文里没有的动作", "reason": "此处出现动作"}]}
    submit(chapter_rows=[], style_observations=[style], conflict_patterns=[])
    assert "WF_REJECT_UPSTREAM" in capsys.readouterr().out
    assert not ref.path(stem + ".validated.json").exists()
    style["evidence"] = [{"anchor": "打断了沉默", "segment_id": rows[1]["segment_id"], "reason": "动作回应了等待"}]
    submit(chapter_rows=[], style_observations=[style])
    checked = ref.load(stem + ".validated.json")
    assert checked["extras_reviewed"] and len(checked["chapter_readings"]) == 2
    ref.merge(None)
    proof = checked["style_observations"][0]["evidence"][0]
    assert proof["excerpt"] == rows[1]["quote"] and proof["chapter_id"] == entry["chapter_ids"][1]
    assert ref.load(ref.CANDIDATES)["style_observations"] == checked["style_observations"]
    assert checked["conflict_patterns"] == []


def test_legacy_supplement_is_bound_resumable_and_keeps_original_receipts(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    ref = _load_module()
    import batch_extras
    args = argparse.Namespace(input="references/source.txt", window=800, overlap=40,
                              source_mode="serial_full", batch_max_chapters=10, batch_max_chars=40000)
    ref.save(args.input, "第1章 散场\n她合上木门，留他独自做选择。\n第2章 代价\n他撕了字据，抬脚追上去。")
    ref.split(args)
    manifest, _ = ref.manifest()
    del manifest["batch_extras_version"]
    ref.save(ref.MANIFEST, manifest)
    ref.split(args)
    data, raw = ref.manifest()
    entry, = data["windows"]
    key = entry["window_id"]
    stem = "learning/cache/" + key
    request = ref.load(stem + ".input.json")
    assert "extras_request" not in request
    rows = [{"segment_id": s["segment_id"], "event": "作出选择", "quote": s["text"].splitlines()[1]}
            for s in request["chapters"]]
    ref.save(stem + ".raw.json", {k: request[k] for k in ("window_id", "source_sha256")} | {"chapter_rows": rows})
    ref.validate_window(argparse.Namespace(window_id=key, input=stem + ".raw.json"))
    paths = [stem + ".validated.json", ref.checkpoint_path(entry), ref.PROGRESS]
    frozen = [ref.path(p).read_bytes() for p in paths]
    ref.save(batch_extras.supplement_path(key), {"binding": {"run_id": "previous-run"}})
    packet = batch_extras.prepare_supplement(ref, key)
    assert all(ch["text"] in raw for ch in packet["chapters"])
    response = {"binding": packet["binding"], "style_observations": [],
                "conflict_patterns": [{**{field: "决定引出代价" for field in
                    ("name", "goal", "foreshadowing", "obstacle", "resolution", "cost", "next_obstacle", "causal_link", "payoff")},
                    "application_scope": "serial_chapter", "confidence": "medium",
                    "evidence": [{"excerpt": rows[1]["quote"], "reason": "撕掉字据是可见的代价"}]}]}
    with pytest.raises(ValueError):
        batch_extras.save_supplement(ref, key, {**response, "binding": {}})
    groups = batch_extras.save_supplement(ref, key, response)
    assert batch_extras.prepare_supplement(ref, key) is None
    assert batch_extras.save_supplement(ref, key, response) == groups
    assert [ref.path(p).read_bytes() for p in paths] == frozen
    ref.merge(None)
    assert ref.load(ref.CANDIDATES)["conflict_patterns"] == groups["conflict_patterns"]
    receipt = batch_extras.supplement_path(key, data["run_id"])
    altered = ref.load(receipt)
    altered["groups"]["conflict_patterns"].clear()
    ref.save(receipt, altered)
    with pytest.raises(ValueError, match="不匹配"):
        ref.merge(None)


def test_batch_merge_keeps_distant_support_for_the_same_style():
    ref = _load_module()
    first = {"rule": "动作回应沉默", "confidence": "high", "evidence": [
        {"source_start": 4, "source_end": 11, "window_id": "window-0001"}]}
    later = {**first, "confidence": "medium", "evidence": [
        {"source_start": 4000, "source_end": 4008, "window_id": "window-0023"}]}
    [rule] = ref.combine_observations([first, later, first])
    assert [p["window_id"] for p in rule["evidence"]] == ["window-0001", "window-0023"]

def test_whole_book_summary_draws_from_later_batches_within_the_existing_budget():
    ref = _load_module()
    windows = [f"window-{i:04d}" for i in range(1, 61)]
    records = [{"confidence": "high", "evidence": [{"window_id": w}]} for w in windows]
    ordered = ref.writing_dna.summary_order(records, {"source_mode": "serial_full", "covered_window_ids": windows})
    assert [row["evidence"][0]["window_id"] for row in ordered[:6]] == windows[::10]
