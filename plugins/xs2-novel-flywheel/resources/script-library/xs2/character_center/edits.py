"""Serialize publication and journal exact scoped card changes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
from uuid import uuid4

from .cards import SOURCES, digest, inventory, source_path, workspace


DIRECTORY = 'learning/character_center'
HISTORY = DIRECTORY + '/history.json'
PENDING = DIRECTORY + '/pending.json'
_SIGNING_KEY = secrets.token_bytes(32)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def atomic(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as handle:
        name = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            name.unlink(missing_ok=True)
            raise
    try:
        name.replace(target)
    finally:
        name.unlink(missing_ok=True)


@contextmanager
def locked(root):
    if os.name == 'nt':
        # A named mutex coordinates cooperative writers without creating a
        # learning directory during legacy voice operations.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateMutexW
        create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        wait = kernel.WaitForSingleObject
        wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = create(None, False, 'Local\\DeterminFlowCharacter-' + digest(os.path.normcase(str(root)).encode()))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if wait(handle, 10000) not in (0, 0x80):
                raise OSError('人物资料正在由其他请求更新。')
            try:
                yield
            finally:
                kernel.ReleaseMutex(handle)
        finally:
            kernel.CloseHandle(handle)
    else:
        import fcntl
        fd = os.open(root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def _journal(root):
    pending = source_path(root, PENDING)
    try:
        staged = json.loads(pending.read_bytes())
    except FileNotFoundError:
        staged = None
    if staged is not None:
        try:
            entry = staged[0]
            target = source_path(root, entry['source_id']) if entry['source_id'] in SOURCES else None
            current = digest(target.read_bytes()) if target and target.is_file() else None
            if current is not None and current == entry['source_revision_after']:
                return staged, 'published'
            if current is None or current != entry['source_revision_before']:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError('人物修订待恢复，但原件已变化。请保留待恢复记录并人工核对。') from error
    path = source_path(root, HISTORY)
    return (json.loads(path.read_bytes()) if path.is_file() else []), 'unpublished' if staged is not None else None


def _recover(root):
    entries, status = _journal(root)
    pending = source_path(root, PENDING)
    if status == 'published':
        pending.replace(source_path(root, HISTORY))
    elif status == 'unpublished':
        pending.unlink()
    return entries


@contextmanager
def legacy_mutation(root):
    root = workspace(root)
    with locked(root):
        if source_path(root, PENDING).exists():
            _recover(root)
        yield


def history(root, character_id=None):
    root = workspace(root)
    entries, _ = _journal(root)
    return {'entries': [item for item in entries if not character_id or item['character_id'] == character_id]}


def _signature(root, receipt):
    return hmac.digest(_SIGNING_KEY, encode([str(root), receipt]), 'sha256').hex()


def authentic_preview(root, receipt):
    if not isinstance(receipt, dict):
        return False
    supplied = receipt.get('preview_id')
    if not isinstance(supplied, str) or len(supplied) != 64 or not supplied.isascii():
        return False
    unsigned = {key: value for key, value in receipt.items() if key != 'preview_id'}
    return hmac.compare_digest(supplied, _signature(workspace(root), unsigned))


def _build(root, args, expected_revision, assistant_source=None):
    view, ranges, documents = inventory(root)
    revision = view['revision']
    if expected_revision != revision:
        raise ValueError('人物档案已更新，请刷新后重新预览。')
    character = next((row for row in view['characters'] if row['id'] == args.get('character_id')), None)
    if character is None:
        raise ValueError('请选择当前作品中的人物。')
    restore_id = args.get('history_id')
    if restore_id:
        old = next((row for row in history(root, character['id'])['entries'] if row['id'] == restore_id), None)
        if old is None:
            raise ValueError('未找到该人物的修订。')
        args = {'section_id': old['section_id'], 'source_id': old['source_id'], 'replacement': old['before']}
    section = next((row for row in character['sections'] if row['id'] == args.get('section_id')
                    and row['source_id'] == args.get('source_id')), None)
    if section is None or not section['editable']:
        raise ValueError('该字段无法唯一定位或受保护。')
    before, after = section['text'], args.get('replacement')
    if restore_id and (old['after'] != before or sum(row['source_id'] == section['source_id']
                      and row['label'] == section['label'] and row['text'] == before
                      for row in character['sections']) != 1):
        raise ValueError('该片段已改动或不再唯一，无法直接回退。')
    if (not isinstance(after, str) or not 0 < len(after) <= 12000 or after.strip() != after
            or after.splitlines() != [after] or '\x00' in after or after == before):
        raise ValueError('请输入一条非空、单行、与原文不同的片段。')
    source_id = section['source_id']
    original = documents[source_id]
    text = original.decode('utf-8-sig')
    start, end = ranges[section['id']]
    updated = text[:start] + after + text[end:]
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    changed = documents | {source_id: bom + updated.encode('utf-8')}
    updated_view, _, _ = inventory(root, changed)
    expected_section = next((row for person in updated_view['characters'] if person['id'] == character['id']
                             for row in person['sections'] if row['id'] == section['id']), None)
    if not expected_section or expected_section['text'] != after or not expected_section['editable']:
        raise ValueError('修改会改变档案结构，请使用该字段原有格式。')
    receipt = dict(revision=revision, source_revision=section['source_revision'], source_id=source_id,
                   character_id=character['id'], section_id=section['id'], before=before, after=after,
                   line=section['line'], impact=f"仅修改 {character['name']} 的「{section['label']}」。",
                   history_id=restore_id)
    if assistant_source is not None:
        from .assistant_hooks import is_current
        if (not isinstance(assistant_source, dict)
                or any(assistant_source.get(key) != receipt[key] for key in ('character_id', 'section_id', 'source_id'))
                or not section['ai_editable'] or restore_id or not is_current(root, assistant_source)):
            raise ValueError('建议依据已变化，请重新分析。')
        receipt['assistant_source'] = assistant_source
    receipt['preview_id'] = _signature(root, receipt)
    return receipt, changed[source_id], updated_view['revision']


def preview(root, args, expected_revision, *, assistant_source=None):
    return _build(workspace(root), args, expected_revision, assistant_source)[0]


def apply(root, receipt, expected_revision):
    root = workspace(root)
    if not authentic_preview(root, receipt):
        raise ValueError('预览凭证失效，请重新预览。')
    # Validate before creating a lock directory. Recheck under the lock before writing.
    args = {key: receipt.get(key) for key in ('character_id', 'section_id', 'source_id', 'history_id')}
    args['replacement'] = receipt.get('after')
    binding = receipt.get('assistant_source')
    if preview(root, args, expected_revision, assistant_source=binding) != receipt:
        raise ValueError('预览凭证不匹配，请重新预览。')
    with locked(root):
        entries = _recover(root)
        confirmed, data, revision = _build(root, args, expected_revision, binding)
        if confirmed != receipt:
            raise ValueError('预览凭证不匹配，请重新预览。')
        source_id = confirmed['source_id']
        target = source_path(root, source_id)
        pending = source_path(root, PENDING)
        archive = source_path(root, HISTORY)
        original = target.read_bytes()
        if digest(original) != confirmed['source_revision']:
            raise ValueError('原件已改动，请重新预览。')
        entry = {key: confirmed[key] for key in ('character_id', 'section_id', 'source_id', 'before', 'after')}
        entry.update(id=uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
                     revision_before=expected_revision, revision_after=revision,
                     source_revision_before=confirmed['source_revision'], source_revision_after=digest(data),
                     restored_from=confirmed['history_id'])
        # A pending journal becomes visible only after its exact card bytes publish.
        atomic(pending, encode([entry, *entries]))
        try:
            if digest(target.read_bytes()) != confirmed['source_revision']:
                raise ValueError('原件已改动，请重新预览。')
            atomic(target, data)
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
        try:
            pending.replace(archive)
        except OSError:
            # Keep the pending record if rollback cannot prove ownership of
            # the card bytes. Future writers must resolve it before continuing.
            if digest(target.read_bytes()) != entry['source_revision_after']:
                raise ValueError('原件在修订期间被外部修改，请先人工核对待恢复记录。')
            atomic(target, original)
            pending.unlink()
            raise
    return dict(status='success', revision=revision, entry=entry)
