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
packet=load('draft_guard_packet',BASE/'prose_policy/context_packet.py')


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def body_digest(body):return hashlib.sha256(body.encode()).hexdigest()
def save(path,value):length.atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def reject(node,reason):
    if os.environ.get('TASK_ID'):
        guard=load('draft_logical_retry',BASE/'production_guard/production_guard.py')
        guard.retry(Path.cwd(),'draft-review/'+os.environ['TASK_ID'],node,reason)
    print(f'<WF_REJECT_UPSTREAM target="{node}">{reason}</WF_REJECT_UPSTREAM>')


def draft_conflict(root,directory,binding,payload,reason,quotes,measured=None):
    source=read(directory/'expression-input.json');body=source['source_body']
    if payload.get('status')=='needs_replan' and (set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]):
        raise ValueError('初稿冲突不能夹带正文补丁')
    if (payload.get('source_sha256',body_digest(body))!=body_digest(body) or not reason or not isinstance(quotes,list)
            or not quotes or any(not isinstance(q,str) or not q or q not in body for q in quotes)):
        raise ValueError('初稿重规划缺少冻结事实稿依据')
    return {'schema':1,'kind':'content_length_conflict','origin':'mvp','task_id':binding['task_id'],
        'source_sha256':body_digest(body),'binding_digest':body_digest(json.dumps(binding,ensure_ascii=False,sort_keys=True)),
        'patch_digest':body_digest(json.dumps(payload,ensure_ascii=False,sort_keys=True)),
        'reason':reason,'evidence':quotes,'measurement':measured,'draft_source_body':body,'no_publication':True}


def verify_conflict(root,state,task):
    ckpt=load('draft_conflict_checkpoint',BASE/'console_service/recovery_checkpoint.py')
    ckpt.prepare_review(root,state,task,str(state.get('values',{}).get('chapter_number','0001')).zfill(4))
    directory=length.safe_path(root,'cache/draft-guard/'+task['task_id']);binding=read(directory/'binding.json')
    payload=read(directory/'expression-draft.json');packet=read(directory/'composition-conflict.json')
    if (task.get('node_states',{}).get('agent_guard_expression_repair',{}).get('status')!='completed'
            or json.loads(task.get('parameter_values',{}).get('guard_expression_patch_result','null'))!=payload):
        raise ValueError('初稿冲突不属于本任务真实模型回复')
    measured=None
    if payload.get('status')=='needs_replan':reason,quotes=payload.get('reason'),payload.get('evidence')
    else:
        source=read(directory/'expression-input.json')['source_body']
        body=revision.apply_patches(source,payload,protected_phrases=read(directory/'expression-input.json')['book_contract']['protected_phrases']) if binding['expression_format']=='patches' else payload['body']
        measured=length.measurement(body.encode(),str(state['values']['chapter_number']).zfill(4),length.target_range(binding['target']))
        if measured['status'] not in ('short','long') or len(read(directory/'length-candidates.json'))<2:raise ValueError('缺少连续初稿篇幅冲突')
        reason='初稿表达修订连续与篇幅冲突，须回到分场和预算规划。';quotes=[source[:100]]
    if packet!=draft_conflict(root,directory,binding,payload,reason,quotes,measured):raise ValueError('初稿重规划凭据已有变化')
    return packet


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
    save(directory/f'{phase}-audit-model.json',packet.local(value,'draft-auditor'))
    return value


def patch_length_budget(source,target):
    return revision.length_edit_budget(length.count_prose(source),length.target_range(target))


def arithmetic_for(root, binding, phase, approved=None):
    guard = load('draft_arithmetic_guard', BASE/'production_guard/production_guard.py')
    runtime = guard.reuse_profile(root, ('agent_guard_facts_audit', 'agent_guard_expression_audit'))
    if runtime is None:
        return policy.Arithmetic(policy.amount), None, None
    journal = guard.store()
    scope = journal.identity([binding, runtime])
    verified = {}
    if phase == 'expression' and approved:
        for event in journal.events(root, kind='verified_arithmetic', task_id=binding['task_id']):
            data = event['data']
            if data['scope'] == scope and data['audit_sha256'] == approved['audit_sha256'] and data['body_sha256'] == approved['body_sha256']:
                verified = data['values']
                break
    return policy.Arithmetic(policy.amount, verified), journal, scope


def reject_candidate(directory,phase,binding,body,issues):
    text=('按本书文风与世界规则修正有据的问题，保留其他已成立内容。\n'
          f'程序实测当前候选{length.count_prose(body)}实字，目标{binding["target"]}。\n'+json.dumps(issues,ensure_ascii=False,indent=2))
    if phase=='expression' and binding.get('expression_format')=='patches' and (directory/'expression-input.json').is_file():
        source=read(directory/'expression-input.json')['source_body']
        text+=('\n本轮edits完整替换上一组补丁，仍应用于source_sha256绑定的冻结原文，不累计上轮候选修改。'
               '按冻结原文计算整组补丁净增删实字，不把上轮候选剩余缺口误作本轮净增量。'
               '只补有功能内容或删无功能复述，不改既定事实；下列预算由程序实测：\n'+
               json.dumps(patch_length_budget(source,binding['target']),ensure_ascii=False,indent=2))
        patch_file=directory/'expression-draft.json'
        if patch_file.is_file():
            previous=read(patch_file)
            try:matches=revision.apply_patches(source,previous).strip()==body
            except ValueError:matches=False
            if matches:
                retained={'source_sha256':body_digest(source),'candidate_sha256':body_digest(body),
                    'candidate_word_count':length.count_prose(body),'previous_patch':previous,'issues':issues}
                save(directory/'expression-last-rejected.json',retained)
                text+=('\n上一组补丁已保存。问题引文可能来自replacement新增文字：请在相应replacement中纠错，'
                       'old仍须取冻结原文，完整重交整组补丁并保留其他已成立修改，不把候选新增句当作old。\n'+
                       json.dumps(retained,ensure_ascii=False,indent=2))
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
    parser.add_argument('--source-file',default='cache/si/chapter.json')
    args=parser.parse_args();root=Path.cwd();task=os.environ.get('TASK_ID','')
    if args.action=='unprepared':raise ValueError('未准备事实核验，不能跳过检查发布正文')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',task):raise ValueError('修稿需要有效任务标识')
    current_book=book_policy.freeze(root,task)['contract']
    composer=load('draft_composition',BASE/'composition_plan/composition_plan.py')
    project=read(root/'.novel-project.json') if (root/'.novel-project.json').is_file() else {}
    number=str(project.get('values',{}).get('chapter_number','0001')).zfill(4)
    quota=composer.current(root,number)
    quota_sha=digest(root/f'planning/length/{number}.json') if quota else ''
    if not length.target_range(args.target):raise ValueError('修稿需要有效成品字数范围')
    multi=length.safe_path(root,args.multi_dir);plan=read(multi/'plan.json')
    directory=length.safe_path(root,f'cache/draft-guard/{task}')
    plan_sha=digest(multi/'plan.json');source_sha=digest(multi/'planning-sources.md')
    if args.action=='prepare':
        if (multi/'allocation.json').exists():allocation.read_allocation(multi,length.target_range(args.target))
        contract=policy.validate_contract(plan.get('continuity'),(multi/'planning-sources.md').read_text(encoding='utf-8-sig'),len(plan['scenes']))
        assembled=read(length.safe_path(root,args.source_file))
        if not isinstance(assembled,dict) or not isinstance(assembled.get('body'),str) or not assembled['body'].strip():raise ValueError('缺少待核验完整初稿')
        source_body=assembled['body'].strip()
        binding={'schema':1,'task_id':task,'plan_sha256':plan_sha,'sources_sha256':source_sha,
                 'composition_quota_sha256':quota_sha,
                 'expression_format':args.expression_format,
                 'model_view':packet.PROTOCOL,
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
        save(directory/'facts-model.json',packet.local(read(directory/'facts-input.json'),'draft-writer'))
        for phase in ('facts','expression'):
            feedback=directory/f'{phase}-feedback.md'
            if not feedback.exists():length.atomic_text(feedback,'')
        print(f'<WF_VAR>guard_dir:cache/draft-guard/{task}</WF_VAR>')
        for phase in ('facts','expression'):
            for key,name in (('input','input.json'),('model','model.json'),('feedback','feedback.md'),('audit_input','audit-input.json'),('audit_model','audit-model.json')):
                print(f'<WF_VAR>guard_{phase}_{key}:cache/draft-guard/{task}/{phase}-{name}</WF_VAR>')
        print('<WF_VAR>guard_enabled:yes</WF_VAR>')
        return
    binding=read(directory/'binding.json');contract=read(directory/'contract.json')
    if binding.get('composition_quota_sha256','')!=quota_sha:raise ValueError('篇幅预算变化，须重建初稿任务')
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
    if binding.get('model_view'):
        packet.verify(read(directory/f'{phase}-model.json'),read(directory/f'{phase}-input.json'),'draft-writer')
    if phase=='expression':
        approved=read(directory/'facts-approved.json');expression=read(directory/'expression-input.json')
        if (approved['body_sha256']!=body_digest(approved['body']) or approved['contract_sha256']!=binding['contract_sha256']
                or expression['source_body']!=approved['body'] or expression['continuity_contract']!=contract
                or expression.get('book_contract')!=facts_source['book_contract']
                or expression.get('source_constraints')!=facts_source['source_constraints']
                or approved['audit_sha256']!=digest(directory/'facts-audit.json')
                or read(directory/'facts-audit.json')['candidate_sha256']!=approved['body_sha256']):
            raise ValueError('已通过的硬事实原文或表达修订输入已有变化')
        payload=read(directory/'expression-draft.json')
        if payload.get('status')=='needs_replan':
            if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:raise ValueError('初稿冲突不能夹带正文修改')
            save(directory/'composition-conflict.json',draft_conflict(root,directory,binding,payload,payload.get('reason'),payload.get('evidence')))
            raise ValueError('CONTENT_LENGTH_CONFLICT：初稿表达须重排分场或篇幅，未发布。')
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
            path=directory/'length-candidates.json';history=read(path) if path.is_file() else []
            key=body_digest(str((directory/'expression-draft.json').stat().st_mtime_ns)+digest(directory/'expression-draft.json'))
            if key not in history:history.append(key)
            save(path,history)
            if len(history)>=2:
                source=read(directory/'expression-input.json')['source_body'];payload=read(directory/'expression-draft.json')
                project=read(root/'.novel-project.json') if (root/'.novel-project.json').is_file() else {}
                number=str(project.get('values',{}).get('chapter_number','0001')).zfill(4)
                measured=length.measurement(body.encode(),number,length.target_range(args.target))
                save(directory/'composition-conflict.json',draft_conflict(root,directory,binding,payload,
                    '初稿表达修订连续与篇幅冲突，须回到分场和预算规划。',[source[:100]],measured))
                raise ValueError('CONTENT_LENGTH_CONFLICT：初稿表达须重排分场或篇幅，未发布。')
            reject_candidate(directory,phase,binding,body,[{'category':'length','reason':f'实测{actual}，目标{lower}—{upper}',
                'goal':'通过局部补丁保留已有文风与硬事实；补足有功能的场景、情绪或说明，或删减无功能复述，不用填充句凑字'}]);return
    if args.action=='candidate':
        audit_context(directory,phase,body,contract,binding);return
    context_path=directory/f'{phase}-audit-input.json';report_path=directory/f'{phase}-audit.json'
    if binding.get('model_view'):
        packet.verify(read(directory/f'{phase}-audit-model.json'),read(context_path),'draft-auditor')
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
        arithmetic, journal, arithmetic_scope = arithmetic_for(
            root, binding, phase, approved if phase == 'expression' else None)
        issues=policy.audit_issues(report,body,contract,phase,arithmetic=arithmetic)
        if phase=='expression':
            resolved=policy.audit_evidence.resolve_report(report,body)
            reading_issues=book_policy.reading().validate_checks(resolved,body,facts_source['book_contract'].get('reading_contract',{}))
            issues += [{'category':'reading_goal','reason':i['impact'],'goal':i['goal']} for i in reading_issues if i['priority'] in ('medium','high')]
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
    if journal is not None and arithmetic.values:
        details = {'task_id': task, 'scope': arithmetic_scope, 'phase': phase,
                   'body_sha256': receipt['body_sha256'], 'audit_sha256': receipt['audit_sha256'],
                   'hits': arithmetic.hits, 'misses': arithmetic.misses}
        if phase == 'facts':
            journal.event(root, 'verified_arithmetic', {**details, 'values': arithmetic.values})
        else:
            journal.event(root, 'arithmetic_reuse', details)
    save(directory/f'{phase}-approved.json',receipt)
    if phase=='facts':
        save(directory/'expression-input.json',{'phase':'expression','source_body':body,'continuity_contract':contract,
             'book_contract':facts_source['book_contract'],
             'source_sha256':body_digest(body),'paragraphs':revision.paragraphs(body),'actual_word_count':length.count_prose(body),
             'length_edit_budget':patch_length_budget(body,args.target),
             'source_constraints':facts_source['source_constraints'],
             'narrative_pov':args.pov,'target_word_count':args.target})
        save(directory/'expression-model.json',packet.local(read(directory/'expression-input.json'),'draft-writer'))
    else:
        save(directory/'final-receipt.json',receipt)
        save(length.safe_path(root,'cache/si/chapter.json'),{'body':body})


if __name__=='__main__':main()
