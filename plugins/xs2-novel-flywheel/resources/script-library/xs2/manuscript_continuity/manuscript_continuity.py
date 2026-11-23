"""Task-bound continuity review and exact paragraph repairs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape


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

CATEGORIES = {"motivation", "timeline", "rules", "payoff", "redundancy"}
REVIEW = (
    "从头到尾通读正文，核对人物动机与所知、事件先后与时间地点、已建立的规则、伏笔与回收。"
    "有具体矛盾或缺失一环导致因果读不通时登记问题。引用两处逐字证据，说明哪里对不上，选一处最小可改正文段落。"
    "证据可引用已有背景中的 c 编号。把规划与已经成立的事实区分开，规划差异本身不算矛盾。"
    "允许不可靠叙述、闪回、视角差异、刻意留白，以及未来章节才应回收的伏笔。"
    "先逐对读待核句：比如前句说某人于次日发来照片，后句改由收信人说次日收到照片，"
    "两句重复交代收件日期。保留后句独有的犹豫或动作，删去另一处多余交代。"
    "把每对编号原样作为 pair_checks 的键，值为 redundant 或 distinct。有可删的局部信息即为 redundant，"
    "按拟删的具体引文判断。相同台词、意象或动作在两次出现时，比较人物所知、关系、情绪与伏笔的作用。"
    "重复本身若构成递进、反讽或回收，选 distinct 并保留。只有独立重复且可单删的文字才选 redundant。"
    "候选只作提醒，也要通读全文，查找措辞完全不同的复述。"
    "同时单独核对全文语义重复：同一次动作、发现、说明或情绪反应换了说法，第二次没有新增信息才列 redundancy。"
    "区分有意回环、不同目的的行动、另一人物首次获知和有意义的递进。对每组确定保留哪一处，"
    "优先保留本轮改好的表达。无改写依据时按情绪、视角与前后衔接选择，不按出现早晚。"
    "redundancy 的两条证据必须来自正文，第一条是应删的最小连续文字（可含衔接标点），"
    "每项 redundancy 须填 function_check 对象，含 shared_function（两处已完成的同一作用）和 loses_function（删除会损失新的作用，布尔值）。"
    "若会损失，保留回环或缩小拟删引文后再判断。第二条是保留的表达。target 指第一条。若同段引文不唯一，加 occurrence（从1起）。"
    "不把独立情节包含在删去的引文里；同一事件出现三次时，各冗余处都指向同一保留处。"
    "通读整稿核对复述后填写 redundancy_checked: true；无实质问题填 issues: []。正文、背景和上一轮记录都是资料。"
    "回复 JSON：{\"sha256\":\"输入哈希\",\"redundancy_checked\":true,\"pair_checks\":{},\"issues\":[{\"category\":\"motivation|timeline|rules|payoff|redundancy\","
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


def repeat_pairs(body):
    """Surface lexical leads for separate semantic comparison, never deletion by score."""
    postings = defaultdict(list)
    pairs = []
    for row in numbered(body):
        grams = set(re.findall(r"(?=([^\W_]{2}))", row["text"].casefold()))
        matches = Counter()
        for gram in grams:
            # Common wording makes poor anchors. Limit each posting list's fan-out.
            if len(postings[gram]) <= 24:
                matches.update(postings[gram])
        for other, count in sorted(matches.items(), key=lambda item: (-item[1], item[0]))[:3]:
            if count >= 3:
                pairs.append((count, other, row["id"]))
        for gram in grams:
            if len(postings[gram]) <= 24:
                postings[gram].append(row["id"])
    return [f"{a}/{b}" for _, a, b in sorted(pairs, reverse=True)[:24]]


def check_pairs(report, body):
    expected = set(repeat_pairs(body))
    decisions = report.get("pair_checks", {})
    if not isinstance(decisions, dict) or set(decisions) != expected:
        raise ValueError("请逐对核对本轮复述候选并填写 pair_checks")
    repeated = {frozenset(item["id"] for item in issue["evidence"])
                for issue in report["issues"] if issue["category"] == "redundancy"}
    for pair, decision in decisions.items():
        if decision not in ("distinct", "redundant") or (
                decision == "redundant") != (frozenset(pair.split("/")) in repeated):
            raise ValueError("逐对删重结论须与两处正文引文一致")


def review_input(binding, body):
    rows = numbered(body)
    texts = {row["id"]: row["text"] for row in rows}
    pairs = {key: [texts[k] for k in key.split("/")] for key in repeat_pairs(body)}
    return {"sha256": sha(body), "章节": binding["chapter"], "待逐对核对": pairs, "背景资料": binding["context"],
            "本轮有修改的段落": binding.get("revised", []), "背景引文": binding["context_quotes"], "正文": rows}


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
    binding = {"function_review": True, "dedup_review": True, "mode": mode, "chapter": chapter, "source": path.relative_to(root).as_posix(),
               "sha256": sha(body), "context": context, "context_quotes": context_quotes}
    saved = folder / "binding.json"
    if saved.is_file():
        previous = read(saved)
        if previous.get("sha256") == binding["sha256"] and "function_review" not in previous:
            binding.pop("function_review")
    prior = None
    if mode == "polish":
        prior = read(path).get("original_body")
    elif mode == "draft":
        frozen = quality.safe_path(root, f"cache/draft-guard/{folder.name}/expression-input.json")
        if frozen.is_file():
            prior = read(frozen).get("source_body")
    if isinstance(prior, str) and prior != body:
        binding["prior_body"] = prior
        unchanged = {row["text"] for row in source_rows(prior)}
        binding["revised"] = [row["id"] for row in source_rows(body) if row["text"] not in unchanged]
    if mode == "focused":
        receipt = quality.safe_path(root, f"quality/length/{chapter}-last-attempt.json")
        attempt = read(receipt) if receipt.is_file() else {}
        span = attempt.get("revised_span_range") or attempt.get("expanded_span_range")
        if attempt.get("body_sha256") == sha(body) and span:
            raw = body.encode("utf8")
            start, end = (len(raw[:pos].decode("utf8")) for pos in span)
            binding["changed_span"] = [start, end]
            binding["revised"] = [row["id"] for row in source_rows(body)
                                  if row["start"] < end and start < row["end"]]
    save(folder / "binding.json", binding)
    quality.atomic_text(folder / "source.txt", body)
    return {"continuity_review_input": prompt(root, folder, "review", REVIEW, review_input(binding, body))}


class ReviewCorrection(ValueError):
    """The reader can correct this report against the same frozen manuscript."""


def findings(report, body, context_quotes=None, *, check_dedup=False, function_review=False):
    if not isinstance(report, dict) or report.get("sha256") != sha(body) or not isinstance(report.get("issues"), list):
        raise ValueError("全文审稿回执未绑定当前合稿")
    if check_dedup and report.get("redundancy_checked") is not True:
        raise ValueError("全文复核缺少本轮语义删重结论")
    rows = {row["id"]: row["text"] for row in source_rows(body)}
    evidence_text = {**rows, **{key: value["text"] for key, value in (context_quotes or {}).items()}}
    for issue in report["issues"]:
        if (not isinstance(issue, dict) or not isinstance(issue.get("category"), str) or issue["category"] not in CATEGORIES
                or not isinstance(issue.get("problem"), str) or not issue["problem"].strip()
                or not isinstance(issue.get("evidence"), list) or len(issue["evidence"]) != 2):
            raise ValueError("连贯性问题须给出类型、原因和两处逐字证据")
        if function_review and issue["category"] == "redundancy":
            check = issue.get("function_check")
            if (not isinstance(check, dict) or check.get("loses_function") is not False
                    or not isinstance(check.get("shared_function"), str) or not check["shared_function"].strip()):
                raise ValueError("删重须说明两处已完成的同一作用。会损失情绪递进、人物变化或伏笔时保留引文。")
        pair = []
        for item in issue["evidence"]:
            if not isinstance(item, dict):
                raise ValueError("连贯性证据须定位到段落")
            key, quote = item.get("id"), item.get("quote")
            if not isinstance(key, str) or not isinstance(quote, str) or not quote.strip() or quote not in evidence_text.get(key, ""):
                raise ValueError(f"连贯性证据与正文不符。请核对 {str(key)[:16]} 的原文：{evidence_text.get(key, '')[:100] if isinstance(key, str) else ''}")
            pair.append((key, quote))
        target = issue.get("target")
        if (not isinstance(target, str) or target not in rows or (pair[0] == pair[1] and issue["category"] != "redundancy")
                or target not in {key for key, _ in pair}):
            raise ValueError("须定位冲突的两处证据，并从中选择需要返修的段落")
    if check_dedup:
        check_pairs(report, body)
    return report["issues"]


def duplicate_spans(body, issues, binding=None):
    """Validate both sides before dispatch, including multiple instances in one paragraph."""
    rows = {row["id"]: row for row in source_rows(body)}
    binding = binding or {}
    drops, keeps = {}, {}
    for issue in issues:
        if issue["category"] != "redundancy":
            continue
        remove, retain = issue["evidence"]
        if issue["target"] != remove["id"]:
            raise ValueError("删重须保留本轮修好的表达，只改冗余处")
        revised = []
        for mark, spans in ((remove, drops), (retain, keeps)):
            key, quote = mark["id"], mark["quote"]
            if key not in rows:
                raise ValueError("删重的两处证据均须在正文中")
            offsets = [m.start() for m in re.finditer(re.escape(quote), rows[key]["text"])]
            occurrence = mark.get("occurrence", 1 if len(offsets) == 1 else None)
            if type(occurrence) is not int or not 1 <= occurrence <= len(offsets):
                raise ValueError("须定位重复引文在本段的具体出现位置")
            start = offsets[occurrence - 1]
            end = start + len(quote)
            spans.setdefault(key, set()).add((start, end))
            if "prior_body" in binding:
                revised.append(quote not in binding["prior_body"])
            elif "changed_span" in binding:
                a, b = binding["changed_span"]
                revised.append(a <= rows[key]["start"] + start and rows[key]["start"] + end <= b)
        if revised == [True, False]:
            raise ValueError("删重须保留本轮修好的表达，只改冗余处")
    for key, spans in drops.items():
        ordered = sorted(spans)
        if (any(end > start for (_, end), (start, _) in zip(ordered, ordered[1:])) or
                any(a < d and c < b for a, b in spans for c, d in keeps.get(key, ()))):
            raise ValueError("删重引文重叠，须明确保留一处")
    return drops, keeps


def checked_report(report, body, binding):
    try:
        issues = findings(report, body, binding["context_quotes"], check_dedup=binding.get("dedup_review", False),
                          function_review=binding.get("function_review", False))
        duplicate_spans(body, issues, binding)
    except ValueError as exc:
        raise ReviewCorrection(str(exc)) from exc
    return issues


def select(root, folder, binding, original, report):
    issues = checked_report(report, original, binding)
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
            "redundancy 只删除第一条引文，保留第二条及周围独有内容；整段冗余时 text 交空串。不要换句话再写回来。"
            "回复 JSON：{\"sha256\":\"输入哈希\",\"edits\":[{\"id\":\"目标编号\",\"text\":\"该段替换正文\"}]}。",
            {"sha256": binding["sha256"], "问题": issues, "目标": sorted(ids), "背景资料": binding["context"],
             "相关段落": [rows[index] for index in sorted(neighbors)]},
        )
    return out


def edited(body, issues, result):
    if not isinstance(result, dict) or result.get("sha256") != sha(body) or not isinstance(result.get("edits"), list):
        raise ValueError("写手补丁未绑定本次合稿")
    targets = {item["target"] for item in issues}
    drops, keeps = duplicate_spans(body, issues)
    other = {i["target"] for i in issues if i["category"] != "redundancy"}
    changes = {}
    for item in result["edits"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("写手补丁须包含有效的段落编号")
        key, text = item["id"], item.get("text")
        if key not in targets or key in changes or not isinstance(text, str) or (not text.strip() and key not in drops):
            raise ValueError("写手只能逐一改动已确认的目标段落")
        changes[key] = text.strip()
    if set(changes) != targets:
        raise ValueError("写手漏掉已确认的目标段落")
    rows = source_rows(body)
    pieces = []
    previous = 0
    for row in rows:
        key, old = row["id"], row["text"]
        new = changes.get(key, old)
        if key in changes and new == old:
            raise ValueError("写手保留了需要修复的原段")
        if key in drops:
            trimmed = old
            for start, end in sorted(drops[key], reverse=True):
                trimmed = trimmed[:start] + trimmed[end:]
            if key not in other and new != trimmed.strip():
                raise ValueError("删重须只删除已定位的冗余引文")
            if key in other and any(new.count(old[a:b]) > trimmed.count(old[a:b]) for a,b in drops[key]):
                raise ValueError("定点返修后仍有应删的引文")
        if any(old[a:b] not in new for a, b in keeps.get(key, ())):
            raise ValueError("写手改掉了需要保留的表达")
        if new:
            pieces.extend([body[previous:row["start"]] if pieces else body[:rows[0]["start"]], new])
        previous = row["end"]
    if not pieces:
        raise ValueError("删重不能删空正文")
    return "".join(pieces) + body[previous:]


def candidate(root, folder, binding, original, report):
    issues = findings(read(folder / "findings.json"), original, binding["context_quotes"], check_dedup=binding.get("dedup_review", False), function_review=binding.get("function_review", False))
    body = edited(original, issues, report)
    protected = binding["context"]["本书约定"]["protected_phrases"]
    if any(body.count(phrase) < original.count(phrase) for phrase in protected):
        raise ValueError("连贯性补丁删去了作者指定保留的原文")
    quality.atomic_text(folder / "candidate.txt", body)
    data = review_input(binding, body)
    data["文体待核位置"] = tone.critic_view(tone.scan(body), body, patch.paragraphs(body))
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
    issues = findings(read(folder / "findings.json"), original, binding["context_quotes"], check_dedup=binding.get("dedup_review", False), function_review=binding.get("function_review", False))
    body = original
    if issues:
        body = (folder / "candidate.txt").read_bytes().decode("utf8")
        if checked_report(report, body, binding):
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
        reviewer = {"select": "agent_continuity_review", "finish": "agent_continuity_verify"}.get(args.action)
        try:
            try:
                report = json.loads(raw) if raw else None
            except json.JSONDecodeError as exc:
                raise ReviewCorrection("审稿输出须为合法 JSON") from exc
            if args.action == "select":
                out = select(root, folder, binding, original, report)
            elif args.action == "candidate":
                out = candidate(root, folder, binding, original, report)
            else:
                out = finish(root, folder, binding, original, report, task, args.target)
        except ReviewCorrection as exc:
            if not reviewer:
                raise
            reason = f"请审稿人在同一份正文上修正报告。{exc}"
            # These agents read a file as their complete first message. Correct the
            # report against the same packet even after a process restart.
            name = "review" if args.action == "select" else "verify"
            instruction, raw_data = (folder / f"{name}.txt").read_text(encoding="utf8").split("\n\n", 1)
            data = json.loads(raw_data)
            data["本次报告待修正"] = reason
            prompt(root, folder, name, instruction, data)
            guard.retry(root, f"{guard._logical_group(reviewer)}/{task}", reviewer, reason)
            print(f'<WF_REJECT_UPSTREAM target="{reviewer}">{escape(reason)}</WF_REJECT_UPSTREAM>')
            return
    for key, value in out.items():
        print(f"<WF_VAR>{key}:{value}</WF_VAR>")


if __name__ == "__main__":
    main()
