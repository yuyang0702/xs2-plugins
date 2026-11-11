"""Opt-in long-run evidence. Novel facts still belong to the P0 archive."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

HERE=Path(__file__).resolve().parent
DIMENSIONS={'memory','cognition','volume'}
KINDS={'memory_omission','retrieval_miss','fact_contradiction','cognition_boundary','volume_handoff','other'}


def now():return datetime.now(timezone.utc).isoformat()
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def identity(value):return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()
def sha(file):return hashlib.sha256(Path(file).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def support():
    spec=importlib.util.spec_from_file_location('longrun_story_support',HERE.parent/'story_support/story_support.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def enabled(root):return (Path(root)/'meta/longrun_contract.json').is_file()


def connect(root):
    folder=Path(root)/'observability';folder.mkdir(parents=True,exist_ok=True)
    if not folder.resolve().is_relative_to(Path(root).resolve()):raise ValueError('观测目录超出本书范围')
    db=sqlite3.connect(folder/'longrun.sqlite3',timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''CREATE TABLE IF NOT EXISTS run_config(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chapters(chapter TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chapter_history(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audits(id TEXT PRIMARY KEY,chapter TEXT NOT NULL,body_sha TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS controller_commits(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pricing_views(id TEXT PRIMARY KEY,data TEXT NOT NULL);
    ''')
    return db


def config(root,db=None):
    if db is None:
        with closing(connect(root)) as connection:return config(root,connection)
    row=db.execute('SELECT data FROM run_config WHERE id=1').fetchone()
    if row is None:raise ValueError('长跑观测尚未初始化')
    frozen=json.loads(row['data'])
    current=support().load(root,'meta/longrun_contract.json')
    if current!=frozen['config']:raise ValueError('本次长跑配置已有变化，请核对本轮冻结记录')
    return frozen


def initialize(root,value,baseline_chapters=()):
    if not isinstance(value,dict) or value.get('schema')!=1 or type(value.get('target_new_characters')) is not int or value['target_new_characters']<1:
        raise ValueError('长跑目标配置无效')
    if not isinstance(value.get('models'),list) or not value['models'] or any(not isinstance(m,str) or ':' not in m for m in value['models']):
        raise ValueError('长跑须有明确授权的模型路径')
    limits=value.get('limits',{})
    if not isinstance(limits,dict) or any(k not in {'max_calls','max_total_tokens','max_configured_cost'} or (v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or v<=0)) for k,v in limits.items()):
        raise ValueError('长跑预算无效')
    body={'config':value,'baseline_chapters':sorted({support().chapter_id(n) for n in baseline_chapters}),'created_at':now()}
    with closing(connect(root)) as db,db:
        old=db.execute('SELECT data FROM run_config WHERE id=1').fetchone()
        if old:
            saved=json.loads(old['data'])
            if saved['config']!=value or saved['baseline_chapters']!=body['baseline_chapters']:raise ValueError('不能覆盖已有长跑配置')
            return saved
        support().write(root,'meta/longrun_contract.json',value)
        db.execute('INSERT INTO run_config VALUES(1,?)',(encoded(body),))
    return body


def file_manifest(root):
    root=Path(root).resolve();result={}
    for file in root.rglob('*'):
        if file.is_symlink():raise ValueError('来源含符号链接，请先使用独立的普通文件副本')
        if file.is_file() and '__pycache__' not in file.parts:result[file.relative_to(root).as_posix()]=sha(file)
    return result


def initialize_copy(source,destination,value):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_dir() or destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('来源与新副本目录须独立，不能复用或嵌套')
    manifest=file_manifest(source)
    if not manifest:raise ValueError('来源作品为空')
    if enabled(source):raise ValueError('来源已有长跑记录，请从未参与长跑的来源建立新副本')
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    baseline=[p.parent.name for p in (destination/'story').glob('[0-9][0-9][0-9][0-9]/chapter.md')]
    initialize(destination,value,baseline)
    support().write(destination,'observability/source-manifest.json',{'source':str(source),'files':manifest})
    return check_sources(destination)


def check_sources(root):
    protected=support().load(root,'observability/source-manifest.json')
    if not protected:return {'checked':False,'unchanged':None}
    actual=file_manifest(protected['source'])
    if actual!=protected['files']:raise ValueError('原稿或来源资料发生变化，长跑已停止')
    return {'checked':True,'unchanged':True,'files_checked':len(actual),'source':protected['source']}


def event(root,kind,payload,key=None):
    item={'kind':kind,'payload':payload};key=key or identity(item)
    with closing(connect(root)) as db,db:
        db.execute('INSERT OR IGNORE INTO events VALUES(?,?)',(key,encoded({**item,'timestamp':now()})))


def _replay_controller(root,db):
    s=support();config(root,db)
    for row in db.execute("SELECT * FROM controller_commits WHERE status='pending' ORDER BY id").fetchall():
        record=json.loads(row['data'])
        for path,text in record['outputs'].items():
            after=hashlib.sha256(text.encode('utf-8')).hexdigest()
            if s.digest(root,path) not in (record['before'][path],after):raise ValueError('长跑控制器目标已有外部变化，保留恢复意图')
        for path,text in record['outputs'].items():s.archive_store().atomic(root,path,text)
        db.execute("UPDATE controller_commits SET status='complete' WHERE id=?",(row['id'],))


def recover_controller(root):
    with closing(connect(root)) as db,db:
        db.execute('BEGIN IMMEDIATE');_replay_controller(root,db)


def publish_controller(root,outputs):
    """Control state may intentionally change chapter-local author intent.

    Reuse P0's durable-intent/CAS/file replacement pattern, with the immutable
    long-run config as authority rather than the very book contract we update.
    """
    s=support();recover_controller(root)
    texts={p:(json.dumps(v,ensure_ascii=False,indent=2).rstrip()+'\n') for p,v in outputs.items()}
    with closing(connect(root)) as db:
        db.execute('BEGIN IMMEDIATE');config(root,db)
        if db.execute("SELECT 1 FROM controller_commits WHERE status='pending'").fetchone():raise ValueError('控制器仍有待恢复提交')
        record={'outputs':texts,'before':{p:s.digest(root,p) for p in texts},'created_at':now()}
        db.execute("INSERT INTO controller_commits(status,data) VALUES('pending',?)",(encoded(record),));db.commit()
        try:
            db.execute('BEGIN IMMEDIATE');_replay_controller(root,db);db.commit()
        except BaseException:db.rollback();raise


def _call_rows(db):return [json.loads(row['data']) for row in db.execute('SELECT data FROM calls ORDER BY rowid')]


def usage_summary(calls):
    complete=[c for c in calls if c.get('usage_status')=='complete']
    uncertain=[c for c in calls if c.get('usage_status')!='complete']
    return {'call_count':len(calls),'actual_tokens':sum(c['total_tokens'] for c in complete),
        'prompt_tokens':sum(c['prompt_tokens'] for c in complete),
        'completion_tokens':sum(c['completion_tokens'] for c in complete),
        'unknown_call_count':len(uncertain),'reserved_unknown_tokens':sum(c.get('reserved_tokens',0) for c in uncertain),
        'failed_call_count':sum(c.get('status')=='failed' for c in calls)}


def pricing_signature(calls,value):return identity([calls,value.get('pricing',{})])


def record_pricing(root,calls,priced):
    with closing(connect(root)) as db,db:
        value=config(root,db)['config']
        if pricing_signature(calls,value)!=pricing_signature(_call_rows(db),value):raise ValueError('计价期间调用记录已有变化')
        db.execute('INSERT OR REPLACE INTO pricing_views VALUES(?,?)',(pricing_signature(calls,value),encoded(priced)))


def cost_summary(calls,value,root=None):
    priced=None
    if root is not None:
        with closing(connect(root)) as db:
            row=db.execute('SELECT data FROM pricing_views WHERE id=?',(pricing_signature(calls,value),)).fetchone()
            if row:priced=json.loads(row['data'])
    if priced is None:
        return {'status':'unpriced' if calls else 'no_usage','currency':value.get('pricing',{}).get('currency','USD'),
            'amount':None,'known_configured_amount':'0','unpriced_call_count':len(calls),
            'basis':'No current host pricing evidence; never assume free.','pricing_snapshot':None}
    rows=priced['calls'];known=[c for c in rows if c.get('cost_status')=='priced']
    partial=sum((Decimal(str(c['cost']['amount'])) for c in known),Decimal(0))
    complete=bool(rows) and len(known)==len(rows)
    return {'status':('priced' if complete else 'partially_priced' if known else 'unpriced' if rows else 'no_usage'),
        'currency':priced['pricing_snapshot']['currency'],'amount':str(partial) if complete else None,
        'known_configured_amount':str(partial),'unpriced_call_count':len(rows)-len(known),
        'basis':'configured prices; not provider invoice','pricing_snapshot':priced['pricing_snapshot']}


def reserve_call(root,metadata,reserved_tokens,projected_cost=None):
    if type(reserved_tokens) is not int or reserved_tokens<1:raise ValueError('调用预留额度无效')
    check_sources(root)
    with closing(connect(root)) as db,db:
        db.execute('BEGIN IMMEDIATE');frozen=config(root,db);value=frozen['config']
        if metadata.get('model_id') not in value['models']:raise ValueError('请求模型不在本次授权范围')
        rows=_call_rows(db);usage=usage_summary(rows);limits=value.get('limits',{})
        if limits.get('max_calls') is not None and len(rows)>=limits['max_calls']:raise ValueError('调用次数已达预算上限')
        if limits.get('max_total_tokens') is not None and usage['actual_tokens']+usage['reserved_unknown_tokens']+reserved_tokens>limits['max_total_tokens']:
            raise ValueError('调用将超出长跑 Token 预算，未知请求仍保留预留额度')
        if limits.get('max_configured_cost') is not None:
            cost=cost_summary(rows,value,root)
            if cost['status'] not in ('priced','no_usage') or projected_cost is None or Decimal(cost['amount'] or '0')+Decimal(str(projected_cost))>Decimal(str(limits['max_configured_cost'])):
                raise ValueError('金额预算无法核对或将达上限')
        key=str(uuid4());model=metadata['model_id'];provider,name=model.split(':',1)
        item={**metadata,'call_id':key,'provider':provider,'model':name,'timestamp':now(),
            'status':'reserved','usage_status':'unknown','reserved_tokens':reserved_tokens}
        db.execute('INSERT INTO calls VALUES(?,?)',(key,encoded(item)))
    return key


def check_budget(root):
    if not enabled(root):return
    check_sources(root)
    with closing(connect(root)) as db:
        value=config(root,db)['config'];usage=usage_summary(_call_rows(db));limits=value.get('limits',{})
        if limits.get('max_calls') is not None and usage['call_count']>=limits['max_calls']:raise ValueError('长跑调用预算已达上限')
        if limits.get('max_total_tokens') is not None and usage['actual_tokens']+usage['reserved_unknown_tokens']>=limits['max_total_tokens']:
            raise ValueError('长跑 Token 预算已达上限')


def finish_call(root,call_id,result):
    with closing(connect(root)) as db,db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT data FROM calls WHERE id=?',(call_id,)).fetchone()
        if not row:raise ValueError('调用预留凭据缺失')
        old=json.loads(row['data'])
        if old.get('status')!='reserved':
            if any(old.get(k)!=v for k,v in result.items()):raise ValueError('已完成调用凭据与新结果不同')
            return old
        data={**old,**result,'call_id':call_id,'completed_at':now()}
        if data.get('usage_status')=='complete':
            if any(type(data.get(k)) is not int or data[k]<0 for k in ('prompt_tokens','completion_tokens','total_tokens')) or data['total_tokens']!=data['prompt_tokens']+data['completion_tokens']:
                data['usage_status']='incomplete';data['usage_errors']=['provider_usage_invalid']
        db.execute('UPDATE calls SET data=? WHERE id=?',(encoded(data),call_id))
    return data


def observe_task(root,state,stage,task,kind):
    if not enabled(root):return
    payload={'chapter':str(state.get('values',{}).get('chapter_number','0001')).zfill(4),'stage':stage,
        'task_id':task.get('task_id',''),'status':task.get('status',''),'run_id':task.get('run_id'),
        'error':str(task.get('error') or '')[:2000],
        'nodes':{k:{f:v.get(f) for f in ('status','attempt_count','session_id','error') if v.get(f) is not None}
                 for k,v in task.get('node_states',{}).items()}}
    event(root,kind,payload)
    def calls_in(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='token_usage_calls' and isinstance(item,list):
                    yield from (row for row in item if isinstance(row,dict))
                elif isinstance(item,(dict,list)):yield from calls_in(item)
        elif isinstance(value,list):
            for item in value:yield from calls_in(item)
    with closing(connect(root)) as db,db:
        for index,row in enumerate(calls_in(task.get('node_states',{}))):
            key=str(row.get('call_id') or identity([task.get('task_id'),row.get('node_id'),row.get('session_id'),index]))
            matched=next((c for c in _call_rows(db) if row.get('run_id') and c.get('run_id')==row['run_id']),None)
            if matched:
                if matched.get('usage_status')!='complete' and row.get('usage_status')=='complete':
                    enriched={**matched,**{k:v for k,v in row.items() if k in ('prompt_tokens','completion_tokens','total_tokens','cached_tokens','reasoning_tokens','usage_status','usage_sources')},'host_call_id':key}
                    db.execute('UPDATE calls SET data=? WHERE id=?',(encoded(enriched),matched['call_id']))
                continue
            if not db.execute('SELECT 1 FROM calls WHERE id=?',(key,)).fetchone():
                db.execute('INSERT INTO calls VALUES(?,?)',(key,encoded({**row,'call_id':key,'reserved_tokens':0,'status':'observed'})))


def accept_chapter(root,chapter,task):
    s=support();chapter=s.chapter_id(chapter)
    if task.get('status')!='completed' or not task.get('task_id'):raise ValueError('缺少本次导出任务凭据')
    states,stale=s.confirmed(root);snapshot=next((x for x in states if x['chapter']==chapter),None)
    report=s.load(root,f'story/{chapter}/reader_report.json',{})
    body=f'story/{chapter}/chapter.md';body_sha=s.digest(root,body)
    if not snapshot or chapter in stale or report.get('verdict')!='pass' or report.get('body_sha256')!=body_sha:
        raise ValueError('章节须有当前可信归档及通过的读者评估')
    from importlib.util import spec_from_file_location,module_from_spec
    spec=spec_from_file_location('longrun_length',HERE.parent/'console_service/length_quality.py')
    length=module_from_spec(spec);spec.loader.exec_module(length)
    row={'chapter':chapter,'body_sha256':body_sha,'archive_commit_id':snapshot.get('archive_commit_id'),
        'reader_sha256':s.digest(root,f'story/{chapter}/reader_report.json'),
        'characters':length.count_prose(s.read(root,body)),'export_task_id':task['task_id'],'accepted_at':now()}
    with closing(connect(root)) as db,db:
        db.execute('INSERT OR IGNORE INTO chapter_history VALUES(?,?)',(identity(row),encoded(row)))
        db.execute('INSERT OR REPLACE INTO chapters VALUES(?,?)',(chapter,encoded(row)))
    return row


def accept_audit(root,request,result):
    s=support();s.verify(root,request['source_hashes'])
    chapter=s.chapter_id(request['chapter']);source=f'story/{chapter}/chapter.md'
    if not isinstance(result,dict) or result.get('verdict') not in ('pass','issues') or not isinstance(result.get('issues'),list):raise ValueError('长跑审查格式无效')
    def anchors(items):
        if not isinstance(items,list) or not items:raise ValueError('审查缺少可回取证据')
        for anchor in items:
            text=request['sources'].get(anchor.get('source_id'))
            quote=anchor.get('quote')
            if not isinstance(text,str) or not isinstance(quote,str) or len(quote.strip())<2 or quote not in text:raise ValueError('审查证据无法核对')
    for issue in result['issues']:
        if issue.get('kind') not in KINDS or issue.get('severity') not in ('low','medium','high') or not issue.get('description'):raise ValueError('审查问题类型或说明无效')
        anchors(issue.get('evidence'))
    checks=result.get('checks',[])
    for check in checks:
        if check.get('dimension') not in DIMENSIONS or check.get('status') not in ('pass','issue','not_applicable') or not check.get('reason'):raise ValueError('审查覆盖说明无效')
        if check['status']!='not_applicable':anchors(check.get('evidence'))
    if result['verdict']=='pass' and result['issues']:raise ValueError('有未解决问题不能标为通过')
    if result['verdict']=='issues' and not result['issues']:raise ValueError('审查结论报告有问题但问题清单为空')
    if any(c['status']=='issue' for c in checks) and (result['verdict']!='issues' or not result['issues']):raise ValueError('检查状态和审查结论不一致')
    row={'request':request,'result':result,'accepted_at':now()};key=identity([request,result])
    with closing(connect(root)) as db,db:
        db.execute('INSERT OR IGNORE INTO audits VALUES(?,?,?,?)',(key,chapter,request['source_hashes'].get(source,''),encoded(row)))
    return row


def report(root):
    s=support()
    with closing(connect(root)) as db:
        frozen=config(root,db);calls=_call_rows(db)
        events=[json.loads(r['data']) for r in db.execute('SELECT data FROM events ORDER BY rowid')]
        chapters=[json.loads(r['data']) for r in db.execute('SELECT data FROM chapters ORDER BY chapter')]
        audits=[json.loads(r['data']) for r in db.execute('SELECT data FROM audits ORDER BY rowid')]
    states,stale=s.confirmed(root);valid={x['chapter']:x for x in states}
    current=[];invalid=[]
    for row in chapters:
        number=row['chapter'];snapshot=valid.get(number)
        if (not snapshot or number in stale or row['body_sha256']!=s.digest(root,f'story/{number}/chapter.md')
                or row['reader_sha256']!=s.digest(root,f'story/{number}/reader_report.json')
                or row['archive_commit_id']!=snapshot.get('archive_commit_id')):invalid.append(number)
        elif number not in frozen['baseline_chapters']:current.append(row)
    current_audits={}
    for audit in audits:
        request=audit['request'];number=request['chapter']
        if request['source_hashes'].get(f'story/{number}/chapter.md')!=s.digest(root,f'story/{number}/chapter.md'):continue
        try:s.verify(root,request['source_hashes'])
        except ValueError:continue
        current_audits[number]=audit
    issues=[{'chapter':n,**issue} for n,a in current_audits.items() for issue in a['result']['issues']]
    coverage={n for n,a in current_audits.items() if DIMENSIONS<={c['dimension'] for c in a['result'].get('checks',[])}}
    blocked_audits=[n for n,a in current_audits.items() if a['result']['verdict']!='pass' or any(c['status']=='issue' for c in a['result'].get('checks',[]))]
    manual={e['payload'].get('id',identity(e['payload'])):e['payload']
            for e in events if e['kind']=='manual_observation'}
    manual_open=[]
    for observation in manual.values():
        if observation.get('status')=='resolved':continue
        evidence_is_current=bool(observation.get('source_hashes'))
        try:s.verify(root,observation.get('source_hashes',{}))
        except ValueError:evidence_is_current=False
        manual_open.append({**observation,'evidence_is_current':evidence_is_current})
    expected={r['chapter'] for r in current};usage=usage_summary(calls)
    characters=sum(r['characters'] for r in current);target=frozen['config']['target_new_characters']
    complete=expected<=coverage;reached=characters>=target
    result={'schema':1,'updated_at':now(),'target_new_characters':target,
        'progress':{'accepted_new_characters':characters,'accepted_new_chapters':sorted(expected),
            'baseline_chapters':frozen['baseline_chapters'],'invalidated_chapters':invalid,'target_reached':reached},
        'usage':usage,'cost':cost_summary(calls,frozen['config'],root),
        'recoveries':{'failures':[e for e in events if e['kind']=='stage_failed'],
            'recovered':[e for e in events if e['kind'] in ('stage_recovered','process_recovered')],
            'restarts':[e for e in events if e['kind']=='driver_start'],
            'controlled_restarts':[e for e in events if e['kind']=='controlled_restart'],
            'boundary_stops':[e for e in events if e['kind']=='boundary_stop'],
            'operator_resumes':[e for e in events if e['kind']=='operator_resume']},
        'audits':{'covered_chapters':sorted(coverage),'missing_chapters':sorted(expected-coverage),
            'issues':issues,'blocked_chapters':blocked_audits,'historical_audit_count':len(audits)},
        'manual_observations':{'open':manual_open,'record_count':len(manual)},
        'acceptance':{'status':('passed' if reached and complete and not issues and not blocked_audits and not manual_open and not invalid and not usage['unknown_call_count'] else 'needs_review' if reached else 'in_progress'),
            'audit_coverage_complete':complete,'note':'Word target, semantic coverage and spending completeness are separate evidence.'},
        'source_integrity':check_sources(root)}
    return result
