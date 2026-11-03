"""Project proven structured mirrors without changing their archives."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from .runtime import runtime_binding, runtime_file
from .sources import safe, source, workspace


VOICE = "meta/character_voice.md"
PROFILES = "meta/character_profiles.md"
NEAR_TERM = "outline/near_term_outline.md"
COMPACT_MIRRORS = {
    "story/0001/character_minor.md": (PROFILES, "", "compact-minor.md"),
    "story/0001/character_state_long.md": (PROFILES, "# 生成前人物基线\n\n", "compact-state.md"),
    "story/0001/single_chapter_guide.md": (NEAR_TERM, "", "compact-guide.md"),
}


def compact_mirror_alias(root, directory, source_id, *, task_id=None):
    """Project existing compact outputs after checking producer and full content."""
    if not source_id:
        return source_id
    root = workspace(root)
    relative = safe(root, source_id).relative_to(root).as_posix()
    if relative not in COMPACT_MIRRORS:
        return source_id
    original, prefix, filename = COMPACT_MIRRORS[relative]
    binding = runtime_binding(root, directory, original, task_id=task_id)
    if binding is None:
        return source_id
    try:
        marker = json.loads(source(root, "cache/se/se_output.json")[0])
    except (ValueError, OSError):
        return source_id
    if (not isinstance(marker, dict) or marker.get("chapter_number") != "0001"
            or marker.get("planned_only") is not True or marker.get("source") != NEAR_TERM
            or not isinstance(marker.get("guide"), str)):
        return source_id
    # Compact preparation writes UTF-8 LF from a universal-newline read. A
    # confirmed or edited state has different contents and keeps its own path.
    original_text = source(root, original)[0].replace("\r\n", "\n").replace("\r", "\n")
    if original == NEAR_TERM and marker["guide"] != original_text:
        return source_id
    if source(root, relative)[0] != prefix + original_text:
        return source_id
    effective = source(root, binding["alias"])[0].replace("\r\n", "\n").replace("\r", "\n")
    return runtime_file(root, directory, filename, prefix + effective, task_id=task_id)


def voice_mirror(root, directory, document, render_voice_char, *, task_id=None):
    """A renderer must prove the Markdown and JSON are the same source view."""
    root = workspace(root)
    binding = runtime_binding(root, directory, VOICE, task_id=task_id)
    if not binding:
        return document
    canonical = source(root, VOICE)[0].replace("\r\n", "\n")
    effective = source(root, binding["alias"])[0].replace("\r\n", "\n")
    title = re.match(r"^# [^\n]+\n\n", canonical)
    rows = document.get("characters") if isinstance(document, dict) else None
    if not title or not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return document

    def render(value):
        return (title[0] + "\n\n---\n\n".join(render_voice_char(row) for row in value["characters"]) + "\n").replace("——", "，")

    def project(value):
        return binding["replacements"].get(value, value) if isinstance(value, str) else value

    try:
        if render(document) != canonical:
            return document
        updated = deepcopy(document)
        for row in updated["characters"]:
            if "voice_positioning" in row:
                row["voice_positioning"] = project(row["voice_positioning"])
            for key, fields in (
                ("syntax_fingerprint", ("sentence_preference", "pause_habit", "dominant_sentence_type")),
                ("emotion_patterns", ("anger", "nervous", "lying")),
            ):
                if isinstance(row.get(key), dict):
                    for field in fields:
                        if field in row[key]:
                            row[key][field] = project(row[key][field])
            if isinstance(row.get("preferences"), list):
                row["preferences"] = [project(item) for item in row["preferences"]]
        return updated if render(updated) == effective else document
    except (AttributeError, TypeError, ValueError):
        # Unknown legacy JSON cannot establish that this is a deterministic alias.
        return document
