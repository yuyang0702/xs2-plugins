"""Guard assembled drafts: source-bound fact repair first, expression repair second."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


BASE=Path(__file__).resolve().parents[1]
policy=load('draft_guard_contract',BASE/'multi_scene/continuity_contract.py')
allocation=load('draft_guard_allocation',BASE/'multi_scene/scene_allocation.py')
length=load('draft_guard_length',BASE/'console_service/length_quality.py')
book_policy=load('draft_guard_book_contract',BASE/'prose_policy/book_contract.py')
revision=load('draft_guard_revision_patch',Path(__file__).with_name('revision_patch.py'))


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def body_digest(body):return hashlib.sha256(body.encode()).hexdigest()
def save(path,value):length.atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def reject(node,reason):print(f'<WF_REJECT_UPSTREAM target="{node}">{reason}</WF_REJECT_UPSTREAM>')


def candidate(directory,phase):
    value=read(directory/f'{phase}-draft.json')
    binding=read(directory/'binding.json')
    if phase=='expression' and binding.get('expression_format')=='patches':
        source=read(directory/'expression-input.json')
        return revision.apply_patches(source['source_body'],value,protected_phrases=source['book_contract']['protected_phrases']).strip()
    if not isinstance(value,dict) or set(value)!={'body'} or not isinstance(value['body'],str) or not value['body'].strip():
        raise ValueError('修稿必须交付仅含body的完整正文对象')
    return value['body'].strip()


def audit_value(directory,phase,body,contract,binding):
    source=read(directory/f'{phase}-input.json')
    return {'schema':1,'phase':phase,'candidate_sha256':body_digest(body),'contract_sha256':policy.contract_digest(contract),
        'book_contract_sha256':binding['book_contract_sha256'],
        'candidate_body':body,'continuity_contract':contract,'source_body':source['source_body'],
        'source_constraints':source['source_constraints'],'book_contract':source['book_contract'],
        'narrative_pov':binding['pov'],'target_word_count':binding['target'],'actual_word_count':length.count_prose(body),
        'evidence_catalog':[{k:r[k] for k in ('id','kind','text')} for r in policy.audit_evidence.catalog(body,policy.audit_evidence.unit_names(contract))]}


def audit_context(directory,phase,body,contract,binding):
    value=audit_value(directory,phase,body,contract,binding)
    save(directory/f'{phase}-audit-input.json',value)
    return value


def reject_candidate(directory,phase,binding,body,issues):
    text=('按本书文风与世界规则修正有据的问题，保留其他已成立内容。\n'
          f'程序实测当前候选{length.count_prose(body)}实字，目标{binding["target"]}。\n'+json.dumps(issues,ensure_ascii=False,indent=2))
    length.atomic_text(directory/f'{phase}-feedback.md',text)
    reject('agent_guard_'+phase+'_repair',text.replace('\n',' '))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','candidate','commit','finish','unprepared'))
    parser.add_argument('--phase',choices=('facts','expression'),default='facts')
    parser.add_argument('--multi-dir',required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--pov',choices=('first_person','third_person'),required=True)
    parser.add_argument('--expression-format',choices=('body','patches'),default='body')
    args=parser.parse_args();root=Path.cwd();task=os.environ.get('TASK_ID','')
    if args.action=='unprepared':raise ValueError('未准备事实核验，不能跳过检查发布正文')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',task):raise ValueError('修稿需要有效任务标识')
    current_book=book_policy.freeze(root,task)['contract']
    if not length.target_range(args.target):raise ValueError('修稿需要有效成品字数范围')
    multi=length.safe_path(root,args.multi_dir);plan=read(multi/'plan.json')
    directory=length.safe_path(root,f'cache/draft-guard/{task}')
    plan_sha=digest(multi/'plan.json');source_sha=digest(multi/'planning-sources.md')
    if args.action=='prepare':
        if (multi/'allocation.json').exists():allocation.read_allocation(multi,length.target_range(args.target))
        contract=policy.validate_contract(plan.get('continuity'),(multi/'planning-sources.md').read_text(encoding='utf-8-sig'),len(plan['scenes']))
        assembled=read(length.safe_path(root,'cache/si/chapter.json'))
        if not isinstance(assembled,dict) or not isinstance(assembled.get('body'),str) or not assembled['body'].strip():raise ValueError('缺少待核验完整初稿')
        source_body=assembled['body'].strip()
        binding={'schema':1,'task_id':task,'plan_sha256':plan_sha,'sources_sha256':source_sha,
                 'expression_format':args.expression_format,
                 'book_contract_sha256':book_policy.digest(current_book),
                 'contract_sha256':policy.contract_digest(contract),'source_sha256':body_digest(source_body),
                 'target':args.target,'pov':args.pov}
        file=directory/'binding.json'
        if file.exists() and read(file)!=binding:raise ValueError('修稿来源或契约已有变化，请创建新任务')
        save(file,binding);save(directory/'contract.json',contract)
        save(directory/'facts-input.json',{'phase':'facts','source_body':source_body,'continuity_contract':contract,
             'book_contract':current_book,
             'source_constraints':(multi/'planning-sources.md').read_text(encoding='utf-8-sig'),
             'narrative_pov':args.pov,'target_word_count':args.target})
        for phase in ('facts','expression'):
            feedback=directory/f'{phase}-feedback.md'
            if not feedback.exists():length.atomic_text(feedback,'')
        print(f'<WF_VAR>guard_dir:cache/draft-guard/{task}</WF_VAR>')
        for phase in ('facts','expression'):
            for key,name in (('input','input.json'),('feedback','feedback.md'),('audit_input','audit-input.json')):
                print(f'<WF_VAR>guard_{phase}_{key}:cache/draft-guard/{task}/{phase}-{name}</WF_VAR>')
        print('<WF_VAR>guard_enabled:yes</WF_VAR>')
        return
    binding=read(directory/'binding.json');contract=read(directory/'contract.json')
    if binding.get('book_contract_sha256')!=book_policy.digest(current_book):
        raise ValueError('本书文风或世界规则已有变化，请新建任务')
    if (binding['task_id']!=task or binding['plan_sha256']!=plan_sha or binding['sources_sha256']!=source_sha
            or binding['contract_sha256']!=policy.contract_digest(contract)
            or binding['target']!=args.target or binding['pov']!=args.pov):
        raise ValueError('修稿来源、事实契约或范围已有变化，请创建新任务')
    facts_source=read(directory/'facts-input.json')
    if (body_digest(facts_source['source_body'])!=binding['source_sha256'] or facts_source['continuity_contract']!=contract
            or book_policy.digest(facts_source.get('book_contract'))!=binding['book_contract_sha256']
            or facts_source.get('source_constraints')!=(multi/'planning-sources.md').read_text(encoding='utf-8-sig')):
        raise ValueError('修稿原文或事实输入已有变化，不能沿用绑定')
    phase=args.phase;repair='agent_guard_'+phase+'_repair';auditor='agent_guard_'+phase+'_audit'
    if phase=='expression':
        approved=read(directory/'facts-approved.json');expression=read(directory/'expression-input.json')
        if (approved['body_sha256']!=body_digest(approved['body']) or approved['contract_sha256']!=binding['contract_sha256']
                or expression['source_body']!=approved['body'] or expression['continuity_contract']!=contract
                or expression.get('book_contract')!=facts_source['book_contract']
                or expression.get('source_constraints')!=facts_source['source_constraints']
                or approved['audit_sha256']!=digest(directory/'facts-audit.json')
                or read(directory/'facts-audit.json')['candidate_sha256']!=approved['body_sha256']):
            raise ValueError('已通过的硬事实原文或表达修订输入已有变化')
    if args.action=='finish':
        receipt=read(directory/'final-receipt.json');current=read(length.safe_path(root,'cache/si/chapter.json'))
        if (receipt['body_sha256']!=body_digest(current['body']) or receipt['body_sha256']!=body_digest(receipt['body'])
                or receipt['contract_sha256']!=binding['contract_sha256'] or receipt['audit_sha256']!=digest(directory/'expression-audit.json')
                or receipt['body_sha256']!=read(directory/'expression-audit.json')['candidate_sha256']):
            raise ValueError('最终采用稿与核验凭据已有变化，不能发布')
        return
    try:body=candidate(directory,phase)
    except (ValueError,FileNotFoundError) as exc:
        reject(repair,str(exc));return
    if phase=='expression':
        lower,upper=length.target_range(args.target);actual=length.count_prose(body)
        if not lower<=actual<=upper:
            reject_candidate(directory,phase,binding,body,[{'category':'length','reason':f'实测{actual}，目标{lower}—{upper}',
                'goal':'通过局部补丁保留已有文风与硬事实；补足有功能的场景、情绪或说明，或删减无功能复述，不用填充句凑字'}]);return
    if args.action=='candidate':
        audit_context(directory,phase,body,contract,binding);return
    context_path=directory/f'{phase}-audit-input.json';report_path=directory/f'{phase}-audit.json'
    # The host may keep intermediate nodes completed when it retries a writer.
    # Refresh this auditor's input and explicitly rerun it on the changed text.
    context=read(context_path) if context_path.exists() else None
    if context is None or context!=audit_value(directory,phase,body,contract,binding):
        audit_context(directory,phase,body,contract,binding)
        reject(auditor,'候选已更新，读取最新核验输入重新审查，旧核验不可复用');return
    try:
        report=read(report_path)
        if binding['expression_format']=='patches' and report.get('book_contract_sha256')!=binding['book_contract_sha256']:
            raise ValueError('核验报告与本书世界/文风契约不匹配')
        issues=policy.audit_issues(report,body,contract,phase)
    except (ValueError,FileNotFoundError,TypeError,KeyError) as exc:
        reject(auditor,'核验凭据无效，请按最新正文重做完整核验：'+str(exc));return
    hard=[i for i in issues if i['category'] in policy.HARD]
    issues=hard or issues
    if not issues and phase=='expression':
        actual=length.count_prose(body);lower,upper=length.target_range(args.target)
        if not lower<=actual<=upper:
            issues=[{'category':'length','reason':f'最终正文实测{actual}，目标{lower}—{upper}，按实字复核后交付',
                     'goal':'先保留已通过的事实与顺序，压缩重复后将有效交涉和选择后果写足；不添新事实或用同义解释凑字'}]
    if issues:
        reject_candidate(directory,phase,binding,body,issues);return
    receipt={'body':body,'body_sha256':body_digest(body),'contract_sha256':binding['contract_sha256'],
             'book_contract_sha256':binding['book_contract_sha256'],
             'source_sha256':body_digest(read(directory/f'{phase}-input.json')['source_body']),
             'audit_sha256':digest(report_path),'phase':phase}
    save(directory/f'{phase}-approved.json',receipt)
    if phase=='facts':
        save(directory/'expression-input.json',{'phase':'expression','source_body':body,'continuity_contract':contract,
             'book_contract':facts_source['book_contract'],
             'source_sha256':body_digest(body),'paragraphs':revision.paragraphs(body),'actual_word_count':length.count_prose(body),
             'source_constraints':facts_source['source_constraints'],
             'narrative_pov':args.pov,'target_word_count':args.target})
    else:
        save(directory/'final-receipt.json',receipt)
        save(length.safe_path(root,'cache/si/chapter.json'),{'body':body})


if __name__=='__main__':main()
