"""Entry point for the plugin-owned long-run acceptance library."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys


def load(name):
    file=Path(__file__).resolve().parents[2]/'resources/script-library/xs2/longrun/ledger.py' if name=='ledger' else Path(__file__).with_name(name+'.py')
    spec=importlib.util.spec_from_file_location('longrun_runtime_'+name,file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','run'])
    parser.add_argument('--host-root',type=Path);parser.add_argument('--resources',type=Path)
    args=parser.parse_args();root=Path.cwd()
    host=args.host_root
    if host is None:
        host=next((p for p in [Path(sys.prefix).parent,*Path(__file__).resolve().parents]
                   if (p/'src/config.py').is_file()),None)
    if host is not None:
        host=host.resolve();sys.path.insert(0,str(host))
        os.environ['DETERMINFLOW_CONFIG_DIR']=str(host/'config')
        os.environ['DETERMINFLOW_DATA_DIR']=str(root/'observability/runtime-data')
        os.environ['DETERMINFLOW_LOGS_DIR']=str(root/'observability/logs')
    if args.action=='status':print(json.dumps(load('ledger').report(root),ensure_ascii=False,indent=2))
    else:
        if host is None or not args.resources:parser.error('run requires --host-root and --resources')
        result=asyncio.run(load('driver').run(root,args.resources,host))
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
