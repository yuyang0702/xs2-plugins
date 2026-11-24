"""Prepare role-specific chapter inputs from the verified local story state."""
import json
import re


_PRIVATE = {
    "source_id", "source_sha256", "source_hashes", "body_sha256", "archive_commit_id",
    "memory_dependencies", "read_set", "physical_source", "source_file",
}
_ROLE_LIMITS = {
    "director": {"facts": 3600, "characters": 2600, "cognition": 3300, "hits": 3000, "ledger": 3600},
    "writer": {"facts": 2000, "characters": 2100, "cognition": 2300, "hits": 1600, "ledger": 1700},
    "audit": {"facts": 3400, "characters": 2400, "cognition": 3500, "hits": 5500, "ledger": 3500},
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def without_verification(value, *, cite_sources=False):
    if isinstance(value, dict):
        return {key: without_verification(item, cite_sources=cite_sources)
                for key, item in value.items()
                if (key not in _PRIVATE or cite_sources and key == "source_id") and not key.endswith("_sha256")}
    if isinstance(value, list):
        return [without_verification(item, cite_sources=cite_sources) for item in value]
    return value


def _source_chapter(row):
    matched = re.search(r"(?:^|/)story/(\d+)(?:/|$)", str(row.get("source_id", "")))
    return row.get("chapter") or row.get("source_chapter") or row.get("chapter_created") or (matched[1] if matched else "")


def _projection(row, keys):
    data = {key: without_verification(row[key]) for key in keys if row.get(key) not in (None, "", [], {})}
    chapter = _source_chapter(row)
    if chapter and "chapter" not in data and "source_chapter" not in data:
        data["source_chapter"] = chapter
    return data


def _words(text):
    result = set()
    for word in re.findall(r"[\u3400-\u9fff]+|[A-Za-z0-9_]+", text.casefold()):
        if word.isascii():
            result.add(word)
        else:
            result.update(word[i:i + 2] for i in range(len(word) - 1))
    return result


def _ranked(rows, query, budget, *, open_only=False, preserve_ids=(), cite_sources=False):
    query_words = _words(query)
    named_ids = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", query))
    ranked = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        required = (row.get("id") in named_ids or row.get("id", row.get("entity_id")) in preserve_ids
                    or any(row.get(key) is True for key in ("pinned", "required", "must_keep")))
        if open_only and row.get("status") in ("resolved", "closed") and row.get("id") not in named_ids:
            continue
        compact = without_verification(row, cite_sources=cite_sources)
        text = _json(compact)
        score = len(_words(text) & query_words)
        chapter = _source_chapter(row)
        order = int(chapter) if str(chapter).isdecimal() else 0
        ranked.append((not required, -score, -order, i, compact, len(text) + 1))
    selected, used = [], 0
    for optional, _, _, _, row, size in sorted(ranked):
        if not optional or used + size <= budget:
            selected.append(row)
            used += size
    return selected


def memory_view(ctx, query, role, *, facts=(), cite_sources=False):
    """Return evidence and cognition, leaving file binding and index data local."""
    memory = ctx["memory"]
    limits = _ROLE_LIMITS[role]
    active = {entry["id"]: entry["name"] for entry in memory.get("entities", []) if entry.get("id") and entry.get("name")}
    cognition = []
    for holder, state in memory.get("cognition", {}).items():
        groups = {"knowledge": "已知", "beliefs": "信念", "rumors": "传言"}
        if role != "writer":
            groups["time_unverified"] = "获知时间待核对"
        for field, label in groups.items():
            for event in state.get(field, []):
                row = _projection(event, ("id", "text", "acquisition", "evidence", "world_time_key", "supersedes"))
                cognition.append({"人物": active.get(holder, holder), "类型": label, **row})
    cognition = _ranked(cognition, query, limits["cognition"])
    event_ids = {row.get("id") for row in cognition}
    fact_keys = {(str(_source_chapter(row)), row.get("description")) for row in facts
                 if isinstance(row.get("description"), str)}
    hit_rows = []
    scene_unverified = (ctx.get("world_current") or {}).get("temporal_status") == "unverified"
    for hit in memory.get("hits", []):
        uncertain_hit = hit.get("event_status") in {"outside_scene_time", "time_unverified", "superseded"}
        if role == "writer" and (uncertain_hit or scene_unverified and hit.get("kind") == "prose"):
            continue
        event = hit.get("event") or {}
        if event.get("id") and event["id"] in event_ids and not cite_sources:
            continue
        if hit.get("kind") == "confirmed_world_fact" and (
            str(_source_chapter(hit)), hit.get("text")
        ) in fact_keys and not cite_sources:
            continue
        row = _projection(hit, ("kind", "text", "evidence", "event_status"))
        if cite_sources and hit.get("source_id"):
            # Planning references use the existing, locally validated citation ID.
            row["source_id"] = hit["source_id"]
        if event:
            row.update(_projection(event, ("holder", "acquisition", "world_time_key")))
        if hit.get("replacements"):
            row["replacements"] = [
                _projection(replacement["event"], ("text", "evidence", "world_time_key"))
                for replacement in hit["replacements"] if replacement.get("event")
            ]
        if row:
            hit_rows.append(row)
    return {
        "scene_time_key": memory.get("scene_time_key"),
        "temporal_boundary": memory.get("temporal_boundary", ""),
        "人物所知、信念与传言": cognition,
        "可核对的原文依据": _ranked(hit_rows, query, limits["hits"], cite_sources=cite_sources),
    }


def payoff_due(row, chapter, finish):
    window = re.fullmatch(r"\s*第?\s*(\d+)(?:\s*章?\s*[-–—至~]\s*第?\s*(\d+))?\s*章?\s*",
                          str(row.get("expected_payoff") or ""))
    return bool(window and int(window[1]) <= int(finish) and int(window[2] or window[1]) >= int(chapter))


def ledger_view(rows, query, role, *, chapter, finish=None):
    rows = [row for row in rows if isinstance(row, dict)]
    due_ids = {row["id"] for row in rows if row.get("id") and row.get("status") not in ("resolved", "closed")
               and (row.get("status") == "near_payoff" or payoff_due(row, chapter, finish or chapter))}
    if role == "writer":
        ids = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", query)) | due_ids
        rows = [row for row in rows if row.get("id") in ids or any(
            row.get(key) is True for key in ("pinned", "required", "must_keep"))]
    return _ranked(rows, query, _ROLE_LIMITS[role]["ledger"], open_only=role != "audit", preserve_ids=due_ids)


def _character_rows(ctx):
    active = {item["name"]: item["id"] for item in ctx["memory"].get("entities", [])}
    rows = ctx.get("chapter_characters", [])
    for row in rows:
        value = _projection(row, ("entity_id", "name", "identity", "snapshot", "drives", "relationships"))
        if not value.get("entity_id") and row.get("name") in active:
            value["entity_id"] = active[row["name"]]
        snapshot = value.get("snapshot")
        if isinstance(snapshot, dict):
            snapshot.pop("cognition", None)
        yield value


def active_characters(ctx, query, role):
    active = {entry["id"] for entry in ctx["memory"].get("entities", [])}
    return _ranked(_character_rows(ctx), query, _ROLE_LIMITS[role]["characters"], preserve_ids=active)


def world_view(ctx, query, role):
    world = ctx.get("world_current") or {}
    keys = ["world_time", "world_time_key", "scene_time_key", "temporal_status", "boundary", "forces", "undercurrents"]
    if role != "writer":
        keys.append("作者规划的幕后演进（不等于角色已知）")
    return {
        **_projection(world, keys),
        "facts": _ranked(world.get("facts") or [], query, _ROLE_LIMITS[role]["facts"]),
    }


def next_ledger_ids(indexes, planned):
    available = {}
    for key, prefix in (("hooks", "h"), ("debts", "d")):
        ids = (row.get("id", "") for row in [*indexes.get(key, []), *planned.get(key, [])]
               if isinstance(row, dict))
        values = (int(match[1]) for value in ids if (match := re.fullmatch(prefix + r"(\d+)", str(value))))
        available[key] = f"{prefix}{max(values, default=0) + 1:03d}"
    return available


def render(ctx, outline, adopted, *, planned=None):
    planned = planned or {}
    query = "\n".join((ctx["memory"].get("query", ""), outline, adopted))
    query += "\n" + "\n".join(src["content"][:350] for src in ctx["sources"]
                                if src["source_id"].endswith("/diff_story_confirmed.md")
                                and str(_source_chapter(src)).isdecimal()
                                and int(_source_chapter(src)) < int(ctx["chapter"]))
    serial = ctx.get("serial") or {}
    draft = adopted or outline
    sources = {row["source_id"]: row["content"] for row in ctx["sources"]}
    conflict = sources.get("meta/conflict_ledger.md", "")
    texts = {}
    for role in _ROLE_LIMITS:
        world = world_view(ctx, query, role)
        sections = [
            ("本章写作计划", draft),
            ("相关人物的当前状态", active_characters(ctx, query, role)),
            ("世界状态与本章相关事实", world),
            ("人物认知与前文证据", memory_view(ctx, query, role, facts=world["facts"])),
            ("本章相关伏笔与叙事债务", {
                key: ledger_view(rows, query, role, chapter=ctx["chapter"])
                for key, rows in ctx["indexes_before"].items()
            }),
        ]
        baseline = [sources[file] for file in ("meta/current_world.md", "meta/current_characters.md")
                    if sources.get(file)]
        if baseline:
            sections.append(("初始世界与人物状态", "\n\n".join(baseline)))
        if role == "director" and conflict:
            paragraphs = re.split(r"\n\s*\n", conflict)
            ranked = _ranked(({"text": part[:800]} for part in paragraphs if part.strip()), query, 1600)
            sections.append(("与本章相关的冲突计划", "\n\n".join(row["text"] for row in ranked)))
        if role != "writer":
            sections.append(("新增伏笔与债务的起始编号（已有条目仍用原编号）",
                             next_ledger_ids(ctx["indexes_before"], planned)))
        if role in {"director", "audit"} and serial.get("enabled"):
            sections.append(("卷级目标与承接", {
                "volume": _projection(serial.get("volume") or {}, ("id", "title", "intent", "start", "end", "exit_conditions")),
                "threads": _ranked([{"id": key, **value} for key, value in serial.get("threads", {}).items()], query, 2400),
                "unmet_exit_conditions": without_verification(serial.get("unmet_exit_conditions", [])),
            }))
        recent = []
        for src in ctx["sources"]:
            chapter = _source_chapter(src)
            if not str(chapter).isdecimal() or int(chapter) >= int(ctx["chapter"]):
                continue
            if (role == "writer" and world.get("temporal_status") != "unverified"
                    and src["source_id"].endswith("/chapter.md")):
                recent.append({"chapter": chapter, "text": src["content"][-1800:]})
            elif role != "writer" and src["source_id"].endswith("/diff_story_confirmed.md"):
                recent.append({"chapter": chapter, "text": src["content"][:1000]})
        sections.append(("最近正文承接" if role == "writer" else "近期已确认的剧情变化",
                         recent[-1:] if role == "writer" else recent[-3:]))
        texts[role] = "# 本章相关故事资料\n\n" + "\n\n".join(
            f"## {title}\n{text if isinstance(text, str) else _json(text)}"
            for title, text in sections if text
        ) + ("\n\n计划属于待写意图。证据和身份映射不赋予角色知识。"
             "信念和传言可能错误，未检索到的记录视为待核对。"
             "人物状态与认知记录有出入时，用最近且在场景时间内有依据的获知过程核对。"
             "如果属于跨时序场景，以明确世界时间和本书叙述权限为准。")
    return texts
