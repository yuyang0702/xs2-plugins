"""Project proven structured mirrors without changing their archives."""
from __future__ import annotations

from copy import deepcopy
import re

from .runtime import runtime_binding
from .sources import source, workspace


VOICE = "meta/character_voice.md"


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
