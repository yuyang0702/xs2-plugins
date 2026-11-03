"""Read, preview and atomically adopt book-local expression policy."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .sources import area, chapter_id, inventory, safe, scan, source, workspace


DIRECTORY = "learning/prose_policy"
STATE = f"{DIRECTORY}/policy.json"
MODES = {"inherit", "narrative_led"}
EMPTY_REVISION = hashlib.sha256(b"xs2.prose_policy:inherit:v1").hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _policy_path(root, relative):
    path = safe(root, relative)
    if path != root / relative:
        raise ValueError("不能将叙述偏好写入链接目录或链接文件。")
    return path


def atomic_bytes(root, relative, data):
    target = _policy_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".pp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _write_lock(root):
    path = _policy_path(root, f"{DIRECTORY}/.policy.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        # Locking byte zero also works on an empty file on Windows. The OS
        # releases this lock on process exit; no stale lock ownership file.
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _load(root):
    path = _policy_path(root, STATE)
    if not path.is_file():
        return {"schema": 1, "mode": "inherit", "overrides": [], "history": []}, EMPTY_REVISION
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
        if (not isinstance(doc, dict) or doc.get("schema") != 1 or doc["mode"] not in MODES
                or not isinstance(doc["overrides"], list) or not isinstance(doc["history"], list)
                or any(not isinstance(item, dict) for item in doc["overrides"])):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("本书叙述偏好文件无法识别；请核对文件。") from exc
    return doc, hashlib.sha256(raw).hexdigest()


def _bind(root, payload):
    if not isinstance(payload, dict):
        raise ValueError("请选择一条明确的表达建议。")
    source_id, quote, replacement = (payload.get(key) for key in ("source_id", "quote", "replacement"))
    if not isinstance(source_id, str) or not area(source_id):
        raise ValueError("请选择体检列表中可以定位的原文。")
    if (not isinstance(quote, str) or not 0 < len(quote) <= 400 or not isinstance(replacement, str)
            or not 0 < len(replacement) <= 400 or replacement != replacement.strip()
            or replacement.splitlines() != [replacement]
            or any(token in replacement for token in ("{{", "}}", "\x00"))
            or replacement.startswith(("#", ">", "`", "~")) or quote == replacement):
        raise ValueError("请给出一条非空、单行、不同于原文的表达建议。")
    path = safe(root, source_id)
    if path != root / source_id:
        raise ValueError("不能通过链接资料确认覆盖；请选择原始来源。")
    text, sha = source(root, source_id)
    finding = next((row for row in scan(source_id, text, sha)
                    if row["quote"] == quote and row["override_eligible"]), None)
    if finding is None:
        raise ValueError("原文不唯一、不再匹配，或该内容未标为可覆盖的表达建议。")
    return {key: finding[key] for key in (
        "source_id", "source_sha256", "quote", "start", "end", "source_category",
    )} | {"replacement": replacement}


def _preview(root, binding, revision):
    # Stateless receipt: recomputed at confirmation, tied to this book,
    # revision, exact source bytes, location, and replacement.
    digest = hashlib.sha256(encode([str(root), revision, binding])).hexdigest()
    return binding | {"revision": revision, "preview_id": digest,
                      "before": binding["quote"], "after": binding["replacement"]}


def _recheck(root, item):
    """Return the current binding, or a non-semantic staleness reason."""
    try:
        if _preview(root, _bind(root, item), item["revision"]) == item:
            return None
    except (OSError, KeyError, ValueError):
        pass
    return "source_changed_or_unavailable"


def _view(root, doc, revision):
    stale = [{"preview_id": row.get("preview_id", ""), "source_id": row.get("source_id", ""),
              "quote": row.get("quote", ""), "reason": reason}
             for row in doc["overrides"] if (reason := _recheck(root, row))]
    return {"mode": doc["mode"], "revision": revision, "overrides": doc["overrides"],
            "stale_overrides": stale}


def read(root):
    root = workspace(root)
    return _view(root, *_load(root))


def audit(root, chapter="0001"):
    root, chapter = workspace(root), chapter_id(chapter)
    state = read(root)
    sources, findings = [], []
    for name in inventory(chapter):
        row = {"source_id": name, "source_kind": area(name), "provenance": "unknown"}
        try:
            text, sha = source(root, name)
        except (ValueError, OSError):
            sources.append(row | {"status": "unavailable", "source_sha256": ""})
            continue
        sources.append(row | {"status": "present" if sha else "missing", "source_sha256": sha})
        if sha:
            findings.extend(scan(name, text, sha))
    return {"chapter": chapter, "revision": state["revision"], "sources": sources,
            "findings": findings, "stale_overrides": state["stale_overrides"]}


def _expect_revision(expected, current):
    if expected != current:
        raise ValueError("叙述偏好已变化，请刷新后再确认。")


def preview_override(root, payload, expected_revision):
    root = workspace(root)
    _, revision = _load(root)
    _expect_revision(expected_revision, revision)
    return _preview(root, _bind(root, payload), revision)


def _selection(root, payload, doc, revision):
    if "overrides" not in payload:
        return doc["overrides"]
    rows = payload["overrides"]
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("请选择已预览的表达建议（最多 100 条）。")
    selected, slots = [], set()
    for item in rows:
        binding = _bind(root, item)
        preview = _preview(root, binding, revision)
        if item == preview:
            receipt = preview
        elif item in doc["overrides"] and _recheck(root, item) is None:
            receipt = item
        else:
            raise ValueError("表达建议已变化，或尚未预览确认。")
        key = (binding["source_id"], binding["start"], binding["end"])
        if key in slots:
            raise ValueError("同一处原文只能采用一条替代表达。")
        slots.add(key)
        selected.append(receipt)
    return selected


def save(root, payload, expected_revision):
    root = workspace(root)
    if (not isinstance(payload, dict) or set(payload) - {"mode", "overrides"}
            or not isinstance(payload.get("mode"), str) or payload["mode"] not in MODES):
        raise ValueError("叙述模式仅支持 inherit 或 narrative_led。")
    doc, revision = _load(root)
    _expect_revision(expected_revision, revision)
    overrides = _selection(root, payload, doc, revision)
    if payload["mode"] == doc["mode"] and overrides == doc["overrides"]:
        return _view(root, doc, revision)
    with _write_lock(root):
        doc, revision = _load(root)
        _expect_revision(expected_revision, revision)
        overrides = _selection(root, payload, doc, revision)
        updated = {"schema": 1, "mode": payload["mode"], "overrides": overrides,
                   "history": [*doc["history"], {
                       "superseded_at": datetime.now(timezone.utc).isoformat(),
                       "revision": revision, "mode": doc["mode"], "overrides": doc["overrides"],
                   }]}
        raw = encode(updated) + b"\n"
        atomic_bytes(root, STATE, raw)
        return _view(root, updated, hashlib.sha256(raw).hexdigest())
