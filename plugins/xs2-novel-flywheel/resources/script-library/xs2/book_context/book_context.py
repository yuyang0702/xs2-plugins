"""Prepare the shared book contract before an adviser has chapters to read."""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def project_constraints(root,book):
    path=book.safe(root,'.novel-project.json');state=book.read(path) if path.is_file() else {};values=state.get('values',{})
    return {'mode':state.get('mode',''),'target_word_count':str(values.get('target_word_count') or ''),
            'conflict_plan_mode':str(values.get('conflict_plan_mode') or '')}


def constraint_prompt(request):
    return ('【作者本次篇幅与作品形态】\n'+json.dumps(request,ensure_ascii=False,indent=2)+
        '\n明确的目标篇幅与短篇/连载范围约束本次建议。不得自行扩大作者上限或把完整短篇规划成连载；'
        '容量不足时先建议取舍主线与场景。未指定时可提出供作者选择的范围，不以题材自动决定篇幅。\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','commit'])
    for key in ('premise','genre','narrative-pov','narrator-scope','style-intent'):parser.add_argument('--'+key,default='')
    parser.add_argument('--target',default=None);parser.add_argument('--scope',default='')
    args=parser.parse_args();root=Path.cwd()
    spec=importlib.util.spec_from_file_location('advisor_book_contract',Path(__file__).resolve().parents[1]/'prose_policy/book_contract.py')
    book=importlib.util.module_from_spec(spec);spec.loader.exec_module(book)
    project={'values':{key:getattr(args,key) for key in ('premise','genre','narrative_pov','narrator_scope','style_intent') if getattr(args,key).strip()}}
    task_id=os.environ.get('TASK_ID','')
    # freeze validates the task identifier before any task-relative path is used.
    if args.action=='prepare':
        frozen=book.freeze(root,task_id,project=project)
        binding={'project':project,'base_sha256':book.digest(book.resolve(root)),
                 'effective_sha256':frozen['sha256'],'base_constraints':project_constraints(root,book)}
        binding['request_constraints']={**binding['base_constraints'],
            'target_word_count':args.target.strip() if args.target and args.target.strip() else binding['base_constraints']['target_word_count'],
            'conflict_plan_mode':args.scope or binding['base_constraints']['conflict_plan_mode']}
        path=book.safe(root,f'cache/book-contract/{task_id}/advisor-binding.json')
        if path.exists() and book.read(path)!=binding:raise ValueError('本书顾问输入已有变化，请新建任务')
        path.write_text(json.dumps(binding,ensure_ascii=False),encoding='utf8')
        constraints_path=book.safe(root,f'cache/book-contract/{task_id}/constraints.md');text=constraint_prompt(binding['request_constraints'])
        if constraints_path.exists() and constraints_path.read_text(encoding='utf8')!=text:raise ValueError('冻结顾问目标已有变化')
        constraints_path.write_text(text,encoding='utf8')
        print('<WF_VAR>advisor_constraints_file:'+f'cache/book-contract/{task_id}/constraints.md</WF_VAR>')
        print('<WF_VAR>advisor_draft_path:'+f'cache/book-contract/{task_id}/advisor-report.json</WF_VAR>')
    else:
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',task_id):raise ValueError('缺少有效顾问任务编号')
        binding=book.read(book.safe(root,f'cache/book-contract/{task_id}/advisor-binding.json'))
        if (project_constraints(root,book)!=binding['base_constraints'] or
                book.safe(root,f'cache/book-contract/{task_id}/constraints.md').read_text(encoding='utf8')!=constraint_prompt(binding['request_constraints'])):
            raise ValueError('作者篇幅或作品形态在顾问分析期间变化，旧建议未发布')
        current=book.digest(book.resolve(root,project=binding['project']));base=book.digest(book.resolve(root))
        if current!=binding['effective_sha256'] or (base!=binding['base_sha256'] and base!=current):
            raise ValueError('本书世界或文风在顾问分析期间变化，旧建议未发布')
        frozen=book.freeze(root,task_id,project=binding['project'])
        report=book.read(book.safe(root,f'cache/book-contract/{task_id}/advisor-report.json'))
        if not isinstance(report,dict) or not report or json.loads(sys.stdin.read())!=report:
            raise ValueError('顾问草稿与本任务实际模型输出不一致')
        spec=importlib.util.spec_from_file_location('advisor_atomic',Path(__file__).resolve().parents[1]/'console_service/length_quality.py')
        quality=importlib.util.module_from_spec(spec);spec.loader.exec_module(quality)
        quality.atomic_text(book.safe(root,'learning/advisor_report.json'),json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('<WF_VAR>book_contract_file:'+frozen['prompt_file']+'</WF_VAR>')
    print(json.dumps({'status':'completed','book_contract_sha256':frozen['sha256']},ensure_ascii=False))


if __name__=='__main__':main()
