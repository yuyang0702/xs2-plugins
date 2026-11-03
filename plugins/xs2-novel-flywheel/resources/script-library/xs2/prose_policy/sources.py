"""Inventory and conservative, location-bearing audit of book source text."""
from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath
import re


FIXED = {
    "meta/character_profiles.md": "character_profile",
    "meta/character_voice.md": "character_voice",
    "meta/character_voice_adaptations.md": "confirmed_voice_adaptation",
    "meta/style_profile.md": "style_profile",
    "meta/story_plan.md": "story_plan",
    "outline/volume_outline.md": "volume_outline",
    "outline/near_term_outline.md": "near_term_outline",
    "learning/active_context.md": "common_context",
    "learning/context/mvp.md": "generated_common_context",
    "learning/context/polish.md": "generated_common_context",
    "cache/story-support/context.md": "generated_common_context",
    "cache/character/voice.json": "character_voice",
    "cache/story_plan/story_plan.json": "story_plan",
    "cache/no/near_term.json": "near_term_outline",
    "meta/world_foundation.md": "world_facts",
    "meta/current_world.md": "world_facts",
    "meta/current_characters.md": "character_state",
    "meta/conflict_ledger.md": "conflict_ledger",
}
CHAPTER_SOURCE = re.compile(
    r"story/([0-9]{4,6})/(single_chapter_guide|storyboard|storyboard_final)\.md"
)
EXPRESSION = {
    "表达建议", "表达倾向", "表达倾向（非固定台词）", "叙述建议", "写法建议", "对白建议",
    "行文建议", "情绪下可能的表达（依当前情境）", "核心声音定位",
    "expression advice", "prose advice", "dialogue advice", "expression guidance",
}
PROTECTED = re.compile(
    r"^(?:作者(?:确认|硬要求|要求|意图)|世界规则|世界事实|身份(?:信息)?|人物身份|已发生(?:事件|事实)?|"
    r"确认事实|知情边界|人物知识|已知信息|事件要求|硬事件|认知偏差|明确表达边界|"
    r"(?:author (?:requirements|confirmed)|identity|world facts|knowledge|canon)\b)", re.I
)
PATTERNS = (
    ("fixed_unit", re.compile(
        r"(?:每句(?:对白|台词|对话)?|每段(?:对白|对话|正文)?|每轮(?:对白|对话)|每次(?:对白|开口)|"
        r"每\s*(?:[0-9]+|[一二三四五六七八九十百千]+)\s*(?:字|句|段))"
        r"[^。！？；;\n]{0,22}(?:必须|至少|不得|不超过|一律|都要|要有|≤)", re.I),
     "按句、段或字数固定执行，可能压过场景需要。"),
    ("fixed_response", re.compile(
        r"(?:遇到|面对|受到)[^。！？；;\n]{1,24}(?:永远|一律|必定|固定(?:先|用|做|说))"
        r"|(?:对白|对话|台词)(?:结束)?后[^。！？；;\n]{0,14}(?:必须|一定要|都要)[^。！？；;\n]{0,14}(?:解释|复述|说明)"
        r"|(?:固定|一律)(?:使用|说出|重复)(?:口癖|台词|动作)", re.I),
     "固定反应或逐次解释，可能抹去关系与处境的差别。"),
    ("rhythm_quota", re.compile(
        r"长短句交替|禁止(?:使用)?破折号|禁止被动语态|每(?:个)?场景至少[^。！？；;\n]{0,12}感官"
        r"|\b(?:every|each) (?:line|sentence|paragraph|dialogue turn)\b.{0,24}\b(?:must|at least|never)\b",
        re.I),
     "固定句式、标点或描写指标，可能造成机械节奏。"),
)
DISCLAIMED = re.compile(r"(?:不要求|不必|无需|不设|不按|不要|避免|拒绝|不是|不需要|不强制|rather than|no need to)", re.I)
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)")
CLAUSE = re.compile(r"[^。！？；;]+[。！？；;]?")
BULLET = re.compile(r"^\s*(?:[-+*]|\d+[.)、])\s+")
EXPRESSION_LABEL = re.compile(r"^(?:长短句偏好|停顿习惯|常用句式|愤怒时|紧张时|撒谎时)[：:]\s*")
MIXED = re.compile(r"(?:[,，:：()（）]|且|并须|并应|同时|否则|必须(?:在|由|等到|知道|保留|发生)|不得(?:在|由|知道)|\band\b)", re.I)


def workspace(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("作品工作区不存在。")
    return root


def safe(root, source_id):
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("资料路径必须是工作区内的相对路径。")
    rel = Path(source_id)
    windows = PureWindowsPath(source_id)
    if rel.is_absolute() or windows.anchor or ".." in windows.parts or ":" in source_id:
        raise ValueError("资料路径不能离开当前作品。")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError("资料路径不能离开当前作品。")
    return target


def chapter_id(value):
    if not re.fullmatch(r"[0-9]{1,6}", str(value)) or int(value) < 1:
        raise ValueError("请选择有效的章节。")
    return f"{int(value):04d}"


def area(source_id):
    if source_id in FIXED:
        return FIXED[source_id]
    match = CHAPTER_SOURCE.fullmatch(source_id)
    if match and int(match[1]) and chapter_id(match[1]) == match[1]:
        return "chapter_outline"
    return None


def inventory(chapter):
    return (*FIXED, *(f"story/{chapter}/{name}.md"
                       for name in ("single_chapter_guide", "storyboard", "storyboard_final")))


def source(root, source_id):
    target = safe(root, source_id)
    if not target.is_file():
        return "", ""
    raw = target.read_bytes()
    return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()


def scan(source_id, text, sha):
    """Locate clues. A format label can identify a section, never its author."""
    kind = area(source_id)
    stack, fence, offset = [], None, 0
    for line_number, raw in enumerate(text.splitlines(keepends=True), 1):
        start = offset
        offset += len(raw)
        line = raw.rstrip("\r\n")
        if marker := FENCE.match(line):
            token, tail = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not tail.strip():
                fence = None
            continue
        if fence is not None or line.lstrip().startswith(">"):
            continue
        if heading := HEADING.match(line):
            level = len(heading[1])
            title = re.sub(r"\s+#+$", "", heading[2]).strip().casefold()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue
        protected = kind in {"world_facts", "character_state", "conflict_ledger", "confirmed_voice_adaptation"} or any(
            PROTECTED.match(title) for _, title in stack
        )
        in_expression = bool(stack and stack[-1][1] in EXPRESSION)
        prefix = BULLET.match(line)
        body_start = prefix.end() if prefix else len(line) - len(line.lstrip())
        if in_expression and (label := EXPRESSION_LABEL.match(line[body_start:])):
            body_start += label.end()
        body = line[body_start:].strip()
        for piece in CLAUSE.finditer(body):
            quote = piece[0].strip()
            if not quote:
                continue
            for rule, pattern, reason in PATTERNS:
                match = pattern.search(quote)
                if not match or DISCLAIMED.search(quote[:match.start()]):
                    continue
                pos = start + body_start + piece.start() + len(piece[0]) - len(piece[0].lstrip())
                # Replace a complete standalone advice unit, not a substring in
                # a compound line, a quoted example, or an unclassified record.
                eligible = (
                    not protected and in_expression and quote == body and
                    kind != "generated_common_context" and source_id.endswith(".md") and
                    match.start() == 0 and len(quote) <= 400 and not MIXED.search(quote) and
                    text.count(quote) == 1
                )
                yield {
                    "source_id": source_id, "source_kind": kind, "source_sha256": sha,
                    "source_category": ("protected" if protected else "expression_advice"
                                        if in_expression else "unknown"),
                    "provenance": "unknown", "review_status": "candidate",
                    "quote": quote, "start": pos, "end": pos + len(quote), "line": line_number,
                    "rule": rule, "reason": reason, "override_eligible": eligible,
                    "suggestion": "核对这是否只是表达建议；保留剧情、身份、知情、世界事实和作者要求，按场景决定表达方式。",
                }
                break
