"""Plugin-only run preflight, fenced execution ownership and bounded retries.

This module never edits a manuscript or a model configuration. SQLite uses the
existing archive database; native task snapshots remain the execution truth.
"""
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from uuid import uuid4

PROTOCOL='production-preflight-v1'
HERE=Path(__file__).resolve().parents[1]
PLACEHOLDER=re.compile(r'\{\{([\w.-]+)\}\}')
BUILTINS={'task_id','workflow_id','workspace','workspace_dir','date','datetime'}
TERMINAL={'failed','stopped','completed'}


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def store():return load('production_guard_archive',HERE/'story_support/archive_store.py')
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def resource(here,name):
    """Find canonical resource identities in source OR prepared layout."""
    here=Path(here).resolve()
    if ('..' in Path(name).parts or Path(name).is_absolute() or '\\' in name
            or ':' in name):raise ValueError('RESOURCE: invalid identity')
    for parent in (here,*here.parents):
        for candidate in (parent/name,parent/'resources'/name):
            if candidate.is_file():return candidate
        if name in ('prompts.json','agents.json','skills.json'):
            candidate=parent/'json'/Path(name).stem/'0.json'
        elif name.startswith('workflows/'):
            pieces=Path(name).parts
            candidate=parent/'workflows/0'/('xs2-novel-flywheel-'+pieces[1])/Path(*pieces[2:])
        elif name.startswith('script-library/'):
            pieces=Path(name).parts
            candidate=parent/'script-libraries/0'/('xs2-novel-flywheel-'+pieces[1])/Path(*pieces[2:])
        else:continue
        if candidate.is_file():return candidate
    raise FileNotFoundError('RESOURCE: missing '+name)


def resource_hashes(here,names):
    return {name:hashlib.sha256(resource(here,name).read_bytes()).hexdigest() for name in names}


def profile(here=None,names=()):
    here=Path(here or HERE)
    # Canonical identities cover sibling script groups and non-Python runtime
    # resources too. Source and prepared layouts must produce the same map.
    if here.parent.name=='script-library':
        groups=[(p.name,p) for p in here.parent.iterdir() if p.is_dir()]
    elif here.parent.name=='0' and here.parent.parent.name=='script-libraries':
        groups=[(p.name.removeprefix('xs2-novel-flywheel-'),p)
                for p in here.parent.iterdir() if p.is_dir() and p.name.startswith('xs2-novel-flywheel-')]
    else:groups=[('xs2',here)]
    files={}
    for group,directory in groups:
        for p in sorted(directory.rglob('*')):
            if (p.is_file() and not {'__pycache__','.git','node_modules'}&set(p.parts)
                    and p.suffix not in {'.pyc','.pyo'}):
                files[f'script-library/{group}/'+p.relative_to(directory).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return {**files,**resource_hashes(here,names)}


def check_definition(definition,parameters,model_metadata=None,*,stage=None):
    variables={v['key'] for v in definition.get('variables',[])}
    errors=[];compatibility={};model_metadata=model_metadata or {}
    stage=stage or str(definition.get('workflow_id','')).removeprefix('xs2-novel-flywheel-')
    for node in definition.get('nodes',[]):
        serialized=json.dumps({k:node.get(k) for k in ('first_message','system_prompt_template','node_params','output_file_path','agent_type','model_override','var_bindings')},ensure_ascii=False)
        missing={key if key in variables else key.split('.')[0] for key in PLACEHOLDER.findall(serialized)}-variables-BUILTINS
        if missing:errors.append(node['id']+': undeclared '+','.join(sorted(missing)))
        params=node.get('node_params') or {}
        if node.get('node_type')=='script' and params.get('script_name'):
            name=params['script_name'];group=params.get('script_group','xs2').removeprefix('xs2-novel-flywheel-')
            if not all(isinstance(v,str) and re.fullmatch(r'[\w-]+',v) for v in (name,group)):
                errors.append(node['id']+': invalid script reference')
            else:
                extension={'python':'py','shell':'sh'}.get(params.get('script_type','shell'),'sh')
                if params.get('script_source','inline')=='library':
                    identity=f'script-library/{group}/{name}/{name}.{extension}'
                else:
                    identity=f'workflows/{stage}/script/{name}.{extension}'
                try:resource(HERE,identity)
                except (FileNotFoundError,ValueError):errors.append(node['id']+': missing script '+identity)
        if node.get('node_type')!='agent':continue
        model_params=params.get('_model_params_override',params.get('model_params',node.get('model_params_override',{})))
        if not isinstance(model_params,dict):
            errors.append(node['id']+': model parameter override must be an object');continue
        thinking=model_params.get('thinking',{})
        if not isinstance(thinking,dict):
            errors.append(node['id']+': thinking parameter must be an object');continue
        route=node.get('model_override','')
        metadata=model_metadata.get(route,{})
        supported=metadata.get('supported_thinking_types')
        mode=thinking.get('type')
        if supported is not None and mode is not None and mode not in supported:
            errors.append(node['id']+': incompatible thinking parameter for declared route capabilities')
        compatibility[node['id']]={'status':'validated_declared_capabilities' if supported is not None else 'unknown',
                                   'route_metadata_available':bool(metadata)}
    if errors:raise ValueError('PREFLIGHT: '+'; '.join(errors))
    return {'protocol':PROTOCOL,'definition_sha256':digest(definition),'parameters_sha256':digest(parameters),
            'model_parameter_compatibility':compatibility}


def _db(root):
    db=store().connect(root)
    db.execute('CREATE TABLE IF NOT EXISTS execution_intents (scope TEXT PRIMARY KEY,owner TEXT NOT NULL,epoch INTEGER NOT NULL,identity TEXT NOT NULL,active INTEGER NOT NULL,started_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS logical_retries (sequence INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,target TEXT NOT NULL,category TEXT NOT NULL,fingerprint TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS launch_reservations (owner TEXT PRIMARY KEY,content TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS logical_runs (owner TEXT PRIMARY KEY,content TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS logical_recovery_tokens (token TEXT PRIMARY KEY,content TEXT NOT NULL,child_owner TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS logical_retry_observations (source_key TEXT PRIMARY KEY,scope TEXT NOT NULL,sequence INTEGER NOT NULL,kind TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS logical_retry_scope_aliases (scope TEXT PRIMARY KEY,normalized TEXT NOT NULL)')
    return db


def claim(root,scope,owner,identity,reservation=None):
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM execution_intents WHERE scope=?',(scope,)).fetchone()
        if row and row['active']:
            if row['owner']!=owner or row['identity']!=digest(identity):raise ValueError('LEASE: 此作品已有有效执行，须先核对原生任务，不自动抢占')
            return dict(row)
        epoch=(row['epoch'] if row else 0)+1
        started=datetime.now(timezone.utc).isoformat()
        db.execute('INSERT OR REPLACE INTO execution_intents VALUES(?,?,?,?,1,?)',(scope,owner,epoch,digest(identity),started))
        if reservation is not None:
            db.execute('INSERT INTO launch_reservations VALUES(?,?)',(owner,json.dumps(reservation,ensure_ascii=False,sort_keys=True)))
        store()._event(db,'execution_claim',{'scope':scope,'owner':owner,'epoch':epoch,'identity':digest(identity),'started_at':started})
        return dict(db.execute('SELECT * FROM execution_intents WHERE scope=?',(scope,)).fetchone())


def verify_claim(root,lease,db=None):
    with (nullcontext(db) if db is not None else closing(_db(root))) as connection:
        row=connection.execute('SELECT * FROM execution_intents WHERE scope=?',(lease['scope'],)).fetchone()
        if not row or dict(row)!=lease or not row['active']:raise ValueError('LEASE: 执行所有者或代次已变化，未发布')
    return lease


def release(root,lease):
    with closing(_db(root)) as db, db:
        result=db.execute('UPDATE execution_intents SET active=0 WHERE scope=? AND owner=? AND epoch=? AND identity=? AND active=1',
                          (lease['scope'],lease['owner'],lease['epoch'],lease['identity']))
        return result.rowcount==1


def classify(reason):
    text=str(reason).lower()
    if text.startswith('composition_review_refresh:'):return 'dependency_refresh'
    if text.startswith('dialogue_review_format:'):return 'format'
    if any(s in text for s in ('resource:','preflight:','dependency','漂移','filenotfound')):return 'installation'
    if any(s in text for s in ('lease:','来源哈希不匹配','来源已有变化','哈希不匹配','冻结资料已有变化','冻结原文已有变化')):return 'source'
    if any(s in text for s in ('context_budget:','上下文容量')):return 'budget'
    if any(s in text for s in ('timeout','connection','tls','ssl','streaming chunk')):return 'transport'
    if any(s in text for s in ('证据','引用','逐字','不在当前','目标id','编号')):return 'evidence'
    if any(s in text for s in ('precision_review_format:','json','协议','schema','格式','字段','须为')):return 'format'
    if 'content_length_conflict' in text:return 'scope'
    return 'content'


def _logical_group(target):
    return load('logical_retry_groups',Path(__file__).with_name('rejections.py')).logical_step(target)


def _run_context(root,owner):
    with closing(_db(root)) as db:
        row=db.execute('SELECT content FROM logical_runs WHERE owner=?',(owner,)).fetchone()
        return json.loads(row['content']) if row else None


def _retry_scope(root,scope,target=None):
    with closing(_db(root)) as db:
        alias=db.execute('SELECT normalized FROM logical_retry_scope_aliases WHERE scope=?',(scope,)).fetchone()
        if alias:
            normalized=alias['normalized']
        else:normalized=None
        group,separator,task=scope.rpartition('/')
        if not separator:return scope,None
        workflow=os.environ.get('WORKFLOW_ID')
        rows=db.execute('SELECT owner,content FROM logical_runs'+(' WHERE owner=?' if workflow else ''),
                        ((workflow+'/'+task,) if workflow else ())).fetchall()
        rows=[r for r in rows if r['owner'].rsplit('/',1)[-1]==task]
        if len(rows)!=1:return normalized or scope,None
        context=json.loads(rows[0]['content'])
        group=_logical_group(target) if target else group
        role_scope='retry/'+context['intent_id']+'/'+group
        return (role_scope if target else normalized or role_scope),context


def retry_history(root,scope):
    normalized,_=_retry_scope(root,scope)
    with closing(_db(root)) as db:return [dict(r) for r in db.execute('SELECT * FROM logical_retries WHERE scope=? ORDER BY sequence',(normalized,))]


def _retry_stop(rows,total=4):
    if len(rows)>=total:return True
    seen=set()
    for row in rows:
        if row['category'] in {'installation','source','budget'}:return True
        if row['category'] in {'format','evidence'}:
            if row['fingerprint'] in seen:return True
            seen.add(row['fingerprint'])
    return False


def _charge_retry(db,scope,target,reason,source_key=None,kind='script'):
    if source_key:
        previous=db.execute('SELECT sequence FROM logical_retry_observations WHERE source_key=?',(source_key,)).fetchone()
        if previous:return previous['sequence'],False
    category=classify(reason);fingerprint=digest([category,str(reason)])
    cursor=db.execute('INSERT INTO logical_retries(scope,target,category,fingerprint,reason,created_at) VALUES(?,?,?,?,?,?)',
                      (scope,target,category,fingerprint,str(reason),datetime.now(timezone.utc).isoformat()))
    if source_key:db.execute('INSERT INTO logical_retry_observations VALUES(?,?,?,?)',(source_key,scope,cursor.lastrowid,kind))
    return cursor.lastrowid,True


def _reconcile_native_failures(root,native,context):
    owner=context['owner'];task=owner.rsplit('/',1)[-1]
    incomplete=[]
    agents={n['id'] for n in native.get('snapshot_definition',{}).get('nodes',[]) if n.get('node_type')=='agent'}
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for node_id,node in native.get('node_states',{}).items():
            if node_id not in agents:continue
            history={r.get('attempt_number'):r for r in node.get('attempt_history',[]) if isinstance(r,dict)}
            attempt=node.get('attempt_count',0)
            if node.get('status')=='failed' and type(attempt) is int and attempt>0:
                history.setdefault(attempt,{'attempt_number':attempt,'status':'failed','error':node.get('error','')})
            if node.get('status')=='failed':
                known={n for n,r in history.items() if type(n) is int and n>0 and r.get('status') in ('failed','completed','skipped')}
                if type(attempt) is not int or attempt<1 or len({n for n in known if n<=attempt})!=attempt:
                    incomplete.append(node_id)
            group=_logical_group(node_id);scope='retry/'+context['intent_id']+'/'+group
            db.execute('INSERT OR REPLACE INTO logical_retry_scope_aliases VALUES(?,?)',(group+'/'+task,scope))
            for number,row in history.items():
                if type(number) is not int or number<1 or row.get('status')!='failed':continue
                reason=row.get('error') or node.get('error') or 'native failed model attempt (reason unavailable)'
                sequence,charged=_charge_retry(db,scope,node_id,reason,digest([owner,node_id,number]),'native_attempt')
                if charged:store()._event(db,'native_retry_observed',{'owner':owner,'node':node_id,'attempt':number,
                    'sequence':sequence,'scope':scope,'sdk_http_retry_observation':'unknown'})
        if incomplete:store()._event(db,'native_retry_coverage_incomplete',{'owner':owner,'nodes':incomplete})
    return incomplete


def retry(root,scope,target,reason,total=4):
    category=classify(reason);fingerprint=digest([category,str(reason)])
    refresh=target=='agent_composition_review' and category=='dependency_refresh'
    if refresh:
        scope='composition-refresh/'+scope.rsplit('/',1)[-1]
    original_scope=scope;scope,context=_retry_scope(root,scope,None if refresh else target)
    native=None;source_key=None
    task=os.environ.get('TASK_ID');workflow=os.environ.get('WORKFLOW_ID');host=host_root()
    if context and task and workflow and context['owner']==workflow+'/'+task and host:
        native=_native(Path(root).resolve(),workflow,task)
        if _reconcile_native_failures(root,native,context):
            raise ValueError('RETRY_STOP: native failed attempt history is incomplete; no fresh paid retry authorized')
        attempt=native.get('node_states',{}).get(target,{}).get('attempt_count',0)
        if type(attempt) is int and attempt>0:source_key=digest([context['owner'],target,attempt])
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        before=list(db.execute('SELECT * FROM logical_retries WHERE scope=?',(scope,)))
        sequence,charged=_charge_retry(db,scope,target,reason,source_key)
        rows=list(db.execute('SELECT * FROM logical_retries WHERE scope=?',(scope,)))
        stop=(len(rows)>2 if refresh else _retry_stop(rows,total) if context else
              (category in {'installation','source','budget'} or len(before)>=total
               or category in {'format','evidence'} and any(r['fingerprint']==fingerprint for r in before)))
        db.execute('INSERT OR REPLACE INTO logical_retry_scope_aliases VALUES(?,?)',(original_scope,scope))
        store()._event(db,'retry_classified',{'scope':scope,'target':target,'category':category,'fingerprint':fingerprint,
            'stop':stop,'ordinal':len(rows),'charged':charged,'sequence':sequence})
    if stop:raise ValueError('RETRY_STOP: '+category+'：'+str(reason))
    # Native reject-upstream can jump directly to the paid agent, bypassing
    # its already-completed budget script. Refresh the same boundary here.
    if task and workflow and host:
        native_path=task_path(host,workflow,task)
        if native_path.is_file():
            native=_read(native_path)
            if any(n.get('id')==target and n.get('node_type')=='agent'
                   for n in native.get('snapshot_definition',{}).get('nodes',[])):
                request_budget(root,target)
    return category


def _budget(components,output_reserve=8192,context_limit=None):
    if type(output_reserve) is not int or output_reserve<0:
        raise ValueError('CONTEXT_BUDGET: invalid output reserve')
    if context_limit is not None and (type(context_limit) is not int or context_limit<1):
        raise ValueError('CONTEXT_BUDGET: invalid context limit')
    sizes={k:{'characters':len(v),'utf8_bytes':len(v.encode())} for k,v in components.items()}
    upper=sum(r['utf8_bytes'] for r in sizes.values())
    result={'components':sizes,'utf8_token_upper_bound':upper,'estimated_tokens':sum((len(v.encode())+1)//2 for v in components.values()),
            'estimate_method':'utf8-bytes/2 heuristic; byte bound excludes message framing and unknown host components',
            'output_reserve':output_reserve,'context_limit':context_limit,
            'usable_context_limit':None if context_limit is None else max(0,context_limit-output_reserve),
            'provider_usage':None,'coverage':'complete_supplied_components',
            'capacity_status':'unknown' if context_limit is None else 'supplied_components_fit'}
    if context_limit is not None and upper+output_reserve>context_limit:
        result['capacity_status']='over_budget'
        result['coverage_plan']={'action':'increase verified capacity or design role-specific lossless review',
            'input_truncated':False,'semantic_review_approved':False,
            'requirements':['complete manuscript and necessary rules','dependency and knowledge-boundary checks',
                            'fresh independent whole-candidate verdict; byte coverage alone is insufficient']}
    return result


def budget(components,output_reserve=8192,context_limit=None):
    result=_budget(components,output_reserve,context_limit)
    if result['capacity_status']=='over_budget':
        raise ValueError('CONTEXT_BUDGET: 保留全文与规则；已知输入超过可用上下文容量 '+str(result['usable_context_limit'])+
                         '；须扩大已核验容量或另行设计有语义覆盖证明的审查；未截断输入')
    return result


def coverage(text,max_chars):
    if type(max_chars) is not int or max_chars<1:raise ValueError('invalid segment capacity')
    raw=text.encode('utf8')
    return [{'start':i,'end':min(i+max_chars,len(text)),'text':text[i:i+max_chars],
             'source_sha256':digest(text),'source_utf8_sha256':hashlib.sha256(raw).hexdigest(),
             'semantic_review_approved':False} for i in range(0,len(text),max_chars)]


def host_root():
    configured=os.environ.get('DETERMINFLOW_PROJECT_DIR')
    candidates=([Path(configured)] if configured else [])+list(Path(__file__).resolve().parents)
    return next((p for p in candidates if (p/'data/workflows').is_dir() and (p/'src').is_dir()),None)


def task_path(host,workflow,task):
    if not re.fullmatch(r'[\w-]+',workflow) or not re.fullmatch(r'[\w-]+',task):raise ValueError('PREFLIGHT: invalid native task identity')
    return host/'data/workflows'/workflow/'tasks'/(task+'.json')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _native(root,workflow,task):
    host=host_root()
    if host is None:raise ValueError('PREFLIGHT: native runtime unavailable')
    native=_read(task_path(host,workflow,task))
    if (native.get('task_id',task)!=task or native.get('workflow_id',workflow)!=workflow
            or Path(native.get('workspace_override') or root).resolve()!=Path(root).resolve()):
        raise ValueError('PREFLIGHT: native task identity/workspace mismatch')
    return native


def reuse_profile(root, roles):
    """Bind reusable work to actual task roles and host configuration by digest."""
    task = os.environ.get('TASK_ID')
    workflow = os.environ.get('WORKFLOW_ID')
    host = host_root() if task and workflow else None
    if not host or not task_path(host, workflow, task).is_file():
        return None
    native = _native(root, workflow, task)
    nodes = {node['id']: node for node in _definition(native)['nodes']}
    if any(role not in nodes for role in roles):
        return None
    # The service resolves relative configuration from its installation root.
    # Script subprocesses run inside the book workspace.
    config = host / Path(os.environ.get('DETERMINFLOW_CONFIG_DIR') or 'config').expanduser()
    files = list(config.glob('*.json'))
    files.extend((config / 'extension-overrides').rglob('*.json'))
    model_config = host / Path(os.environ.get('DETERMINFLOW_MODELS_CONFIG_FILE') or config / 'models_config.json').expanduser()
    files.extend((host / '.env', model_config,
                  host / 'data/workflows' / workflow / '.user-models.json'))
    versions = {str(file.resolve()): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in files if file.is_file()}
    return digest({
        'roles': [nodes[role] for role in roles],
        'host_configuration': versions,
        'resources': profile(names=('agents.json', 'prompts.json', 'skills.json')),
    })


def _definition(native):
    snapshot=dict(native['snapshot_definition'])
    variables=native.get('snapshot_variables')
    if variables is not None:
        if 'variables' in snapshot and snapshot['variables']!=variables:
            raise ValueError('PREFLIGHT: native variable snapshots disagree')
        snapshot['variables']=variables
    return snapshot


def _capabilities(root):
    path=Path(root)/'meta/model_capabilities.json'
    return _read(path) if path.is_file() else {}


def _input_parameters(root,snapshot,parameters):
    """Canonicalize declared file paths without reading their file contents.

    Native scripts may replace a file default's input placeholders with the
    equivalent resolved path. Only declared immutable inputs can resolve those
    placeholders; arbitrary runtime outputs do not gain input authority.
    """
    variables={v['key']:v for v in snapshot.get('variables',[])}
    outputs={key for key,v in variables.items() if v.get('source_type')=='output'}
    outputs.update(n['output_variable'] for n in snapshot.get('nodes',[]) if n.get('output_variable'))
    inputs={key:parameters.get(key,variable.get('default')) for key,variable in variables.items()
            if key not in outputs and (key in parameters or 'default' in variable)}
    def expand(value,stack=()):
        if not isinstance(value,str):return value
        def replacement(match):
            key=match[1]
            if key not in variables or key in outputs:return match[0]
            if key in stack or len(stack)>10:raise ValueError('PREFLIGHT: cyclic/deep immutable file path reference')
            raw=inputs.get(key,variables[key].get('default',match[0]))
            resolved=expand(raw,(*stack,key))
            if isinstance(resolved,str):return resolved
            return json.dumps(resolved,ensure_ascii=False,separators=(',',':'))
        return PLACEHOLDER.sub(replacement,value)
    root=Path(root).resolve();normalized=dict(inputs)
    for key,value in inputs.items():
        if variables[key].get('type')!='file' or not isinstance(value,str):continue
        rendered=expand(value,(key,)).strip()
        if not rendered:normalized[key]='';continue
        try:path=(root/rendered).resolve()
        except (OSError,ValueError) as exc:raise ValueError('PREFLIGHT: invalid immutable file path: '+key) from exc
        normalized[key]=path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    return normalized


def _manifest(root,stage,chapter,task,workflow,native):
    snapshot=_definition(native);parameters=native.get('parameter_values',{})
    capabilities=_capabilities(root)
    manifest=check_definition(snapshot,_input_parameters(root,snapshot,parameters),capabilities,stage=stage)
    manifest.update(stage=stage,chapter=chapter,task_id=task,workflow_id=workflow,task_created_at=native['created_at'],
                    resources=profile(names=('prompts.json','agents.json','skills.json',f'workflows/{stage}/definition.json')),
                    capability_sha256=digest(capabilities),report_protocol='local-review-v2',
                    models={n['id']:n.get('model_override') for n in snapshot['nodes'] if n.get('node_type')=='agent'},
                    transport_observation='first-token/compression metrics unavailable at plugin script boundary')
    return manifest


def _retry_input_file_hashes(root,native):
    snapshot=_definition(native);variables={v['key']:v for v in snapshot.get('variables',[])}
    parameters=native.get('parameter_values',{});inputs=_input_parameters(root,snapshot,parameters)
    referenced=set(PLACEHOLDER.findall(json.dumps(snapshot.get('nodes',[]),ensure_ascii=False)))
    referenced.update((n.get('node_params') or {}).get('first_message_source_variable') for n in snapshot.get('nodes',[]))
    pending=list(referenced)
    while pending:
        key=pending.pop();variable=variables.get(key,{})
        raw=parameters.get(key,variable.get('default',''))
        for dependency in PLACEHOLDER.findall(raw if isinstance(raw,str) else ''):
            if dependency not in referenced:referenced.add(dependency);pending.append(dependency)
    root=Path(root).resolve();sources={}
    for key,value in inputs.items():
        if key not in referenced or variables[key].get('type')!='file' or not isinstance(value,str) or not value.strip():continue
        # These plugin runtime namespaces contain regenerated views/proposals,
        # not independent author sources. Author feedback is bound separately;
        # authoritative narrative/style/world rules use book_contract.resolve.
        if value.startswith(('cache/','learning/prose_policy/runtime/')):continue
        path=(root/value).resolve()
        sources[key]={'path':value,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()
                      if path.is_relative_to(root) and path.is_file() else None}
    return sources


def _retry_compatibility(root,manifest,native,state):
    values=state.get('values',{})
    feedback=values.get('author_feedback_file') or native.get('parameter_values',{}).get('author_feedback_file')
    feedback_hash=''
    for relative in dict.fromkeys([feedback,native.get('parameter_values',{}).get('author_feedback_file')]):
        if not isinstance(relative,str) or not relative:continue
        path=(Path(root)/relative).resolve()
        if path.is_relative_to(Path(root).resolve()) and path.is_file():
            feedback_hash=hashlib.sha256(path.read_bytes()).hexdigest();break
    body=Path(root)/f"story/{manifest['chapter']}/chapter.md"
    contract=load('retry_book_contract',HERE/'prose_policy/book_contract.py').resolve(root)
    return digest({'stage':manifest['stage'],'chapter':manifest['chapter'],
        'effective':{k:manifest[k] for k in ('definition_sha256','parameters_sha256','resources','capability_sha256','models')},
        'author_values':values,'mode':state.get('mode'),'feedback_sha256':feedback_hash,
        'model_preferences':{k:v for k,v in state.items() if k.lower().endswith('model') or k in ('modelOverrides','modelParams')},
        'declared_source_files':_retry_input_file_hashes(root,native),'book_rules_sha256':digest(contract),
        'source_body_sha256':hashlib.sha256(body.read_bytes()).hexdigest() if body.is_file() else ''})


def _register_retry_run(root,manifest,native):
    owner=manifest['workflow_id']+'/'+manifest['task_id'];path=Path(root)/'.novel-project.json'
    state=_read(path) if path.is_file() else {}
    compatibility=_retry_compatibility(root,manifest,native,state)
    context={'owner':owner,'intent_id':digest([owner,native['created_at']]),'stage':manifest['stage'],
             'chapter':manifest['chapter'],'compatibility':compatibility,'manifest_sha256':digest(manifest),
             'sdk_http_retry_observation':'unknown'}
    recovery=state.get('productionRetryRecovery') or {};token=recovery.get('token');inheritable=False
    if (token and state.get('autoNext') is True and state.get('autoArmed') is True
            and state.get('autoController')=='server-v1'
            and _intent_ref(state,manifest['stage'],manifest['workflow_id'],manifest['task_id'],native)):
        with closing(_db(root)) as db:
            row=db.execute('SELECT content,child_owner FROM logical_recovery_tokens WHERE token=?',(token,)).fetchone()
        inherited=json.loads(row['content']) if row else {}
        source=inherited.get('source_owner','').split('/',1)
        if (row and row['child_owner'] in (None,owner) and inherited.get('compatibility')==compatibility
                and inherited.get('stage')==manifest['stage'] and inherited.get('chapter')==manifest['chapter'] and len(source)==2):
            prior=_native(root,*source)
            source_context=_run_context(root,inherited['source_owner'])
            inheritable=(prior.get('status')=='failed' and source_context is not None
                         and source_context['intent_id']==inherited.get('intent_id')
                         and source_context['compatibility']==compatibility)
            if inheritable:context['intent_id']=source_context['intent_id']
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT content FROM logical_runs WHERE owner=?',(owner,)).fetchone()
        if previous:
            saved=json.loads(previous['content'])
            if saved!=context:raise ValueError('PREFLIGHT: logical retry run identity changed')
            return saved
        if inheritable:
            changed=db.execute('UPDATE logical_recovery_tokens SET child_owner=? WHERE token=? AND (child_owner IS NULL OR child_owner=?)',
                               (owner,token,owner)).rowcount
            if not changed:raise ValueError('LEASE: automatic retry intent already handed to another native task')
        db.execute('INSERT INTO logical_runs VALUES(?,?)',(owner,json.dumps(context,ensure_ascii=False,sort_keys=True)))
        store()._event(db,'logical_run_started',context)
    return context


def recovery_retry_context(root,state,stage,task):
    """Reconcile actual failed attempts and issue a single-child recovery proof.

    Missing legacy native/run evidence retains the existing recovery API. A
    recorded run never trusts caller-supplied attempt counts or a clock.
    """
    host=host_root();workflow=task.get('workflow_id') or os.environ.get('WORKFLOW_ID');task_id=task.get('task_id')
    if not host or not workflow or not task_id:return None
    path=task_path(host,workflow,task_id)
    if not path.is_file():return None
    owner=workflow+'/'+task_id;context=_run_context(root,owner)
    if context is None:return None
    native=_native(Path(root).resolve(),workflow,task_id)
    saved_path=Path(root)/'cache/production-runs'/task_id/'manifest.json'
    if (native.get('status')!='failed' or context['stage']!=stage or context['chapter']!=str(state.get('values',{}).get('chapter_number','0001')).zfill(4)):
        return None
    if (not saved_path.is_file() or digest(_read(saved_path)['manifest'])!=context['manifest_sha256']
            or _read(saved_path)['manifest']['task_created_at']!=native.get('created_at')):
        raise ValueError('PREFLIGHT: native retry lineage lacks matching frozen run evidence')
    incomplete=_reconcile_native_failures(root,native,context)
    with closing(_db(root)) as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM logical_retries WHERE scope LIKE ?',('retry/'+context['intent_id']+'/%',))]
    groups={r['scope'] for r in rows}
    current_manifest=_manifest(Path(root).resolve(),stage,context['chapter'],task_id,workflow,native)
    changed=_retry_compatibility(root,current_manifest,native,state)!=context['compatibility']
    exhausted=not changed and (bool(incomplete) or any(_retry_stop([r for r in rows if r['scope']==scope]) for scope in groups))
    proof={'source_owner':owner,'intent_id':context['intent_id'],'compatibility':context['compatibility'],
           'stage':stage,'chapter':context['chapter'],'sdk_http_retry_observation':'unknown'}
    token=digest(proof)
    with closing(_db(root)) as db, db:
        db.execute('INSERT OR IGNORE INTO logical_recovery_tokens VALUES(?,?,NULL)',
                   (token,json.dumps(proof,ensure_ascii=False,sort_keys=True)))
    return {**proof,'token':token,'exhausted':exhausted,'meaningful_context_changed':changed,
            'native_attempt_coverage':'incomplete' if incomplete else 'recorded_attempts_only',
            'observed_failed_attempts_and_rejections':len(rows)}


def _active(root,scope):
    with closing(_db(root)) as db:
        row=db.execute('SELECT * FROM execution_intents WHERE scope=? AND active=1',(scope,)).fetchone()
        return dict(row) if row else None


def terminal_native_task(root,workflow,task):
    """Read a terminal task only when its native record belongs to this workspace."""
    host=host_root()
    if host is None:return None
    path=task_path(host,workflow,task)
    if not path.is_file():return None
    prior=_read(path)
    if (prior.get('status') not in TERMINAL or not prior.get('workspace_override')
            or Path(prior['workspace_override']).resolve()!=Path(root).resolve()
            or prior.get('workflow_id',workflow)!=workflow or prior.get('task_id',task)!=task):return None
    saved=Path(root)/'cache/production-runs'/task/'manifest.json'
    if saved.is_file() and _read(saved)['manifest']['task_created_at']!=prior.get('created_at'):return None
    return prior


def _terminal_owner(root,lease):
    """Only an authoritative native owner in this workspace permits release."""
    parts=lease['owner'].split('/',1)
    if len(parts)!=2 or terminal_native_task(root,*parts) is None:return False
    return release(root,lease)


def reserve_launch(root,state,stage):
    """Reserve before native Task creation; caller must durably save mutated state.

    production.launch_check calls this only after all checks succeed. The host
    saves productionLaunchLease alongside autoPending before create_task. A
    failed/uncertain create MUST retain this token until native reconciliation;
    a clock, pause, missing Task, or exception is never proof of no creation.
    """
    if not (state.get('autoNext') is True and state.get('autoArmed') is True
            and state.get('autoController')=='server-v1'):return None
    chapter=str(state.get('values',{}).get('chapter_number','0001')).zfill(4)
    if not re.fullmatch(r'[0-9]{4}',chapter) or chapter=='0000':raise ValueError('PREFLIGHT: invalid chapter')
    scope='book/manuscript';old=_active(root,scope)
    token=state.get('productionLaunchLease') or {}
    identity={'stage':stage,'chapter':chapter,'values_sha256':digest(state.get('values',{})),
              'checkpoint_sha256':digest(state.get('automaticCheckpoint'))}
    context=state.get('productionLaunchContext') or {}
    if old and old==token.get('lease') and token.get('stage')==stage and token.get('chapter')==chapter:
        if old['identity']!=digest(identity):raise ValueError('LEASE: 已保留启动意图的输入已有变化')
        with closing(_db(root)) as db:
            row=db.execute('SELECT content FROM launch_reservations WHERE owner=?',(old['owner'],)).fetchone()
        previous=json.loads(row['content']) if row else {}
        if (previous.get('parameters') is not None and 'effective_parameters' in context
                and context['effective_parameters']!=previous['parameters']):
            raise ValueError('LEASE: 已保留启动意图的完整参数已有变化')
        return verify_claim(root,old)
    if old:_terminal_owner(root,old)
    reservation={'identity':identity,'stage':stage,'chapter':chapter,
                 'parameters':context.get('effective_parameters'),'workflow_id':context.get('workflow_id')}
    lease=claim(root,scope,'intent:'+uuid4().hex,identity,reservation=reservation)
    state['productionLaunchLease']={'stage':stage,'chapter':chapter,'lease':lease}
    return lease


def _intent_ref(state,stage,workflow,task,native):
    intent=state.get('autoPending') or {};ref=state.get('refs',{}).get(stage) or {}
    linked=(ref.get('workflow_id')==workflow and ref.get('task_id')==task)
    linked=linked or (intent.get('stage')==stage and intent.get('workflow_id')==workflow and intent.get('task_id')==task)
    if not linked:return False
    if intent:
        if intent.get('stage')!=stage or intent.get('workflow_id')!=workflow:return False
        if task in intent.get('before_task_ids',[]):return False
        if any(native.get('parameter_values',{}).get(k)!=v for k,v in intent.get('parameters',{}).items()):return False
    return True


def _handoff(root,stage,chapter,workflow,task,native,manifest):
    state_path=Path(root)/'.novel-project.json'
    state=_read(state_path) if state_path.is_file() else {}
    token=state.get('productionLaunchLease') or {};lease=token.get('lease')
    restored=False
    if not lease:
        # A crash between reservation commit and host state save must not
        # authorize a fresh launch. An already durable native Task ref and the
        # exact request stored in that reservation can, however, prove handoff.
        old=_active(root,'book/manuscript')
        if old and old['owner'].startswith('intent:'):
            with closing(_db(root)) as db:
                row=db.execute('SELECT content FROM launch_reservations WHERE owner=?',(old['owner'],)).fetchone()
            reservation=json.loads(row['content']) if row else {}
            identity={'stage':stage,'chapter':chapter,'values_sha256':digest(state.get('values',{})),
                      'checkpoint_sha256':digest(state.get('automaticCheckpoint'))}
            parameters=reservation.get('parameters')
            if (reservation.get('identity')==identity and old['identity']==digest(identity)
                    and reservation.get('workflow_id')==workflow and isinstance(parameters,dict)
                    and _intent_ref(state,stage,workflow,task,native)
                    and all(native.get('parameter_values',{}).get(k)==v for k,v in parameters.items())):
                token={'stage':stage,'chapter':chapter,'lease':old};lease=old;restored=True
    if (not lease or token.get('stage')!=stage or token.get('chapter')!=chapter
            or not _intent_ref(state,stage,workflow,task,native)):
        raise ValueError('LEASE: 创建前意图尚无持久任务归属证明，未交接执行')
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM execution_intents WHERE scope=?',(lease['scope'],)).fetchone()
        if not row or dict(row)!=lease or not row['active'] or not row['owner'].startswith('intent:'):
            raise ValueError('LEASE: 创建前意图所有者或代次已变化')
        db.execute('UPDATE execution_intents SET owner=?,epoch=epoch+1,identity=? WHERE scope=?',
                   (workflow+'/'+task,digest(manifest),lease['scope']))
        current=dict(db.execute('SELECT * FROM execution_intents WHERE scope=?',(lease['scope'],)).fetchone())
        store()._event(db,'execution_handoff',{'scope':lease['scope'],'intent_owner':lease['owner'],
                                              'owner':current['owner'],'epoch':current['epoch'],'restored_missing_token':restored})
        return current


def release_launch(root,state,stage):
    """Reconcile a terminal native ref; keep every unproven create intent."""
    token=state.get('productionLaunchLease') or {}
    if token.get('stage')!=stage:return False
    lease=token.get('lease');ref=state.get('refs',{}).get(stage) or {}
    intent=state.get('autoPending') or {}
    if not ref and intent.get('stage')==stage:
        ref={k:intent.get(k) for k in ('workflow_id','task_id')}
    if not lease or not ref.get('workflow_id') or not ref.get('task_id'):return False
    native=terminal_native_task(root,ref['workflow_id'],ref['task_id'])
    if not native or not _intent_ref(state,stage,ref['workflow_id'],ref['task_id'],native):return False
    current=_active(root,lease['scope'])
    if current==lease:return release(root,lease)
    if current and current['owner']==ref['workflow_id']+'/'+ref['task_id']:return _terminal_owner(root,current)
    return False


def _finish(root,saved):
    lease=saved['lease'];receipt={'task_id':saved['manifest']['task_id'],'workflow_id':saved['manifest']['workflow_id'],
                                'manifest_sha256':digest(saved['manifest']),'epoch':lease['epoch']}
    with closing(_db(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM execution_intents WHERE scope=?',(lease['scope'],)).fetchone()
        if not row or any(row[k]!=v for k,v in lease.items() if k!='active'):
            raise ValueError('LEASE: 完成时执行所有者或代次已变化')
        if not row['active']:
            events=db.execute("SELECT data FROM run_events WHERE kind='execution_complete'")
            if not any(json.loads(r['data'])==receipt for r in events):raise ValueError('LEASE: 已释放执行缺少本次完成凭据')
            return
        db.execute('UPDATE execution_intents SET active=0 WHERE scope=?',(lease['scope'],))
        store()._event(db,'execution_complete',receipt)


def run(root,stage,chapter,task,workflow,finish=False):
    root=Path(root).resolve();native=_native(root,workflow,task)
    manifest=_manifest(root,stage,chapter,task,workflow,native)
    owner=workflow+'/'+task;scope='book/manuscript'
    path=root/'cache/production-runs'/task/'manifest.json'
    if path.is_file():
        saved=_read(path)
        if saved['manifest']!=manifest:raise ValueError('PREFLIGHT: frozen effective inputs/resources changed')
        if finish:_finish(root,saved)
        else:verify_claim(root,saved['lease'])
        return saved
    if finish:raise ValueError('PREFLIGHT: completion lacks frozen execution manifest')
    old=_active(root,scope)
    if old and old['owner']!=owner:
        if old['owner'].startswith('intent:'):
            lease=_handoff(root,stage,chapter,workflow,task,native,manifest)
        else:
            _terminal_owner(root,old)
            lease=claim(root,scope,owner,manifest)
    else:lease=claim(root,scope,owner,manifest)
    record={'manifest':manifest,'lease':lease,'retry_context':_register_retry_run(root,manifest,native)}
    store().atomic(root,path.relative_to(root).as_posix(),json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return record


def _owned_entry(entries,key):
    """Prefer the effective identity; bridge source/prepared owner aliases."""
    prefix='xs2-novel-flywheel-'
    local=key.removeprefix(prefix)
    for candidate in dict.fromkeys((key,local,prefix+local)):
        if candidate in entries:return candidate,entries[candidate]
    return key,{}


def request_budget(root,node_id):
    """Inspect the actual task's next role input, including complete file values.

    Provider tokenizers and server-side compression are not available here.
    An explicit book capability may impose a conservative fail-closed limit.
    """
    root=Path(root).resolve();task=os.environ['TASK_ID'];workflow=os.environ['WORKFLOW_ID']
    assert_current(root)
    native=_native(root,workflow,task);definition=_definition(native)
    node=next((n for n in definition['nodes'] if n['id']==node_id),None)
    if not node or node.get('node_type')!='agent':raise ValueError('PREFLIGHT: budget target is not a native agent')
    retry_context=_run_context(root,workflow+'/'+task)
    if retry_context:
        if _reconcile_native_failures(root,native,retry_context):
            raise ValueError('RETRY_STOP: native failed attempt history is incomplete before paid call')
        retry_scope='retry/'+retry_context['intent_id']+'/'+_logical_group(node_id)
        with closing(_db(root)) as db:
            prior=list(db.execute('SELECT * FROM logical_retries WHERE scope=?',(retry_scope,)))
        if _retry_stop(prior):raise ValueError('RETRY_STOP: logical role-group failure budget exhausted before paid call')
    values=dict(native.get('parameter_values',{}));variables={v['key']:v for v in definition.get('variables',[])}
    parts={};missing=set();unknown=set();files={};optional_missing=[];errors=[];resolved={}
    def text(value):
        if value is None:return ''
        return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'))
    def value_for(key,stack=()):
        if key in resolved:return resolved[key]
        if key in stack or len(stack)>10:
            errors.append('cyclic/deep variable reference '+key);return '{{'+key+'}}'
        variable=variables.get(key,{})
        if key not in values:
            if key in BUILTINS:
                unknown.add('host_builtin:'+key);return '{{'+key+'}}'
            if 'default' not in variable:
                missing.add(key);return '{{'+key+'}}'
        raw=text(values.get(key,variable.get('default','')))
        expanded=PLACEHOLDER.sub(lambda match:value_for(match[1],(*stack,key)),raw)
        if variable.get('type')=='file':
            requested=expanded.strip()
            if not requested:
                if variable.get('required'):errors.append('required file variable is empty: '+key)
                expanded=''
            else:
                path=(root/requested).resolve()
                if not path.is_relative_to(root):raise ValueError('PREFLIGHT: file variable escapes workspace: '+key)
                if path.is_file():
                    raw_bytes=path.read_bytes()
                    # UTF-8 decoding is lossless, including BOM and CRLF; no slicing.
                    expanded=raw_bytes.decode('utf8')
                    files[key]={'path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(raw_bytes).hexdigest(),
                                'utf8_bytes':len(raw_bytes),'characters':len(expanded)}
                else:
                    expanded=''
                    if variable.get('required'):errors.append('required input file missing: '+key)
                    else:optional_missing.append(key)
        resolved[key]=expanded
        return expanded
    def expand(value):return PLACEHOLDER.sub(lambda match:value_for(match[1]),text(value))
    params=node.get('node_params') or {}
    message=node.get('first_message','')
    source=params.get('first_message_source_variable')
    if source and source in values and text(values[source]).strip():message='{{'+source+'}}'
    parts['message']=expand(message)
    agents=_read(resource(HERE,'agents.json')).get('agents',{})
    agent_key,agent=_owned_entry(agents,expand(node.get('agent_type','default')))
    if not agent:unknown.add('host_agent_definition:'+agent_key)
    template=agent.get('prompt_template',agent_key)
    prompts=_read(resource(HERE,'prompts.json'))
    template,prompt=_owned_entry(prompts.get('agents',{}),template)
    sections=prompt.get('sections',[])
    if not sections:unknown.add('host_prompt_template:'+template)
    append=expand(agent.get('system_prompt_template',''))+expand(node.get('system_prompt_template',''))
    base='\n'.join(text(r.get('content','')) for r in sections if r.get('enabled',True))
    if '{{custom_append}}' in base:base=base.replace('{{custom_append}}',append)
    else:base+='\n'+append
    # Base prompt system variables come from the host PromptBuilder, rather
    # than the workflow variable pool. Keep them visible as unknown components.
    unknown.update('host_system_variable:'+key for key in PLACEHOLDER.findall(base))
    parts['system_prompt']=base
    parts['schema']=expand(json.dumps(params.get('json_output_schema',{}),ensure_ascii=False))
    parts['tool_definitions']=json.dumps({'agent_tools':agent.get('tools'),
        'disallowed_tools':agent.get('disallowed_tools'),'node_tools':params.get('tools'),
        'declared_tool_definitions':params.get('tool_definitions',[])},ensure_ascii=False)
    model=expand(node.get('model_override') or agent.get('model',''))
    caps=_capabilities(root).get(model,{})
    effective_params=dict(agent.get('model_params') or {})
    effective_params.update(params.get('_model_params_override') or params.get('model_params') or {})
    parts['model_request_parameters']=expand(json.dumps(effective_params,ensure_ascii=False))
    reserve=caps.get('output_reserve',8192)
    # Never reserve less than an explicitly requested output capacity.
    requested=[effective_params.get(k) for k in ('max_tokens','max_completion_tokens','max_output_tokens')]
    if type(reserve) is int:reserve=max([reserve]+[v for v in requested if type(v) is int and v>0])
    result=_budget(parts,context_limit=caps.get('context_limit'),output_reserve=reserve)
    unknown.update(['host_tool_definitions','host_effective_system_overrides','host_history_and_message_framing',
                    'provider_tokenizer','provider_compression','host_model_route_and_default_parameters'])
    result.update(node_id=node_id,unresolved_variables=sorted(missing),model=model,
                  resource_resolution={'agent_key':agent_key,'prompt_template_key':template},
                  input_files=files,optional_missing_files=sorted(set(optional_missing)),input_errors=errors,
                  unknown_components=sorted(unknown),coverage='complete_known_referenced_components',
                  exact_request_observed=False,context_limit_source='book_declared' if 'context_limit' in caps else 'unknown')
    result['input_sha256'] = digest(parts)
    if result['capacity_status']=='supplied_components_fit':result['capacity_status']='known_components_fit_full_request_unknown'
    relative=f'cache/production-runs/{task}/budgets/{node_id}.json'
    store().atomic(root,relative,json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    store().event(root,'request_budget',{'task_id':task,'node_id':node_id,'budget':result})
    if errors or missing:raise ValueError('PREFLIGHT: incomplete request inputs: '+','.join(errors+sorted(missing)))
    if result['capacity_status']=='over_budget':
        raise ValueError('CONTEXT_BUDGET: 已知完整输入超过可用上下文容量 '+str(result['usable_context_limit'])+
                         '；保留全文与规则，详见 '+relative+'；未截断输入')
    return result


def assert_current(root,db=None):
    """Fence native publication; offline library callers retain their old API."""
    task=os.environ.get('TASK_ID');workflow=os.environ.get('WORKFLOW_ID')
    if not task or not workflow:return
    path=Path(root)/'cache/production-runs'/task/'manifest.json'
    if not path.is_file():
        host=host_root();native_path=task_path(host,workflow,task) if host else None
        native=json.loads(native_path.read_text(encoding='utf-8-sig')) if native_path and native_path.is_file() else {}
        if not any(n.get('id')=='script_production_start' for n in native.get('snapshot_definition',{}).get('nodes',[])):return
        raise ValueError('PREFLIGHT: native publication lacks frozen execution manifest')
    saved=_read(path);verify_claim(root,saved['lease'],db=db)
    if saved['lease']['owner']!=workflow+'/'+task:raise ValueError('LEASE: publication native owner mismatch')
    native=_native(Path(root).resolve(),workflow,task);manifest=saved['manifest']
    current=_manifest(Path(root).resolve(),manifest['stage'],manifest['chapter'],task,workflow,native)
    if current!=manifest:
        raise ValueError('PREFLIGHT: effective inputs/resources changed, checkpoint revalidation required')
    return {'lease':saved['lease'],'manifest_sha256':digest(manifest),
            'task_id':task,'workflow_id':workflow}


def _verify_publication(root,proof,db):
    """Verify persisted ownership under the caller's existing write lock.

    Replay must use the original proof, even when invoked by another task or
    outside a native process. Completed historical receipts are read-only and
    do not call this function.
    """
    verify_claim(root,proof['lease'],db=db)
    task=proof['task_id'];workflow=proof['workflow_id']
    saved=_read(Path(root)/'cache/production-runs'/task/'manifest.json')
    manifest=saved['manifest']
    if (saved['lease']!=proof['lease'] or digest(manifest)!=proof['manifest_sha256']
            or proof['lease']['owner']!=workflow+'/'+task):
        raise ValueError('LEASE: 持久发布凭据与原执行所有者不一致')
    native=_native(Path(root).resolve(),workflow,task)
    if _manifest(Path(root).resolve(),manifest['stage'],manifest['chapter'],task,workflow,native)!=manifest:
        raise ValueError('PREFLIGHT: pending publication effective inputs/resources changed')
    return proof


@contextmanager
def publication(root,db=None,proof=None):
    """Keep the lease fence and canonical mutation in one SQLite write lock.

    Callers with an existing archive transaction pass its connection. No nested
    writer connection is opened. The yielded proof belongs in durable intents.
    """
    if db is not None:
        if not db.in_transaction:raise ValueError('LEASE: publication requires an active write transaction')
        current=_verify_publication(root,proof,db) if proof else assert_current(root,db=db)
        yield current
        return
    with closing(_db(root)) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        current=_verify_publication(root,proof,connection) if proof else assert_current(root,db=connection)
        yield current


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('start','finish','budget'));p.add_argument('--stage',required=True);p.add_argument('--chapter',default='0001');p.add_argument('--node')
    args=p.parse_args()
    if args.command=='budget':request_budget(Path.cwd(),args.node)
    else:run(Path.cwd(),args.stage,args.chapter,os.environ['TASK_ID'],os.environ['WORKFLOW_ID'],args.command=='finish')
    print('Plugin production preflight complete')


if __name__=='__main__':main()
