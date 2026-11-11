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
from functools import lru_cache
from pathlib import Path
from uuid import uuid4


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("xs2_story_upstream", HERE / "upstream.py")
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def _guarded_rejection(message):
    spec=importlib.util.spec_from_file_location('plugin_rejection_transport',Path(__file__).resolve().parents[1]/'production_guard/rejections.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.emit(message)

@lru_cache(maxsize=1)
def archive_store():
    spec = importlib.util.spec_from_file_location('story_archive_store', HERE / 'archive_store.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def memory():
    spec = importlib.util.spec_from_file_location('story_memory', HERE / 'memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def serial():
    spec = importlib.util.spec_from_file_location('story_serial', HERE / 'serial.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _prose_policy():
    entry = HERE.parent / "prose_policy" / "prose_policy.py"
    policy_spec = importlib.util.spec_from_file_location("xs2_story_prose_policy", entry)
    policy = importlib.util.module_from_spec(policy_spec)
    policy_spec.loader.exec_module(policy)
    return policy


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
    if relative.startswith('@memory/scene-time/'):
        return archive_store().digest(root,relative)
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
    files.append('meta/entity_registry.json')
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
    with archive_store().verification_reader(root) as verification:
        for path in sorted((Path(root) / "story").glob("[0-9][0-9][0-9][0-9]/confirmed_state.json")):
            number = int(path.parent.name)
            if before is not None and number >= int(before):
                continue
            try:
                canonical = safe(root, f"story/{number:04d}/confirmed_state.json")
                if canonical != path.absolute():
                    raise ValueError("确认记录指向别名路径")
                data = json.loads(canonical.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict) or data.get("chapter") != f"{number:04d}":
                    raise ValueError("确认记录章节无效")
                archive_store().verify_snapshot(root, data, reader=verification)
                hashes = data.get("source_hashes")
                if not isinstance(hashes, dict) or not isinstance(data.get("body_sha256"), str) or not data["body_sha256"]:
                    raise ValueError("确认记录缺少来源校验")
                verify(root, hashes)
                dependencies = list(hashes) + [item.get('source_id','') for item in data.get('memory_dependencies',[]) if isinstance(item,dict)]
                if any(re.match(r'story/([0-9]{4})/', file) and re.match(r'story/([0-9]{4})/', file)[1] in stale for file in dependencies):
                    raise ValueError('依赖的前文档案已失效')
                if digest(root, f"story/{number:04d}/chapter.md") != data.get("body_sha256"):
                    raise ValueError("正文已修改")
                valid.append(data)
            except (ValueError, OSError):
                stale.append(path.parent.name)
    return valid, stale


def chapter_start_indexes(root, chapter):
    """An explicitly empty snapshot is authoritative, not a fallback trigger."""
    prior, _ = confirmed(root, before=int(chapter))
    old = load(root, f"story/{chapter}/confirmed_state.json", {})
    if old and not prior:
        archive_store().historical_snapshot(root, old)
        try:
            verify(root, old.get('source_hashes', {}))
        except ValueError:
            return {'hooks': [], 'debts': []}
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


def chapter_outline(root, chapter, text=None):
    """Keep complete target-chapter sections, including nested scene headings."""
    if text is None:
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


def archive_status(root, _states=None):
    states, stale = confirmed(root) if _states is None else _states
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


def context(root, chapter="0001", question="", scope="chapter", *, runtime=None, chapter_drafts=True,
            archive_observation=False):
    archive_store().recover(root)
    root = Path(root).resolve()
    chapter = chapter_id(chapter)
    policy = _prose_policy()
    preference = runtime["context"] if runtime is not None else policy.effective_context(root, chapter)

    def effective(file, canonical):
        if preference["mode"] != "narrative_led":
            return canonical
        if runtime is not None:
            alias = runtime["aliases"].get(file)
            return read(root, alias) if alias else canonical
        return policy.effective_text(root, file, canonical)

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
        original = read(root, file)
        text = effective(file, original)
        if scope == "chapter" and file == "outline/near_term_outline.md":
            original = chapter_outline(root, chapter, original)
            text = chapter_outline(root, chapter, text)
        if text:
            # Preserve both the beginning and latest additions of growing indexes.
            chosen = text if len(text) <= 6500 else text[:3000] + "\n（中段按本次问题检索）\n" + text[-3500:]
            if len(text) > 6500:
                terms = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}", question)
                relevant = [p for p in text.split("\n\n") if any(t in p for t in terms)]
                chosen += "\n" + "\n\n".join(relevant[:6])[:2500]
            entries.append({"source_id": file, "content": chosen})
            evidence[file] = original
    drafts = []
    if chapter_drafts and scope == "chapter" and preference["instructions"]:
        for name in ("single_chapter_guide", "storyboard", "storyboard_final"):
            file = f"story/{chapter}/{name}.md"
            original = read(root, file)
            text = effective(file, original)
            if text != original:
                drafts.append({"source_id": file, "content": text[:6500],
                               "boundary": "待写计划，不是已发生事实。"})
                sources[file] = digest(root, file)
                evidence[file] = original
    # upstream story_state_text is real reused code, now fed the relevant file state.
    chars = latest.get("characters", [])
    query_plan=load(root,f'planning/chapters/{chapter}.json',{})
    effective_outline=chapter_outline(root,chapter,effective('outline/near_term_outline.md',read(root,'outline/near_term_outline.md')))
    active_text = question + readable({k:v for k,v in query_plan.items() if k in {*PLAN_LABELS,'setup','title'}}) + effective_outline
    recalled = memory().retrieve(root, chapter, active_text, states=states, outline_text=effective_outline)
    active_ids = {e['id'] for e in recalled['entities']}
    active_names = {e['name'] for e in recalled['entities']}
    chars = sorted(chars, key=lambda c: c.get('entity_id') not in active_ids and c.get('name') not in active_names)
    selected=[]; omitted=[]; size=0
    for character in chars:
        amount=len(json.dumps(character,ensure_ascii=False))
        if size+amount<=10000 or character.get('entity_id') in active_ids or character.get('name') in active_names:
            selected.append(character);size+=amount
        else:omitted.append(character.get('entity_id') or character.get('name'))
    recalled['omitted_character_states']=omitted
    time_key=recalled['scene_time_key']
    time_unverified=(time_key is not None and (type(latest.get('world_time_key')) is not int or latest['world_time_key']>time_key))
    if time_unverified:
        selected=[{**c,'identity':'作者身份索引；本场景状态待核实',
            'snapshot':{'temporal_status':'unverified','scene_time_key':time_key,
                'cognition':recalled['cognition'].get(c.get('entity_id'),{})},
            'drives':{},'relationships':[]} for c in selected]
    upstream_state = {"characters": [{"name": c.get("name", ""), "identity": c.get("identity", ""),
                                     "current_status": json.dumps(c.get("snapshot", {}), ensure_ascii=False),
                                     "motivation": json.dumps(c.get("drives", {}), ensure_ascii=False),
                                     "relationships": json.dumps(c.get("relationships", []), ensure_ascii=False)} for c in selected]}
    for hit in recalled['hits']:
        evidence[hit['source_id']] = read(root,hit['source_id'])
        sources[hit['source_id']] = hit['source_sha256']
    for dependency in recalled['read_set']:
        sources[dependency['source_id']]=dependency['source_sha256']
        evidence[dependency['source_id']]=read(root,dependency['source_id'])
    recent = [p for p in bodies(root) if int(p.parent.name) <= int(chapter)][-3:]
    for path in recent:
        file = path.relative_to(root).as_posix()
        text = read(root, file)
        excerpt = text if len(text) <= 16000 else text[:2500] + "\n（正文中段省略）\n" + text[-9000:]
        entries.append({"source_id": file, "content": excerpt})
        evidence[file] = text
        # A previous verdict about this same body is the output of post-hoc,
        # not a source for a fresh observation or independent arbitration.
        if archive_observation and path.parent.name == chapter:
            continue
        diff = read(root, f"story/{path.parent.name}/diff_story_confirmed.md")
        if diff:
            entries.append({"source_id": f"story/{path.parent.name}/diff_story_confirmed.md", "content": diff[:4000]})
            evidence[f"story/{path.parent.name}/diff_story_confirmed.md"] = diff
            sources[f"story/{path.parent.name}/diff_story_confirmed.md"] = digest(root,f"story/{path.parent.name}/diff_story_confirmed.md")
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
    serial_state=serial().status(root,chapter,states=states)
    if serial_state.get('enabled'):
        sources['meta/serial_contract.json']=digest(root,'meta/serial_contract.json')
        if time_unverified:
            serial_state['entry']['characters']=[]
            serial_state['entry']['world']={'temporal_status':'unverified'}
    return {"chapter": chapter, "scope": scope, "sources": entries, "adopted_plan": adopted_context,
            "serial":serial_state,
            "memory": recalled,
            "state_text": upstream.story_state_text(upstream_state, mode="deep"),
            "world_current": ({'temporal_status':'unverified','scene_time_key':time_key,
                'boundary':'上一叙事位置的世界状态不直接沿用到本场景；静态规则遵循本书契约'} if time_unverified else latest.get("world", {})), "indexes_before": indexes,
            "archive_status": archive_status(root),
            "methods": methods(question), "source_hashes": sources,
            "stale_chapters": stale, "evidence_texts": evidence,
            **({"prose_policy": preference} if preference["instructions"] else {}),
            **({"chapter_drafts": drafts} if drafts else {})}


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
    archive_store().recover(root)
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
                "impact": memory().impact(root),
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
    serial_check=serial().need_plan(root,chapter)
    if not serial_check['ready']:
        return {'ready':False,'action':'outline','chapter':chapter,'reason_code':serial_check['reason_code'],
            'serial':serial_check,'changed_sources':[], 'next_step':'核对本卷承接并完成后续滚动规划。',
            'message':'本章需要更新滚动计划或复核跨卷承接；原稿与作者选择均保留。'}
    adopted = load(root, f"planning/chapters/{chapter}.json")
    if adopted:
        changed = changed_sources(root, adopted.get("source_hashes", {}))
        if not changed:
            return {"ready": True, "action": "mvp", "chapter": chapter,
                    "reason_code": "ready", "changed_sources": [],
                    "next_step": f"开始生成第 {int(chapter)} 章正文。",
                    "message": "已核对前文档案与采用方案，可继续本章。"}
        source_names = "、".join('本章世界时间序号' if p.startswith('@memory/scene-time/') else p for p in changed[:4])
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


def prepare_context(root, chapter, check=False, *, task_id=None, archive_observation=False):
    chapter = chapter_id(chapter)
    if check:
        result = preflight(root, chapter)
        if not result['ready']:
            raise ValueError(result['message'])
    policy = _prose_policy()
    runtime = policy.prepare_runtime(root, chapter, task_id=task_id or uuid4().hex)
    # MVP will produce a new guide before using it. Review stages can use the
    # selected existing guide as separately identified planning evidence.
    ctx = context(root, chapter, runtime=runtime, chapter_drafts=not check,
                  archive_observation=archive_observation)
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
    text += '\n\n## 卷级承接与滚动规划（作者统筹资料，不赋予角色知识）\n'+json.dumps(ctx['serial'],ensure_ascii=False,indent=2)
    text += '\n\n## 远距离原文与认知来源\n' + json.dumps(ctx['memory'],ensure_ascii=False,indent=2)
    text += ('\n\n检索命中是核对资料，不要求逐项写进正文。作者掌握的身份映射和世界事实不直接赋予人物；'
             '误信、传言、获知过程与客观事实分别使用。未记录获知来源不等于确定不知，可保留有依据的常识与推断。'
             '叙述者是否可知、是否可靠、揭示时机及有意歧义依本书契约，不以限知规则统一约束全部作品。'
             '倒叙、插叙或跨时序场景不能直接沿用上一叙事位置的全部人物状态；明确世界时间时按该时间核对，未知则保留待核实。')
    text += "\n\n## 本书依据与最近正文\n" + "\n\n".join(
        f"### {s['source_id']}\n{s['content']}" for s in ctx['sources']
        if s['source_id'] not in {*PRIORITY_FILES, 'outline/volume_outline.md', 'outline/near_term_outline.md'})
    text += "\n\n## 用户已采用的本章计划\n" + (adopted_note + '\n\n' + render_plan(adopted) if adopted else "尚未采用额外方案，按现有大纲原创。")
    if not adopted:
        outline_alias = runtime["aliases"].get("outline/near_term_outline.md")
        text += "\n\n## 本章大纲（待写计划，不是已发生事实）\n" + (
            chapter_outline(root, chapter, read(root, outline_alias) if outline_alias else None)
            or "未找到本章独立大纲，请核对章节规划。")
    preference_path = Path(root) / 'learning/character_center/preferences.json'
    if preference_path.is_file():
        entry = HERE.parent / 'character_center' / 'character_center.py'
        if entry.is_file():
            center_spec = importlib.util.spec_from_file_location('xs2_story_character_center', entry)
            center = importlib.util.module_from_spec(center_spec)
            center_spec.loader.exec_module(center)
            guidance = center.planned_preferences(root, chapter)
            if guidance:
                text += '\n\n## 作者采用的场景表达参考\n仅限下列场景和人物。按情境参考，不复述样句，不作为人物或世界事实。\n'
                text += readable(guidance)
    if ctx.get("chapter_drafts"):
        text += "\n\n## 本章细纲（待写计划，不是已发生事实）\n" + "\n\n".join(
            f"### {item['source_id']}\n{item['content']}" for item in ctx["chapter_drafts"]
        )
    indexes = ctx["indexes_before"]
    for key in ("hooks", "debts"):
        write(root, f"cache/story-support/{chapter}/{key}-before.md", readable(indexes.get(key, [])) or "暂无前文已确认条目。")
    text += "\n\n## 本章开始前的伏笔与债务\n" + readable(indexes)
    text += "\n\n返修已有章节时，以本章开始前的已确认人物、世界、伏笔状态为准。全书账本可能已推进到后续章节，不能把后续发生的事提前写成角色已知；只修改本章，后续正文留待衔接复核。"
    text += "\n\n## 参考剧情方法（按需要选用）\n" + "\n\n".join(d["text"] for d in ctx["methods"]["directions"])
    text += '\n\n## 人物信念与声音\n' + ctx['methods']['character']
    text += '\n\n## 局部剧情讨论约束\n' + '\n'.join(ctx['methods']['rescue_rules'])
    text += "\n\n事实与人物知识分开。章节方案是待写计划，不是已发生事实。世界规则、视角与本书风格先于方法偏好。"
    text += ("\n\n## 内部核对与正文表达的边界\n"
             "以上材料用于规划和核对，不是正文需要逐条念出的事实清单。人物只说当场需要争取或确认的信息；"
             "已由行为和结果成立的因果，不在对白后反复翻译。必要的证词、条件和承诺仍须清楚。"
             "物件来历、感受与回忆随当下注意力取舍，不给每件道具相同分量。"
             "这段指导只改变材料的使用方式，不修改既有事实、人物卡、风格文件或作者已确认的约束。")
    if runtime["directory"]:
        runtime["common_file"] = policy.runtime_file(root, runtime["directory"], "common.md", text + "\n")
    else:
        write(root, "cache/story-support/context.md", text)
    write(root, f"story/{chapter}/planning_context.json", {"chapter": chapter, "adopted_request": (adopted or {}).get("request_id", ""),
          "adopted_option": (adopted or {}).get("option_id", ""), "source_hashes": ctx["source_hashes"],
          "memory_dependencies": ctx['memory']['read_set'],
          "projects": [p["project"] for p in json.loads((HERE/"UPSTREAM.json").read_text())["projects"]]})
    return ctx | {"prose_policy_runtime": runtime}


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


def review_file(chapter, name):
    task = os.environ.get('TASK_ID', '')
    if task:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task):
            raise ValueError('审核任务编号无效')
        return f'cache/story-support/reviews/{task}/{chapter}/{name}'
    return {'observer.json':'cache/observer/obs_output.json',
            'arbiter.json':'cache/arbiter/arb_output.json'}.get(name, f'cache/story-support/{chapter}/{name}')


def begin_review(root, chapter):
    archive_store().recover(root)
    chapter = chapter_id(chapter)
    body = read(root, f"story/{chapter}/chapter.md")
    if not body.strip():
        raise ValueError("本章还没有正文。")
    hashes = source_hashes(root, include_outline=False, before=chapter)
    previous, _ = confirmed(root, before=int(chapter))
    hashes.update({f"story/{s['chapter']}/confirmed_state.json": digest(root, f"story/{s['chapter']}/confirmed_state.json") for s in previous})
    write(root, review_file(chapter, 'review-source.json'), {"chapter": chapter,
          "task_id": os.environ.get('TASK_ID', ''),
          "body_sha256": digest(root, f"story/{chapter}/chapter.md"),
          "source_hashes": hashes,
          "book_contract_sha256": archive_store().contract(root)})
    # Bind the review to this chapter's inputs, never a different chapter's cache.
    base = chapter_start_indexes(root, chapter)
    write(root, review_file(chapter, 'indexes-before.json'), base)
    dependencies = load(root,f'story/{chapter}/planning_context.json',{}).get('memory_dependencies',[])
    write(root,review_file(chapter,'memory-dependencies.json'),dependencies)
    source = load(root, review_file(chapter, 'review-source.json'))
    source['serial_contract_sha256']=digest(root,'meta/serial_contract.json')
    source['memory_dependencies'] = dependencies
    source['source_hashes'].update({relative: digest(root, relative) for relative in (
        review_file(chapter, 'indexes-before.json'),
        review_file(chapter, 'memory-dependencies.json'),
        f'story/{chapter}/planned_world_state.json', f'story/{chapter}/planned_hooks.json',
        f'story/{chapter}/planned_debts.json')})
    write(root, review_file(chapter, 'review-source.json'), source)


def confirmed_indexes(root, chapter, proposed, arb, body):
    base = load(root, review_file(chapter, 'indexes-before.json'), {})
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
            if operation == 'advance' and identity in planned and identity not in entries and item in operations:
                # This is the first observed manifestation of a planned thread.
                operation = 'plant'
            if operation != 'plant' and identity not in entries:
                raise ValueError('不能推进或回收尚未在正文埋下的伏笔或债务。')
            if item in additions and identity in planned and identity not in entries:
                raise ValueError('新发现的伏笔编号与本章计划重复，请重新核对。')
            value = {**old, **item, 'operation': operation, 'evidence': quote, 'source': '正文确认', 'source_chapter': chapter}
            value['status'] = 'resolved' if operation == 'resolve' else ('progressing' if operation == 'advance' and key == 'hooks' else 'open')
            value.setdefault('chapter_created', int(chapter))
            if operation == 'resolve': value['chapter_resolved'] = int(chapter)
            if operation == 'advance': value['last_advanced'] = int(chapter)
            entries[identity] = value
        result[key] = list(entries.values())
    return base, result


def observed_characters(proposed, body):
    if not isinstance(proposed, dict):
        raise ValueError("确认状态格式无效。")
    items = proposed.get('characters', [])
    if not isinstance(items, list):
        raise ValueError('人物状态必须是列表。')
    for item in items:
        if not isinstance(item, dict) or not item.get('name'):
            raise ValueError("人物状态缺少姓名。")
        quote = validated_evidence(item.get("evidence"), body,
                                   "人物状态的正文依据无法核实，未更新正式档案。")
        yield item, quote


def validate_observation(root, chapter):
    chapter = chapter_id(chapter)
    body = read(root, f"story/{chapter}/chapter.md")
    obs = load(root, review_file(chapter, "observer.json"), {})
    proposed = obs.get('confirmed_state') if isinstance(obs, dict) else None
    list(observed_characters(proposed, body))
    confirmed_indexes(root, chapter, proposed, {}, body)


@lru_cache(maxsize=1)
def observation_cache():
    spec = importlib.util.spec_from_file_location('archive_observation', HERE/'archive_observation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reuse_observation(root, chapter):
    chapter = chapter_id(chapter)
    source = load(root, review_file(chapter, 'review-source.json'))
    journal = archive_store()
    guard = journal.execution_guard()
    cache = observation_cache()
    binding = cache.identity(root, source, journal, guard)
    prior = cache.previous(root, source, binding, journal)
    if prior is None:
        if source.get('task_id'):
            journal.event(root, 'archive_observation_miss', {'task_id': source['task_id'], 'chapter': chapter})
        return False
    guard.assert_current(root)
    verify(root, source['source_hashes'])
    if source['body_sha256'] != digest(root, f'story/{chapter}/chapter.md'):
        raise ValueError('观察复用期间正文已有变化')
    observation, receipt, origin = prior
    write(root, review_file(chapter, 'observer.json'), observation)
    try:
        validate_observation(root, chapter)
    except ValueError:
        journal.event(root, 'archive_observation_miss', {'task_id': source['task_id'], 'chapter': chapter})
        return False
    journal.event(root, 'archive_observation_reuse', {
        'task_id': source['task_id'], 'origin_commit_id': origin, 'observer_sha256': receipt['observer_sha256'],
    })
    return True


def validate_cached_observation(root, chapter):
    chapter = chapter_id(chapter)
    source = load(root, review_file(chapter, 'review-source.json'))
    journal = archive_store()
    guard = journal.execution_guard()
    guard.assert_current(root)
    verify(root, source['source_hashes'])
    if source['body_sha256'] != digest(root, f'story/{chapter}/chapter.md'):
        raise ValueError('观察复用期间正文已有变化')
    observation = load(root, review_file(chapter, 'observer.json'))
    if observation_cache().provenance(root, source, observation, journal, guard) is None:
        raise ValueError('观察结果缺少当前来源与可信归档凭据')
    validate_observation(root, chapter)


def commit(root, chapter):
    journal = archive_store()
    journal.recover(root)
    archive_revision = journal.revision(root)
    chapter = chapter_id(chapter)
    source = load(root, review_file(chapter, 'review-source.json'))
    if not source or source["body_sha256"] != digest(root, f"story/{chapter}/chapter.md"):
        raise ValueError("正文在审核过程中有变化，请重新质量审核。")
    verify(root, source["source_hashes"])
    if source.get('serial_contract_sha256',digest(root,'meta/serial_contract.json'))!=digest(root,'meta/serial_contract.json'):
        raise ValueError('审核期间卷级契约已有变化，请重新核对')
    if source.get('book_contract_sha256', journal.contract(root)) != journal.contract(root):
        raise ValueError('本书规则在审核过程中已有变化，请重新审核')
    obs = load(root, review_file(chapter, "observer.json"), {})
    arb = load(root, review_file(chapter, "arbiter.json"), {})
    if not isinstance(obs, dict) or not isinstance(arb, dict) or "story_confirmed" not in arb:
        raise ValueError("后验产物不完整，未更新正式档案。")
    inputs = {'source': source, 'observer_candidate': obs, 'arbiter_confirmed': arb}
    provenance = observation_cache().provenance(root, source, obs, journal, journal.execution_guard())
    if provenance is None and source.get('task_id') and journal.events(
            root, kind='archive_observation_reuse', task_id=source['task_id']):
        raise ValueError('复用观察的依据已有变化，请重新运行完整观察和裁决')
    if provenance:
        inputs['observation_reuse'] = provenance
    commit_id = journal.identity([chapter, inputs, journal.contract(root)])
    saved = journal.existing(root, commit_id)
    if saved:
        return saved
    body = read(root, f"story/{chapter}/chapter.md")
    prior, _ = confirmed(root, before=int(chapter))
    previous = prior[-1] if prior else {}
    proposed = obs.get("confirmed_state", {})
    observed = [item for item,quote in observed_characters(proposed,body)]
    old_characters, observed, identities = memory().canonicalize(root, previous.get('characters',[]), observed,
                                                               arb.get('identity_rulings',[]), body, previous.get('entities',[]))
    memory_events = memory().validate_events(root,chapter,arb.get('memory_events',[]),prior,identities,body)
    serial_progress=serial().validate_progress(root,chapter,arb.get('serial_progress',[]),body)
    chars = {c['entity_id']:c for c in old_characters}
    evidence_changes = []
    for item in observed:
        quote = validated_evidence(item['evidence'],body,'人物证据无效')
        name = item["name"]
        key = item['entity_id']
        old = chars.get(key, {"name": name})
        chars[key] = {**old, **item, "evidence": quote, "source_chapter": chapter}
        for field in ('snapshot', 'drives'):
            if field in item and not isinstance(item[field], dict):
                raise ValueError('人物处境与动机必须是结构化状态。')
            chars[key][field] = {**old.get(field, {}), **{k:v for k,v in item.get(field, {}).items() if v not in ('', None)}}
        if 'relationships' in item:
            if not isinstance(item['relationships'], list) or any(not isinstance(r, dict) for r in item['relationships']):
                raise ValueError('人物关系格式无效。')
            relationships = {r.get('target'): r for r in old.get('relationships', [])}
            relationships.update({r.get('target'): r for r in item['relationships'] if r.get('target')})
            chars[key]['relationships'] = list(relationships.values())
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
    snapshot = {"version": 1, "archive_commit_id": commit_id, "task_id": source.get('task_id', ''), "chapter": chapter, "updated_at": now(), "body_sha256": source["body_sha256"],
                "source_hashes": {p: h for p, h in source["source_hashes"].items() if not p.startswith('cache/')}, "characters": list(chars.values()), "world": world,
                "indexes_before": indexes_before, "indexes": indexes,
                "character_changes": changes, "story_changes": arb["story_confirmed"],
                "memory_events": memory_events,
                "serial_progress":serial_progress,
                "entities": list(identities.values()),
                "world_time_key": authored.get('world_time_key'),
                "memory_dependencies": source.get('memory_dependencies',[]),
                "pending_world": [i for i in arb.get("world_rulings", {}).get("entries", []) if i.get("verdict") != "adopt"]}
    target = f"story/{chapter}/confirmed_state.json"
    old = load(root, target)
    outputs = {target: snapshot}
    if old and old != snapshot:
        outputs[f"archive/history/{chapter}/{old['body_sha256'][:16]}-{journal.identity(old)[:12]}.json"] = old
    outputs[f"story/{chapter}/confirmed_state.md"] = f"# 第 {int(chapter)} 章结束后的确认状态\n\n" + readable({"人物状态": snapshot["characters"], "世界局势": world, "人物变化": changes})
    states, stale = confirmed(root)
    # Earlier edits invalidate dependent snapshots through their source hashes.
    dependents = [s['chapter'] for s in states if target in s.get('source_hashes', {})]
    states = sorted([s for s in states if s['chapter'] != chapter and s['chapter'] not in dependents] + [snapshot], key=lambda s: s['chapter'])
    refresh_archive(root, _states=(states, sorted(set(n for n in stale if n != chapter) | set(dependents))), _write=lambda r, p, v: outputs.update({p: v}), _replacements={chapter:snapshot})
    guards = {**source['source_hashes'], f'story/{chapter}/chapter.md': source['body_sha256']}
    guards['meta/serial_contract.json']=source.get('serial_contract_sha256',digest(root,'meta/serial_contract.json'))
    return journal.publish(root, snapshot, outputs, guards, inputs, archive_revision,transient_guards=['meta/serial_contract.json'])


def refresh_archive(root, _states=None, _write=None, _replacements=None):
    if _states is None:
        def guards():
            values = source_hashes(root, include_outline=False)
            values.update({p.relative_to(root).as_posix(): digest(root, p.relative_to(root).as_posix()) for p in Path(root).glob('story/[0-9][0-9][0-9][0-9]/confirmed_state.json')})
            return values
        archive_store().publish_views(root,
            lambda sink: refresh_archive(root, _states=confirmed(root), _write=sink), guards)
        return archive_status(root)
    write = _write or globals()['write']
    states, stale = confirmed(root) if _states is None else _states
    status = archive_status(root, (states, stale))
    write(root, "archive/current_status.json", status)
    if serial().contract(root):
        target=str(int(states[-1]['chapter'])+1).zfill(4) if states else '0001'
        write(root,'planning/serial/status.json',serial().status(root,target,states=states))
    write(root, 'archive/impact_report.json', memory().impact(root,states=states,stale=stale,replacements=_replacements))
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
    parser.add_argument("command", choices=["context", "begin-reader", "commit-reader", "begin-review",
        "validate-observation", "reuse-observation", "validate-cached-observation", "commit", "preflight",
        "refresh", "recover", "abandon-commit", "recall", "impact", "serial"])
    parser.add_argument("--chapter", default="0001")
    parser.add_argument("--commit-id", default="")
    parser.add_argument('--query', default='')
    parser.add_argument('--serial-action',default='status',choices=['bootstrap','prepare','normalize','commit','approve','status'])
    parser.add_argument("--check", action='store_true')
    parser.add_argument("--archive-observation", action='store_true')
    parser.add_argument("--emit-effective-context", action='store_true')
    parser.add_argument("--policy-alias", action="append", default=[])
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.command=='serial':
        serial().main([args.serial_action,'--chapter',args.chapter]);return
    if args.command in {'recall','impact'}:
        archive_store().recover(root)
        result=memory().retrieve(root,args.chapter,args.query) if args.command=='recall' else memory().impact(root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command in {'recover', 'abandon-commit'}:
        if args.command == 'recover':
            archive_store().recover(root)
        else:
            archive_store().abandon(root, None if args.commit_id else chapter_id(args.chapter), args.commit_id or None)
        print(json.dumps(archive_store().publications(root), ensure_ascii=False))
        return
    if args.command == "validate-observation":
        try:
            validate_observation(root, args.chapter)
        except ValueError:
            _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_obs">[archive_evidence] 对照本章原文重新复制证据，'
                  '包括代词、原标点，不能把“她”改成人名。首次进入正文的伏笔和债务用 plant；'
                  '缺乏原文依据则不收录。</WF_REJECT_UPSTREAM>')
        return
    if args.command == 'reuse-observation':
        guard = archive_store().execution_guard()
        if guard.reuse_profile(root, ('agent_obs',)):
            guard.request_budget(root, 'agent_obs')
        hit = reuse_observation(root, args.chapter)
        print(f'<WF_VAR>archive_observation_reused:{"yes" if hit else "no"}</WF_VAR>')
        if hit:
            print(f'<WF_VAR>archive_reuse_body_file:story/{chapter_id(args.chapter)}/chapter.md</WF_VAR>')
        return
    if args.command == 'validate-cached-observation':
        validate_cached_observation(root, args.chapter)
        return
    action = {"context": prepare_context, "begin-reader": begin_reader, "commit-reader": commit_reader,
              "begin-review": begin_review, "commit": commit, "preflight": preflight}
    result = (refresh_archive(root) if args.command == "refresh" else
              prepare_context(root, args.chapter, args.check, task_id=os.environ.get("TASK_ID"),
                              archive_observation=args.archive_observation)
              if args.command == 'context' else action[args.command](root, args.chapter))
    if args.command == "context":
        if os.environ.get('TASK_ID'):
            contract_spec=importlib.util.spec_from_file_location('story_book_contract',HERE.parent/'prose_policy/book_contract.py')
            contract_module=importlib.util.module_from_spec(contract_spec);contract_spec.loader.exec_module(contract_module)
            frozen=contract_module.freeze(root,os.environ['TASK_ID'])
            print(f"<WF_VAR>book_contract_file:{frozen['prompt_file']}</WF_VAR>")
        runtime = result["prose_policy_runtime"]
        common = runtime.get('common_file') or 'cache/story-support/context.md'
        print(f"<WF_VAR>revision_context_path:{common}</WF_VAR>")
        if runtime["directory"] or args.emit_effective_context:
            # A whitespace value decodes to an explicit empty string in the
            # host's WF_VAR parser when the book inherits its existing prose.
            print(f"<WF_VAR>prose_policy_runtime:{runtime['directory'] or ' '}</WF_VAR>")
            print(f"<WF_VAR>prose_policy_prompt:{runtime['prompt_file'] or ' '}</WF_VAR>")
            print(f"<WF_VAR>story_support_context:{common}</WF_VAR>")
        for spec in args.policy_alias:
            key, sep, source_id = spec.partition("=")
            if not sep or not re.fullmatch(r"pp_[a-z_]+", key):
                raise ValueError("无效的工作流叙述资料别名。")
            alias=source_id
            if runtime['directory']:
                policy = _prose_policy()
                alias = policy.runtime_alias(root, runtime["directory"], source_id, task_id=runtime["task_id"])
                if alias == source_id:
                    alias = policy.compact_mirror_alias(root, runtime["directory"], source_id,
                                                        task_id=runtime["task_id"])
            if alias != source_id or args.emit_effective_context:
                print(f"<WF_VAR>{key}:{alias or ' '}</WF_VAR>")
            if key=='pp_learning_context':print(f"<WF_VAR>revision_reference_path:{alias}</WF_VAR>")
    if args.command == 'begin-review':
        for key, name in [('obs_output_file','observer.json'), ('archive_observer_path','observer.json'), ('archive_arbiter_path','arbiter.json')]:
            print(f'<WF_VAR>{key}:{review_file(chapter_id(args.chapter), name)}</WF_VAR>')
    if args.command == "preflight" and not result["ready"]:
        raise ValueError(result["message"])
    print(json.dumps({"status": "completed", "command": args.command, "chapter": args.chapter}, ensure_ascii=False))


if __name__ == "__main__":
    main()
