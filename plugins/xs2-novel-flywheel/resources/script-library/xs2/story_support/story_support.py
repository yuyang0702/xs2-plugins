"""Shared, file-only story support; upstream code is exercised at runtime.

No model is called here. Facts, proposals and character knowledge stay separate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("xs2_story_upstream", HERE / "upstream.py")
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)
BASE_FILES = (
    "meta/world_foundation.md", "meta/character_profiles.md", "meta/character_voice.md",
    "meta/style_profile.md", "learning/active_context.md", "meta/story_plan.md",
    "outline/volume_outline.md", "outline/near_term_outline.md", "meta/hooks.md",
    "meta/debts.md", "meta/conflict_ledger.md",
)
# Live contracts precede broader setting material. Generated current-state
# pages are only a baseline before a book has any chapter history.
PRIORITY_FILES = (
    "learning/active_context.md", "meta/story_plan.md",
    "meta/current_world.md", "meta/current_characters.md",
)
# Stable creative foundations are bound to review snapshots and adopted plans.
# Outlines and generated ledgers are versioned separately.
CHECKPOINT_FILES = BASE_FILES[:6]
LABELS = {"name": "人物", "identity": "身份", "drives": "动力与底线", "snapshot": "当前处境",
          "location": "位置", "physical": "身体状态", "resources": "资源", "goal": "当前目标",
          "emotion": "情绪", "knowledge": "所知信息", "misbelief": "误解", "relationships": "关系",
          "target": "对象", "change": "变化", "evidence": "正文依据", "facts": "确认事实",
          "forces": "势力", "undercurrents": "暗线", "description": "内容", "status": "状态",
          "source_chapter": "来源章节", "chapter": "章节", "current_state": "当前状态",
          "world_time": "世界时间", "time_advanced_days": "经过天数", "bottom_line": "底线",
          "motivation": "动机", "strength": "实力", "power": "影响力", "intent": "意图",
          "action": "行动", "landed": "已发生", "missed": "尚未发生", "deviated": "实际变化",
          "unplanned": "计划外事件", "planned": "原计划", "actual": "实际发展", "note": "说明",
          "judgment": "判断", "reason": "原因", "event": "事件", "suggestion": "建议",
          "from": "关系起点", "to": "关系对象", "id": "编号", "expected_payoff": "预期兑现",
          "chapter_created": "埋设章节", "chapter_resolved": "兑现章节", "last_advanced": "最近推进",
          "source": "来源", "state_changes": "状态变化", "relationship_changes": "关系变化",
          "evidence_position": "依据位置"}


def now():
    return datetime.now(timezone.utc).isoformat()


def chapter_id(value):
    if not re.fullmatch(r"[0-9]{1,6}", str(value)) or int(value) < 1:
        raise ValueError("请选择有效的章节。")
    return f"{int(value):04d}"


def safe(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError("资料路径不能离开当前作品。")
    return path


def read(root, relative):
    path = safe(root, relative)
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def load(root, relative, default=None):
    text = read(root, relative)
    return json.loads(text) if text.strip() else default


def write(root, relative, value):
    path = safe(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="story-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def digest(root, relative):
    path = safe(root, relative)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def validated_evidence(evidence, body, error):
    """Check every quotation without joining unrelated passages into one quote.

    New outputs use a list for independent passages. Older outputs sometimes
    concatenate sentences or paragraphs; split those only at sentence/line
    boundaries and verify every resulting passage. Never fuzzy-match words.
    """
    normalized_body = re.sub(r"\s+", " ", body.strip())

    def exists(quote):
        if not isinstance(quote, str):
            return False
        quote = re.sub(r"\s+", " ", quote.strip())
        if len(quote) < 2:
            return False
        pattern = re.escape(quote)
        if re.match(r"[A-Za-z0-9_]", quote[0]):
            pattern = r"(?<![A-Za-z0-9_])" + pattern
        if re.match(r"[A-Za-z0-9_]", quote[-1]):
            pattern += r"(?![A-Za-z0-9_])"
        return re.search(pattern, normalized_body) is not None

    if isinstance(evidence, list):
        if not evidence or not all(exists(quote) for quote in evidence):
            raise ValueError(error)
        return [quote.strip() for quote in evidence]
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(error)
    if exists(evidence):
        return evidence.strip()

    passages = []
    for line in evidence.strip().splitlines():
        if not line.strip():
            continue
        if exists(line):
            passages.append(line.strip())
        else:
            # Keep punctuation and all nonempty text, including a final fragment,
            # so a fabricated sentence cannot disappear during normalization.
            passages.extend(part.strip() for part in
                            re.split(r"(?<=[。！？!?])", line) if part.strip())
    if len(passages) < 2 or not all(exists(quote) for quote in passages):
        raise ValueError(error)
    return passages


def bodies(root):
    return sorted((Path(root) / "story").glob("[0-9][0-9][0-9][0-9]/chapter.md"))


def source_hashes(root, include_outline=True, before=None):
    files = list(BASE_FILES if include_outline else CHECKPOINT_FILES)
    files += [p.relative_to(root).as_posix() for p in bodies(root)
              if before is None or int(p.parent.name) < int(before)]
    return {file: digest(root, file) for file in files}


def verify(root, hashes):
    if any(digest(root, path) != value for path, value in hashes.items()):
        raise ValueError("前文、设定或计划已有变化，这份建议已过期，请重新讨论。")


def changed_sources(root, hashes):
    """Return changed source paths so a stale plan can explain what invalidated it."""
    return sorted(path for path, value in hashes.items() if digest(root, path) != value)


def readable(value, depth=0):
    if isinstance(value, dict):
        return "\n".join(f"{'  '*depth}- **{LABELS.get(k, k)}**：" +
                         ("\n" + readable(v, depth+1) if isinstance(v, (dict, list)) else str(v))
                         for k, v in value.items() if k not in {"body_sha256", "source_hashes", "version", "updated_at"})
    if isinstance(value, list):
        return "\n".join(("\n" + readable(v, depth) if isinstance(v, dict) else f"{'  '*depth}- {v}") for v in value)
    return str(value)


def confirmed(root, before=None):
    valid, stale = [], []
    for path in sorted((Path(root) / "story").glob("[0-9][0-9][0-9][0-9]/confirmed_state.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        number = int(path.parent.name)
        if before is not None and number >= int(before):
            continue
        try:
            verify(root, data.get("source_hashes", {}))
            if digest(root, f"story/{number:04d}/chapter.md") != data.get("body_sha256"):
                raise ValueError("正文已修改")
            valid.append(data)
        except ValueError:
            stale.append(path.parent.name)
    return valid, stale


def chapter_start_indexes(root, chapter):
    """An explicitly empty snapshot is authoritative, not a fallback trigger."""
    prior, _ = confirmed(root, before=int(chapter))
    old = load(root, f"story/{chapter}/confirmed_state.json", {})
    snapshot = prior[-1] if prior else old
    field = "indexes" if prior else "indexes_before"
    if isinstance(snapshot.get(field), dict):
        return {key: snapshot[field].get(key, []) for key in ("hooks", "debts")}

    def predates(entry):
        if not isinstance(entry, dict):
            return False
        created = entry.get("chapter_created", entry.get("source_chapter"))
        markers = [created] + [entry[key] for key in
                   ("source_chapter", "chapter_resolved", "last_advanced") if key in entry]
        # A current ledger cannot reconstruct a prior version of an entry that
        # was advanced/resolved later. Omit it instead of guessing its old state.
        return all(re.fullmatch(r"[0-9]{1,6}", str(value)) and
                   0 < int(value) < int(chapter) for value in markers)

    return {key: [entry for entry in load(root, f"archive/{key}.json", []) if predates(entry)]
            for key in ("hooks", "debts")}


def chapter_outline(root, chapter):
    """Keep complete target-chapter sections, including nested scene headings."""
    text = read(root, "outline/near_term_outline.md")
    headings = list(re.finditer(r"^(#{1,6})[ \t]+([^\n]+)", text, re.M))
    sections = []
    active_chapter_level = None
    for i, heading in enumerate(headings):
        level = len(heading[1])
        if active_chapter_level is not None and level <= active_chapter_level:
            active_chapter_level = None
        number = re.match(r"(?:第\s*)?([0-9]+)\s*章\b", heading[2])
        if not number:
            continue
        if active_chapter_level is not None:
            continue
        if int(number[1]) != int(chapter):
            active_chapter_level = level
            continue
        end = next((following.start() for following in headings[i+1:]
                    if len(following[1]) <= level), len(text))
        sections.append(text[heading.start():end].strip())
        active_chapter_level = level
    return "\n\n".join(sections)


def archive_status(root):
    states, stale = confirmed(root)
    last = states[-1] if states else None
    written = [p.parent.name for p in bodies(root)]
    return {"updated_chapter": last["chapter"] if last else "", "stale_chapters": stale,
            "pending_chapters": [n for n in written if n not in {s["chapter"] for s in states}],
            "message": (f"已更新至第 {int(last['chapter'])} 章" if last else "尚无已确认的动态档案") +
                       ("；正文有修改，部分档案等待重新审核" if stale else "")}


def methods(question=""):
    """Use actual upstream method paragraphs and its unchanged chunk parser."""
    source = (HERE / "vendor/novel-copilot/references/divergence-patterns.md").read_text(encoding="utf-8")
    ids = ["D2", "D6", "D9", "D13", "D15"]
    picked = []
    for key in ids:
        match = re.search(r"^### " + key + r":.*?(?=^### |^## |\Z)", source, re.M | re.S)
        if match:
            # Keep the explanation, not chapter quotas or mandatory POV changes.
            excerpt = match.group(0).split("步骤：")[0][:600]
            picked.append({"id": key, "text": excerpt, "source": "novel-copilot"})
    chunks = upstream.parse_markdown_chunks(source, "剧情发散", "divergence-patterns.md")
    depth = (HERE / 'vendor/novel-copilot/references/character-depth-engine.md').read_text(encoding='utf-8')
    character = depth.split('**每卷至少')[0] + '\n' + depth.split('### 17.2 声音指纹')[1].split('### 17.3')[0]
    rescue = (HERE / 'vendor/novel-helper/packages/server/src/writingBlockRescue/prompt.ts').read_text(encoding='utf-8')
    rescue_rules = [json.loads('"' + m.group(1) + '"').replace('BOOK_MEMORY_COARSE', '共同故事依据')
                    for m in re.finditer(r'"([145]\) [^"\n]+)"', rescue)]
    return {"directions": picked, "indexed_sections": len(chunks),
            'character': character, 'rescue_rules': rescue_rules,
            "boundary": "方法按需要选择；不执行固定爽点、句式或章节配额；一致性和视角先于新颖度。"}


def context(root, chapter="0001", question="", scope="chapter"):
    root = Path(root).resolve()
    chapter = chapter_id(chapter)
    sources = source_hashes(root)
    entries = []
    evidence = {}
    states, stale = confirmed(root, before=int(chapter))
    latest = states[-1] if states else {}
    historical = any(int(p.parent.name) >= int(chapter) for p in bodies(root))
    indexes = chapter_start_indexes(root, chapter)
    ordered_files = list(dict.fromkeys((*PRIORITY_FILES, *BASE_FILES)))
    for file in ordered_files:
        if scope == "chapter" and file == "outline/volume_outline.md":
            continue
        if file in {"meta/current_world.md", "meta/current_characters.md", "meta/hooks.md", "meta/debts.md"} and (states or historical):
            continue
        if file == "meta/conflict_ledger.md" and historical:
            continue
        text = read(root, file)
        if scope == "chapter" and file == "outline/near_term_outline.md":
            text = chapter_outline(root, chapter)
        if text:
            # Preserve both the beginning and latest additions of growing indexes.
            chosen = text if len(text) <= 6500 else text[:3000] + "\n（中段按本次问题检索）\n" + text[-3500:]
            if len(text) > 6500:
                terms = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}", question)
                relevant = [p for p in text.split("\n\n") if any(t in p for t in terms)]
                chosen += "\n" + "\n\n".join(relevant[:6])[:2500]
            entries.append({"source_id": file, "content": chosen})
            evidence[file] = text
    # upstream story_state_text is real reused code, now fed the relevant file state.
    chars = latest.get("characters", [])
    active_text = question + read(root, f"planning/chapters/{chapter}.json") + chapter_outline(root, chapter)
    chars = sorted(chars, key=lambda c: str(c.get("name", "")) not in active_text)
    upstream_state = {"characters": [{"name": c.get("name", ""), "identity": c.get("identity", ""),
                                     "current_status": json.dumps(c.get("snapshot", {}), ensure_ascii=False),
                                     "motivation": json.dumps(c.get("drives", {}), ensure_ascii=False),
                                     "relationships": json.dumps(c.get("relationships", []), ensure_ascii=False)} for c in chars[:12]]}
    recent = [p for p in bodies(root) if int(p.parent.name) <= int(chapter)][-3:]
    for path in recent:
        file = path.relative_to(root).as_posix()
        text = read(root, file)
        excerpt = text if len(text) <= 16000 else text[:2500] + "\n（正文中段省略）\n" + text[-9000:]
        entries.append({"source_id": file, "content": excerpt})
        evidence[file] = text
        diff = read(root, f"story/{path.parent.name}/diff_story_confirmed.md")
        if diff:
            entries.append({"source_id": f"story/{path.parent.name}/diff_story_confirmed.md", "content": diff[:4000]})
            evidence[f"story/{path.parent.name}/diff_story_confirmed.md"] = diff
    adopted = load(root, f"planning/chapters/{chapter}.json")
    adopted_context = None
    if adopted:
        compatible = True
        try:
            verify(root, adopted['source_hashes'])
        except ValueError:
            compatible = False
        adopted_context = {"content": render_plan(adopted), "compatible": compatible,
                           "boundary": "作者已选择的待写方案；仍须与本次设定和正文核对，不是已发生事实。"}
    return {"chapter": chapter, "scope": scope, "sources": entries, "adopted_plan": adopted_context,
            "state_text": upstream.story_state_text(upstream_state, mode="deep"),
            "world_current": latest.get("world", {}), "indexes_before": indexes,
            "archive_status": archive_status(root),
            "methods": methods(question), "source_hashes": sources,
            "stale_chapters": stale, "evidence_texts": evidence}


PLOT_PROMPT = """
你同时是剧情讨论伙伴和网文策划，先直接回答最新问题。依据所给故事资料，按题材选择资源、权力、信息差、关系、制度、环境、内在矛盾等相关因素，不将所有题材套成末日或所有人写成恶人。
人物有各自利益、顾虑、所知和误解；善意、合作、算计、背叛都要有动机与代价。世界按既有时间、规则和行动因果发展，不为制造冲突凭空改变。
借鉴novel-copilot的线索/关系/配角独立行动发散，novel-helper的局部讨论与场景卡片；比较少量有区别的方向，不强行融合。已发生事实优先，新设想明确标明。情节与人物知识分开，遵守本书视角。
爽点是有准备的期待兑现，可是脱险、智胜、认可、真相、关系选择，不能限定为打脸。表达重点场景中的目标、压力、选择、转折、后果；例行过程概述，安静情感场景可保留。没有蒸馏照常原创，已有采用风格持续保留。
输出严格JSON：{"reply":"可供作者阅读的中文Markdown，先给结论，解释人物动机、依据、看点、风险","options":[{"id":"A","title":"方向名","reason":"推荐理由","risks":["风险"],"new_info":["尚未确定的新设计"],"scores":{"rhythm_fit":4,"drive_intensity":4,"thread_advancement":4,"emotional_utilization":4,"novelty":3,"hook_strength":4,"surprise":3},"chapters":[{"chapter":"0004","title":"章名","goal":"目标","conflict":"阻力及利益关系","choice":"人物选择及动机","turning_point":"转折","cost":"代价与影响","reveal":"信息变化","payoff":"本章兑现什么期待","hook":"长篇有依据的后续压力；短篇核心收束","time_advance":"世界时间变化","setup":[{"source_id":"输入sources中的真实source_id","quote":"该来源中连续存在的短句","use":"如何触发"}]}]}]}。
用户只询问分析/评价时options可以为空，不强行提出修改。请求发展方案时提供2-3个不同方向，只规划尚未写出的章节，单次至多12章；讨论章范围只提本章。短篇所有阶段归同一章且完成核心收束，长篇普通章不提前完结。
每个章节计划至少引用一条真实依据。新书缺少档案时可引用source_id=user_brief的用户原始创意，明确新设计，不伪称已有伏笔。source_id和quote由程序校验，不能编造。方案仅建议，不能宣称已经采用或写成正文。不暴露文件路径等内部实现给作者。
"""


def rank(options):
    """Adapted novel-copilot cmd_score's 8-dimensional weighted sum.

    Consistency is a validation gate, never a low-weight bonus. Scores are model
    judgments, not a promise of quality; no fixed payoff/novelty veto is retained.
    """
    weights = {"rhythm_fit": .20, "drive_intensity": .20, "thread_advancement": .20,
               "emotional_utilization": .15, "novelty": .10, "hook_strength": .10, "surprise": .05}
    for option in options:
        scores = option.get("scores", {})
        numbers = {}
        for key in weights:
            value = float(scores.get(key, 3))
            if not math.isfinite(value) or not 1 <= value <= 5:
                raise ValueError("方案评分需为 1 到 5 的有效数字，请重新分析。")
            numbers[key] = value
        option["score"] = round(sum(numbers[k] * w for k, w in weights.items()) / 5 * 100)
    return sorted(options, key=lambda o: -o["score"])


def parse_proposal(text, source, brief, mode="serial"):
    """Python port of novel-helper's fenced patch parsing and normalization.

    Normalize explicit, chapter-addressed deltas; never full-tree replacement.
    """
    raw = text.strip()
    fence = re.search(r"```(?:stagePatch|json)\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1)
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str) or not data["reply"].strip():
        raise ValueError("剧情建议缺少可读内容，请重新分析。")
    texts = {**source.get("evidence_texts", {}), "user_brief": brief}
    options = []
    raw_options = data.get("options", [])
    if not isinstance(raw_options, list):
        raise ValueError("候选方案格式无效。")
    for i, original in enumerate(raw_options[:3]):
        if not isinstance(original, dict) or not isinstance(original.get("chapters"), list):
            raise ValueError("候选方案缺少章节计划。")
        option = {"id": str(original.get("id", chr(65+i)))[:40], "title": str(original.get("title", "发展方向"))[:120],
                  "reason": str(original.get("reason", ""))[:3000], "risks": original.get("risks", []),
                  "new_info": original.get("new_info", []), "scores": original.get("scores", {}), "chapters": []}
        if not isinstance(option["scores"], dict):
            raise ValueError("方案评分格式无效。")
        for key in ('risks', 'new_info'):
            if not isinstance(option[key], list) or any(not isinstance(v, str) for v in option[key]):
                raise ValueError("方案风险与新设计必须是可读的文字列表。")
            option[key] = [v[:3000] for v in option[key][:15]]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', option['id']):
            raise ValueError("方案编号格式无效。")
        for item in original["chapters"][:12]:
            if not isinstance(item, dict):
                raise ValueError("章节计划格式无效。")
            chapter = chapter_id(item.get("chapter", source["chapter"]))
            if source.get("scope") == "chapter" and chapter != source["chapter"]:
                raise ValueError("方案超出了选定的章节范围。")
            if mode == "short" and chapter != "0001":
                raise ValueError("短篇的所有阶段应在同一篇内完成。")
            plan = {key: str(item.get(key, "")).strip()[:4000] for key in
                    ("title", "goal", "conflict", "choice", "turning_point", "cost", "reveal", "payoff", "hook", "time_advance")}
            if not all(plan[k] for k in ("goal", "conflict", "choice", "payoff")):
                raise ValueError("方案缺少目标、阻力、人物选择或期待兑现。")
            anchors = item.get("setup", [])
            if not isinstance(anchors, list) or not anchors:
                raise ValueError("章节方案缺少可追溯的前文依据。")
            valid = []
            for anchor in anchors[:8]:
                if not isinstance(anchor, dict):
                    raise ValueError("前文依据格式无效。")
                sid, quote = str(anchor.get("source_id", "")), str(anchor.get("quote", "")).strip()
                if len(quote) < 2 or sid not in texts or quote not in texts[sid]:
                    raise ValueError("模型引用的前文依据无法核实，请重新讨论。")
                valid.append({"source_id": sid, "quote": quote[:500], "use": str(anchor.get("use", ""))[:2000]})
            plan.update(chapter=chapter, setup=valid)
            option["chapters"].append(plan)
        if not option["chapters"] or len({p["chapter"] for p in option["chapters"]}) != len(option["chapters"]):
            raise ValueError("章节计划为空或有重复。")
        options.append(option)
    if len({o["id"] for o in options}) != len(options):
        raise ValueError("候选方案编号重复。")
    return data["reply"].strip(), rank(options)


PLAN_LABELS = {"goal": "本章目标", "conflict": "阻力与利益关系", "choice": "人物选择",
               "turning_point": "转折", "cost": "代价与后果", "reveal": "信息变化",
               "payoff": "期待与兑现", "hook": "收束与后续", "time_advance": "世界时间推进"}


def render_plan(plan):
    lines = [f"### 第 {int(plan['chapter'])} 章 · {plan.get('title', '采用的剧情计划')}"]
    lines += [f"- **{label}**：{plan.get(key, '')}" for key, label in PLAN_LABELS.items() if plan.get(key)]
    lines += ["\n**前文依据**"] + [f"- {a['quote']}：{a.get('use', '')}" for a in plan.get("setup", [])]
    return "\n".join(lines)


def apply_plan(root, entry, option_id):
    root = Path(root).resolve()
    if entry.get("status") != "completed" or not entry.get("plot_options"):
        raise ValueError("请先完成剧情方案分析。")
    receipt_path = f"planning/receipts/{entry['id']}-{option_id}.json"
    receipt = load(root, receipt_path)
    if receipt:
        return {**receipt, "already_applied": True}
    option = next((o for o in entry["plot_options"] if o["id"] == option_id), None)
    if not option:
        raise ValueError("请选择有效的候选方案。")
    verify(root, entry.get("plot_source", {}))
    for plan in option["chapters"]:
        if read(root, f"story/{plan['chapter']}/chapter.md").strip():
            raise ValueError("方案涉及已经写出的章节，请使用基于正文与读者意见的返修流程。")
    outline = read(root, "outline/near_term_outline.md")
    backup = f"planning/backups/{entry['id']}-{option_id}/near_term_outline.md"
    write(root, backup, outline)
    for plan in option["chapters"]:
        number = plan["chapter"]
        stored = {**plan, "request_id": entry["id"], "option_id": option_id, "adopted_at": now(),
                  "source_hashes": source_hashes(root, include_outline=False, before=number)}
        old = read(root, f"planning/chapters/{number}.json")
        if old:
            write(root, f"planning/backups/{entry['id']}-{option_id}/{number}.json", old)
        write(root, f"planning/chapters/{number}.json", stored)
        marker = f"<!-- adopted-plan:{number} -->"
        end = f"<!-- /adopted-plan:{number} -->"
        outline = re.sub(re.escape(marker) + r"[\s\S]*?" + re.escape(end), "", outline)
        outline += f"\n\n{marker}\n{render_plan(plan)}\n{end}"
    write(root, "outline/near_term_outline.md", outline)
    result = {"request_id": entry["id"], "option_id": option_id, "title": option["title"],
              "chapters": [p["chapter"] for p in option["chapters"]], "applied_at": now(), "already_applied": False}
    write(root, receipt_path, result)
    return result


def preflight(root, chapter):
    chapter = chapter_id(chapter)
    missing = sorted(path.stem for path in (Path(root) / "archive/chapter_resets").glob("[0-9][0-9][0-9][0-9].json")
                     if int(path.stem) < int(chapter) and not read(root, f"story/{path.stem}/chapter.md").strip())
    if missing:
        number = missing[0]
        return {"ready": False, "action": "mvp", "chapter": number,
                "reason_code": "chapter_missing", "changed_sources": [],
                "next_step": f"在章节目录中重新生成第 {int(number)} 章，完成质量审核后再继续。",
                "message": f"第 {int(number)} 章已经删除，不能跳过这一章的正文和确认档案继续创作。"}
    states, stale = confirmed(root, before=int(chapter))
    previous = [p for p in bodies(root) if int(p.parent.name) < int(chapter)]
    if stale:
        stale_chapter = stale[0]
        return {"ready": False, "action": "post-hoc", "chapter": stale_chapter,
                "reason_code": "archive_stale", "changed_sources": [],
                "next_step": f"重新审核第 {int(stale_chapter)} 章，并同步确认档案后再续写。",
                "message": f"第 {int(stale_chapter)} 章的正文或依据发生过变化，原档案已过期。请先重新完成质量审核。"}
    for path in previous:
        if not any(s["chapter"] == path.parent.name for s in states):
            previous_chapter = path.parent.name
            return {"ready": False, "action": "post-hoc", "chapter": previous_chapter,
                    "reason_code": "archive_pending", "changed_sources": [],
                    "next_step": f"先审核第 {int(previous_chapter)} 章并同步人物、世界和伏笔档案。",
                    "message": f"第 {int(previous_chapter)} 章已有正文，但还没有同步确认档案。请先完成质量审核。"}
    adopted = load(root, f"planning/chapters/{chapter}.json")
    if adopted:
        changed = changed_sources(root, adopted.get("source_hashes", {}))
        if not changed:
            return {"ready": True, "action": "mvp", "chapter": chapter,
                    "reason_code": "ready", "changed_sources": [],
                    "next_step": f"开始生成第 {int(chapter)} 章正文。",
                    "message": "已核对前文档案与采用方案，可继续本章。"}
        source_names = "、".join(changed[:4])
        more = f"等 {len(changed)} 项" if len(changed) > 4 else ""
        return {"ready": False, "action": "outline", "chapter": chapter,
                "reason_code": "adopted_plan_stale", "changed_sources": changed,
                "next_step": f"在创作助手中核对第 {int(chapter)} 章旧方案与当前方向，重新生成并采用剧情方案后，再生成正文。",
                "message": f"第 {int(chapter)} 章已采用方案的依据发生变化（{source_names}{more}）。旧方案仍保留在备份中；请先用创作助手核对当前设定和原选择，并采用更新后的章节方案。仅重新生成大纲不会更新旧方案。"}
    outline = read(root, "outline/near_term_outline.md")
    planned = {int(n) for n in re.findall(r"(?:第\s*|###\s*)(\d+)\s*章", outline)}
    if int(chapter) not in planned:
        return {"ready": False, "action": "outline", "chapter": chapter,
                "reason_code": "outline_missing", "changed_sources": [],
                "next_step": f"补充第 {int(chapter)} 章的剧情规划；已有作品和资料都会保留。",
                "message": f"近期大纲尚未覆盖第 {int(chapter)} 章。请先补充本章规划，不需要重新开书。"}
    return {"ready": True, "action": "mvp", "chapter": chapter,
            "reason_code": "ready", "changed_sources": [],
            "next_step": f"开始生成第 {int(chapter)} 章正文。",
            "message": "已核对前文档案与大纲覆盖，可继续本章。"}


def prepare_context(root, chapter, check=False):
    chapter = chapter_id(chapter)
    if check:
        result = preflight(root, chapter)
        if not result['ready']:
            raise ValueError(result['message'])
    ctx = context(root, chapter)
    adopted = load(root, f"planning/chapters/{chapter}.json")
    adopted_note = ''
    if adopted:
        try:
            verify(root, adopted["source_hashes"])
        except ValueError:
            if check: raise
            adopted_note = '【待重新协调】原采用计划的依据已变化。以下保留作者原选择供讨论和规划核对，不能直接作为有效生产计划；审核以正文为准。请由创作助手比较新设定与原选择后重新采用，禁止静默删除或忽略原选择。'
    priority = "\n\n".join(
        f"### {item['source_id']}\n{item['content']}" for item in ctx["sources"]
        if item["source_id"] in PRIORITY_FILES
    )
    text = "# 本章共同创作上下文\n\n## 当前创作契约\n" + priority
    text += "\n\n## 已确认的动态状态\n" + ctx["state_text"]
    text += "\n\n## 已确认的世界状态\n" + readable(ctx["world_current"])
    text += "\n\n## 本书依据与最近正文\n" + "\n\n".join(
        f"### {s['source_id']}\n{s['content']}" for s in ctx['sources']
        if s['source_id'] not in {*PRIORITY_FILES, 'outline/volume_outline.md', 'outline/near_term_outline.md'})
    text += "\n\n## 用户已采用的本章计划\n" + (adopted_note + '\n\n' + render_plan(adopted) if adopted else "尚未采用额外方案，按现有大纲原创。")
    if not adopted:
        text += "\n\n## 本章大纲（待写计划，不是已发生事实）\n" + (
            chapter_outline(root, chapter) or "未找到本章独立大纲，请核对章节规划。")
    indexes = ctx["indexes_before"]
    for key in ("hooks", "debts"):
        write(root, f"cache/story-support/{chapter}/{key}-before.md", readable(indexes.get(key, [])) or "暂无前文已确认条目。")
    text += "\n\n## 本章开始前的伏笔与债务\n" + readable(indexes)
    text += "\n\n返修已有章节时，以本章开始前的已确认人物、世界、伏笔状态为准。全书账本可能已推进到后续章节，不能把后续发生的事提前写成角色已知；只修改本章，后续正文留待衔接复核。"
    text += "\n\n## 参考剧情方法（按需要选用）\n" + "\n\n".join(d["text"] for d in ctx["methods"]["directions"])
    text += '\n\n## 人物信念与声音\n' + ctx['methods']['character']
    text += '\n\n## 局部剧情讨论约束\n' + '\n'.join(ctx['methods']['rescue_rules'])
    text += "\n\n事实与人物知识分开。章节方案是待写计划，不是已发生事实。世界规则、视角与本书风格先于方法偏好。"
    write(root, "cache/story-support/context.md", text)
    write(root, f"story/{chapter}/planning_context.json", {"chapter": chapter, "adopted_request": (adopted or {}).get("request_id", ""),
          "adopted_option": (adopted or {}).get("option_id", ""), "source_hashes": ctx["source_hashes"],
          "projects": [p["project"] for p in json.loads((HERE/"UPSTREAM.json").read_text())["projects"]]})
    return ctx


def begin_reader(root, chapter):
    chapter = chapter_id(chapter)
    if not read(root, f"story/{chapter}/chapter.md").strip():
        raise ValueError("本章还没有正文，不能评估。")
    write(root, f"cache/story-support/{chapter}/reader-source.json",
          {"chapter": chapter, "body_sha256": digest(root, f"story/{chapter}/chapter.md")})
    # Preserve the last verified legacy report before future chapters overwrite
    # the shared compatibility path. Never guess the chapter of an unbound report.
    legacy = load(root, "quality/reader_report.json", {})
    old_chapter = str(legacy.get("chapter_number", ""))
    if re.fullmatch(r"[0-9]{4}", old_chapter) and old_chapter != "0000":
        target = f"story/{old_chapter}/reader_report.json"
        if not read(root, target):
            write(root, target, legacy)


def commit_reader(root, chapter):
    chapter = chapter_id(chapter)
    source = load(root, f"cache/story-support/{chapter}/reader-source.json", {})
    if source.get("body_sha256") != digest(root, f"story/{chapter}/chapter.md"):
        raise ValueError("正文在评估过程中有变化，请重新评估。")
    report = load(root, f"story/{chapter}/reader_report.json", {})
    if not isinstance(report, dict) or report.get("verdict") not in ("pass", "revise", "reject"):
        raise ValueError("读者报告缺少有效结论，请重新评估。")
    reported_chapter = str(report.get("chapter_number", chapter)).zfill(4)
    if reported_chapter != chapter:
        raise ValueError("读者报告属于其他章节，未登记评估结果。")
    report.update(chapter_number=chapter, body_sha256=source["body_sha256"])
    write(root, f"story/{chapter}/reader_report.json", report)
    write(root, "quality/reader_report.json", report)
    return report


def begin_review(root, chapter):
    chapter = chapter_id(chapter)
    body = read(root, f"story/{chapter}/chapter.md")
    if not body.strip():
        raise ValueError("本章还没有正文。")
    write(root, f"cache/story-support/{chapter}/review-source.json", {"chapter": chapter,
          "body_sha256": digest(root, f"story/{chapter}/chapter.md"),
          "source_hashes": source_hashes(root, include_outline=False, before=chapter)})
    # Bind the review to this chapter's inputs, never a different chapter's cache.
    base = chapter_start_indexes(root, chapter)
    write(root, f'cache/story-support/{chapter}/indexes-before.json', base)


def confirmed_indexes(root, chapter, proposed, arb, body):
    base = load(root, f'cache/story-support/{chapter}/indexes-before.json', {})
    result = {}
    for key, prefix in [('hooks', 'h'), ('debts', 'd')]:
        entries = {item['id']: dict(item) for item in base.get(key, []) if isinstance(item, dict) and item.get('id')}
        planned = {item['id']: item for item in load(root, f'story/{chapter}/planned_{key}.json', []) if isinstance(item, dict) and item.get('id')}
        operations = proposed.get(key, [])
        additions = arb.get('new_' + key, [])
        if not isinstance(operations, list) or not isinstance(additions, list):
            raise ValueError('伏笔或债务确认格式无效。')
        for item in operations + additions:
            if not isinstance(item, dict) or not re.fullmatch(prefix + r'\d+', str(item.get('id', ''))):
                raise ValueError('伏笔或债务必须保留有效的原编号。')
            quote = validated_evidence(item.get('evidence'), body,
                                       '伏笔或债务缺少真实正文依据，未更新确认档案。')
            identity = item['id']
            old = entries.get(identity, planned.get(identity, {}))
            operation = item.get('operation', 'plant')
            if operation not in ('plant', 'advance', 'resolve'):
                raise ValueError('伏笔确认操作无效。')
            if operation != 'plant' and identity not in entries:
                raise ValueError('不能推进或回收尚未在正文埋下的伏笔或债务。')
            if item in additions and identity in planned and identity not in entries:
                raise ValueError('新发现的伏笔编号与本章计划重复，请重新核对。')
            value = {**old, **item, 'evidence': quote, 'source': '正文确认', 'source_chapter': chapter}
            value['status'] = 'resolved' if operation == 'resolve' else ('progressing' if operation == 'advance' and key == 'hooks' else 'open')
            value.setdefault('chapter_created', int(chapter))
            if operation == 'resolve': value['chapter_resolved'] = int(chapter)
            if operation == 'advance': value['last_advanced'] = int(chapter)
            entries[identity] = value
        result[key] = list(entries.values())
    return base, result


def commit(root, chapter):
    chapter = chapter_id(chapter)
    source = load(root, f"cache/story-support/{chapter}/review-source.json")
    if not source or source["body_sha256"] != digest(root, f"story/{chapter}/chapter.md"):
        raise ValueError("正文在审核过程中有变化，请重新质量审核。")
    verify(root, source["source_hashes"])
    obs = load(root, "cache/observer/obs_output.json", {})
    arb = load(root, "cache/arbiter/arb_output.json", {})
    if not isinstance(obs, dict) or not isinstance(arb, dict) or "story_confirmed" not in arb:
        raise ValueError("后验产物不完整，未更新正式档案。")
    body = read(root, f"story/{chapter}/chapter.md")
    prior, _ = confirmed(root, before=int(chapter))
    previous = prior[-1] if prior else {}
    chars = {c["name"]: c for c in previous.get("characters", []) if c.get("name")}
    proposed = obs.get("confirmed_state", {})
    if not isinstance(proposed, dict):
        raise ValueError("确认状态格式无效。")
    evidence_changes = []
    if not isinstance(proposed.get('characters', []), list):
        raise ValueError('人物状态必须是列表。')
    for item in proposed.get("characters", []):
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("人物状态缺少姓名。")
        quote = validated_evidence(item.get("evidence"), body,
                                   "人物状态的正文依据无法核实，未更新正式档案。")
        name = item["name"]
        old = chars.get(name, {"name": name})
        chars[name] = {**old, **item, "evidence": quote, "source_chapter": chapter}
        for field in ('snapshot', 'drives'):
            if field in item and not isinstance(item[field], dict):
                raise ValueError('人物处境与动机必须是结构化状态。')
            chars[name][field] = {**old.get(field, {}), **{k:v for k,v in item.get(field, {}).items() if v not in ('', None)}}
        if 'relationships' in item:
            if not isinstance(item['relationships'], list) or any(not isinstance(r, dict) for r in item['relationships']):
                raise ValueError('人物关系格式无效。')
            relationships = {r.get('target'): r for r in old.get('relationships', [])}
            relationships.update({r.get('target'): r for r in item['relationships'] if r.get('target')})
            chars[name]['relationships'] = list(relationships.values())
        evidence_changes.append({"name": name, "change": item.get("snapshot", {}), "evidence": quote})
    # Existing books can be reviewed without inventing full states; retain the
    # observer's sourced deltas for next CM, but label incomplete snapshots.
    changes = obs.get("character_diff", {})
    world = {**previous.get("world", {})}
    facts = list(world.get("facts", []))
    for item in arb.get("world_rulings", {}).get("entries", []):
        if item.get("verdict") == "adopt":
            quote = validated_evidence(item.get('evidence'), body,
                                       '新增世界事实缺少真实正文依据，未更新确认档案。')
            facts.append({"description": item.get("fact", ""), "source_chapter": chapter, 'evidence': quote})
    world["facts"] = list({f["description"]: f for f in facts}.values())
    authored = load(root, f"story/{chapter}/planned_world_state.json", {})
    if authored:
        world["作者规划的幕后演进（不等于角色已知）"] = authored
    indexes_before, indexes = confirmed_indexes(root, chapter, proposed, arb, body)
    snapshot = {"version": 1, "chapter": chapter, "updated_at": now(), "body_sha256": source["body_sha256"],
                "source_hashes": source["source_hashes"], "characters": list(chars.values()), "world": world,
                "indexes_before": indexes_before, "indexes": indexes,
                "character_changes": changes, "story_changes": arb["story_confirmed"],
                "pending_world": [i for i in arb.get("world_rulings", {}).get("entries", []) if i.get("verdict") != "adopt"]}
    target = f"story/{chapter}/confirmed_state.json"
    old = load(root, target)
    if old and old != snapshot:
        write(root, f"archive/history/{chapter}/{old['body_sha256'][:16]}.json", old)
    write(root, target, snapshot)
    for key, items in indexes.items():
        write(root, f'archive/{key}.json', items)
        write(root, f'meta/{key}.md', ('# 已确认伏笔' if key == 'hooks' else '# 已确认叙事债务') + '\n\n' + (readable(items) or '暂无确认条目。'))
    write(root, f"story/{chapter}/confirmed_state.md", f"# 第 {int(chapter)} 章结束后的确认状态\n\n" + readable({"人物状态": snapshot["characters"], "世界局势": world, "人物变化": changes}))
    refresh_archive(root)
    return snapshot


def refresh_archive(root):
    states, stale = confirmed(root)
    status = archive_status(root)
    write(root, "archive/current_status.json", status)
    latest = states[-1] if states else {}
    # A revision of an early chapter can invalidate later snapshots. Rebuild
    # shared indexes from the latest still-valid snapshot, never future facts.
    for key in ("hooks", "debts"):
        entries = latest.get("indexes", {}).get(key, [])
        write(root, f"archive/{key}.json", entries)
        write(root, f"meta/{key}.md", ("# 已确认伏笔" if key == "hooks" else "# 已确认叙事债务")
              + "\n\n" + (readable(entries) or "暂无确认条目。"))
    write(root, "meta/current_characters.md", "# 人物当前状态\n\n" + status["message"] + "\n\n" +
          (readable(latest.get("characters", [])) or "暂无已确认人物状态。") +
          "\n\n## 本章人物变化\n" + readable(latest.get("character_changes", {})))
    write(root, "meta/current_world.md", "# 世界当前局势\n\n" + status["message"] + "\n\n" + readable(latest.get("world", {})))
    timeline = [{"chapter": s["chapter"], "变化": s.get("story_changes", {})} for s in states]
    write(root, "meta/story_timeline.md", "# 剧情变化记录\n\n" + readable(timeline))
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["context", "begin-reader", "commit-reader", "begin-review", "commit", "preflight", "refresh"])
    parser.add_argument("--chapter", default="0001")
    parser.add_argument("--check", action='store_true')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    action = {"context": prepare_context, "begin-reader": begin_reader, "commit-reader": commit_reader,
              "begin-review": begin_review, "commit": commit, "preflight": preflight}
    result = (refresh_archive(root) if args.command == "refresh" else
              prepare_context(root, args.chapter, args.check) if args.command == 'context' else action[args.command](root, args.chapter))
    if args.command == "preflight" and not result["ready"]:
        raise ValueError(result["message"])
    print(json.dumps({"status": "completed", "command": args.command, "chapter": args.chapter}, ensure_ascii=False))


if __name__ == "__main__":
    main()
