#!/usr/bin/env python3
"""Standalone XS2 learning contract; standard library only, cwd = workspace.

Model calls belong to Workflow Agent nodes. Source/evidence stays in learning/;
only explicitly selected abstract mechanisms enter generation context.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "learning/cache/windows.json"
CANDIDATES = "learning/candidates.json"
ACTIVE = "learning/active.json"
SCOPES = {"story-plan", "outline", "mvp", "polish", "post-hoc"}


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


def normalize(args):
    data, raw = manifest()
    window = next((item for item in data["windows"] if item["window_id"] == args.window_id), None)
    if window is None:
        raise ValueError("未知窗口")
    payload = load(args.input)
    if (not isinstance(payload, dict) or payload.get("window_id") != window["window_id"]
            or payload.get("source_sha256") != data["source"]["text_sha256"]):
        raise ValueError("模型返回的窗口身份或来源哈希不一致")
    items = payload.get("candidates")
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError("每个窗口须返回至多 12 条 candidates（允许空数组）")
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("候选必须是对象")
        mechanism = text_field(item, "mechanism", 100)
        guidance = text_field(item, "transfer_guidance")
        constraints = strings(item, "constraints")
        scopes = strings(item, "scopes", False)
        if not set(scopes) <= SCOPES:
            raise ValueError("候选包含未知流程范围")
        confidence = item.get("confidence")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("confidence 只能为 high、medium、low")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError("每条候选需要 1～8 条证据")
        checked = []
        for proof in evidence:
            if not isinstance(proof, dict):
                raise ValueError("证据必须是对象")
            start, end = proof.get("source_start"), proof.get("source_end")
            excerpt = text_field(proof, "excerpt", 300)
            if (proof.get("window_id") != window["window_id"] or type(start) is not int
                    or type(end) is not int or not window["source_start"] <= start < end <= window["source_end"]
                    or raw[start:end] != excerpt):
                raise ValueError("证据位置或摘录与原文不匹配")
            checked.append({"window_id": window["window_id"], "source_start": start,
                            "source_end": end, "excerpt": excerpt, "reason": text_field(proof, "reason")})
        # Reject literal copying in generation-facing fields; semantic abstraction
        # still requires the user to inspect candidates before selection.
        for value in [mechanism, guidance, *constraints]:
            if any(value[offset:offset + 20] in raw for offset in range(max(0, len(value) - 19))):
                raise ValueError("抽象写法包含连续 20 字原文，请重新提炼")
        semantic = {"mechanism": mechanism, "transfer_guidance": guidance,
                    "constraints": constraints, "scopes": scopes}
        candidates.append({"candidate_id": "mechanism-" + digest(semantic)[:20],
                           **semantic, "confidence": confidence, "evidence": checked})
    save(f"learning/cache/{window['window_id']}.validated.json",
         {"source_sha256": data["source"]["text_sha256"], "window_id": window["window_id"], "candidates": candidates})


def merge(args):
    data, _ = manifest()
    merged = {}
    for window in data["windows"]:
        packet = load(f"learning/cache/{window['window_id']}.validated.json")
        if packet.get("source_sha256") != data["source"]["text_sha256"] or packet.get("window_id") != window["window_id"]:
            raise ValueError("窗口结果过期或身份不匹配")
        for candidate in packet["candidates"]:
            current = merged.setdefault(candidate["candidate_id"], {**candidate, "evidence": []})
            for proof in candidate["evidence"]:
                if proof not in current["evidence"]:
                    current["evidence"].append(proof)
    result = {"schema": "xs2.reference.candidates.v1", "source": data["source"],
              "covered_window_ids": [item["window_id"] for item in data["windows"]],
              "candidates": list(merged.values())}
    result["candidates_sha256"] = digest(result["candidates"])
    save(CANDIDATES, result)
    review_page(result)
    print(f"<script_out>已生成 {len(merged)} 条候选。请在 learning/selection.html 中选择写法；尚未自动采用。</script_out>")


def review_page(data):
    # All source fields are escaped before embedding in a local, script-free form.
    cards = []
    for candidate in data["candidates"]:
        proofs = "".join(f"<p>{html.escape(proof['excerpt'])}（位置 {proof['source_start']}～{proof['source_end']}）</p>" for proof in candidate["evidence"])
        cards.append(f"<article><label><input type='checkbox' value='{candidate['candidate_id']}'>"
                     f" {html.escape(candidate['mechanism'])}</label><p>{html.escape(candidate['transfer_guidance'])}</p>"
                     f"<p>适用流程：{html.escape(', '.join(candidate['scopes']))}；置信度：{candidate['confidence']}</p>"
                     f"<p>边界：{html.escape('；'.join(candidate['constraints']))}</p><details><summary>查看依据</summary>{proofs}</details></article>")
    content = """<!doctype html><meta charset="utf-8"><title>选择参考写法</title>
<style>body{max-width:850px;margin:36px auto;font:16px/1.7 system-ui;background:#f5f6fa;padding:20px}article{background:white;padding:18px;margin:14px 0;border-radius:10px}button{padding:12px 24px}label{font-weight:bold}</style>
<h1>选择要用于这本小说的写法</h1><p>全部默认不选。选择后下载 selection.json，放到本书工作区 learning/ 下，再运行“采用参考写法”工作流。空选择会清空已采用写法。</p>
""" + "".join(cards) + """<button id="download">下载我的选择</button><script>
document.getElementById('download').onclick=()=>{
const selection={candidates_sha256:HASH, selected_candidate_ids:[...document.querySelectorAll('input:checked')].map(i=>i.value)};
const url=URL.createObjectURL(new Blob([JSON.stringify(selection,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};</script>""".replace("HASH", json.dumps(data["candidates_sha256"]))
    save("learning/selection.html", content)


def adopt(args):
    data = load(CANDIDATES)
    if data.get("candidates_sha256") != digest(data["candidates"]):
        raise ValueError("候选文件被修改，请重新蒸馏")
    selection = load(args.selection)
    if not isinstance(selection, dict) or selection.get("candidates_sha256") != data["candidates_sha256"]:
        raise ValueError("选择文件对应的候选已变化，请重新选择")
    ids = selection.get("selected_candidate_ids")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("必须显式提供不重复的候选 ID 数组")
    by_id = {item["candidate_id"]: item for item in data["candidates"]}
    if not set(ids) <= set(by_id):
        raise ValueError("选择了不存在的候选写法")
    version = (load(ACTIVE)["version"] if path(ACTIVE).exists() else 0) + 1
    blueprint = {"schema": "xs2.project.learning.blueprint.v1", "version": version,
                 "created_at": datetime.now(timezone.utc).isoformat(), "source": data["source"],
                 "candidate_set_sha256": data["candidates_sha256"],
                 "selected_candidate_ids": ids,
                 "mechanisms": [{key: by_id[item][key] for key in ("candidate_id", "mechanism", "transfer_guidance", "constraints", "scopes")} for item in ids]}
    target = f"learning/blueprints/v{version:04d}.json"
    if path(target).exists():
        raise ValueError("蓝图版本已存在，不允许覆盖")
    save(target, blueprint)
    save(ACTIVE, {"version": version, "blueprint_path": target, "blueprint_sha256": digest(blueprint)})
    render("all")
    print(f"<script_out>已确认 {len(ids)} 条写法，创作蓝图版本 v{version:04d}</script_out>")


def render(scope):
    lines = ["# 用户已选写法", ""]
    version = 0
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
            lines.extend([f"## {item['mechanism']}", item["transfer_guidance"],
                          "使用边界：" + "；".join(item["constraints"]), ""])
    if len(lines) <= 4:
        lines.append("本阶段没有已选参考写法，按作者原创设定正常创作。")
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
    split_parser.set_defaults(handler=split)
    normalize_parser = commands.add_parser("normalize")
    normalize_parser.add_argument("--input", required=True)
    normalize_parser.add_argument("--window-id", required=True)
    normalize_parser.set_defaults(handler=normalize)
    commands.add_parser("merge").set_defaults(handler=merge)
    adopt_parser = commands.add_parser("adopt")
    adopt_parser.add_argument("--selection", default="learning/selection.json")
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
