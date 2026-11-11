"""Plugin-owned durable publication intents and append-only run receipts.

SQLite commits the intent before file replacement. A pending intent is never
trusted by consumers. Replay is compare-and-swap, not unconditional repair.
No model calls, prose rules, or host-runtime imports belong in this module.
"""
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sqlite3
import tempfile


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def path(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if Path(relative).is_absolute() or not target.is_relative_to(root):
        raise ValueError('归档路径不能离开当前作品')
    return target


def digest(root, relative):
    match=re.fullmatch(r'@memory/scene-time/([0-9]{4})',relative)
    if match:
        source=path(root,f'story/{match[1]}/planned_world_state.json')
        data=json.loads(source.read_text(encoding='utf-8-sig')) if source.is_file() else {}
        value=data.get('world_time_key')
        if value is not None and type(value) is not int:
            raise ValueError('场景世界时间序号须为整数或省略')
        return identity(value)
    target = path(root, relative)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ''


def contract(root, persistent=False):
    source = Path(__file__).resolve().parents[1] / 'prose_policy/book_contract.py'
    spec = importlib.util.spec_from_file_location('archive_book_contract', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.resolve(root)
    if persistent:
        value.pop('reading_contract',None) # Reading taste does not revoke historical facts.
        # Production clears these two chapter-local directions on advance.
        # They freeze the current review but do not revoke completed history.
        for field in ('human_intent', 'world_intent'):
            value['author_intent'].pop(field, None)
    return identity(value)


def connect(root):
    target = path(root, 'archive/longform.sqlite3')
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    if db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('publications','run_events')").fetchone()[0] == 2:
        return db
    db.executescript('''
        CREATE TABLE IF NOT EXISTS publications (
          id TEXT PRIMARY KEY, chapter TEXT NOT NULL, status TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE NOT NULL,
          kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')
    return db


def _event(db, kind, data):
    key = identity([kind, data])
    db.execute('INSERT OR IGNORE INTO run_events(event_key,kind,data,created_at) VALUES(?,?,?,?)',
               (key, kind, encoded(data), datetime.now(timezone.utc).isoformat()))


def event(root, kind, data):
    with closing(connect(root)) as db, db:
        _event(db, kind, data)


def events(root, *, kind=None, task_id=None):
    if not path(root, 'archive/longform.sqlite3').is_file():
        return []
    predicates, params = [], []
    if kind is not None:
        predicates.append('kind=?')
        params.append(kind)
    if task_id is not None:
        predicates.append("json_extract(data, '$.task_id')=?")
        params.append(task_id)
    where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
    with closing(connect(root)) as db:
        return [dict(row) | {'data': json.loads(row['data'])}
                for row in db.execute('SELECT * FROM run_events' + where + ' ORDER BY sequence', params)]


def publications(root):
    if not path(root, 'archive/longform.sqlite3').is_file():
        return []
    with closing(connect(root)) as db:
        return [dict(row) for row in db.execute('SELECT id,chapter,status,created_at FROM publications ORDER BY rowid')]


def revision(root):
    return len(publications(root))


def atomic(root, relative, content):
    target = path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='archive-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _guards(root, record, persistent=False):
    expected = record.get('persistent_contract', record['contract']) if persistent else record['contract']
    if contract(root, persistent=persistent) != expected or any(
            digest(root, relative) != expected for relative, expected in record['guards'].items()
            if not persistent or (not relative.startswith('cache/') and relative not in record.get('transient_guards',[]))):
        raise ValueError('章节提交依据已有变化，保留待恢复记录，请重新核对正文与设定')


def execution_guard():
    source=Path(__file__).resolve().parents[1]/'production_guard/production_guard.py'
    spec=importlib.util.spec_from_file_location('archive_execution_fence',source)
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    return guard


def _replay(root, db, row):
    record = json.loads(row['content'])
    # recover() already holds BEGIN IMMEDIATE. Verify the intent's original
    # epoch on this connection, retaining the same lock through replacement.
    with execution_guard().publication(root,db=db,proof=record.get('execution_fence')):
        _guards(root, record)
        # Each destination may contain either frozen previous bytes or exact
        # intended bytes after a crash; check all before changing any of them.
        for relative, text in record['outputs'].items():
            wanted = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if digest(root, relative) not in (record['previous'][relative], wanted):
                raise ValueError(f'章节归档恢复目标存在冲突：{relative}')
        for relative, text in record['outputs'].items():
            if digest(root, relative) != hashlib.sha256(text.encode('utf-8')).hexdigest():
                atomic(root, relative, text)
        _guards(root, record)
        db.execute("UPDATE publications SET status='complete' WHERE id=?", (row['id'],))
        _event(db, 'archive_complete', {'chapter': row['chapter'], 'commit_id': row['id']})


def recover(root):
    if not path(root, 'archive/longform.sqlite3').is_file():
        return
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute("SELECT * FROM publications WHERE status='pending' ORDER BY rowid").fetchall():
            _replay(root, db, row)


def abandon(root, chapter=None, commit_id=None):
    """Explicit operator action: retain intent and outputs, permit fresh review."""
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if commit_id:
            rows = db.execute("SELECT id,chapter FROM publications WHERE id=? AND status='pending'", (commit_id,)).fetchall()
        elif chapter:
            rows = db.execute("SELECT id,chapter FROM publications WHERE chapter=? AND status='pending'", (chapter,)).fetchall()
        else:
            raise ValueError('请选择章节或具体提交编号')
        for row in rows:
            db.execute("UPDATE publications SET status='abandoned' WHERE id=?", (row['id'],))
            _event(db, 'archive_abandoned', {'chapter': row['chapter'], 'commit_id': row['id']})


@contextmanager
def verification_reader(root):
    """One read transaction per history scan; never cache across requests."""
    if not path(root,'archive/longform.sqlite3').is_file():
        yield {'db':None,'managed':set()}
        return
    with closing(connect(root)) as db:
        db.execute('BEGIN')
        managed={row['chapter'] for row in db.execute('SELECT chapter FROM publications')}
        yield {'db':db,'managed':managed}


def existing(root, commit_id, reader=None):
    if not path(root, 'archive/longform.sqlite3').is_file():
        return None
    if reader is not None and reader['db'] is None:return None
    with (nullcontext(reader['db']) if reader is not None else closing(connect(root))) as db:
        row = db.execute('SELECT * FROM publications WHERE id=?', (commit_id,)).fetchone()
        if row and row['status'] == 'complete':
            record = json.loads(row['content'])
            _guards(root, record, persistent=True)
            snapshot = record['snapshot']
            if not snapshot.get('chapter'):
                raise ValueError('归档编号不属于章节提交')
            current = path(root, f"story/{snapshot['chapter']}/confirmed_state.json")
            if not current.is_file() or json.loads(current.read_text(encoding='utf-8-sig')) != snapshot:
                raise ValueError('确认档案已有变化，不能复用旧提交')
            return snapshot
    return None


def verify_snapshot(root, snapshot, reader=None):
    key = snapshot.get('archive_commit_id')
    managed=reader['managed'] if reader is not None else {row['chapter'] for row in publications(root)}
    if not key and snapshot.get('chapter') in managed:
        raise ValueError('受管章节缺少归档提交凭据')
    if key and existing(root, key, reader=reader) != snapshot:
        raise ValueError('章节提交尚未完成或确认档案与凭据不符')


def historical_snapshot(root, snapshot):
    key = snapshot.get('archive_commit_id')
    if not key:
        verify_snapshot(root, snapshot)
        return snapshot
    with closing(connect(root)) as db:
        row = db.execute("SELECT content FROM publications WHERE id=? AND status IN ('complete','abandoned')", (key,)).fetchone()
        if not row or json.loads(row['content'])['snapshot'] != snapshot:
            raise ValueError('历史确认档案与归档凭据不符')
    return snapshot


def publish_views(root, builder, guards_builder):
    guard=execution_guard()
    recover(root)
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        fence=guard.assert_current(root,db=db)
        if db.execute("SELECT id FROM publications WHERE status='pending'").fetchone():
            raise ValueError('存在待恢复章节提交')
        guards = guards_builder()
        expected_contract = contract(root)
        outputs = {}
        builder(lambda r, p, v: outputs.update({p: v}))
        rendered = {p: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).rstrip() + '\n' for p, v in outputs.items()}
        key = identity(['views', db.execute('SELECT count(*) FROM publications').fetchone()[0], rendered])
        record = {'snapshot': {}, 'outputs': rendered, 'guards': guards, 'contract': expected_contract,
                  'inputs': {'kind':'derived_views'}, 'previous': {p: digest(root, p) for p in rendered},
                  'execution_fence':fence}
        db.execute('INSERT INTO publications VALUES(?,?,?,?,?)', (key, '', 'pending', encoded(record), datetime.now(timezone.utc).isoformat()))
        _event(db, 'archive_prepare', {'chapter':'', 'commit_id':key})
    recover(root)


def publish(root, snapshot, outputs, guards, inputs, expected_revision, transient_guards=()):
    guard=execution_guard()
    key = snapshot['archive_commit_id']
    # A durable intent serializes publishers across processes, including crash
    # recovery. No second publication may overtake a pending one.
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        fence=guard.assert_current(root,db=db)
        if db.execute('SELECT count(*) FROM publications').fetchone()[0] != expected_revision:
            raise ValueError('归档版本已有变化，请重新提交')
        pending = db.execute("SELECT id FROM publications WHERE status='pending'").fetchone()
        if pending:
            raise ValueError('存在待恢复的章节提交，请先恢复')
        if db.execute('SELECT id FROM publications WHERE id=?', (key,)).fetchone():
            raise ValueError('章节提交已登记，请核对现有凭据')
        rendered = {relative: (value if isinstance(value, str) else
                    json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)).rstrip() + '\n'
                    for relative, value in outputs.items()}
        record = {'snapshot': snapshot, 'outputs': rendered, 'guards': guards,
                  'execution_fence':fence,
                  'transient_guards':list(transient_guards),
                  'contract': inputs['source'].get('book_contract_sha256', contract(root)), 'inputs': inputs,
                  'persistent_contract': contract(root, persistent=True),
                  'previous': {relative: digest(root, relative) for relative in rendered}}
        _guards(root, record)
        db.execute('INSERT INTO publications VALUES(?,?,?,?,?)',
                   (key, snapshot['chapter'], 'pending', encoded(record), datetime.now(timezone.utc).isoformat()))
        _event(db, 'archive_prepare', {'chapter': snapshot['chapter'], 'commit_id': key})
    recover(root)
    return snapshot
