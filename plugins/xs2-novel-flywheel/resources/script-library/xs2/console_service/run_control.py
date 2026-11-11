"""Durable, bounded dispatch admission over the host's existing task engine."""
from contextlib import closing
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import time
from uuid import uuid4


@lru_cache(maxsize=1)
def serial():
    spec=importlib.util.spec_from_file_location('run_serial',Path(__file__).resolve().parents[1]/'story_support/serial.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def connect(root):
    db=serial().support().archive_store().connect(root)
    db.executescript('''CREATE TABLE IF NOT EXISTS serial_runs(
        id TEXT PRIMARY KEY, created REAL NOT NULL, status TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_serial_run ON serial_runs(status) WHERE status='active';
        CREATE TABLE IF NOT EXISTS serial_dispatches(
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, chapter TEXT NOT NULL, stage TEXT NOT NULL,
        input_sha TEXT NOT NULL, task_id TEXT UNIQUE, status TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS serial_task_observations(reservation_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS serial_resumes(id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL,cost INTEGER NOT NULL,created REAL NOT NULL);
    ''')
    return db


def admit(root,state,stage):
    config=serial().contract(root)
    if not config:
        if state.get('serialRunId'):raise ValueError('本书连续运行契约缺失，请先恢复配置')
        return None
    s=serial().support();chapter=s.chapter_id(state.get('values',{}).get('chapter_number','0001'))
    signature=s.archive_store().identity({'values':state.get('values',{}),'stage':stage,
        'contract':s.archive_store().contract(root,persistent=True),
        'serial_contract':s.digest(root,'meta/serial_contract.json'),
        'models':{k:v for k,v in state.items() if 'model' in k.lower()}})
    limits={'max_dispatches':10000,'max_chapters':9999,'max_stage_attempts':8,**config.get('run_limits',{})}
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        run_id=state.get('serialRunId');run=db.execute('SELECT * FROM serial_runs WHERE id=?',(run_id,)).fetchone() if run_id else None
        if run and run['status']=='finished':run=None;run_id=None
        active=db.execute("SELECT * FROM serial_runs WHERE status='active'").fetchone()
        reservation=state.get('serialReservation')
        if not run:
            if active:
                latest=db.execute('SELECT * FROM serial_dispatches WHERE run_id=? ORDER BY created DESC,rowid DESC LIMIT 1',(active['id'],)).fetchone()
                ref=(state.get('refs',{}).get(stage) or {}).get('task_id')
                if latest and latest['input_sha']==signature and (latest['status']=='reserved' or (ref and latest['task_id']==ref)):
                    run=active;run_id=active['id'];reservation=latest['id']
                else:raise ValueError('本书已有连续任务运行，不能重复创建派发链')
            else:
                run_id=str(uuid4());db.execute('INSERT INTO serial_runs VALUES(?,?,?)',(run_id,time.time(),'active'))
                run=db.execute('SELECT * FROM serial_runs WHERE id=?',(run_id,)).fetchone()
        if active and active['id']!=run_id:raise ValueError('连续运行归属冲突')
        elapsed=time.time()-run['created']
        if elapsed<0 or ('max_elapsed_seconds' in limits and elapsed>limits['max_elapsed_seconds']):
            raise ValueError('连续运行已达到时间预算，停止派发')
        old=db.execute('SELECT * FROM serial_dispatches WHERE id=?',(reservation,)).fetchone() if reservation else None
        if old and old['run_id']==run_id and old['status'] in ('reserved','running','bound','pending','preparing','pre_running','retry_waiting','resume_pending','paused'):
            if old['input_sha']!=signature:raise ValueError('正在执行的派发输入已有变化，不能复用或覆盖')
            state['serialRunId']=run_id;state['serialReservation']=old['id'];return old['id']
        count,attempts=counts(db,run_id,chapter,stage)
        chapters={row[0] for row in db.execute('SELECT DISTINCT chapter FROM serial_dispatches WHERE run_id=?',(run_id,))}
        if count>=limits['max_dispatches'] or attempts>=limits['max_stage_attempts'] or (chapter not in chapters and len(chapters)>=limits['max_chapters']):
            raise ValueError('连续运行派发或重试次数已达预算上限；重启不会重置预算')
        reservation=str(uuid4())
        db.execute('INSERT INTO serial_dispatches VALUES(?,?,?,?,?,?,?,?)',
            (reservation,run_id,chapter,stage,signature,None,'reserved',time.time()))
    state['serialRunId']=run_id;state['serialReservation']=reservation
    return reservation


def counts(db,run_id,chapter,stage):
    count=db.execute('SELECT count(*) FROM serial_dispatches WHERE run_id=?',(run_id,)).fetchone()[0]
    count+=db.execute('SELECT coalesce(sum(r.cost),0) FROM serial_resumes r JOIN serial_dispatches d ON d.id=r.reservation_id WHERE d.run_id=?',(run_id,)).fetchone()[0]
    attempts=db.execute('SELECT count(*) FROM serial_dispatches WHERE run_id=? AND chapter=? AND stage=?',(run_id,chapter,stage)).fetchone()[0]
    attempts+=db.execute('SELECT coalesce(sum(r.cost),0) FROM serial_resumes r JOIN serial_dispatches d ON d.id=r.reservation_id WHERE d.run_id=? AND d.chapter=? AND d.stage=?',(run_id,chapter,stage)).fetchone()[0]
    return count,attempts


def observe(root,state,stage,task):
    reservation=state.get('serialReservation')
    if not reservation and not task.get('task_id'):return
    if not reservation and not state.get('serialRunId') and serial().contract(root) is None:return
    if not task.get('task_id'):raise ValueError('派发任务编号缺失')
    with closing(connect(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM serial_dispatches WHERE id=?',(reservation,)).fetchone() if reservation else db.execute('SELECT * FROM serial_dispatches WHERE task_id=?',(task['task_id'],)).fetchone()
        if row is None and not reservation:return
        if row and not reservation:
            active=db.execute("SELECT id FROM serial_runs WHERE status='active'").fetchone()
            if active and active['id']!=row['run_id']:raise ValueError('恢复任务不属于当前连续运行')
            state['serialReservation']=reservation=row['id'];state['serialRunId']=row['run_id']
        number=serial().support().chapter_id(state.get('values',{}).get('chapter_number','0001'))
        if not row or row['run_id']!=state.get('serialRunId') or row['stage']!=stage or row['chapter']!=number:
            raise ValueError('连续派发任务归属不符')
        if row['task_id'] and row['task_id']!=task['task_id']:raise ValueError('重复任务不能复用同一派发凭据')
        status=task.get('status','bound')
        observation={'run_id':task.get('run_id'),'attempts':{key:int(value.get('attempt_count') or 0) for key,value in task.get('node_states',{}).items()}}
        if row['status'] in ('completed','failed','stopped','cancelled'):
            old=db.execute('SELECT data FROM serial_task_observations WHERE reservation_id=?',(reservation,)).fetchone()
            previous=json.loads(old['data']) if old else {}
            # A downstream node's first execution is ordinary progress, not a
            # restored attempt. Count only repeated executions beyond that base.
            delta=sum(max(0,n-max(1,previous.get('attempts',{}).get(key,0))) for key,n in observation['attempts'].items())
            resumed=(status=='resume_pending' or delta>0 or (observation['run_id'] and observation['run_id']!=previous.get('run_id')))
            if not resumed and status==row['status']:return
            if row['status'] not in ('failed','stopped') or not resumed:raise ValueError('已结束任务缺少有效恢复证据')
            limits={'max_dispatches':10000,'max_stage_attempts':8,**(serial().contract(root) or {}).get('run_limits',{})}
            run=db.execute('SELECT created FROM serial_runs WHERE id=?',(row['run_id'],)).fetchone()
            elapsed=time.time()-run['created']
            if elapsed<0 or ('max_elapsed_seconds' in limits and elapsed>limits['max_elapsed_seconds']):
                raise ValueError('恢复已达到连续运行时间预算上限')
            total,attempts=counts(db,row['run_id'],row['chapter'],stage)
            cost=max(1,delta)
            if total+cost>limits['max_dispatches'] or attempts+cost>limits['max_stage_attempts']:raise ValueError('恢复已达到连续运行预算上限')
            db.execute('INSERT INTO serial_resumes VALUES(?,?,?,?)',(str(uuid4()),reservation,cost,time.time()))
        db.execute('UPDATE serial_dispatches SET task_id=?,status=? WHERE id=?',(task['task_id'],status,reservation))
        db.execute('INSERT OR REPLACE INTO serial_task_observations VALUES(?,?)',(reservation,json.dumps(observation)))


def finish(root,state):
    if not state.get('serialRunId'):return
    with closing(connect(root)) as db, db:
        db.execute("UPDATE serial_runs SET status='finished' WHERE id=?",(state['serialRunId'],))


def status(root,state):
    with closing(connect(root)) as db:
        count=db.execute('SELECT count(*) FROM serial_dispatches WHERE run_id=?',(state.get('serialRunId'),)).fetchone()[0]
        resumes=db.execute('SELECT coalesce(sum(r.cost),0) FROM serial_resumes r JOIN serial_dispatches d ON d.id=r.reservation_id WHERE d.run_id=?',(state.get('serialRunId'),)).fetchone()[0]
    return {'run_id':state.get('serialRunId'),'dispatches':count,'resumes':resumes}
