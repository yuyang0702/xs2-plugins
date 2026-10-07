#!/usr/bin/env python3
"""Standalone XS2 learning contract; standard library only, cwd = workspace.

Model calls belong to Workflow Agent nodes. Source/evidence stays in learning/;
only explicitly selected abstract mechanisms enter generation context.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import writing_dna

MANIFEST = "learning/cache/windows.json"
CANDIDATES = "learning/candidates.json"
ACTIVE = "learning/active.json"
SCOPES = {"build", "character", "story-plan", "outline", "mvp", "polish", "post-hoc"}
LAYERS = {"language", "structure", "narrative_lens", "dialogue", "imagery", "theme", "character"}
POV_COMPATIBILITY = {"direct", "adaptable", "risky"}
APPLICATION_SCOPES = {"short_full", "serial_opening", "serial_chapter", "serial_arc", "general"}

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
    temporary = target.with_suffix(target.suffix + ".tmp")
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
    writing_dna.prepare(raw, source, getattr(args, "source_mode", "auto"), save)
    save("learning/dna/upstream.json", json.loads((Path(__file__).parent / "vendor/writing-dna-skill/UPSTREAM.json").read_text(encoding="utf-8")))
    windows = []
    start = 0
    while start < len(raw):
        upper = min(len(raw), start + args.window)
        ends = [start + match.end() for match in re.finditer(r"[。！？!?；;\n]", raw[start:upper])]
        end = max([point for point in ends if point >= start + args.window // 2], default=upper)
        if upper == len(raw):
            end = upper
        window_id = f"window-{len(windows) + 1:04d}"
        packet = {"window_id": window_id, "source_start": start, "source_end": end,
                  "text": raw[start:end], "source_sha256": source_hash}
        # IDs let a model select exact evidence without retyping font-obfuscated
        # characters. Positions and excerpts are generated from the real source.
        catalog = []
        for line in re.finditer(r"[^\n]+", packet["text"]):
            for offset in range(line.start(), line.end(), 160):
                stop = min(offset + 160, line.end())
                if packet["text"][offset:stop].strip():
                    catalog.append({"evidence_id": f"{window_id}-e{len(catalog)+1:04d}",
                                    "source_start": start + offset, "source_end": start + stop,
                                    "excerpt": raw[start + offset:start + stop]})
        packet["evidence_catalog"] = catalog
        windows.append(packet)
        if len(windows) > 100:
            raise ValueError("超过 Core 的 100 窗口上限，请分卷导入或增大窗口")
        if end == len(raw):
            break
        start = end - args.overlap
    save(MANIFEST, {"schema": "xs2.reference.windows.v1", "source": source, "windows": windows})
    for window in windows:
        save(f"learning/cache/{window['window_id']}.json", window)
    ids = json.dumps([item["window_id"] for item in windows])
    print(f"<WF_VAR>window_ids:{ids}</WF_VAR>")
    print(f"<script_out>已完整分窗：{len(windows)} 个窗口</script_out>")


def evidence_position(proof, window, raw):
    if not isinstance(proof, dict):
        raise ValueError("证据必须是对象")
    if proof.get("window_id") != window["window_id"]:
        raise ValueError("证据窗口身份不一致")
    if proof.get("evidence_id"):
        selected = next((item for item in window.get("evidence_catalog", [])
                         if item["evidence_id"] == proof["evidence_id"]), None)
        if selected is None:
            raise ValueError("证据编号不属于当前窗口")
        start, end, excerpt = selected["source_start"], selected["source_end"], selected["excerpt"]
        if not window["source_start"] <= start < end <= window["source_end"] or raw[start:end] != excerpt:
            raise ValueError("证据目录与来源快照不一致")
        return start, end, excerpt, False
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


def normalize(args):
    data, raw = manifest()
    window = next((item for item in data["windows"] if item["window_id"] == args.window_id), None)
    if window is None:
        raise ValueError("未知窗口")
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
    if not items and not source_sha256:
        source_sha256 = data["source"]["text_sha256"]
    if source_sha256 != data["source"]["text_sha256"]:
        raise ValueError("模型返回的窗口身份或来源哈希不一致")
    candidates = []
    observations, patterns = writing_dna.checked_extras(payload, window, raw, text_field, strings, evidence_position)
    relocated = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("候选必须是对象")
        mechanism = text_field(item, "mechanism", 100)
        guidance = text_field(item, "transfer_guidance")
        constraints = strings(item, "constraints")
        scopes = strings(item, "scopes", False)
        misplaced = set(scopes) & APPLICATION_SCOPES
        scopes = [scope for scope in scopes if scope not in misplaced]
        if not scopes or not set(scopes) <= SCOPES:
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
        candidates.append({"candidate_id": "mechanism-" + digest(semantic)[:20],
                           **semantic, "confidence": confidence, "evidence": checked})
    save(f"learning/cache/{window['window_id']}.validated.json",
         {"source_sha256": source_sha256, "window_id": window["window_id"],
          "evidence_positions_relocated": relocated, "candidates": candidates,
          "style_observations": observations, "conflict_patterns": patterns})
    print(f"<script_out>已校验 {window['window_id']}：{len(candidates)} 条候选，精确定位修正 {relocated} 条证据</script_out>")


def _candidate_similarity(left, right):
    """Conservative lexical similarity for paraphrased mechanisms.

    The Agent remains responsible for meaning; this only merges very close
    paraphrases after evidence validation and keeps all evidence/constraints.
    """
    if left.get("layer") != right.get("layer"):
        return 0.0
    left_text = re.sub(r"[\s，。；、：:（）()]+", "", left.get("mechanism", ""))
    right_text = re.sub(r"[\s，。；、：:（）()]+", "", right.get("mechanism", ""))
    if not left_text or not right_text:
        return 0.0
    return difflib.SequenceMatcher(None, left_text, right_text).ratio()


def _merge_similar(candidates):
    clusters = []
    for candidate in candidates:
        match = next((cluster for cluster in clusters if _candidate_similarity(cluster[0], candidate) >= 0.72), None)
        if match is None:
            clusters.append([candidate])
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
        merged.append(merged_item)
    return merged


def merge(args):
    data, _ = manifest()
    merged = {}
    observations = []
    patterns = []
    for window in data["windows"]:
        packet = load(f"learning/cache/{window['window_id']}.validated.json")
        if packet.get("source_sha256") != data["source"]["text_sha256"] or packet.get("window_id") != window["window_id"]:
            raise ValueError("窗口结果过期或身份不匹配")
        for key, target in (("style_observations", observations), ("conflict_patterns", patterns)):
            for item in packet.get(key, []):
                if item not in target:
                    target.append(item)
        for candidate in packet["candidates"]:
            current = merged.setdefault(candidate["candidate_id"], {**candidate, "evidence": []})
            for proof in candidate["evidence"]:
                if proof not in current["evidence"]:
                    current["evidence"].append(proof)
    candidates = _merge_similar(list(merged.values()))
    result = {"schema": "xs2.reference.candidates.v2", "source": data["source"],
              "covered_window_ids": [item["window_id"] for item in data["windows"]],
              "candidates": candidates, "style_observations": observations, "conflict_patterns": patterns}
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
        proofs = "".join(f"<p>{html.escape(proof['excerpt'])}（位置 {proof['source_start']}～{proof['source_end']}）</p>" for proof in candidate["evidence"])
        cards.append(f"<article><label><input type='checkbox' value='{candidate['candidate_id']}'>"
                     f" {html.escape(candidate['mechanism'])}</label><p>{html.escape(candidate['transfer_guidance'])}</p>"
                     f"<p>层次：{html.escape(candidate.get('layer', 'narrative_lens'))}；适用流程：{html.escape(', '.join(candidate['scopes']))}；置信度：{candidate['confidence']}；支持窗口：{candidate.get('support_count', 1)}</p>"
                     f"<p>视角兼容：{html.escape(candidate.get('pov_compatibility', 'adaptable'))}</p>"
                     f"<p>边界：{html.escape('；'.join(candidate['constraints']))}</p>"
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
    from reference_choices import with_reference_choices, text
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
    previous = {}
    active = load(ACTIVE) if path(ACTIVE).exists() else {}
    if active:
        previous = load(active["blueprint_path"])
        if digest(previous) != active["blueprint_sha256"]:
            raise ValueError("已采用蓝图校验失败，不能覆盖已有写法")
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
        render("all")
        print(f"<script_out>已保留 {len(retained)} 条写法，本次没有新增，无需重复采用。</script_out>")
        return
    version = active.get("version", 0) + 1
    mechanisms = list(previous.get("mechanisms", []))
    for item in additions:
        mechanism = {key: by_id[item].get(key) for key in (
            "candidate_id", "mechanism", "layer", "transfer_guidance", "constraints", "scopes",
            "source_pov", "target_pov", "pov_compatibility", "adaptation_guidance", "risk_flags",
            "application_scope", "support_count", "variants")}
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
    render("all")
    print(f"<script_out>已保留 {len(retained)} 条写法；本次新增 {len(additions)} 条写法、{len(reference_additions['style'])} 条风格、{len(reference_additions['conflict'])} 条冲突。创作蓝图版本 v{version:04d}</script_out>")


def prepare_choices(args):
    from reference_choices import with_reference_choices
    data = load(CANDIDATES) if path(CANDIDATES).exists() else {"source": {}, "candidates": [], "candidates_sha256": digest([])}
    save(CANDIDATES, with_reference_choices(data))
    print("<script_out>风格、写法与冲突候选已准备；暂无参考时可继续原创创作。</script_out>")


def render(scope):
    lines = ["# 用户已选写法", ""]
    version = 0
    has_reference = False
    if path(ACTIVE).exists():
        active = load(ACTIVE)
        blueprint = load(active["blueprint_path"])
        if digest(blueprint) != active["blueprint_sha256"]:
            raise ValueError("创作蓝图被修改，请重新确认")
        version = active["version"]
        lines.extend([f"蓝图版本：v{version:04d}。只将已选机制用于当前阶段；与作者当前创意冲突时说明冲突，禁止强行套用。", ""])
        for item in blueprint["mechanisms"]:
            if scope != "all" and scope not in item["scopes"]:
                continue
            has_reference = True
            lines.extend([f"## {item['mechanism']}", item["transfer_guidance"],
                          "分析层次：" + str(item.get("layer") or "narrative_lens"),
                          "使用边界：" + "；".join(item.get("constraints") or []),
                          "视角兼容：" + str(item.get("pov_compatibility") or "adaptable"),
                          "视角适配：" + str(item.get("adaptation_guidance") or "无"),
                          "篇幅适用：" + "、".join(item.get("application_scope") or ["general"]),
                          "风险提示：" + ("；".join(item.get("risk_flags") or []) or "无"), ""])
        from reference_choices import text
        for kind, label in (("styles", "本书已确认的风格原则"), ("conflicts", "本书已确认的冲突推进参考")):
            values = blueprint.get(kind, [])
            if not values:
                continue
            has_reference = True
            lines.extend(["# " + label, ""])
            for index, item in enumerate(values, 1):
                # Deliberately omit source titles/plots, excerpts and statistics.
                lines.extend([f"## {index}. 已确认适配", item["guidance"], "使用边界：" + text(item.get("limits")), ""])
        lines.extend(["参考风格与本书基线共同使用：已有正文的统一风格、事实、人物声音和作者意图优先。发现冲突时提出适配建议，不自动替换基线，不清除旧规则。",
                      "风格是表达倾向，不是句长或标点配额；根据场景允许变化，避免每段机械执行全部规则。",
                      "冲突参考须落实成本书的目标、前置伏笔、阻碍、行动、代价和回收，写入现有大纲与冲突/伏笔账本。短篇回收核心问题，长篇普通章保留主线压力；无前置依据不得突发新危机。", ""])
    if not has_reference:
        lines.append("本阶段没有已选参考写法，按作者原创设定正常创作。")
    advisor_file = path("learning/advisor_report.json")
    if advisor_file.exists():
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
                                            "context_sha256": digest("\n".join(lines) + "\n")})


def main():
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    split_parser = commands.add_parser("split")
    split_parser.add_argument("--input", required=True)
    split_parser.add_argument("--window", type=int, default=4200)
    split_parser.add_argument("--overlap", type=int, default=400)
    split_parser.add_argument("--source-mode", default="auto")
    split_parser.set_defaults(handler=split)
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("--input", required=True)
    normalize_parser.add_argument("--window-id", required=True)
    normalize_parser.set_defaults(handler=normalize)
    commands.add_parser("merge").set_defaults(handler=merge)
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
    prepare_parser.set_defaults(handler=lambda args: render(args.scope))
    args = root.parse_args()
    try:
        args.handler(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"参考学习未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
