"""Adapt the pinned Lieflat detector to XS2's frozen chapter and paragraph IDs."""
from bisect import bisect_right
from collections import Counter
from hashlib import sha256
from functools import lru_cache
import importlib.util
from pathlib import Path
import re

REVISION = "fe77df00a27cf94428632ad449a4aecdcb83db41"
_spec = importlib.util.spec_from_file_location("xs2_lieflat_detect", Path(__file__).parent / "vendor/lieflat/detect.py")
detector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detector)

GUIDANCE = (
    "这些是原稿的待核位置。结合本书声音和整场阅读核对。只把能说明阅读损失、有逐字原文依据的项放进现有 issues。"
    "辨别同义换名是否让指代费解、承接是否重复上段结论、冒号是否空喊判断、排比是否重复同一信息。"
    "对话纠错、口癖、引文和有意复沓可保留。句长和标点密度仅供描述。沿用原审稿协议，不设命中清零目标。"
    "整篇润色请读全章，提示只用于找位置。沿开篇、中段和收尾分别留心：人物已经用行动作答后又解说；"
    "数轮对话只轮流复述信息；多个比喻替读者反复说明同一种感情；前后动作或称谓没有接上。"
    "不同场景各自成立的问题分别写入 issues。局部可改善也可标 low，说明具体阅读损失、逐字引文和可试的改法。"
    "若填写 scene_focus，quote 选连续原文，evidence 同时引目标和另一处原文。preserve 只填必须照录的原句，想保留的含义写入建议。"
    "保留原文中的幽默与真正改变关系的对白。没有充分依据可以不提。"
)
SEMANTIC = {"rename": "段内换名", "cohesion": "段间衔接", "colon": "冒号用途", "iso3": "三句同构"}

@lru_cache(maxsize=1)
def semantic_rubric():
    path = Path(__file__).parent / "vendor/lieflat/semantic-criteria.md"
    sections = re.split(r"(?m)^## ", path.read_text(encoding="utf-8"))[1:5]
    return {name: [line for line in section.splitlines() if line.startswith("| ")
                   and not line.startswith("| 标签 |")]
            for name, section in zip(SEMANTIC.values(), sections)}

SCENE_COMMISSION = (
    "本轮委托是逐场内容编辑。按人物当前要办的事、时地和转折划分自然场面，连续同场的对白与动作合在一起。"
    "在 scene_pass 用自然场面覆盖授权全文。比较本场与书中已经成立的声音、视角和节奏。"
    "提出 revise 时引用一处原文并在 impact 说清具体阅读损失或可得的增益，action 指出想改善的效果。"
    "处理方法由写手选择。场面已经成立时用 keep，允许整章保留。"
)

WRITER_COMMISSION = (
    "你负责本轮逐场试写，有权在作者授权范围内提出审稿人没有指出的场面改法。"
    "先独立连读全文，按自然场面为有提升空间的冲突写出替代段落，再把有具体增益的版本提交给下一位独立审稿人比较。"
    "场面表的 keep 标出值得保住的作用，允许保住这一作用并改写附近的问答、动作或叙述。"
    "选最适合本场的改动尺度；原稿更好或两版相当时可以保留，包括交空补丁。"
    "可以删掉重复的对白，也可以把篇幅花在原先被一句带过的转折。保留既有事实，按书中人物所知写。"
    "每处可单独成立的修改标 independent:true；必须连读的一组用唯一 group_id；不提交原样替换。"
)


def verified_scenes(rows, paragraphs):
    """Keep uniquely locatable scene notes; the full critic report stays on disk."""
    by_id = {p["id"]: p["text"] for p in paragraphs}
    result = []
    if not isinstance(rows, list):
        raise ValueError("scene_pass 须为逐场审读的数组。")
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or row.get("decision") not in ("keep","revise")
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ("paragraph_id","quote","action","impact"))):
            raise ValueError(f"scene_pass[{index}] 缺少场景证据、阅读影响或修改决定。")
        pid, quote = row["paragraph_id"], row["quote"]
        if quote not in by_id.get(pid, ""):
            matches = [key for key, paragraph in by_id.items() if quote in paragraph]
            if len(matches) != 1:
                continue
            pid = matches[0]
        result.append({**row, "paragraph_id":pid})
    return result


def scene_goals(rows, prior_goals):
    existing = {quote for goal in prior_goals for quote in goal.get("excerpts", [])}
    result = []
    for index, row in enumerate(rows):
        pid, quote = row["paragraph_id"], row["quote"]
        if row["decision"] == "keep" or quote in existing:
            continue
        result.append({"id":f"scene-edit-{index}", "source":"local_critic", "level":"advisory",
                       "paragraph_id":pid, "excerpts":[quote],
                       "goal":row["action"] + " 阅读影响：" + row["impact"]})
    return result


def trial_windows(rows, paragraphs):
    """Separate passages around the critic's ordered points of attention."""
    positions = {row["id"]: i for i, row in enumerate(paragraphs)}
    centers = sorted({positions[row["paragraph_id"]] for row in rows})
    if not centers:
        return []
    cuts = [0, *((a+b)//2+1 for a,b in zip(centers,centers[1:])), len(paragraphs)]
    return [{"anchor":paragraphs[center]["id"], "first":paragraphs[start]["id"],
             "last":paragraphs[stop-1]["id"]} for center,start,stop in zip(centers,cuts,cuts[1:])]


def untried_windows(windows, edits, *, first_read=True, require_trials=True):
    touched = {int(edit["paragraph_id"][1:]) for edit in edits if edit["old"] != edit["replacement"]}
    if require_trials and windows and not touched:
        raise ValueError("逐场试写尚未交付可对读的替代稿。请读 scene_workshop，在各场找到值得试写的段落，"
                         "提交实际候选供独立审稿决定是否采用。")
    # Window edges approximate scene boundaries. A gap is useful evidence
    # about coverage, not grounds for discarding valid work in other scenes.
    covered = [any(int(w["first"][1:]) <= i <= int(w["last"][1:]) for i in touched) for w in windows]
    missing = [w for w, has_trial in zip(windows,covered) if not has_trial]
    if require_trials and first_read and missing and (sum(covered)==1 or any(not a and not b for a,b in zip(covered,covered[1:]))):
        ranges = "、".join(w["first"]+" 至 "+w["last"] for w in missing)
        raise ValueError("本轮是全章逐场对读，草案仍集中在局部。请完整重交已有改动，并为尚未试写的场面提交实际替代写法："
                         + ranges + "。每场挑最有用的一处，独立审稿可以保留原稿。")
    return missing


def scan(body):
    docs = [("chapter.md", body)]
    return {"revision": REVISION, "sha256": sha256(body.encode()).hexdigest(),
            "hanzi": detector.hanzi(body), "metrics": detector.measure_docs(docs),
            "candidates": detector.extract_candidates(docs)}


def critic_view(scan_result, body, paragraphs):
    starts = [0]
    for line in body.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    # A paragraph can start after a BOM/leading blanks and span several lines.
    by_line = {}
    for row in paragraphs:
        first = bisect_right(starts, row["start"])
        last = bisect_right(starts, row["end"] - 1)
        for line in range(first, last + 1):
            by_line[line] = row["id"]

    groups = []
    for level, name, *_ in detector.REGEX_HITS:
        if level in ("A", "B"):
            groups.append((name, scan_result["metrics"]["hits"][name], "excerpt"))
    for key, name in SEMANTIC.items():
        groups.append((name, scan_result["candidates"][key], None))
    hints = []
    totals = {}
    for name, items, excerpt_key in groups:
        totals[name] = len(items)
        # Spread a bounded set of pointers through the chapter. Full records stay on disk.
        count = min(4, len(items))
        for i in range(count):
            index = round(i * (len(items) - 1) / (count - 1)) if count > 1 else 0
            item = items[index]
            line = item["line"]
            if line in by_line:
                hint = {"rule": name, "paragraph": by_line[line], "line": line}
                if excerpt_key:
                    hint["excerpt"] = item[excerpt_key]
                elif name == SEMANTIC["cohesion"]:
                    hint["prev_tail"] = item["prev_tail"][-80:]
                    hint["next_head"] = item["next_head"][:80]
                elif name == SEMANTIC["iso3"]:
                    hint["sentences"] = [s[:100] for s in item["sents"]]
                elif name == SEMANTIC["colon"]:
                    hint["excerpt"] = item["colon_before"][-50:] + "：" + item["colon_after"][:60]
                else:
                    hint["excerpt"] = item["para"][:140]
                hints.append(hint)
    return {"revision": REVISION, "handoff_version": 2, "guidance": GUIDANCE,
            "semantic_criteria": {name: rules for name, rules in semantic_rubric().items() if totals.get(name)},
            "candidate_counts_after_upstream_sampling": totals,
            "upstream_truncation": scan_result["candidates"]["meta"]["truncated"], "hints": hints}


def marked_phrases(text):
    """Yield literal A/B rule hits with offsets in the submitted text."""
    start = 0
    for line in text.splitlines(keepends=True):
        for level, _, pattern, *_ in detector.REGEX_HITS:
            if level in ("A", "B"):
                for hit in re.finditer(pattern, line.rstrip("\r\n")):
                    yield start + hit.start(), start + hit.end(), hit.group()
        start += len(line)


def fragment_review(text):
    """Give the writer evidence from exactly the text it is allowed to change."""
    view = critic_view(scan(text), text, [{"id": "target", "start": 0, "end": len(text)}])
    return {
        "guidance": "mandatory_phrases 中每一处须更换说法并保留信息。语义候选结合语境判断，保住人物口吻、笑点和必要细节。",
        "mandatory_phrases": list(dict.fromkeys(phrase for _, _, phrase in marked_phrases(text))),
        "hints": [{k: v for k, v in h.items() if k != "paragraph"} for h in view["hints"][:8]],
    }


def include_rule_hits(units, paragraphs):
    """Union literal Lieflat marks with the existing exact, non-overlapping edit ranges."""
    by_paragraph = {}
    for unit in units:
        by_paragraph.setdefault(unit["paragraph_id"], []).append(unit)
    for para in paragraphs:
        pid, text = para["id"], para["text"]
        if text.lstrip("\ufeff").startswith("# "):
            continue
        hits = [(a, b) for a, b, _ in marked_phrases(text)]
        if not hits:
            continue
        intervals = []
        original = by_paragraph.get(pid, [])
        for u in original:
            pos = -1
            for _ in range(u["occurrence"]):
                pos = text.index(u["old"], pos + 1)
            intervals.append((pos, pos + len(u["old"])))
        if all(any(a <= x and y <= b for a, b in intervals) for x, y in hits):
            continue
        merged = []
        for a, b in sorted(intervals + hits):
            if merged and a < merged[-1][1]:
                merged[-1][1] = max(b, merged[-1][1])
            else:
                merged.append([a, b])
        rebuilt = []
        for index, (a, b) in enumerate(merged, 1):
            old = text[a:b]
            occurrence = 1 + sum(1 for match in re.finditer("(?=" + re.escape(old) + ")", text) if match.start() < a)
            rebuilt.append({"id": f"{pid}-s{index}", "paragraph_id": pid, "old": old, "occurrence": occurrence})
        by_paragraph[pid] = rebuilt
    return [u for para in paragraphs for u in by_paragraph.get(para["id"], [])]


def annotate_rewrites(report, paragraphs=None):
    if paragraphs is not None and "rewrite_units" in report:
        report["rewrite_units"] = include_rule_hits(report["rewrite_units"], paragraphs)
    for unit in report.get("rewrite_units", []):
        unit["lieflat_review"] = fragment_review(unit["old"])


def comparison(before, after, outcomes=()):
    rows = ["# 章节文体复测", "", "本表比较同一章冻结原稿与最终采用稿的规则命中。命中数包含正常表达。",
            "", f"改前 {before['hanzi']} 汉字，改后 {after['hanzi']} 汉字。",
            "", "| 规则 | 改前命中 | 改后命中 | 改前／千汉字 | 改后／千汉字 |",
            "|---|---:|---:|---:|---:|"]
    if min(before["hanzi"], after["hanzi"]) < 500:
        rows.insert(3, "文本不足 500 汉字时，密度受单处命中影响较大。")
    changes = []
    for level, name, *_ in detector.REGEX_HITS:
        old, new = [s["metrics"]["hits"][name] for s in (before, after)]
        rates = [s["metrics"]["density"][name] if s["hanzi"] else "—" for s in (before, after)]
        rows.append(f"| {level} · {name} | {len(old)} | {len(new)} | {rates[0]} | {rates[1]} |")
        for verb, items, other in (("减少", old, new), ("新增", new, old)):
            remaining = Counter(h["excerpt"] for h in other)
            for hit in items:
                excerpt = hit["excerpt"]
                if remaining[excerpt]:
                    remaining[excerpt] -= 1
                else:
                    changes.append(f"- {verb} · {name} · 第 {hit['line']} 行　{excerpt}")
    rows.extend(["", "## 命中片段变化", "", "按规则和匹配文字配对；行号分别对应改前或改后版本。", ""])
    rows.extend(changes or ["两版匹配文字及次数相同。"])
    remaining = [(name, hit) for name, hits in after["metrics"]["hits"].items() for hit in hits]
    rows.extend(["", "## 终稿仍有的命中", ""])
    rows.extend([f"- {name} · 第 {hit['line']} 行　{hit['excerpt']}" for name, hit in remaining]
                or ["终稿无逐行规则命中。"])
    kept = [o for o in outcomes if o.get("status") == "keep"]
    if kept:
        rows.extend(["", "## 审稿者明确保留的目标", ""])
        rows.extend(f"- {o['id']}　{o.get('reason', '')}" for o in kept)
    rows.extend(["", "## 复核依据", "", f"- 改前 SHA-256　{before['sha256']}",
                 f"- 改后 SHA-256　{after['sha256']}",
                 f"- 检测器　[Lieflat Less AI Tone / shiujan](https://github.com/larashero3-dotcom/lieflat-less-ai-tone/tree/{REVISION})",
                 "- 完整计数和语义候选保存在本次修订目录的 tone-before.json、tone-after.json。"])
    return "\n".join(rows) + "\n"
