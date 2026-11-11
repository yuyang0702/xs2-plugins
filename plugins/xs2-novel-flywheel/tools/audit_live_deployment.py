"""Read-only deployment inventory; never runs a model, workflow or upgrade.

Compare source, installed checkout, prepared resources and the running API.
Artifacts contain local configuration evidence. Human stdout is compact and
never includes provider credentials. Existing Tasks/Runs and books are hashed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import quote

OWNER='xs2-novel-flywheel'
SOURCE=Path(__file__).resolve().parents[1]

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def manifest(root):return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
def request(url):
    with urlopen(url,timeout=30) as response:return json.load(response)

def workflow_gaps(expected,current):
    """Identify missing runtime behavior while allowing author models/UI edits."""
    issues=[];actual={n['id']:n for n in current.get('nodes',[])}
    for node in expected.get('nodes',[]):
        id=node['id'];local=actual.get(id)
        if local is None:issues.append('missing_node:'+id);continue
        # max_reject_count is a legacy-only field removed by host serialization.
        # The live scheduler consumes the responsible node's auto_retry_count.
        for key in ('node_type','agent_type','output_variable','output_file_path','enable_reject_upstream','auto_retry_count','fail_auto_skip'):
            if key in node and local.get(key)!=node[key]:issues.append('node_field:'+id+':'+key)
        for key in ('script_source','script_group','script_name','script_type','script_argv','script_stdin_variable','json_output_schema'):
            if key in node.get('node_params',{}) and local.get('node_params',{}).get(key)!=node['node_params'][key]:issues.append('node_param:'+id+':'+key)
        required=set(re.findall(r'\{\{([\w_]+)\}\}',node.get('first_message','')))-{'recommendations_file'}
        supplied=set(re.findall(r'\{\{([\w_]+)\}\}',local.get('first_message','')))
        issues.extend('missing_input:'+id+':'+key for key in sorted(required-supplied))
    keys={v['key'] for v in current.get('variables',[])}
    issues.extend('missing_variable:'+v['key'] for v in expected.get('variables',[]) if v['key'] not in keys and v['key']!='recommendations_file')
    return issues

def prompt_gaps(expected,current):
    actual={s['name']:s for s in current.get('sections',[])}
    return {'missing_sections':[s['name'] for s in expected.get('sections',[]) if s['name'] not in actual],
        'changed_sections':[s['name'] for s in expected.get('sections',[]) if s['name'] in actual and s.get('content','')!=actual[s['name']].get('content','')]}

def collect(host,out,url):
    out.mkdir(parents=True,exist_ok=True)
    protected={}
    for root in (host/'data/workspaces',Path('C:/xs2/data/verification/20261108-local-revision-v1/cases'),Path('C:/xs2/data/verification/20261108-longrun-100k/book')):
        if root.is_dir():protected[str(root)]=manifest(root)
    records={}
    for root in sorted((host/'data/workflows').iterdir()):
        if root.is_dir():
            for folder in ('tasks','runs'):
                for p in (root/folder).rglob('*'):
                    if p.is_file():records[p.relative_to(host).as_posix()]=sha(p)
    models={str(p.relative_to(host)):sha(p) for p in [host/'.env',*sorted((host/'config').glob('*.json')),*sorted((host/'data/workflows').glob('*/.user-models.json'))] if p.is_file()}
    save(out/'protected.json',{'workspaces':protected,'task_records':records,'model_config_hashes':models})
    endpoints={'extensions':'/api/extensions','plugins':'/api/plugins','workflows':'/api/workflows',
        'agents':'/api/agent-definitions/config','templates':'/api/prompt-templates','scripts':'/api/workflows/script-library/scripts','novel-resources':'/api/novel-console/resources'}
    responses={}
    def fetch(item):
        key,path=item
        try:return key,request(url+path)
        except Exception as exc:return key,{'error':type(exc).__name__+': '+str(exc)}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for key,value in pool.map(fetch,endpoints.items()):
            responses[key]=value;save(out/'live'/f'{key}.json',value)
    workflows=responses['workflows']
    if not isinstance(workflows,list):raise ValueError('Live workflow inventory unavailable')
    with ThreadPoolExecutor(max_workers=5) as pool:
        for key,value in pool.map(fetch,[(w['workflow_id'],'/api/workflows/'+quote(w['workflow_id'],safe='')) for w in workflows]):
            save(out/'live/workflows'/f'{key}.json',value)
    templates=responses['templates'].get('templates',[])
    with ThreadPoolExecutor(max_workers=5) as pool:
        for key,value in pool.map(fetch,[(t,'/api/prompt-sections/config?prompt_type='+quote(t,safe='')) for t in templates if t.startswith(OWNER+'-')]):
            save(out/'live/prompts'/f'{key}.json',value)
    lock=read(host/'data/plugins/plugins.lock.json');record=lock['plugins'][OWNER]['active_revision'];checkout=host/'data/plugins'/record['checkout']
    resources=[p for folder in ('resources','runtime') for p in (SOURCE/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')]
    mismatches=[p.relative_to(SOURCE).as_posix() for p in resources if not (checkout/p.relative_to(SOURCE)).is_file() or sha(p)!=sha(checkout/p.relative_to(SOURCE))]
    workflow_status=[]
    for source in sorted((SOURCE/'resources/workflows').glob('*/definition.json')):
        id=OWNER+'-'+source.parent.name;target=host/'data/workflows'/id
        marker=read(target/'.extension.json') if (target/'.extension.json').is_file() else {}
        prepared=host/'data/plugins/runtime-resources'/OWNER/'workflows/0'/id/'definition.json'
        live_path=out/'live/workflows'/f'{id}.json';live=read(live_path).get('definition',{}) if live_path.is_file() else {}
        workflow_status.append({'id':id,'deployed':(target/'definition.json').is_file(),'conflicts':marker.get('conflicts',[]),
            'live_nodes':next((w['node_count'] for w in workflows if w['workflow_id']==id),None),'source_nodes':len(read(source)['nodes']),
            'source_sha256':sha(source),'deployed_sha256':sha(target/'definition.json') if (target/'definition.json').is_file() else None,
            'runtime_gaps':workflow_gaps(read(prepared),live) if prepared.is_file() else ['prepared_source_unavailable']})
    prompt_status=[]
    expected_prompts=read(SOURCE/'resources/prompts.json')['agents']
    for local_id,expected in expected_prompts.items():
        id=OWNER+'-'+local_id;p=out/'live/prompts'/f'{id}.json'
        effective=read(p).get('config',{}) if p.is_file() else {}
        gaps=prompt_gaps(expected,effective)
        if any(gaps.values()):prompt_status.append({'agent':id,**gaps})
    scripts=responses['scripts'];script_status=[]
    def script_fetch(item):
        id=item['group']+'--'+item['name'];kind=item.get('script_type','python')
        path='/api/workflows/script-library/'+quote(item['group'],safe='')+'/'+quote(item['name'],safe='')+'/script?type='+kind
        key,value=fetch((id,path));raw_group=item['group'].removeprefix(OWNER+'-')
        source=SOURCE/'resources/script-library'/raw_group/item['name']/(item['name']+('.py' if kind=='python' else '.sh'))
        matches=source.is_file() and value.get('exists') is True and value.get('content')==source.read_text(encoding='utf8')
        return {'id':key,'source_exists':source.is_file(),'matches':matches,'error':value.get('error','')}
    with ThreadPoolExecutor(max_workers=5) as pool:
        script_status=list(pool.map(script_fetch,[s for s in scripts if s.get('owner')==OWNER])) if isinstance(scripts,list) else []
    save(out/'script-status.json',script_status)
    if not script_status:raise ValueError('No live plugin script inspected; script API may be unavailable')
    override_status={}
    for p in (host/'config/extension-overrides').glob('*.json'):
        data=read(p).get('extensions',{}).get(OWNER,{})
        override_status[p.name]={section:list(values) if isinstance(values,dict) else values for section,values in data.get('values',{}).items()}
        if data:save(out/'overrides'/p.name,read(p))
    result={'source':str(SOURCE),'installed_revision':record['content_sha256'],'checkout':str(checkout),'resource_files_checked':len(resources),
        'checkout_mismatches':mismatches,'workflows':workflow_status,'overrides':override_status,
        'prompt_gaps':prompt_status,'script_entries_checked':len(script_status),'script_entry_mismatches':[s for s in script_status if not s['matches']],
        'task_record_files':len(records),'protected_workspace_files':sum(map(len,protected.values())),
        'running_workflows':[{k:w[k] for k in ('workflow_id','running_tasks')} for w in workflows if w.get('running_tasks')],
        'enabled_extensions':responses['extensions'].get('enabled',[]),'plugins_restart_required':responses['plugins'].get('restart_required')}
    save(out/'inventory.json',result)
    print(json.dumps({k:result[k] for k in ('installed_revision','checkout_mismatches','task_record_files','protected_workspace_files',
        'running_workflows','enabled_extensions','plugins_restart_required','script_entries_checked','script_entry_mismatches')}
        |{'workflows_with_gaps':[w['id'] for w in workflow_status if w['runtime_gaps']],
          'prompts_with_gaps':[w['agent'] for w in prompt_status]},ensure_ascii=False))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host',default='C:/xs2/DeterminFlow');p.add_argument('--output',required=True);p.add_argument('--url',default='http://127.0.0.1:8020')
    a=p.parse_args();collect(Path(a.host),Path(a.output),a.url.rstrip('/'))
