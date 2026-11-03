"""Read-only effective projections and task-scoped workflow files."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
from uuid import uuid4

from .sources import area, chapter_id, safe, source, workspace
from .store import DIRECTORY, atomic_bytes, read


NARRATIVE_LED = """## 本书叙述偏好：叙述主导

保留作者要求的事件、结果、人物身份与知识边界、世界规则、既定视角和声音。人物的表达倾向供场景取舍，不是固定动作、台词或反应步骤；待写计划不算已发生事实。
在场景合适时，让行动、感知、犹豫、取舍与后果承担更多叙事。关键要求、证词、报价、拒绝及关系转折可由原本必要的对白落地；普通回应、停顿和闲话也可以保留人物味。不要逐句解释对白的作用，不设对白、动作、沉默、标点或句长配额。
压缩重复手续、规则说明和事后总结；不用工艺步骤、心理标签或景物填篇幅。规划给场景留下表达空间，写作与润色保留事件和声线；评估结合实际段落和阅读影响提出建议。
"""


def _active(state):
    if state["mode"] != "narrative_led":
        return []
    stale = {item["preview_id"] for item in state["stale_overrides"]}
    return [item for item in state["overrides"] if item.get("preview_id") and item["preview_id"] not in stale]


def _transform(root, source_id, rows, supplied=None):
    text, sha = source(root, source_id)
    if supplied is not None and supplied != text and supplied != text.replace("\r\n", "\n").replace("\r", "\n"):
        return supplied
    for item in sorted(rows, key=lambda item: item["start"], reverse=True):
        start, end = item["start"], item["end"]
        if sha == item["source_sha256"] and text[start:end] == item["quote"]:
            text = text[:start] + item["replacement"] + text[end:]
    if supplied is not None and "\r" not in supplied:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def effective_text(root, source_id, text=None):
    root = workspace(root)
    safe(root, source_id)
    rows = [item for item in _active(read(root)) if item["source_id"] == source_id]
    if not rows:
        return source(root, source_id)[0] if text is None else text
    return _transform(root, source_id, rows, text)


def _context(state):
    instructions = NARRATIVE_LED if state["mode"] == "narrative_led" else ""
    if instructions and state["stale_overrides"]:
        names = sorted({item["source_id"] for item in state["stale_overrides"]})
        instructions += "\n有原文已变化，旧替代建议未应用；请重新核对：" + "、".join(names) + "。\n"
    return {"mode": state["mode"], "revision": state["revision"], "instructions": instructions,
            "stale_overrides": state["stale_overrides"]}


def effective_context(root, chapter="0001"):
    chapter_id(chapter)
    return _context(read(root))


def prepare_runtime(root, chapter="0001", *, task_id):
    """Publish task-local file aliases without changing any book source file."""
    root = workspace(root)
    chapter_id(chapter)
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", task_id):
        raise ValueError("叙述偏好需要有效的任务标识。")
    state = read(root)
    context = _context(state)
    result = {"task_id": task_id, "context": context, "aliases": {}, "directory": "", "prompt_file": ""}
    if not context["instructions"]:
        return result
    key = _task_key(task_id)
    directory = f"{DIRECTORY}/runtime/{key}/{uuid4().hex}"
    result.update(directory=directory, prompt_file=f"{directory}/preference.md")
    atomic_bytes(root, result["prompt_file"], context["instructions"].encode("utf-8"))
    rows = _active(state)
    manifest = {}
    for source_id in dict.fromkeys(item["source_id"] for item in rows):
        original, sha = source(root, source_id)
        selected = [item for item in rows if item["source_id"] == source_id and item["source_sha256"] == sha]
        updated = _transform(root, source_id, selected, original)
        if updated != original:
            alias = _alias_path(directory, source_id)
            atomic_bytes(root, alias, updated.encode("utf-8"))
            result["aliases"][source_id] = alias
            manifest[source_id] = {
                "source_sha256": sha, "effective_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
                "replacements": {item["quote"]: item["replacement"] for item in selected},
            }
    atomic_bytes(root, f"{directory}/sources.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    return result


def _task_key(task_id):
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]


def _alias_path(directory, source_id):
    # Keep a deep chapter's original path out of the derived filename; Windows
    # workspace paths can otherwise exceed the normal process path limit.
    key = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:20]
    return f"{directory}/f-{key}{PurePosixPath(source_id).suffix}"


def _runtime_directory(root, directory, task_id):
    if (not isinstance(directory, str)
            or not re.fullmatch(rf"{DIRECTORY}/runtime/[a-f0-9]{{24}}/[a-f0-9]{{32}}", directory)
            or (task_id is not None and directory.split("/")[-2] != _task_key(task_id))
            or not safe(root, directory).is_dir() or safe(root, directory) != root / directory):
        raise ValueError("无效的任务内叙述资料路径。")


def runtime_file(root, directory, name, text, *, task_id=None):
    """Write a named runtime derivative; callers never supply a book path."""
    root = workspace(root)
    _runtime_directory(root, directory, task_id)
    if not re.fullmatch(r"[a-z][a-z0-9_-]*\.(?:md|json)", name):
        raise ValueError("无效的任务内叙述资料文件名。")
    target = f"{directory}/{name}"
    atomic_bytes(root, target, text.encode("utf-8"))
    return target


def runtime_binding(root, directory, source_id, *, task_id=None):
    """Return an effective file record only while both original and copy match."""
    root = workspace(root)
    if not directory or not source_id:
        return None
    _runtime_directory(root, directory, task_id)
    source_id = safe(root, source_id).relative_to(root).as_posix()
    if not area(source_id):
        return None
    manifest = json.loads(source(root, f"{directory}/sources.json")[0])
    entry = manifest.get(source_id)
    alias = _alias_path(directory, source_id)
    if (entry and entry["source_sha256"] == source(root, source_id)[1]
            and entry["effective_sha256"] == source(root, alias)[1]):
        return {**entry, "alias": alias}
    return None


def runtime_alias(root, directory, source_id, *, task_id=None):
    entry = runtime_binding(root, directory, source_id, task_id=task_id)
    return entry["alias"] if entry else source_id


def runtime_common(root, directory, *, task_id=None):
    root = workspace(root)
    _runtime_directory(root, directory, task_id)
    path = f"{directory}/common.md"
    if not safe(root, path).is_file():
        raise ValueError("本次任务的有效故事上下文不存在。")
    return path
