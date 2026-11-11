"""Independent long-run report and audit-input Script Library entry."""
import argparse
import importlib.util
import json
from pathlib import Path

def load(name):
    spec=importlib.util.spec_from_file_location('longrun_independent_'+name,Path(__file__).with_name(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','prepare-audit'])
    parser.add_argument('--chapter',default='0001');args=parser.parse_args();root=Path.cwd()
    log=load('ledger');log.recover_controller(root)
    result=log.report(root) if args.action=='status' else load('audits').prepare(root,args.chapter)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
