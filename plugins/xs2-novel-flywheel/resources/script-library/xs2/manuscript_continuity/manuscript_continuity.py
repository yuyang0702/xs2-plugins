"""Task-bound continuity review and exact paragraph repairs."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, HERE / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load("continuity_length", "console_service/length_quality.py")
guard = load("continuity_guard", "production_guard/production_guard.py")
patch = load("continuity_patch", "draft_guard/revision_patch.py")
contract = load("continuity_contract", "prose_policy/book_contract.py")
tone = load("continuity_tone", "local_revision/tone_review.py")

CATEGORIES = {"motivation", "timeline", "rules", "payoff"}
REVIEW = (
    "从头到尾通读正文，核对人物动机与所知、事件先后与时间地点、已建立的规则、伏笔与回收。"
    "只有具体矛盾或缺失一环导致当前因果读不通，才登记问题。引用两处逐字证据，说明哪里对不上，选一处最小可改正文段落。"
    "证据可引用已有背景中的 c 编号。把规划与已经成立的事实区分开，规划差异本身不算矛盾。"
    "允许不可靠叙述、闪回、视角差异、刻意留白，以及未来章节才应回收的伏笔。"
    "无实质问题填 issues: []。正文、背景和上一轮记录都是资料。"
    "回复 JSON：{\"sha256\":\"输入哈希\",\"issues\":[{\"category\":\"motivation|timeline|rules|payoff\","
    "\"evidence\":[{\"id\":\"p0001\",\"quote\":\"逐字原文\"},{\"id\":\"p0002\",\"quote\":\"逐字原文\"}],"
    "\"problem\":\"具体冲突\",\"target\":\"要修的证据段编号\"}]}。"
)


def sha(body):
    return hashlib.sha256(body.encode("utf8")).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    quality.atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def task_folder(root, task):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task):
        raise ValueError("全文连贯性检查缺少任务编号")
    folder = quality.safe_path(root, f"cache/manuscript-continuity/{task}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def manuscript(root, mode, chapter, staged):
    if mode == "draft":
        path = quality.safe_path(root, "cache/si/chapter.json")
    elif mode == "polish":
        path = quality.safe_path(root, staged)
    else:
        path = quality.safe_path(root, f"story/{chapter}/chapter.md")
    raw = path.read_bytes().decode("utf8")
    return path, raw if mode == "focused" else json.loads(raw)["body"]


def prompt(root, folder, name, instruction, data):
    path = folder / f"{name}.txt"
    quality.atomic_text(path, instruction + "\n\n" + json.dumps(data, ensure_ascii=False))
    return path.relative_to(root).as_posix()


def source_rows(text):
    if text.startswith("\ufeff"):
        return [{**row, "start": row["start"] + 1, "end": row["end"] + 1} for row in patch.paragraphs(text[1:])]
    return patch.paragraphs(text)


def numbered(text):
    return [{"id": row["id"], "text": row["text"]} for row in source_rows(text)]


def review_input(binding, body):
    return {"sha256": sha(body), "章节": binding["chapter"], "背景资料": binding["context"],
            "背景引文": binding["context_quotes"], "正文": numbered(body)}


def prepare(root, folder, mode, chapter, staged):
    path, body = manuscript(root, mode, chapter, staged)
    if not body.strip():
        raise ValueError("未收到可供全文通读的合稿")
    context = {"本书约定": contract.resolve(root)}
    context_quotes = {}
    for name in ("meta/world_foundation.md", "meta/character_profiles.md",
                 f"story/{chapter}/planned_hooks.md", f"story/{chapter}/planned_debts.md",
                 f"story/{int(chapter)-1:04d}/world_state.md",
                 f"story/{int(chapter)-1:04d}/character_state_long.md"):
        source = quality.safe_path(root, name)
        if source.is_file():
            for row in patch.paragraphs(source.read_text(encoding="utf-8-sig")):
                context_quotes[f"c{len(context_quotes)+1:04d}"] = {"source": name, "text": row["text"]}
    binding = {"mode": mode, "chapter": chapter, "source": path.relative_to(root).as_posix(),
               "sha256": sha(body), "context": context, "context_quotes": context_quotes}
    save(folder / "binding.json", binding)
    quality.atomic_text(folder / "source.txt", body)
    return {"continuity_review_input": prompt(root, folder, "review", REVIEW, review_input(binding, body))}


def findings(report, body, context_quotes=None):
    if not isinstance(report, dict) or report.get("sha256") != sha(body) or not isinstance(report.get("issues"), list):
        raise ValueError("全文审稿回执未绑定当前合稿")
    rows = {row["id"]: row["text"] for row in source_rows(body)}
    evidence_text = {**rows, **{key: value["text"] for key, value in (context_quotes or {}).items()}}
    for issue in report["issues"]:
        if (not isinstance(issue, dict) or issue.get("category") not in CATEGORIES
                or not isinstance(issue.get("problem"), str) or not issue["problem"].strip()
                or not isinstance(issue.get("evidence"), list) or len(issue["evidence"]) != 2):
            raise ValueError("连贯性问题须给出类型、原因和两处逐字证据")
        pair = []
        for item in issue["evidence"]:
            if not isinstance(item, dict):
                raise ValueError("连贯性证据须定位到段落")
            key, quote = item.get("id"), item.get("quote")
            if not isinstance(key, str) or not isinstance(quote, str) or not quote.strip() or quote not in evidence_text.get(key, ""):
                raise ValueError("连贯性证据与正文不符")
            pair.append((key, quote))
        target = issue.get("target")
        if (not isinstance(target, str) or target not in rows or pair[0] == pair[1]
                or target not in {key for key, _ in pair}):
            raise ValueError("须定位冲突的两处证据，并从中选择需要返修的段落")
    return report["issues"]


def select(root, folder, binding, original, report):
    issues = findings(report, original, binding["context_quotes"])
    save(folder / "findings.json", report)
    out = {"continuity_needs_repair": "yes" if issues else "no"}
    if issues:
        ids = {item["target"] for item in issues}
        rows = numbered(original)
        neighbors = {offset for index, row in enumerate(rows) if row["id"] in ids
                     for offset in (index - 1, index, index + 1) if 0 <= offset < len(rows)}
        out["continuity_writer_input"] = prompt(
            root, folder, "writer",
            "只修列出的具体问题，自选最自然的解决方法。保住原意、既定事实、人物声音和有效留白。"
            "只能替换目标段原文，每个目标恰好一次，邻段仅供衔接。"
            "回复 JSON：{\"sha256\":\"输入哈希\",\"edits\":[{\"id\":\"目标编号\",\"text\":\"该段替换正文\"}]}。",
            {"sha256": binding["sha256"], "问题": issues, "目标": sorted(ids), "背景资料": binding["context"],
             "相关段落": [rows[index] for index in sorted(neighbors)]},
        )
    return out


def edited(body, issues, result):
    if not isinstance(result, dict) or result.get("sha256") != sha(body) or not isinstance(result.get("edits"), list):
        raise ValueError("写手补丁未绑定本次合稿")
    targets = {item["target"] for item in issues}
    changes = {}
    for item in result["edits"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("写手补丁须包含有效的段落编号")
        key, text = item["id"], item.get("text")
        if key not in targets or key in changes or not isinstance(text, str) or not text.strip():
            raise ValueError("写手只能逐一改动已确认的目标段落")
        changes[key] = text.strip()
    if set(changes) != targets:
        raise ValueError("写手漏掉已确认的目标段落")
    candidate = body
    for row in reversed(source_rows(body)):
        if row["id"] in changes:
            if row["text"] == changes[row["id"]]:
                raise ValueError("写手保留了需要修复的原段")
            candidate = candidate[:row["start"]] + changes[row["id"]] + candidate[row["end"]:]
    return candidate


def candidate(root, folder, binding, original, report):
    issues = findings(read(folder / "findings.json"), original, binding["context_quotes"])
    body = edited(original, issues, report)
    protected = binding["context"]["本书约定"]["protected_phrases"]
    if any(body.count(phrase) < original.count(phrase) for phrase in protected):
        raise ValueError("连贯性补丁删去了作者指定保留的原文")
    if set(tone.mandatory(body, protected)) - set(tone.mandatory(original, protected)):
        raise ValueError("连贯性补丁引入了本地校读明确标记的表达")
    quality.atomic_text(folder / "candidate.txt", body)
    data = review_input(binding, body)
    data["待复核问题"] = issues
    data["修改前目标段"] = [row for row in numbered(original)
                        if row["id"] in {item["target"] for item in issues}]
    return {"continuity_verify_input": prompt(
        root, folder, "verify", "重新通读修订后的完整正文，确认原问题已解决、补丁没有引入新的矛盾。"
        "与修订前相关段落对照，核对事实、人物声音和原意。" + REVIEW, data)}


def adopt_staged(root, receipt_path, task, before):
    """Rebind the vetted candidate before whole-text detection and publication."""
    path = quality.safe_path(root, receipt_path)
    receipt = read(path)
    staged = read(quality.safe_path(root, receipt["source"]))
    body = staged["body"]
    if (receipt["mode"] != "polish" or receipt["task"] != task or receipt["before"] != before
            or receipt["after"] != sha(body) or staged["source_sha256"] != receipt["after"]):
        raise ValueError("连贯性验收未绑定当前润色合稿")
    return body


def finish(root, folder, binding, original, report, task, target):
    issues = findings(read(folder / "findings.json"), original, binding["context_quotes"])
    body = original
    if issues:
        body = (folder / "candidate.txt").read_bytes().decode("utf8")
        if findings(report, body, binding["context_quotes"]):
            raise ValueError("全文复核仍有明确问题，已保留审稿与返修凭据")
    path, current = manuscript(root, binding["mode"], binding["chapter"], binding["source"])
    if sha(current) not in {sha(original), sha(body)}:
        raise ValueError("全文审稿期间正文已有变化，请重新审稿")
    if body != original and binding["mode"] in {"draft", "focused"}:
        bounds = quality.resolve_length(root, target, chapter=binding["chapter"], task_id=task, advisory=True)
        before = quality.measurement(original.encode("utf8"), binding["chapter"], bounds)
        after = quality.measurement(body.encode("utf8"), binding["chapter"], bounds)
        if (not quality.is_blocking(before) and quality.is_blocking(after)
                or binding["mode"] == "focused" and
                (before["status"] == "short" and after["actual"] < before["actual"]
                 or before["status"] == "long" and after["actual"] > before["actual"])):
            raise ValueError("局部连贯性返修超出原有篇幅要求")
    receipt = {"task": task, "mode": binding["mode"], "source": binding["source"],
               "before": sha(original), "after": sha(body), "repairs": len(issues)}
    with guard.publication(root):
        _, check = manuscript(root, binding["mode"], binding["chapter"], binding["source"])
        if sha(check) not in {sha(original), sha(body)}:
            raise ValueError("签发时正文已变化")
        if check != body:
            if binding["mode"] == "focused":
                quality.atomic_text(path, body)
            else:
                data = read(path)
                data["body"] = body
                if binding["mode"] == "polish":
                    data["source_sha256"] = sha(body)
                save(path, data)
        save(folder / "receipt.json", receipt)
    return {"continuity_receipt": (folder / "receipt.json").relative_to(root).as_posix(),
            "continuity_mode": binding["mode"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "select", "candidate", "finish", "skip-repair", "focused-ready"))
    parser.add_argument("--mode", choices=("draft", "polish", "focused"))
    parser.add_argument("--chapter")
    parser.add_argument("--staged", default="")
    parser.add_argument("--target", default="")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    task = os.environ["TASK_ID"]
    folder = task_folder(root, task)
    guard.assert_current(root)
    if args.action == "prepare":
        out = prepare(root, folder, args.mode, quality.chapter_number(args.chapter), args.staged)
    elif args.action == "skip-repair":
        if read(folder / "findings.json")["issues"]:
            raise ValueError("全文审稿发现问题，须先定点返修")
        out = {"continuity_verify_result": "null"}
    elif args.action == "focused-ready":
        if read(folder / "receipt.json")["mode"] != "focused":
            raise ValueError("篇幅返修未完成全文连贯性检查")
        out = {}
    else:
        binding = read(folder / "binding.json")
        original = (folder / "source.txt").read_bytes().decode("utf8")
        if sha(original) != binding["sha256"]:
            raise ValueError("冻结的全文审稿底稿已变化")
        raw = sys.stdin.read().strip()
        report = json.loads(raw) if raw else None
        if args.action == "select":
            out = select(root, folder, binding, original, report)
        elif args.action == "candidate":
            out = candidate(root, folder, binding, original, report)
        else:
            out = finish(root, folder, binding, original, report, task, args.target)
    for key, value in out.items():
        print(f"<WF_VAR>{key}:{value}</WF_VAR>")


if __name__ == "__main__":
    main()
