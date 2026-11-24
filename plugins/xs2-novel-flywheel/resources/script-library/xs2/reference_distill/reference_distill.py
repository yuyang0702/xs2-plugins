#!/usr/bin/env python3
"""Standalone XS2 learning contract; standard library only, cwd = workspace.

Model calls belong to Workflow Agent nodes. Source/evidence stays in learning/;
only explicitly selected abstract mechanisms enter generation context.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import writing_dna
from dialogue_learning import dialogue_context, normalize_dialogue_samples, combine_samples, render_adaptations
from distill_schema import DIMENSIONS, EXPORT_LAYOUTS, LAYERS, POV_COMPATIBILITY
from reference_choices import DIMENSION_NAMES, mechanism_scopes
from source_chapters import CHAPTER_HEADING, chapter_batches, coverage, numbering_gaps, source_units, split_ranges
@lru_cache(maxsize=1)
def reading():
    spec=importlib.util.spec_from_file_location('reference_reading_goals',Path(__file__).resolve().parents[1]/'prose_policy/reading_contract.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

MANIFEST = "learning/cache/windows.json"
CANDIDATES = "learning/candidates.json"
ACTIVE = "learning/active.json"
SCOPES = {"build", "character", "novel-advisor", "story-plan", "outline", "mvp", "polish", "post-hoc", "export"}
APPLICATION_SCOPES = {"short_full", "serial_opening", "serial_chapter", "serial_arc", "general"}
OPENING_HEADING = re.compile(
    r"^(?:#{1,6}\s|<h[1-6]\b|第[\s零一二三四五六七八九十百千两〇\d]+[章节卷回部篇]|"
    r"(?:序章|楔子|引子|正文|上篇|上卷)(?:\s|[：:]|$)|chapter\s|prologue\b)", re.I
)
WINDOW_GROUPS = {'candidates': ('candidate', 12), 'style_observations': ('style', 12),
                 'conflict_patterns': ('conflict', 8)}
MAX_ITEM_REPAIR_ROUNDS = 2
PROGRESS = "learning/cache/progress.json"
WINDOW_BATCH_SIZE = 32

# Workflow captures subprocess stdout as UTF-8.  Windows may otherwise select
# the active console code page (for example GBK), which turns Chinese status
# messages into mojibake in the task panel.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def path(raw):
    item = Path(raw)
    root = Path.cwd().resolve()
    resolved = (root / item).resolve()
    if item.is_absolute() or ".." in item.parts or not resolved.is_relative_to(root):
        raise ValueError("路径必须位于当前工作区内")
    return resolved


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load(raw):
    return json.loads(path(raw).read_text(encoding="utf-8-sig"))


def save(raw, value):
    target = path(raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
    temporary = target.with_suffix(target.suffix + "." + uuid4().hex + ".tmp")
    temporary.write_text(text + "\n", encoding="utf-8")
    temporary.replace(target)


def text_field(item, key, limit=800):
    value = item.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{key} 必须是非空字符串，且不超过 {limit} 字符")
    return value.strip()


def strings(item, key, allow_empty=True):
    values = item.get(key)
    if not isinstance(values, list) or len(values) > 16:
        raise ValueError(f"{key} 必须是至多 16 项的数组")
    if not allow_empty and not values:
        raise ValueError(f"{key} 不可为空")
    return [text_field({"value": value}, "value", 400) for value in values]


def optional_strings(item, key, limit=8):
    value = item.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{key} 必须是至多 {limit} 项的数组")
    return [text_field({"value": item}, "value", 400) for item in value]


def manifest():
    data = load(MANIFEST)
    source = data["source"]
    raw = path(source["snapshot_path"]).read_text(encoding="utf-8")
    if digest(raw) != source["text_sha256"]:
        raise ValueError("参考资料快照哈希不一致，请重新蒸馏")
    return data, raw


def read_packet(entry):
    if "packet_sha256" not in entry:
        return entry
    packet = load(f"learning/cache/{entry['window_id']}.json")
    if digest(packet) != entry["packet_sha256"]:
        raise ValueError("窗口与分窗清单的哈希不符")
    return packet


def checkpoint_path(entry):
    return f"learning/cache/batches/{entry['batch_id']}.json"


def batch_ledger(entry, run_id):
    try:
        stored = load(checkpoint_path(entry))
        if stored.get("run_id") == run_id and isinstance(stored.get("validated"), dict):
            return stored
    except (FileNotFoundError, ValueError, AttributeError):
        pass
    return {"run_id": run_id, "validated": {}}


def initial_coverage(data, completed):
    return {**data.get("completeness", {}), **coverage(data["chapters"], data["windows"], completed)}


def write_progress(data, completed):
    scope = initial_coverage(data, completed)
    batches = {}
    for entry in data["windows"]:
        batch = batches.setdefault(entry["batch_id"], {"total": 0, "validated": 0})
        batch["total"] += 1
        batch["validated"] += entry["window_id"] in completed
    save(PROGRESS, {"run_id": data["run_id"], "source_sha256": data["source"]["text_sha256"],
                    "source_mode": data["source_mode"], "source_coverage": scope,
                    "validated_window_ids": sorted(completed), "batches": batches})
    return scope


def record_validation(data, entry, checked):
    if entry.get("packet_sha256"):
        checked["packet_sha256"] = entry["packet_sha256"]
    save(f"learning/cache/{entry['window_id']}.validated.json", checked)
    if "batch_id" not in entry:  # previous manifest version
        return
    receipt = checkpoint_path(entry)
    ledger = batch_ledger(entry, data["run_id"])
    ledger["validated"][entry["window_id"]] = digest(checked)
    save(receipt, ledger)
    progress = load(PROGRESS)
    if progress["run_id"] != data["run_id"]:
        raise ValueError("分窗进度属于其他分析轮次")
    write_progress(data, set(progress["validated_window_ids"]) | {entry["window_id"]})


def recovered_windows(data):
    """Skip only evidence-validated results with matching run and durable receipts."""
    completed = set()
    ledgers = {}
    for entry in data["windows"]:
        batch = entry["batch_id"]
        if batch not in ledgers:
            ledgers[batch] = batch_ledger(entry, data["run_id"])["validated"]
        key = entry["window_id"]
        result = f"learning/cache/{key}.validated.json"
        if key in ledgers[batch] and path(result).is_file():
            try:
                checked = load(result)
                if (checked["run_id"] == data["run_id"] and checked["source_sha256"] == data["source"]["text_sha256"]
                        and checked["window_id"] == key and checked.get("packet_sha256") == entry.get("packet_sha256")
                        and digest(checked) == ledgers[batch][key]):
                    completed.add(key)
            except (KeyError, ValueError, TypeError):
                pass
    return completed


def write_chapter_input(window, raw, pending=None):
    selected = [segment for segment in window["chapter_segments"]
                if pending is None or segment["segment_id"] in pending]
    save(f"learning/cache/{window['window_id']}.input.json", {
        "analysis": "chapter_batch", "window_id": window["window_id"],
        "source_sha256": window["source_sha256"],
        "chapters": [{"segment_id": row["segment_id"], "title": row["title"],
                      "text": raw[row["source_start"]:row["source_end"]]} for row in selected],
    })


def split(args):
    if not 800 <= args.window <= 12000 or not 0 <= args.overlap < args.window // 2:
        raise ValueError("window 必须为 800～12000，overlap 必须小于窗口的一半")
    raw = path(args.input).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if not raw.strip():
        raise ValueError("参考资料为空")
    source_hash = digest(raw)
    snapshot = f"learning/sources/{source_hash}.txt"
    if path(snapshot).exists():
        if path(snapshot).read_text(encoding="utf-8") != raw:
            raise ValueError("已有来源快照损坏")
    else:
        # Preserve exact offsets: no stripping or appended newline.
        target = path(snapshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw, encoding="utf-8")
    source = {"text_sha256": source_hash, "snapshot_path": snapshot, "characters": len(raw)}
    requested_mode = getattr(args, "source_mode", "auto")
    effective_mode = requested_mode
    imported = {}
    if path(args.input) == path("references/url-imported-corpus.txt") and path("references/url-import.json").is_file():
        receipt = load("references/url-import.json")
        if receipt.get("corpus_sha256") == source_hash:
            imported = receipt
            declared = imported.get("source_mode")
            if requested_mode == "auto" and declared in ("short_full", "serial_chapters", "serial_full"):
                effective_mode = declared
            if requested_mode == "serial_full" and declared == "serial_chapters":
                raise ValueError("导入记录是长篇章节样本，请重新导入整本目录后分析全文。")
        elif requested_mode == "serial_full":
            raise ValueError("网页目录记录与原文哈希不一致，请重新导入整本目录。")
    mode, chapters = source_units(raw, effective_mode)
    batch_max_chapters = getattr(args, "batch_max_chapters", None)
    batch_max_chars = getattr(args, "batch_max_chars", None)
    batched = mode == "serial_full" and batch_max_chapters is not None
    if batched and (not 1 <= batch_max_chapters <= 30 or batch_max_chars is None
                    or not 800 <= batch_max_chars <= 60000):
        raise ValueError("每批章节上限须在 1～30，每批字符上限须在 800～60000")
    # Keep the established whole-text windows for older modes. Full books never
    # spend a model window or its overlap on a neighbouring chapter.
    ranges = ((start, end, [chapter["id"]]) for chapter in chapters for start, end in
              split_ranges(raw, chapter["start"], chapter["end"], args.window, args.overlap)) if mode == "serial_full" else (
              (start, end, [c["id"] for c in chapters if c["start"] < end and start < c["end"]])
              for start, end in split_ranges(raw, 0, len(raw), args.window, args.overlap))
    basis = "imported_text"
    if mode == "serial_full":
        basis = "user_declared" if requested_mode == "serial_full" else "end_marker"
    provenance = {"completeness_basis": basis}
    if imported:
        provenance.update(completeness_basis="catalog", catalog_complete=imported.get("catalog_complete"),
                          work_finished=imported.get("work_finished"))
    if mode == "serial_full":
        provenance["chapter_boundaries"] = ("source_chapters" if re.search(r"^===== SOURCE CHAPTER", raw, re.M)
                                            else "headings" if CHAPTER_HEADING.search(raw)
                                            else "file_boundaries" if len(chapters) > 1 else "unsegmented")
        provenance["numbering_gaps"] = numbering_gaps(chapters)
        provenance["whole_book_eligible"] = (not provenance["numbering_gaps"] and provenance.get("catalog_complete") is not False
                                             and provenance.get("work_finished") is not False)
        if not provenance["whole_book_eligible"]:
            gap = next(iter(provenance["numbering_gaps"]), None)
            reason = (f"章号缺少第 {gap['first_missing']}～{gap['last_missing']} 章" if gap
                      else "目录未全部导入或作品仍在连载")
            raise ValueError(f"{reason}。请补齐后重新分析，或选择长篇章节样本。")
    writing_dna.prepare(raw, source, mode, save, units_info=(mode, chapters),
                        completeness=provenance,
                        direction=getattr(args, "learning_direction", "general"),
                        focus=getattr(args, "learning_focus", ""))
    save("learning/dna/upstream.json", json.loads((Path(__file__).parent / "vendor/writing-dna-skill/UPSTREAM.json").read_text(encoding="utf-8")))
    settings_data = {"version": 1, "source": source_hash, "window": args.window, "overlap": args.overlap,
                     "mode": mode, "completeness": provenance}
    if batched:
        settings_data.update(version=2, batch_max_chapters=batch_max_chapters, batch_max_chars=batch_max_chars)
    settings = digest(settings_data)
    previous = load(MANIFEST) if mode == "serial_full" and path(MANIFEST).is_file() else {}
    resume = previous.get("settings_sha256") == settings
    run_id = previous["run_id"] if resume else uuid4().hex
    windows = []
    chapters_by_id = {chapter["id"]: chapter for chapter in chapters}
    if batched:
        groups = ((segments[0]["source_start"], segments[-1]["source_end"],
                   [seg["chapter_id"] for seg in segments], segments)
                  for segments in chapter_batches(raw, chapters, batch_max_chapters, batch_max_chars, args.overlap))
    else:
        groups = ((start, end, ids, None) for start, end, ids in ranges)
    for start, end, chapter_ids, segments in groups:
        window_id = f"window-{len(windows) + 1:04d}"
        batch_id = f"batch-{len(windows) // WINDOW_BATCH_SIZE + 1:04d}"
        packet = {"window_id": window_id, "source_start": start, "source_end": end,
                  "text": raw[start:end], "source_sha256": source_hash, "source_mode": mode,
                  "chapter_ids": chapter_ids, "chapter_id": chapter_ids[0] if len(chapter_ids) == 1 else None,
                  "batch_id": batch_id}
        if segments is not None:
            packet["chapter_segments"] = segments
            write_chapter_input(packet, raw)
        elif mode == "serial_full":
            chapter = chapters_by_id[chapter_ids[0]]
            packet.update(chapter_title=chapter["title"], chapter_range=[chapter["start"], chapter["end"]])
        # IDs let a model select exact evidence without retyping font-obfuscated
        # characters. Positions and excerpts are generated from the real source.
        if segments is None:
            packet["dialogue_context"] = dialogue_context(raw, start, end, packet.get("chapter_range"))
            catalog = []
            for line in re.finditer(r"[^\n]+", packet["text"]):
                for offset in range(line.start(), line.end(), 160):
                    stop = min(offset + 160, line.end())
                    if packet["text"][offset:stop].strip():
                        catalog.append({"evidence_id": f"{window_id}-e{len(catalog)+1:04d}",
                                        "source_start": start + offset, "source_end": start + stop,
                                        "excerpt": raw[start + offset:start + stop]})
            packet["evidence_catalog"] = catalog
        save(f"learning/cache/{window_id}.json", packet)
        if mode == "serial_full":
            entry = {k: v for k, v in packet.items() if k not in {"text", "dialogue_context", "evidence_catalog"}}
            windows.append({**entry, "packet_sha256": digest(packet)})
        else:
            windows.append(packet)
        feedback = f"learning/cache/{window_id}.feedback.md"
        if not resume or not path(feedback).is_file():
            save(feedback, "")
    data = {"schema": "xs2.reference.windows.v2", "run_id": run_id, "source": source, "source_mode": mode,
            "chapters": chapters, "windows": windows, "settings_sha256": settings, "completeness": provenance}
    if batched:
        data["chapter_batch_limits"] = {"chapters": batch_max_chapters, "characters": batch_max_chars}
    completed = recovered_windows(data) if resume else set()
    data["source_coverage"] = write_progress(data, completed)
    save(MANIFEST, data)
    metadata = load("learning/dna/metadata.json")
    save("learning/dna/metadata.json", {**metadata, "source_coverage": data["source_coverage"]})
    ids = json.dumps([item["window_id"] for item in windows if item["window_id"] not in completed])
    print(f"<WF_VAR>source_mode:{mode}</WF_VAR>")
    print(f"<WF_VAR>chapter_batch_mode:{str(batched).lower()}</WF_VAR>")
    print(f"<WF_VAR>window_ids:{ids}</WF_VAR>")
    print(f"<script_out>已完整分窗：{len(chapters)} 章，{len(windows)} 个窗口，复用 {len(completed)} 个已校验窗口。</script_out>")


def evidence_position(proof, window, raw):
    if not isinstance(proof, dict):
        raise ValueError("证据必须是对象")
    if proof.get("window_id") != window["window_id"]:
        raise ValueError("证据窗口身份不一致")
    if "end_evidence_id" in proof and not proof.get("evidence_id"):
        raise ValueError("连续证据需要起始证据编号")
    if proof.get("evidence_id"):
        def catalog_row(identifier):
            selected = next((item for item in window.get("evidence_catalog", [])
                             if item["evidence_id"] == identifier), None)
            if selected is None:
                raise ValueError("证据编号不属于当前窗口")
            start, end = selected["source_start"], selected["source_end"]
            if not window["source_start"] <= start < end <= window["source_end"] or raw[start:end] != selected["excerpt"]:
                raise ValueError("证据目录与来源快照不一致")
            return start, end

        start, end = catalog_row(proof["evidence_id"])
        if "end_evidence_id" in proof:
            last_start, end = catalog_row(proof["end_evidence_id"])
            if last_start < start or end - start > 600:
                raise ValueError("连续证据编号须按原文顺序且跨度不超过 600 字符")
        return start, end, raw[start:end], False
    excerpt = proof.get("excerpt")
    if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 300:
        raise ValueError("excerpt 必须是非空字符串，且不超过 300 字符")
    start, end = proof.get("source_start"), proof.get("source_end")
    if (type(start) is int and type(end) is int
            and window["source_start"] <= start < end <= window["source_end"]
            and raw[start:end] == excerpt):
        return start, end, excerpt, False
    # Models select evidence; exact character counting belongs to the script.
    # Relocate only a unique literal match within the current verified window.
    text = raw[window["source_start"]:window["source_end"]]
    offset = text.find(excerpt)
    if offset < 0:
        raise ValueError("证据摘录在当前窗口原文中不存在")
    if text.find(excerpt, offset + 1) >= 0:
        raise ValueError("证据摘录在当前窗口有多处匹配，请提供更完整摘录或准确位置")
    start = window["source_start"] + offset
    return start, start + len(excerpt), excerpt, True


def checked_export_layout(item, evidence, raw, source_sha256):
    layout = item["export_layout"]
    if item.get("dimension") != "layout" or layout not in EXPORT_LAYOUTS:
        raise ValueError("export_layout 仅可用于 layout，值须为 preserve 或 short_body_only")
    if layout == "short_body_only":
        metadata = load("learning/dna/metadata.json")
        if metadata.get("source", {}).get("text_sha256") != source_sha256:
            raise ValueError("export_layout 的语料元数据与当前来源不一致")
        units = metadata["source_units"]
        if metadata["source_mode"] != "short_full" or len(units) != 1:
            raise ValueError("export_layout 的 short_body_only 需要单篇短篇全文")
        unit = units[0]
        body = raw[unit["source_start"]:unit["source_end"]]
        opening = body.lstrip()
        start = unit["source_start"] + len(body) - len(opening)
        if (not opening or OPENING_HEADING.match(opening)
                or not any(proof["source_start"] <= start < proof["source_end"] for proof in evidence)):
            raise ValueError("export_layout 的 short_body_only 需要短篇正文开头的实际证据，且开头无章节标题")
    return layout


def _checked_candidate(item, window, raw, source_sha256):
    relocated = 0
    if not isinstance(item, dict):
        raise ValueError("候选必须是对象")
    mechanism = text_field(item, "mechanism", 100)
    guidance = text_field(item, "transfer_guidance")
    constraints = strings(item, "constraints")
    dimension = item.get('dimension')
    if 'dimension' in item and dimension not in DIMENSIONS:
        raise ValueError('dimension 不是支持的参考维度')
    scopes = (strings(item, 'scopes', False) if not dimension
              else optional_strings(item, 'scopes', 16))
    misplaced = set(scopes) & APPLICATION_SCOPES
    scopes = [scope for scope in scopes if scope not in misplaced]
    if (not dimension and not scopes) or not set(scopes) <= SCOPES:
        raise ValueError("候选包含未知流程范围")
    confidence = item.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError("confidence 只能为 high、medium、low")
    layer = item.get("layer", "narrative_lens")
    if layer not in LAYERS:
        raise ValueError("layer 不是支持的写法层次")
    source_pov = optional_strings(item, "source_pov", 4)
    target_pov = optional_strings(item, "target_pov", 4)
    pov_compatibility = item.get("pov_compatibility", "adaptable")
    if pov_compatibility not in POV_COMPATIBILITY:
        raise ValueError("pov_compatibility 只能为 direct、adaptable 或 risky")
    adaptation_guidance = item.get("adaptation_guidance", "")
    if not isinstance(adaptation_guidance, str) or len(adaptation_guidance) > 800:
        raise ValueError("adaptation_guidance 必须是 800 字以内的文本")
    risk_flags = optional_strings(item, "risk_flags", 8)
    application_scope = list(dict.fromkeys([*optional_strings(item, "application_scope", 5), *sorted(misplaced)]))
    if not set(application_scope) <= APPLICATION_SCOPES:
        raise ValueError("application_scope 包含未知的篇幅适用范围")
    evidence = item.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
        raise ValueError("每条候选需要 1～8 条证据")
    checked = []
    for proof in evidence:
        if not isinstance(proof, dict):
            raise ValueError("证据必须是对象")
        start, end, excerpt, repaired = evidence_position(proof, window, raw)
        relocated += int(repaired)
        checked.append({"window_id": window["window_id"], "source_start": start,
                        "source_end": end, "excerpt": excerpt, "reason": text_field(proof, "reason")})
    # Reject literal copying in generation-facing fields; semantic abstraction
    # still requires the user to inspect candidates before selection.
    for value in [mechanism, guidance, *constraints]:
        if any(value[offset:offset + 20] in raw for offset in range(max(0, len(value) - 19))):
            raise ValueError("抽象写法包含连续 20 字原文，请重新提炼")
    semantic = {"mechanism": mechanism, "transfer_guidance": guidance,
                "constraints": constraints, "scopes": scopes,
                "layer": layer, "source_pov": source_pov, "target_pov": target_pov,
                "pov_compatibility": pov_compatibility,
                "adaptation_guidance": adaptation_guidance, "risk_flags": risk_flags,
                "application_scope": application_scope}
    if "dimension" in item:
        semantic["dimension"] = item["dimension"]
        semantic["scopes"] = list(mechanism_scopes(semantic))
    if "export_layout" in item:
        layout = checked_export_layout(item, checked, raw, source_sha256)
        if layout != "preserve":
            semantic["export_layout"] = layout
    objectives=reading().abstract_definitions(item['reading_objectives'],[raw]) if item.get('reading_objectives',[])!=[] else []
    if objectives:semantic['reading_objectives']=objectives
    return {"candidate_id": "mechanism-" + digest(semantic)[:20],
            **semantic, "confidence": confidence, "evidence": checked}, relocated


def normalize(args):
    data, raw = manifest()
    entry = next((item for item in data["windows"] if item["window_id"] == args.window_id), None)
    if entry is None:
        raise ValueError("未知窗口")
    window = read_packet(entry)
    payload = load(args.input)
    if (not isinstance(payload, dict) or payload.get("window_id") != window["window_id"]):
        raise ValueError("模型返回的窗口身份或来源哈希不一致")
    items = payload.get("candidates")
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError("每个窗口须返回至多 12 条 candidates（允许空数组）")
    source_sha256 = payload.get("source_sha256")
    # 空候选是合法结果；模型有时会省略无法观察到的来源哈希。窗口文件
    # 已由 split 阶段使用同一份快照生成，此时由脚本补齐哈希，避免把空结果
    # 误判为失败。只要返回了候选，仍要求模型提供正确哈希。
    if not items and not source_sha256 and data.get("source_mode") != "serial_full":
        source_sha256 = data["source"]["text_sha256"]
    if source_sha256 != data["source"]["text_sha256"]:
        raise ValueError("模型返回的窗口身份或来源哈希不一致")
    candidates = []
    observations, patterns = writing_dna.checked_extras(payload, window, raw, text_field, strings, evidence_position)
    relocated = 0
    for item in items:
        candidate, fixed = _checked_candidate(item, window, raw, source_sha256)
        candidates.append(candidate)
        relocated += fixed
        samples = normalize_dialogue_samples(item.get('dialogue_samples'), window, raw, evidence_position)
        if samples:
            candidates[-1]['dialogue_samples'] = samples
    record_validation(data, entry,
         {"source_sha256": source_sha256, "window_id": window["window_id"], "run_id": data.get('run_id'),
          "source_mode": data.get("source_mode"), "chapter_id": window.get("chapter_id"),
          "evidence_positions_relocated": relocated, "candidates": candidates,
          "style_observations": observations, "conflict_patterns": patterns})
    print(f"<script_out>已校验 {window['window_id']}：{len(candidates)} 条候选，精确定位修正 {relocated} 条证据</script_out>")


def _frozen_window(window_id):
    data, raw = manifest()
    entry = next((w for w in data['windows'] if w['window_id'] == window_id), None)
    if entry is None or not re.fullmatch(r'window-\d{4,}', window_id):
        raise ValueError('未知窗口')
    window = read_packet(entry)
    start, end = window['source_start'], window['source_end']
    if window['text'] != raw[start:end] or window['source_sha256'] != data['source']['text_sha256']:
        raise ValueError('窗口与参考资料快照不一致')
    if 'dialogue_context' in window and window['dialogue_context'] != dialogue_context(raw, start, end, window.get('chapter_range')):
        raise ValueError('对白窗口语境与参考资料快照不一致')
    for row in window.get('evidence_catalog', []):
        a, z = row['source_start'], row['source_end']
        if not start <= a < z <= end or raw[a:z] != row['excerpt']:
            raise ValueError('证据目录与参考资料快照不一致')
    serial = data.get("source_mode") == "serial_full"
    binding = [digest([data.get('run_id'), entry["packet_sha256"]]) if serial else digest(data),
               data['source']['text_sha256'], data["run_id"] if serial else os.environ.get('TASK_ID', '')]
    return binding, {
        **window, 'packet_sha256': entry.get("packet_sha256"), 'run_id': data.get('run_id')}, raw


def _window_items(value, limit, group):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f'{group} 必须为至多 {limit} 项的数组')
    return value


def _check_window_record(state, identifier, entry, window, raw):
    """Store a single checked record, or keep only this record for repair."""
    group, value = entry['group'], entry['value']
    try:
        if entry.get('section'):
            prefix, limit = WINDOW_GROUPS[group]
            items = _window_items(value, limit, group)
            for index, item in enumerate(items, 1):
                key = f'{prefix}-{index:02d}'
                if group == 'candidates' and isinstance(item, dict):
                    item = dict(item)
                    samples = item.pop('dialogue_samples', None)
                    if samples is not None:
                        _check_window_record(state, f'{key}.dialogue-samples',
                                             {'group': 'dialogue_samples', 'parent': key, 'value': samples}, window, raw)
                _check_window_record(state, key, {'group': group, 'value': item}, window, raw)
        elif group == 'dialogue':
            samples = normalize_dialogue_samples([value], window, raw, evidence_position)
            state['dialogue'][identifier] = {'parent': entry['parent'], 'sample': samples[0]}
        elif group == 'dialogue_samples':
            items = _window_items(value, 3, group)
            for index, item in enumerate(items, 1):
                _check_window_record(state, f"{entry['parent']}.dialogue-{index:02d}",
                                     {'group': 'dialogue', 'parent': entry['parent'], 'value': item}, window, raw)
        elif group == 'candidates':
            checked, fixed = _checked_candidate(value, window, raw, window['source_sha256'])
            state['accepted'][group][identifier] = checked
            state['evidence_positions_relocated'] += fixed
        else:
            observed, conflict = writing_dna.checked_extras(
                {group: [value]}, window, raw, text_field, strings, evidence_position)
            state['accepted'][group][identifier] = (observed or conflict)[0]
    except (ValueError, KeyError, TypeError) as error:
        state['pending'][identifier] = {**entry, 'error': str(error)}
    else:
        state['pending'].pop(identifier, None)


def _apply_window_repairs(state, payload, window, raw):
    if (type(payload.get('repair_round')) is not int or payload['repair_round'] != state['round']
            or not isinstance(payload.get('repairs'), list) or len(payload['repairs']) > 68):
        return '返修回复须使用当前 repair_round 与 repairs 数组。'
    provided = {}
    pending = dict(state['pending'])
    for row in payload['repairs']:
        if not isinstance(row, dict) or not isinstance(row.get('repair_id'), str):
            continue
        identifier = row['repair_id']
        if identifier in pending:
            provided.setdefault(identifier, []).append(row)
    for identifier, rows in provided.items():
        if len(rows) != 1 or 'value' not in rows[0]:
            continue
        entry = pending[identifier]
        row = rows[0]
        if row['value'] is None:
            try:
                reason = text_field(row, 'reason', 400)
            except ValueError:
                continue
            state['unresolved'].append({'repair_id': identifier, 'group': entry['group'],
                                        'reason': entry['error'], 'repair_note': reason})
            state['pending'].pop(identifier)
            continue
        _check_window_record(state, identifier, {**entry, 'value': row['value']}, window, raw)
    return ''


def _window_output(state, window):
    groups = {group: [rows[key] for key in sorted(rows)] for group, rows in state['accepted'].items()}
    samples_by_parent = {}
    for _, item in sorted(state['dialogue'].items()):
        samples_by_parent.setdefault(item['parent'], []).append(item['sample'])
    groups['candidates'] = [checked | ({'dialogue_samples': samples_by_parent[key]}
                                      if key in samples_by_parent else {})
                            for key, checked in sorted(state['accepted']['candidates'].items())]
    unresolved = state['unresolved'] + [{'repair_id': key, 'group': row['group'], 'reason': row['error']}
                                        for key, row in state['pending'].items()]
    return {'source_sha256': window['source_sha256'], 'window_id': window['window_id'], 'run_id': window['run_id'],
            'source_mode': window.get('source_mode'), 'chapter_id': window.get('chapter_id'),
            'evidence_positions_relocated': state['evidence_positions_relocated'],
            'unresolved': unresolved, **groups}


def _archive_window_reply(window_id, binding, raw_bytes, response, errors):
    receipt = {'window_id': window_id, 'source_binding': binding[:2],
               'response_sha256': hashlib.sha256(raw_bytes).hexdigest(), 'response': response,
               'raw_text': raw_bytes.decode('utf-8-sig', errors='replace'), 'error': errors[0], 'errors': errors,
               'note': '原始回复含待返修内容。逐条验收结果见窗口记录。'}
    relative = f'learning/cache/rejected/{window_id}-{digest(receipt)[:20]}.json'
    if not path(relative).exists():
        save(relative, receipt)
    return relative


def _item_repair_feedback(state, reply_error, archive):
    issues = []
    remaining = 12000
    for key, item in state['pending'].items():
        issue = {'repair_id': key, 'group': item['group'], 'error': item['error']}
        original = json.dumps(item['value'], ensure_ascii=False)
        if len(original) <= min(3600, remaining):
            issue['original'] = item['value']
            remaining -= len(original)
        elif remaining:
            preview = original[:min(250, remaining)]
            issue['original_preview'] = preview
            remaining -= len(preview)
        issues.append(issue)
    return ('本轮只返修列出的条目，已核验项会原样保留。返回 window_id、source_sha256、repair_round 和 repairs。'
            '每个 repairs 项包含 repair_id 与 value，value 为该条完整修正。'
            '证据不足时用 value:null 并填写 reason。证据必须从当前原文选取。'
            f'\nrepair_round: {state["round"]}\n' + (reply_error + '\n' if reply_error else '')
            + json.dumps(issues, ensure_ascii=False) + '\n本次原始回复：' + archive)


def _chapter_reading(row, segment, raw):
    a, b = segment["source_start"], segment["source_end"]
    quote = row.get("quote")
    if not isinstance(quote, str) or not 6 <= len(quote) <= 120 or not quote.strip():
        raise ValueError("需要 6～120 字的连续原文")
    position = raw.find(quote, a, b)
    if position < 0 or raw.find(quote, position + 1, b) >= 0:
        raise ValueError("引文须能在当前章节片段中唯一定位")
    result = {}
    for key in ("event", "state", "lead", "cue", "technique", "guidance"):
        value = row.get(key, "")
        if not isinstance(value, str) or len(value) > 180:
            raise ValueError(f"{key} 须为 180 字以内的文本")
        result[key] = value.strip()
    if not result["event"]:
        raise ValueError("缺少事件或局部叙事观察")
    return {**result, "chapter_id": segment["chapter_id"], "segment_id": segment["segment_id"],
            "evidence": {"chapter_id": segment["chapter_id"], "source_start": position,
                         "source_end": position + len(quote), "excerpt": quote}}


def _validate_chapter_batch(binding, window, raw, response):
    prefix = f"learning/cache/{window['window_id']}"
    receipt = prefix + ".chapter-review.json"
    state = load(receipt) if path(receipt).is_file() else {}
    accepted = state.get("accepted", {}) if state.get("binding") == binding else {}
    segments = {s["segment_id"]: s for s in window["chapter_segments"]}
    valid_identity = (isinstance(response, dict) and response.get("window_id") == window["window_id"]
                      and response.get("source_sha256") == window["source_sha256"]
                      and isinstance(response.get("chapter_rows"), list))
    problems = {}
    if valid_identity:
        for row in response["chapter_rows"][:len(segments) * 2]:
            key = row.get("segment_id") if isinstance(row, dict) else None
            if not isinstance(key, str) or key not in segments or key in accepted:
                continue
            try:
                accepted[key] = _chapter_reading(row, segments[key], raw)
            except ValueError as exc:
                problems[key] = str(exc)
    missing = [key for key in segments if key not in accepted]
    save(receipt, {"binding": binding, "accepted": accepted})
    if missing:
        feedback = "只补当前分析包中的片段。逐字复制可以唯一定位的原文。"
        if not valid_identity:
            feedback += " 请按分析包返回正确的 window_id、source_sha256 和 chapter_rows。"
        feedback += "\n" + json.dumps({key: problems.get(key, "缺少有效阅读项") for key in missing}, ensure_ascii=False)
        write_chapter_input(window, raw, missing)
        save(prefix + ".feedback.md", feedback)
        print('<WF_REJECT_UPSTREAM target="agent_distill_batch">' + html.escape(feedback) + '</WF_REJECT_UPSTREAM>')
        return
    notes = [accepted[key] for key in segments]
    candidates = []
    for note in notes:
        if not note["technique"] or not note["guidance"]:
            continue
        proof = note["evidence"]
        try:
            candidate, _ = _checked_candidate({
                "mechanism": note["technique"], "transfer_guidance": note["guidance"], "constraints": [],
                "scopes": ["story-plan", "outline", "mvp"], "confidence": "medium",
                "application_scope": ["serial_chapter"],
                "evidence": [{**proof, "window_id": window["window_id"], "reason": "该原文展示了提炼的写法"}],
            }, window, raw, window["source_sha256"])
        except ValueError:
            continue
        candidates.append(candidate)
        if len(candidates) == 2:
            break
    data = load(MANIFEST)
    if data.get("run_id") != window["run_id"]:
        raise ValueError("窗口结果过期或身份不匹配")
    save(prefix + ".feedback.md", "")
    record_validation(data, window, {
        "run_id": window["run_id"], "source_sha256": window["source_sha256"], "window_id": window["window_id"],
        "source_mode": "serial_full", "chapter_readings": notes, "candidates": candidates,
        "style_observations": [], "conflict_patterns": [],
    })
    print(f'<script_out>已校验 {window["window_id"]} 的 {len(notes)} 个章节片段。</script_out>')


def validate_window(args):
    """Retain individually validated entries while retrying only open issues."""
    binding, window, raw = _frozen_window(args.window_id)
    prefix = f"learning/cache/{window['window_id']}"
    input_path = path(args.input)
    if not input_path.is_relative_to(path('learning/cache')):
        raise ValueError('模型回复必须位于本书学习缓存')
    stamp = input_path.stat().st_mtime_ns
    raw_bytes = input_path.read_bytes()
    attempt = [stamp, hashlib.sha256(raw_bytes).hexdigest()]
    try:
        response = json.loads(raw_bytes.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        response = None
    if "chapter_segments" in window:
        _validate_chapter_batch(binding, window, raw, response)
        return
    allowed_hashes = {window['source_sha256']}
    if window.get('source_mode') != 'serial_full':
        allowed_hashes.add(None)
    if (not isinstance(response, dict) or response.get('window_id') != window['window_id']
            or not isinstance(response.get("source_sha256"), (str, type(None)))
            or response.get('source_sha256') not in allowed_hashes):
        message = '模型返回的窗口身份或来源哈希不一致' if isinstance(response, dict) else '窗口分析回复必须是 JSON 对象'
        relative = _archive_window_reply(window['window_id'], binding, raw_bytes, response, [message])
        previous = path(prefix + '.feedback.md')
        notice = message + '。请按当前窗口编号和来源哈希重交。未通过回复：' + relative
        current = previous.read_text(encoding='utf-8-sig').strip() if previous.is_file() else ''
        feedback = current if current.startswith(notice) else '\n\n'.join(filter(None, (notice, current)))
        save(prefix + '.feedback.md', feedback)
        print('<WF_REJECT_UPSTREAM target="agent_distill_window">' + html.escape(feedback) + '</WF_REJECT_UPSTREAM>')
        return

    review_path = prefix + '.review.json'
    state = load(review_path) if path(review_path).is_file() else {}
    if state.get('binding') != binding:
        state = {'binding': binding, 'round': 0, 'accepted': {group: {} for group in WINDOW_GROUPS},
                 'dialogue': {}, 'pending': {}, 'unresolved': [], 'evidence_positions_relocated': 0}
    if state.get('attempt') != attempt and not state.get('finished'):
        reply_error = ''
        if state['round'] == 0:
            for group in WINDOW_GROUPS:
                _check_window_record(state, group, {'group': group, 'section': True,
                                     'value': response.get(group, None if group == 'candidates' else [])}, window, raw)
        else:
            reply_error = _apply_window_repairs(state, response, window, raw)
        if _frozen_window(args.window_id)[0] != binding or input_path.read_bytes() != raw_bytes:
            raise ValueError('校验期间来源或模型回复发生变化')
        problems = [item['error'] for item in state['pending'].values()]
        if reply_error:
            problems.insert(0, reply_error)
        if problems:
            relative = _archive_window_reply(window['window_id'], binding, raw_bytes, response, problems)
        if state['pending'] and state['round'] < MAX_ITEM_REPAIR_ROUNDS:
            state['round'] += 1
            state['feedback'] = _item_repair_feedback(state, reply_error, relative)
        else:
            state['finished'] = True
            state['feedback'] = ''
        state['attempt'] = attempt
        save(review_path, state)

    save(prefix + '.feedback.md', state['feedback'])
    if not state.get('finished'):
        print('<WF_REJECT_UPSTREAM target="agent_distill_window">' + html.escape(state['feedback']) + '</WF_REJECT_UPSTREAM>')
        return
    checked = _window_output(state, window)
    data = load(MANIFEST)
    if data.get('run_id') != window['run_id']:
        raise ValueError("窗口结果过期或身份不匹配")
    record_validation(data, window, checked)
    print(f'<script_out>已校验 {window["window_id"]}：{len(checked["candidates"])} 条候选，'
          f'{len(checked["unresolved"])} 项证据不足或未完成返修</script_out>')


def _candidate_similarity(left, right):
    """Conservative lexical similarity for paraphrased mechanisms.

    The Agent remains responsible for meaning; this only merges very close
    paraphrases after evidence validation and keeps all evidence/constraints.
    """
    if left.get('reading_objectives',[])!=right.get('reading_objectives',[]):return 0
    if any(left.get(key) != right.get(key) for key in ("dimension", "layer", "export_layout")):
        return 0.0
    left_text = re.sub(r"[\s，。；、：:（）()]+", "", left.get("mechanism", ""))
    right_text = re.sub(r"[\s，。；、：:（）()]+", "", right.get("mechanism", ""))
    if not left_text or not right_text:
        return 0.0
    return difflib.SequenceMatcher(None, left_text, right_text).ratio()


def _merge_similar(candidates):
    clusters = []
    by_shape = {}
    for candidate in candidates:
        # Different layers, dimensions or reading goals can never merge.
        shape = (candidate.get("dimension"), candidate.get("layer"), candidate.get("export_layout"),
                 digest(candidate["reading_objectives"]) if candidate.get("reading_objectives") else None)
        compatible = by_shape.setdefault(shape, [])
        match = next((cluster for cluster in compatible if _candidate_similarity(cluster[0], candidate) >= 0.72), None)
        if match is None:
            cluster = [candidate]
            clusters.append(cluster)
            compatible.append(cluster)
        else:
            match.append(candidate)
    merged = []
    for cluster in clusters:
        base = max(cluster, key=lambda item: (item.get("confidence") == "high", len(item.get("mechanism", ""))))
        merged_item = {**base, "evidence": []}
        evidence_sources = set()
        constraints = set()
        scopes = set()
        risk_flags = set()
        source_pov = set()
        target_pov = set()
        application_scope = set()
        variants = []
        for item in cluster:
            for proof in item.get("evidence", []):
                if proof not in merged_item["evidence"]:
                    merged_item["evidence"].append(proof)
            constraints.update(item.get("constraints", []))
            scopes.update(item.get("scopes", []))
            risk_flags.update(item.get("risk_flags", []))
            source_pov.update(item.get("source_pov", []))
            target_pov.update(item.get("target_pov", []))
            application_scope.update(item.get("application_scope", []))
            if item.get("mechanism") != base.get("mechanism"):
                variants.append(item.get("mechanism"))
            evidence_sources.update(proof.get("window_id", "") for proof in item.get("evidence", []))
        merged_item["constraints"] = sorted(constraints)
        merged_item["scopes"] = sorted(scopes)
        merged_item["risk_flags"] = sorted(risk_flags)
        merged_item["source_pov"] = sorted(source_pov)
        merged_item["target_pov"] = sorted(target_pov)
        merged_item["application_scope"] = sorted(application_scope)
        merged_item["support_count"] = len(evidence_sources)
        merged_item["variants"] = sorted(set(filter(None, variants)))
        samples = combine_samples(cluster)
        if samples:
            merged_item['dialogue_samples'] = samples
        merged.append(merged_item)
    return merged


def merge(args):
    data, _ = manifest()
    if data.get("source_mode") == "serial_full" and len(recovered_windows(data)) != len(data["windows"]):
        raise ValueError("尚有未通过校验或已过期的窗口，请恢复分析")
    merged = {}
    observations = []
    patterns = []
    unresolved = []
    for window in data["windows"]:
        packet = load(f"learning/cache/{window['window_id']}.validated.json")
        if (packet.get("source_sha256") != data["source"]["text_sha256"]
                or packet.get("window_id") != window["window_id"]
                or packet.get('run_id') != data.get('run_id')):
            raise ValueError("窗口结果过期或身份不匹配")
        unresolved.extend({**issue, 'window_id': window['window_id']} for issue in packet.get('unresolved', []))
        for key, target in (("style_observations", observations), ("conflict_patterns", patterns)):
            for item in packet.get(key, []):
                if item not in target:
                    target.append(item)
        for candidate in packet["candidates"]:
            current = merged.setdefault(candidate["candidate_id"], {**candidate, "evidence": []})
            samples = combine_samples([current, candidate])
            if samples:
                current['dialogue_samples'] = samples
            for proof in candidate["evidence"]:
                if proof not in current["evidence"]:
                    current["evidence"].append(proof)
    candidates = _merge_similar(list(merged.values()))
    completed = {w["window_id"] for w in data["windows"]}
    scope = write_progress(data, completed) if "chapters" in data else {}
    if scope:
        metadata = load("learning/dna/metadata.json")
        save("learning/dna/metadata.json", {**metadata, "source_coverage": scope})
    result = {"schema": "xs2.reference.candidates.v2", "source": data["source"], "run_id": data.get("run_id"),
              "source_mode": data.get("source_mode", "auto"), "source_coverage": scope,
              "covered_window_ids": [item["window_id"] for item in data["windows"]],
              "candidates": candidates, "style_observations": observations, "conflict_patterns": patterns}
    if unresolved:
        result['unresolved'] = unresolved
    result["candidates_sha256"] = digest(result["candidates"])
    from reference_choices import with_reference_choices
    result = with_reference_choices(result)
    save(CANDIDATES, result)
    review_page(result)
    writing_dna.bundle(result, candidates, observations, patterns, load, save)
    print(f"<script_out>已生成 {len(candidates)} 条候选（已合并近似机制）。请在 learning/selection.html 中选择写法；尚未自动采用。</script_out>")


def review_page(data):
    # All source fields are escaped before embedding in a local, script-free form.
    cards = []
    for candidate in data["candidates"]:
        proofs = "".join(f"<blockquote style='white-space:pre-wrap'>{html.escape(proof['excerpt'])}</blockquote>"
                         f"<p>{html.escape(proof['reason'])}（位置 {proof['source_start']}～{proof['source_end']}）</p>"
                         for proof in candidate["evidence"])
        dimension = DIMENSION_NAMES.get(candidate.get("dimension"))
        dimension_label = f"<p>参考维度：{dimension}</p>" if dimension else ""
        goals=''.join('<p>阅读目标：'+html.escape(g['intent'])+'；验收：'+html.escape(g['acceptance_question'])+'；边界：'+html.escape('；'.join(g.get('limits',[])))+'</p>' for g in candidate.get('reading_objectives',[]))
        cards.append(f"<article><label><input type='checkbox' value='{candidate['candidate_id']}'>"
                     f" {html.escape(candidate['mechanism'])}</label><p>{html.escape(candidate['transfer_guidance'])}</p>"
                     f"{dimension_label}"
                     f"<p>层次：{html.escape(candidate.get('layer', 'narrative_lens'))}；适用流程：{html.escape(', '.join(candidate['scopes']))}；置信度：{candidate['confidence']}；支持窗口：{candidate.get('support_count', 1)}</p>"
                     f"<p>视角兼容：{html.escape(candidate.get('pov_compatibility', 'adaptable'))}</p>"
                     f"<p>边界：{html.escape('；'.join(candidate['constraints']))}</p>{goals}"
                     f"<p>适配：{html.escape(candidate.get('adaptation_guidance', '无'))}</p>"
                     f"<p>风险：{html.escape('；'.join(candidate.get('risk_flags', [])) or '无')}</p><details><summary>查看依据</summary>{proofs}</details></article>")
    content = """<!doctype html><meta charset="utf-8"><title>选择参考写法</title>
<style>body{max-width:850px;margin:36px auto;font:16px/1.7 system-ui;background:#f5f6fa;padding:20px}article{background:white;padding:18px;margin:14px 0;border-radius:10px}button{padding:12px 24px}label{font-weight:bold}</style>
<h1>选择要用于这本小说的写法</h1><p>选择后下载 selection.json，放到本书工作区 learning/ 下，再运行“采用参考写法”工作流。已采用写法持续保留，本次只新增；空选择不会清空之前的写法。</p>
""" + "".join(cards) + """<button id="download">下载我的选择</button><script>
document.getElementById('download').onclick=()=>{
const selection={candidates_sha256:HASH, selected_candidate_ids:[...document.querySelectorAll('input:checked')].map(i=>i.value)};
const url=URL.createObjectURL(new Blob([JSON.stringify(selection,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};</script>""".replace("HASH", json.dumps(data["candidates_sha256"]))
    save("learning/selection.html", content)


def adopt(args):
    from reference_choices import DIMENSION_NAMES, active_blueprint, with_reference_choices, text
    data = load(CANDIDATES)
    if data.get("candidates_sha256") != digest(data["candidates"]):
        raise ValueError("候选文件被修改，请重新蒸馏")
    selection_text = getattr(args, "selection_json", "").strip()
    selection = json.loads(selection_text) if selection_text else load(args.selection)
    if not isinstance(selection, dict) or selection.get("candidates_sha256") != data["candidates_sha256"]:
        raise ValueError("选择文件对应的候选已变化，请重新选择")
    data = with_reference_choices(data)
    ids = selection.get("selected_candidate_ids")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("必须显式提供不重复的候选 ID 数组")
    by_id = {item["candidate_id"]: item for item in data["candidates"]}
    active, previous = active_blueprint(Path.cwd())
    if active:
        if previous.get("selected_candidate_ids") != [item["candidate_id"] for item in previous["mechanisms"]]:
            raise ValueError("已采用蓝图的机制与选择记录不一致")
    retained = previous.get("selected_candidate_ids", [])
    if not set(ids) <= set(by_id) | set(retained):
        raise ValueError("选择了不存在的候选写法")
    additions = [item for item in ids if item not in retained]
    reference_additions = {}
    for kind in ("style", "conflict"):
        chosen = selection.get("selected_" + kind + "_ids", [])
        retained_refs = previous.get("selected_" + kind + "_ids", [])
        if not isinstance(chosen, list) or any(not isinstance(item, str) for item in chosen) or len(set(chosen)) != len(chosen):
            raise ValueError("风格或冲突选择必须是无重复 ID 数组")
        choices = {item["choice_id"]: item for item in data[kind + "_choices"]}
        if not set(chosen) <= set(choices) | set(retained_refs):
            raise ValueError("选择了不存在的风格或冲突")
        added = [item for item in chosen if item not in retained_refs]
        if added and selection.get("reference_choices_sha256") != data["reference_choices_sha256"]:
            raise ValueError("风格与冲突分析已变化，请刷新后重新选择")
        reference_additions[kind] = []
        adaptations = selection.get("reference_adaptations", {})
        if not isinstance(adaptations, dict):
            raise ValueError("本书适配说明格式无效")
        for identifier in added:
            choice = choices[identifier]
            guidance = text(adaptations.get(identifier)) or (choice["transfer_guidance"] if not choice["requires_adaptation"] else "")
            if not guidance:
                raise ValueError("请先为所选风格或冲突填写本书适配说明，再确认采用")
            reference_additions[kind].append({"choice_id": identifier, "kind": kind,
                "title": choice["title"], "guidance": guidance, "source": choice["source"],
                "application_scope": choice.get("application_scope", ["general"]),
                "limits": choice.get("limits", []), "adaptation_status": "confirmed"})
    if active and not additions and not any(reference_additions.values()):
        render_adopted_contexts()
        print(f"<script_out>已保留 {len(retained)} 条写法，本次没有新增，无需重复采用。</script_out>")
        return
    version = active.get("version", 0) + 1
    mechanisms = list(previous.get("mechanisms", []))
    for item in additions:
        mechanism = {key: by_id[item].get(key) for key in (
            "candidate_id", "mechanism", "layer", "transfer_guidance", "constraints", "scopes",
            "source_pov", "target_pov", "pov_compatibility", "adaptation_guidance", "risk_flags",
            "application_scope", "support_count", "variants")}
        if by_id[item].get('reading_objectives'):
            mechanism['reading_objectives']=reading().definitions(by_id[item]['reading_objectives'])
        dimension = by_id[item].get('dimension')
        if dimension:
            if dimension not in DIMENSION_NAMES:
                raise ValueError('蒸馏写法维度无效')
            mechanism.update(dimension=dimension, evidence=by_id[item]['evidence'])
            if dimension == 'voice' and by_id[item].get('dialogue_samples'):
                mechanism['layer'] = 'dialogue'
            if dimension == 'layout' and by_id[item].get('export_layout'):
                mechanism['export_layout'] = by_id[item]['export_layout']
            if dimension != 'topic' and not mechanism.get('reading_objectives'):
                mechanism['reading_objectives'] = [{
                    'dimension': 'voice' if dimension == 'voice' else 'custom',
                    'intent': mechanism['transfer_guidance'],
                    'planning_question': '本书哪一场的实际处境适合借鉴这条方法？',
                    'acceptance_question': reading().creative().REFERENCE_QUESTION,
                    'limits': mechanism.get('constraints') or [],
                }]
        mechanism["source"] = by_id[item].get("source") or data["source"]
        mechanisms.append(mechanism)
    sources = list(previous.get("sources") or ([previous["source"]] if previous.get("source") else []))
    for source in [data["source"], *data.get("sources", [])]:
        if source not in sources:
            sources.append(source)
    blueprint = {"schema": "xs2.project.learning.blueprint.v1", "version": version,
                 "created_at": datetime.now(timezone.utc).isoformat(), "source": data["source"],
                 "sources": sources,
                 "candidate_set_sha256": data["candidates_sha256"],
                 "selected_candidate_ids": [*retained, *additions],
                 "mechanisms": mechanisms}
    for kind, values in reference_additions.items():
        plural = "styles" if kind == "style" else "conflicts"
        blueprint[plural] = [*previous.get(plural, []), *values]
        blueprint["selected_" + kind + "_ids"] = [*previous.get("selected_" + kind + "_ids", []), *[item["choice_id"] for item in values]]
    target = f"learning/blueprints/v{version:04d}.json"
    if path(target).exists():
        raise ValueError("蓝图版本已存在，不允许覆盖")
    save(target, blueprint)
    save(ACTIVE, {"version": version, "blueprint_path": target, "blueprint_sha256": digest(blueprint)})
    render_adopted_contexts()
    print(f"<script_out>已保留 {len(retained)} 条写法；本次新增 {len(additions)} 条写法、{len(reference_additions['style'])} 条风格、{len(reference_additions['conflict'])} 条冲突。创作蓝图版本 v{version:04d}</script_out>")


def prepare_choices(args):
    from reference_choices import with_reference_choices
    data = load(CANDIDATES) if path(CANDIDATES).exists() else {"source": {}, "candidates": [], "candidates_sha256": digest([])}
    save(CANDIDATES, with_reference_choices(data))
    print("<script_out>风格、写法与冲突候选已准备；暂无参考时可继续原创创作。</script_out>")


def analyze_dimensions(args):
    """Perform multi-dimensional analysis on reference material."""
    from distillation_upgrade import ReferenceAnalysisUpgrade
    
    analyzer = ReferenceAnalysisUpgrade(load, save, digest)
    
    print("正在进行多维度分析...")
    combined_analysis = analyzer.perform_analysis()
    
    print("正在增强候选数据...")
    analyzer.enhance_candidates(combined_analysis)
    
    print("正在保存分析结果...")
    analyzer.save_analyses(combined_analysis)
    
    plot_count = combined_analysis["analyses"]["plot"]["plot_dimensions"]["conflict_escalation"]["count"]
    char_count = combined_analysis["analyses"]["character"]["character_dimensions"]["character_arcs"]["count"]
    conflict_count = combined_analysis["analyses"]["conflict"]["conflict_dimensions"]["escalation_paths"]["count"]
    technique_count = combined_analysis["analyses"]["technique"]["technique_dimensions"]["dialogue_craft"]["count"]
    
    print(f"<script_out>多维度分析完成：剧情 {plot_count} 项、角色 {char_count} 项、冲突 {conflict_count} 项、技法 {technique_count} 项。分析结果已保存至 learning/analysis/</script_out>")


def validate_analysis(args):
    """Validate analysis results for completeness and consistency."""
    if not path("learning/reference_analysis.json").exists():
        raise ValueError("分析文件不存在，请先执行 analyze-dimensions")
    
    analysis = load("learning/reference_analysis.json")
    
    # Validate schema
    if analysis.get("schema") != "xs2.reference.multi_dimensional_analysis.v1":
        raise ValueError("分析文件格式版本不匹配")
    
    # Validate presence of all dimensions
    required_dims = ["plot", "character", "conflict", "technique"]
    analyses = analysis.get("analyses", {})
    missing = [dim for dim in required_dims if dim not in analyses]
    
    if missing:
        raise ValueError(f"分析结果缺失维度：{', '.join(missing)}")
    
    # Validate summaries
    summary = analysis.get("summary", {})
    for dim in required_dims:
        if not summary.get(dim):
            print(f"警告：{dim} 维度的摘要为空")
    
    print("<script_out>分析结果验证通过。所有维度数据完整。</script_out>")


def generate_summary(args):
    """Generate human-readable summary of all analyses."""
    if not path("learning/reference_analysis.json").exists():
        raise ValueError("分析文件不存在，请先执行 analyze-dimensions")
    
    analysis = load("learning/reference_analysis.json")
    summary = analysis.get("summary", {})
    source = analysis.get("source", {})
    
    lines = [
        "# 参考小说多维度分析摘要",
        "",
        f"来源：{source.get('title', '未知')}",
        f"作者：{source.get('author', '未知')}",
        "",
        summary.get("plot", "剧情分析数据不足"),
        "",
        summary.get("character", "角色分析数据不足"),
        "",
        summary.get("conflict", "冲突分析数据不足"),
        "",
        summary.get("technique", "技法分析数据不足"),
        "",
        "# 应用指南",
        "",
        "以上分析提取的是可迁移的创作技巧和设计模式，不是具体内容。",
        "应用时必须：",
        "1. 创造本书独特的人物、情节和世界观",
        "2. 禁止复制参考作品的具体台词、场景或事件",
        "3. 根据本书篇幅和风格重新设计所有元素",
        "4. 定期进行原创性检测，避免无意识模仿"
    ]
    
    summary_text = "\n".join(lines)
    save("learning/analysis_summary.md", summary_text)
    
    print("<script_out>分析摘要已生成：learning/analysis_summary.md</script_out>")


def check_originality(args):
    """Check writing originality against reference."""
    from distillation_upgrade import OriginalityDetector
    
    if not args.input:
        raise ValueError("必须指定待检测文本文件路径 --input")
    
    if not path(args.input).exists():
        raise ValueError(f"文件不存在：{args.input}")
    
    text = path(args.input).read_text(encoding="utf-8")
    threshold = args.threshold if hasattr(args, 'threshold') and args.threshold else 0.75
    
    detector = OriginalityDetector(load, save)
    result = detector.check_originality(text, threshold)
    report = detector.generate_report(result)
    
    # Save report
    save("learning/originality_report.json", result)
    save("learning/originality_report.md", report)
    
    status = "通过" if result.get("original") else "存在问题"
    max_sim = result.get("max_similarity", 0)
    print(f"<script_out>原创性检测完成：{status}。最高相似度 {max_sim:.1%}。报告已保存至 learning/originality_report.md</script_out>")


def render_adopted_contexts():
    render('all')
    for scope in ('novel-advisor', 'character', 'story-plan', 'outline', 'export'):
        render(scope)
    for scope in ('mvp', 'polish'):
        if not path(f'learning/receipts/{scope}.json').is_file():
            render(scope)


def render(scope, chapter=None):
    from reference_choices import DIMENSION_NAMES, active_blueprint, mechanism_scopes, text
    lines = ["# 用户已选写法（创作参考）", "",
             "本页的蒸馏写法、风格、对白和冲突方法均按场景自选，可改用或略过。以作者明确要求、人物此刻的处境和声音、以及本书事实为准。",
             reading().creative().REFERENCE_GUIDANCE, ""]
    version = 0
    has_reference = False
    dialogue_receipt = {'applied':0, 'pending':0, 'skipped':0}
    candidate_ids = []
    shown_guidance = {}
    active, blueprint = active_blueprint(Path.cwd())
    if active:
        version = active["version"]
        lines.extend([f"蓝图版本：v{version:04d}。以下是适合当前阶段的参考。", ""])
        for item in blueprint["mechanisms"]:
            dimension = item.get('dimension')
            if scope == 'all' and dimension or scope != 'all' and scope not in mechanism_scopes(item):
                continue
            if dimension == 'voice' and item.get('layer') == 'dialogue' and scope in ('mvp', 'polish'):
                continue  # Dialogue guidance is injected by the verified scene adaptation below.
            has_reference = True
            if item.get('candidate_id'):
                candidate_ids.append(item['candidate_id'])
            if dimension:
                shown_guidance[item['candidate_id']] = item['transfer_guidance']
                lines.extend([f"## {DIMENSION_NAMES[dimension]}", item['transfer_guidance']])
                limits = text(item.get('constraints'))
                lines.extend(['使用边界：' + limits, ''] if limits else [''])
                continue
            lines.extend([f"## {item['mechanism']}", item["transfer_guidance"],
                          "分析层次：" + str(item.get("layer") or "narrative_lens"),
                          "使用边界：" + "；".join(item.get("constraints") or []),
                          "视角兼容：" + str(item.get("pov_compatibility") or "adaptable"),
                          "视角适配：" + str(item.get("adaptation_guidance") or "无"),
                          "篇幅适用：" + "、".join(item.get("application_scope") or ["general"]),
                          "风险提示：" + ("；".join(item.get("risk_flags") or []) or "无"), ""])
        for kind, label in (("styles", "本书已选风格参考"), ("conflicts", "本书已选冲突推进参考")):
            values = blueprint.get(kind, [])
            if not values:
                continue
            has_reference = True
            lines.extend(["# " + label, ""])
            for index, item in enumerate(values, 1):
                # Deliberately omit source titles/plots, excerpts and statistics.
                lines.extend([f"## {index}. 已确认适配", item["guidance"], "使用边界：" + text(item.get("limits")), ""])
        lines.extend(["参考风格与本书基线共同使用：作者明确要求和既有事实优先，人物声音结合当下处境理解。模型生成的风格偏好不自动成为禁令；不改写已保存的基线或作者禁令。",
                      "风格是表达倾向，不是句长或标点配额；根据场景允许变化，避免每段机械执行全部规则。",
                      "使用冲突参考时，可借鉴它怎样改变人物的选择、代价或关系，按本书情节取舍。", ""])
        excluded = {item['candidate_id'] for item in blueprint['mechanisms']
                    if item.get('dimension') and scope not in mechanism_scopes(item)}
        eligible = [identifier for identifier in blueprint.get('selected_candidate_ids', [])
                    if identifier not in excluded]
        dialogue_lines, dialogue_receipt = render_adaptations(
            Path.cwd(), {**blueprint, 'selected_candidate_ids': eligible}, scope, chapter)
        lines.extend(dialogue_lines)
        has_reference = has_reference or bool(dialogue_receipt['applied'])
    if not has_reference:
        lines.append("本阶段没有已选参考写法，按作者原创设定正常创作。")
    objectives=reading().for_book(Path.cwd()) if active and any(r.get('reading_objectives') for r in blueprint.get('mechanisms',[])) else None
    if objectives:
        adapted = {match['reference_id'] for match in dialogue_receipt.get('matches', [])}
        objectives['objectives'] = [goal for goal in objectives['objectives']
                                    if goal['source_candidate_id'] in candidate_ids
                                    or goal['source_candidate_id'] in adapted]
        for goal in objectives['objectives']:
            if goal['intent'] == shown_guidance.get(goal['source_candidate_id']):
                goal.pop('intent')
        objectives = objectives if objectives['objectives'] else None
    if objectives:
        lines.extend(['','## 范文阅读效果参考',json.dumps(reading().model_view(objectives),ensure_ascii=False,indent=2),
            '按当前场景需要借鉴阅读效果，审核可给建议，采用与否由人物和场景决定。'])
    advisor_file = path("learning/advisor_report.json")
    if advisor_file.exists() and scope not in {'novel-advisor', 'export'}:
        try:
            advisor = load("learning/advisor_report.json")
            lines.extend(["", "# 小说顾问建议", "以下建议用于辅助创作决策；如果与作者明确要求冲突，以作者要求为准。", json.dumps(advisor, ensure_ascii=False, indent=2)])
        except (OSError, ValueError):
            lines.extend(["", "# 小说顾问建议", "顾问报告存在但暂时无法解析，请以页面展示的报告为准。"])
    lines.extend(["仅使用抽象机制。不得推测或复用参考作品人物、事件、句子和包装。", ""])
    target = "learning/active_context.md" if scope == "all" else f"learning/context/{scope}.md"
    save(target, "\n".join(lines))
    # Per-stage receipt makes the consumed version inspectable without inserting provenance in prompts.
    save(f"learning/receipts/{scope}.json", {"blueprint_version": version, "context_path": target,
                                            "blueprint_sha256": active.get('blueprint_sha256'),
                                            "dialogue":dialogue_receipt, "chapter":chapter, "candidate_ids":candidate_ids,
                                            "task_id": os.environ.get('TASK_ID', ''),
                                            "context_sha256": digest("\n".join(lines) + "\n")})


def main():
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    split_parser = commands.add_parser("split")
    split_parser.add_argument("--input", required=True)
    split_parser.add_argument("--window", type=int, default=4200)
    split_parser.add_argument("--overlap", type=int, default=400)
    split_parser.add_argument("--batch-max-chapters", type=int)
    split_parser.add_argument("--batch-max-chars", type=int)
    split_parser.add_argument("--source-mode", default="auto")
    split_parser.add_argument("--learning-direction", choices=['general','zhihu_short','custom'], default='general')
    split_parser.add_argument("--learning-focus", default='')
    split_parser.set_defaults(handler=split)
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("--input", required=True)
    normalize_parser.add_argument("--window-id", required=True)
    normalize_parser.set_defaults(handler=normalize)
    validation_parser=commands.add_parser('validate-window')
    validation_parser.add_argument('--input',required=True)
    validation_parser.add_argument('--window-id',required=True)
    validation_parser.set_defaults(handler=validate_window)
    commands.add_parser("merge").set_defaults(handler=merge)
    def cross_action(args):
        import cross_chapter
        if args.command == "cross-prepare":
            cross_chapter.prepare()
        elif args.command == "cross-validate":
            cross_chapter.validate(args.batch_id)
        else:
            cross_chapter.finalize()
    commands.add_parser("cross-prepare").set_defaults(handler=cross_action)
    cross_parser = commands.add_parser("cross-validate")
    cross_parser.add_argument("--batch-id", required=True)
    cross_parser.set_defaults(handler=cross_action)
    commands.add_parser("cross-finalize").set_defaults(handler=cross_action)
    commands.add_parser("prepare-choices").set_defaults(handler=prepare_choices)
    dna_parser = commands.add_parser("finalize-dna")
    dna_parser.add_argument("--input", default="learning/dna/summary.raw.json")
    dna_parser.set_defaults(handler=lambda args: writing_dna.finalize(args, load, save, digest))
    adopt_parser = commands.add_parser("adopt")
    adopt_parser.add_argument("--selection", default="learning/selection.json")
    adopt_parser.add_argument("--selection-json", default="", help="网页提交的候选哈希与选择 ID，优先于选择文件")
    adopt_parser.set_defaults(handler=adopt)
    prepare_parser = commands.add_parser("prepare-context")
    prepare_parser.add_argument("--scope", choices=sorted(SCOPES), required=True)
    prepare_parser.add_argument("--chapter", default=None)
    prepare_parser.set_defaults(handler=lambda args: render(args.scope, args.chapter))
    analyze_parser = commands.add_parser("analyze-dimensions")
    analyze_parser.set_defaults(handler=analyze_dimensions)
    validate_parser = commands.add_parser("validate-analysis")
    validate_parser.set_defaults(handler=validate_analysis)
    summary_parser = commands.add_parser("generate-summary")
    summary_parser.set_defaults(handler=generate_summary)
    originality_parser = commands.add_parser("check-originality")
    originality_parser.add_argument("--input", required=True, help="待检测的文本文件")
    originality_parser.add_argument("--threshold", type=float, default=0.75, help="相似度阈值 (0-1)")
    originality_parser.set_defaults(handler=check_originality)
    args = root.parse_args()
    try:
        args.handler(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"参考学习未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
