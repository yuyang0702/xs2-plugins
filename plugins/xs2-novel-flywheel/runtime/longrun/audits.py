"""Host-side independent audit orchestration shipped inside the plugin."""
import importlib.util
import json
from pathlib import Path

def load(name):
    library=Path(__file__).resolve().parents[2]/'resources/script-library/xs2/longrun'
    file=library/('audits.py' if name=='sources' else 'ledger.py') if name in ('sources','ledger') else Path(__file__).with_name(name+'.py')
    spec=importlib.util.spec_from_file_location('longrun_runtime_audit_'+name,file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

async def perform(root,chapter,model):
    log=load('ledger');s=log.support();packet=load('sources').prepare(root,chapter)
    folder=f"observability/audits/{chapter}/{packet['body_sha256'][:16]}"
    previous=s.load(root,folder+'/result.json')
    old=s.load(root,folder+'/request.json')
    if previous and old:
        try:
            log.accept_audit(root,old,previous)
            return previous
        except ValueError:pass
    s.write(root,folder+'/request.json',packet)
    error=''
    from src.workflow.output_selection import _json_document
    transport=load('transport')
    for attempt in range(3):
        text=await transport.request(root,model,load('sources').SYSTEM,json.dumps(packet,ensure_ascii=False)+error,
            {'stage':'longrun-audit','chapter':chapter,'node_id':'independent_audit','attempt':attempt+1})
        s.write(root,folder+f'/response-{attempt+1}.txt',text)
        try:
            result=_json_document(text)
            if {c['dimension'] for c in result.get('checks',[])}!=log.DIMENSIONS:raise ValueError('checks没有完整覆盖三个维度')
            for probe in result.get('probes',[]):
                if not isinstance(probe,dict) or not isinstance(probe.get('query'),str) or not probe['query'].strip() or probe.get('source_id') not in packet['sources'] or not isinstance(probe.get('quote'),str) or len(probe['quote'])<2 or probe['quote'] not in packet['sources'][probe['source_id']]:
                    raise ValueError('检索探针缺少可核对来源')
            log.accept_audit(root,packet,result)
            s.write(root,folder+'/result.json',result)
            oldprobes=s.load(root,'observability/reference-probes.json',[])
            for probe in result.get('probes',[])[:3]:
                value={**probe,'source_sha256':s.digest(root,probe['source_id']),'created_chapter':chapter}
                if not any(log.identity(v)==log.identity(value) for v in oldprobes):oldprobes.append(value)
            s.write(root,'observability/reference-probes.json',oldprobes)
            return result
        except (ValueError,TypeError,KeyError) as exc:
            error='\n上一份输出未通过格式/证据检查，请修正：'+str(exc)
    raise ValueError('独立长跑审查连续三次未能提交有效证据')
