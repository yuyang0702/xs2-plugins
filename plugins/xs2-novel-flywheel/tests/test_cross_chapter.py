import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "resources/script-library/xs2/reference_distill"
sys.path.insert(0, str(SCRIPT))
import cross_chapter as cross
import writing_dna
from distillation_upgrade import ReferenceAnalysisUpgrade


def corpus(tmp_path, monkeypatch, mode="serial_full"):
    monkeypatch.chdir(tmp_path)
    bodies = ["她把一枚弯齿钥匙藏在门槛下。\n当时没人留意。", "赶路。敲门。上楼。",
              "她记起门槛下那枚弯齿钥匙，用它打开了夹层。\n她取出卷宗。", "雨季里，她缓缓读完每一页卷宗。"]
    raw, rows, windows = "", [], []
    for i, body in enumerate(bodies, 1):
        raw += f"第{i}章\n"
        start = len(raw)
        raw += body + "\n"
        row = {"id": f"c{i}", "title": f"第{i}章", "start": start, "end": len(raw)}
        rows.append(row)
        windows.append({"chapter_id": row["id"], "window_id": f"w{i}", "source_start": start, "source_end": len(raw)})
    source = {"snapshot_path": "learning/source.txt", "text_sha256": cross.digest(raw)}
    Path("learning").mkdir()
    # Deliberately use CRLF on disk with logical code-point offsets.
    cross.path(source["snapshot_path"]).write_bytes(raw.replace("\n", "\r\n").encode("utf-8"))
    cross.save("learning/cache/windows.json", {"source": source, "windows": windows, "run_id": "one"})
    cross.save("learning/candidates.json", {"source": source, "source_mode": mode, "source_coverage": {"chapters": rows}})
    for w in windows:
        proof = {"source_start": w["source_start"], "source_end": w["source_start"] + 3,
                 "excerpt": raw[w["source_start"]:w["source_start"] + 3]}
        cross.save(f"learning/cache/{w['window_id']}.validated.json", {
            "window_id": w["window_id"], "source_sha256": source["text_sha256"], "run_id": "one",
            "style_observations": [{"layer": "character", "rule": "识别行动中的取舍", "evidence": [proof]}]})
    return raw, source


def prepare_reply():
    cross.prepare()
    batch = next(iter(cross.load(cross.PLAN)["batches"]))
    prefix = f"{cross.ROOT}/{batch}"
    packet = cross.load(prefix + ".packet.json")
    reply = {key: packet[key] for key in ("batch_id", "source_sha256", "packet_sha256")}
    observations, proofs = [], []
    for chapter in packet["chapters"]:
        passage = chapter["passages"][0]
        proof = {"passage_id": passage["passage_id"], "excerpt": passage["text"].split("。")[0] + "。"}
        proofs.append(proof)
        observations.append({"chapter_id": chapter["chapter_id"], "observations": [
            {"dimension": "plot", "statement": "记录本章当下的行动", "evidence": [proof]}]})
    explicit = {"dimension": "foreshadowing", "status": "confirmed", "statement": "初次藏钥匙在后来开锁时兑现",
                "reason": "后文回忆藏钥匙的地点并交代了用途", "limits": "只核验这一对事件",
                "bridge_excerpt": "用它打开了夹层", "support_type": "explicit_callback",
                "evidence": [{**proofs[0], "role": "before"}, {**proofs[2], "role": "after"}]}
    possible = {**explicit, "dimension": "character_arc", "support_type": "inferred", "statement": "人物可能变得更主动",
                "reason": "只有行动相似，还缺少选择前后的动机", "bridge_excerpt": ""}
    reply.update(chapter_observations=observations, findings=[explicit, possible])
    cross.save(prefix + ".reply.json", reply)
    return batch, prefix, reply


def test_rereads_original_chapters_and_persists_findings(tmp_path, monkeypatch, capsys):
    raw, _ = corpus(tmp_path, monkeypatch)
    batch, prefix, reply = prepare_reply()
    cross.validate(batch)
    cross.finalize()
    report = cross.load(cross.REPORT)
    assert report["coverage"]["reviewed_chapter_count"] == 4
    assert [item["status"] for item in report["findings"]] == ["confirmed", "possible"]
    for proof in report["findings"][0]["evidence"]:
        assert raw[proof["source_start"]:proof["source_end"]] == proof["excerpt"]
    assert [p["phase"] for p in report["phase_pacing"]] == ["opening", "middle", "closing"]
    assert sum(p["chapter_count"] for p in report["phase_pacing"]) == 4
    assert cross.load(cross.SUMMARY)["total_findings"] == 2
    plot = {"plot_dimensions": {key: {} for key in ("foreshadowing", "pacing")}}
    person = {"character_dimensions": {key: {} for key in ("character_arcs", "relationships")}}
    ReferenceAnalysisUpgrade._apply_cross_analysis(report, plot, person, {}, {})
    assert plot["plot_dimensions"]["foreshadowing"]["setup_payoff_distance"]["mean_chapter_distance"] == 2
    assert person["character_dimensions"]["character_arcs"]["cross_chapter_findings"][0]["status"] == "possible"
    cross.prepare()
    assert "<WF_VAR>cross_batch_ids:[]</WF_VAR>" in capsys.readouterr().out
    packet = cross.load(prefix + ".packet.json")
    assert packet["chapters"][0]["first_read_leads"]
    assert reply["packet_sha256"] == packet["packet_sha256"]


@pytest.mark.parametrize("fault", ["fabricated", "wrong_chapter", "reverse", "stale_packet", "bridge", "missing_focus"])
def test_rejects_invalid_cross_reading(tmp_path, monkeypatch, capsys, fault):
    corpus(tmp_path, monkeypatch)
    batch, prefix, reply = prepare_reply()
    item = reply["findings"][0]
    if fault == "fabricated":
        item["evidence"][0]["excerpt"] = "不存在的原文"
    elif fault == "wrong_chapter":
        item["evidence"][0] = {**item["evidence"][1], "role": "before"}
    elif fault == "reverse":
        item["evidence"].reverse()
    elif fault == "stale_packet":
        reply["packet_sha256"] = "old"
    elif fault == "bridge":
        item["bridge_excerpt"] = "未写明的因果"
    else:
        reply["chapter_observations"].pop()
    cross.save(prefix + ".reply.json", reply)
    cross.validate(batch)
    assert 'WF_REJECT_UPSTREAM target="agent_cross_chapter"' in capsys.readouterr().out
    assert not cross.path(prefix + ".validated.json").exists()
    with pytest.raises(ValueError, match="未完成"):
        cross.finalize()


def test_shared_name_alone_stays_possible(tmp_path, monkeypatch):
    corpus(tmp_path, monkeypatch)
    batch, prefix, reply = prepare_reply()
    reply["findings"][0]["bridge_excerpt"] = "弯齿钥匙"
    cross.save(prefix + ".reply.json", reply)
    cross.validate(batch)
    cross.finalize()
    assert cross.load(cross.REPORT)["findings"][0]["status"] == "possible"


def test_stale_source_and_tampered_receipt_fail(tmp_path, monkeypatch):
    raw, source = corpus(tmp_path, monkeypatch)
    batch, prefix, _ = prepare_reply()
    cross.validate(batch)
    checked = cross.load(prefix + ".validated.json")
    checked["findings"][0]["evidence"][0]["excerpt"] = "悄悄替换"
    cross.save(prefix + ".validated.json", checked)
    with pytest.raises(ValueError, match="未完成"):
        cross.finalize()
    cross.path(source["snapshot_path"]).write_text(raw.replace("钥匙", "假货"), encoding="utf-8")
    with pytest.raises(ValueError, match="原章已变化"):
        cross.validate(batch)


def test_sample_modes_skip_whole_book_inference(tmp_path, monkeypatch):
    corpus(tmp_path, monkeypatch, mode="serial_chapters")
    cross.prepare()
    assert not cross.load(cross.PLAN)["batches"]
    cross.finalize()
    assert cross.load(cross.REPORT)["findings"] == []


def test_large_book_covers_every_focus_and_retrieves_distant_text():
    chapters = [{"chapter_id": str(i), "passages": [{"text": f"章节独有情节 {i}"}]} for i in range(421)]
    for i in (3, 388):
        chapters[i]["passages"][0]["text"] += "弯齿钥匙压在旧缎子底下"
    packets = list(cross._make_packets(chapters, {"run_id": "one", "source_sha256": "source"}))
    assert len(packets) > 100
    assert [cid for packet in packets for cid in packet["focus_chapter_ids"]] == [c["chapter_id"] for c in chapters]
    assert max(len(p["chapters"]) for p in packets) <= 13
    assert "388" in {c["chapter_id"] for c in packets[0]["chapters"]}


def test_full_mode_cli_reaches_profile_and_multidimensional_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("source.txt").write_text("第一章 门槛\n她藏起钥匙。\n第二章 归来\n她用旧日藏好的钥匙开了门。", encoding="utf-8")

    def cli(*arguments):
        result = subprocess.run([sys.executable, str(SCRIPT / "reference_distill.py"), *arguments],
                                capture_output=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert "WF_REJECT_UPSTREAM" not in result.stdout, result.stdout

    cli("split", "--input", "source.txt", "--source-mode", "serial_full")
    data = cross.load("learning/cache/windows.json")
    for window in data["windows"]:
        wid = window["window_id"]
        output = f"learning/cache/{wid}.raw.json"
        cross.save(output, {"window_id": wid, "source_sha256": window["source_sha256"], "candidates": []})
        cli("validate-window", "--input", output, "--window-id", wid)
    cli("merge")
    cli("cross-prepare")
    batch = next(iter(cross.load(cross.PLAN)["batches"]))
    packet = cross.load(f"{cross.ROOT}/{batch}.packet.json")
    reply = {key: packet[key] for key in ("batch_id", "source_sha256", "packet_sha256")}
    quotes = ["她藏起钥匙。", "她用旧日藏好的钥匙开了门。"]
    proofs = [{"passage_id": chapter["passages"][0]["passage_id"], "excerpt": quote}
              for chapter, quote in zip(packet["chapters"], quotes, strict=True)]
    reply["chapter_observations"] = [{"chapter_id": chapter["chapter_id"], "observations": [
        {"dimension": "plot", "statement": "本章交代物件与行动", "evidence": [proof]}]}
        for chapter, proof in zip(packet["chapters"], proofs)]
    reply["findings"] = [{"dimension": "foreshadowing", "status": "confirmed", "statement": "藏钥匙的动作在开门时兑现",
                          "reason": "后章明确提及旧日藏好的钥匙", "limits": "只涉及所见二章", "support_type": "explicit_callback",
                          "bridge_excerpt": "旧日藏好的钥匙开了门", "evidence": [
                              {**proofs[0], "role": "before"}, {**proofs[1], "role": "after"}]}]
    cross.save(f"{cross.ROOT}/{batch}.reply.json", reply)
    cli("cross-validate", "--batch-id", batch)
    cli("cross-finalize")
    cross.save("learning/dna/summary.raw.json", {"source_sha256": data["source"]["text_sha256"], "documents": {
        name: "在两章中根据动作的直接后果核对所见的联系，写下它如何推动人物的下一步选择，并说明概括适用的范围。"
        for name in writing_dna.DOCUMENTS}})
    cli("finalize-dna")
    cli("analyze-dimensions")
    cli("validate-analysis")
    cli("generate-summary")
    profile = cross.load("learning/dna/profile.json")
    assert profile["cross_chapter_analysis"]["coverage"]["reviewed_chapter_count"] == 2
    plot = cross.load("learning/analysis/plot_analysis.json")
    assert plot["plot_dimensions"]["foreshadowing"]["setup_payoff_distance"]["confirmed_count"] == 1
    assert "1 项已确认，0 项待证" in cross.path("learning/analysis_summary.md").read_text(encoding="utf-8")
