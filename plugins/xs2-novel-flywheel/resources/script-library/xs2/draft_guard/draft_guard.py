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
    if payload.get('source_sha256',body_digest(body))!=body_digest(body) or not reason:
        raise ValueError('初稿重规划缺少冻结事实稿依据')
    try:quotes=revision.exact_evidence(body,quotes)
    except ValueError as exc:raise ValueError('初稿重规划缺少冻结事实稿依据') from exc
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
        revised=revision.apply_patches(source['source_body'],value,protected_phrases=source['book_contract']['protected_phrases']).strip()
        if binding.get('inspect_first') and value['edits'] and revised==source['source_body']:
            raise ValueError('这组补丁应用后正文未变，请撤回无实际作用的补丁。')
        return revised
    if not isinstance(value,dict) or set(value)!={'body'} or not isinstance(value['body'],str) or not value['body'].strip():
        raise ValueError('修稿必须交付仅含body的完整正文对象')
    return value['body'].strip()


COMMITMENT_CHECK = (
    '核对台词是否把未确认的期限、金额、保证或条款说成已经约定，或擅自加上会改变剧情责任的承诺。'
    '用 source_constraints、continuity_contract 和 book_contract 核对；答应做某事与承诺何时完成是两件事。'
    '有依据的约定、新提议、有依据的角色撒谎以及本场应作出的决定照常成立。实质篡改既定事实时用 issues 的 facts，'
    '引用当前问题台词并在理由中说明既定依据，不把计划当成已发生。'
)
QUESTION_CHECK = (
    '检查一个话轮是否把多个独立问题一口气抛给对方，只为让读者得到资料。'
    '结合同场动作和接话判断；同一顾虑的自然追问、符合关系的审问、紧急确认可以成立。'
    '明显生硬时用 convenient_dialogue，按顺序引当场语境和问题台词，'
    '返修先保留此刻真正要问的事，其余随回应或动作自然出现。'
)

ISSUE_GUIDANCE = (
    '事实核对与表达意见分开。只有有当前原文及既定事实或前后知情证据的实质矛盾才报硬事实问题。'
    '未确认的推测、偏好的语气、节奏和留白量可用 advisory=true，只作为建议。'
    '表达问题按最小可修位置给逐字原文、可见的读感损害与目标。'
    '沿开场交锋、关键抉择和补写位置看谁在听、此人此刻需要知道什么，动作、停顿或紧随的后果是否已表达清楚。'
    '用停顿、动作、跳切或留白传达成立的意思可以直接通过，没发现问题时 issues=[]。'
    '逐句可修问题使用 scene_focus，附不同位置的当前证据；有效指令、接话和必要信息写入 preserve。'
    '编辑要求被写进正文时，另给冻结资料中的 source_quote。没有固定表达维度或通过评语。'
)


def audit_value(directory,phase,body,contract,binding):
    source=read(directory/f'{phase}-input.json')
    compare=phase=='expression' and binding.get('inspect_first') and body!=source['source_body']
    edits=read(directory/'expression-draft.json')['edits'] if compare else []
    combined = (phase == 'facts' and binding.get('combined_precheck')
                and not (directory/'facts-draft.json').is_file())
    growth = {}
    if phase == 'expression' and binding.get('added_text_review'):
        mixed = binding.get('mixed_added_text_review', False)
        growth = {'growth_edit_indices': revision.growth_indices(edits, include_mixed=True) if mixed else revision.growth_indices(edits),
                  'addition_goals': [row for row in expression_goals(directory) if 'scene_anchor' not in row]}
    scene_goals = [row for row in expression_goals(directory) if 'scene_anchor' in row] if phase=='expression' else []
    narrator=policy.first_person_narrator(contract,binding['pov'])
    event_guidance=''
    if any('expected_state' in row for row in contract['events']):
        event_guidance=(
            policy.EVENT_STATE_GUIDANCE+'event_observations.observed_state 填正文实际状态。'
            '正文写成其他状态时仍引用这一步的当前原文。只有未出现才把 observed_state 和 quote 都填 null。'
        )
    return {'schema':1,'phase':phase,'candidate_sha256':body_digest(body),'contract_sha256':policy.contract_digest(contract),
        'book_contract_sha256':binding['book_contract_sha256'],
        'candidate_body':body,'continuity_contract':contract,'source_body':source['source_body'],
        **({'edits':edits,'edits_sha256':packet.digest(edits)} if edits else {}),
        **growth,
        **({'scene_goals':scene_goals} if scene_goals else {}),
        **({'facts_from_confirmed_sources':True} if phase=='facts' and binding.get('facts_from_confirmed_sources') else {}),
        **({'review_scope':'original_facts_and_expression'} if combined else {}),
        'source_constraints':source['source_constraints'],'book_contract':source['book_contract'],
        'narrative_pov':binding['pov'],'target_word_count':binding['target'],'actual_word_count':length.count_prose(body),
        **({'first_person_narrator_fact_id':narrator} if narrator else {}),
        'evidence_guidance':('核对先发生的动作与后来告知的区别。正文明确写“告诉我……已经做完”时，分别引告知动作和已完成的分句。'
            '非货币物品先在同一交付场面明确数量、随后由人物接过时，取从数量到交付的连续原文。'
            '数量引文须包含明确数字及单位，并位于对应事件引文内；两个引文可使用同一段足够短的连续原文。'
            'fact_observations 记录指向该共享事实的称名或替换。容器、部件、同场另一物件只作上下文。'
            '存在真实的指代替换时，在 issues 的 facts 中同时给出事实 ID、当前原文及实际替换关系。'
            + ('first_person_narrator_fact_id 是冻结计划中的第一人称叙述者。正文未自称姓名时，'
               '核对叙述中的第一人称指代，用实际代词作为 value，引用当前叙述原文，填写 is_name=false 及真实 same_referent。'
               '区分旁白与对话中别人的自称。读者能跟住「我」时不要求正文补名；视角或身份确实变化再举证。' if narrator else '')
            + COMMITMENT_CHECK + event_guidance
            + (QUESTION_CHECK + (ISSUE_GUIDANCE if binding.get('combined_precheck') else policy.expression_rules.GUARD_GUIDANCE)
               if phase == 'expression' or combined else '')
            + (policy.expression_rules.SCENE_OUTCOME_GUIDANCE if scene_goals else '')
            + (revision.PRESERVATION_GUIDANCE if compare else '')
            + (revision.GROWTH_REVIEW_GUIDANCE if growth and (growth['growth_edit_indices'] or growth['addition_goals']) else '')),
        'evidence_catalog':[{k:r[k] for k in ('id','kind','text')} for r in policy.audit_evidence.catalog(body,policy.audit_evidence.unit_names(contract))]}


def audit_context(directory,phase,body,contract,binding):
    value=audit_value(directory,phase,body,contract,binding)
    save(directory/f'{phase}-audit-input.json',value)
    save(directory/f'{phase}-audit-model.json',packet.local(value,'draft-auditor'))
    return value


def patch_length_budget(source,target,target_policy=None):
    bounds=length.required_bounds(target_policy) if target_policy is not None else length.target_range(target)
    return revision.length_edit_budget(length.count_prose(source),bounds)


ADDITION_GOALS_FILE = 'expression-addition-goals.json'


def expression_goals(directory):
    path = directory/ADDITION_GOALS_FILE
    if not path.is_file():
        return []
    ledger = read(path)
    if ledger['source_sha256'] != read(directory/'expression-input.json')['source_sha256']:
        raise ValueError('表达返修编号与冻结原文不一致')
    return ledger['goals']


def bind_audit_contract_echo(report, context):
    """Repair a one-digit echo only after both independent bindings match."""
    echoed = report.get('contract_sha256') if isinstance(report, dict) else None
    expected = context['contract_sha256']
    if (isinstance(echoed, str) and re.fullmatch(r'[0-9a-f]{64}', echoed)
            and all(report.get(key) == context[key] for key in ('candidate_sha256', 'book_contract_sha256'))
            and sum(a != b for a, b in zip(echoed, expected)) == 1):
        return {**report, 'contract_sha256': expected}
    return report


def audit_candidate(directory, report, body, contract, phase, *, arithmetic=None, precheck=False):
    source = read(directory/'facts-input.json')
    facts = read(directory/'facts-audit.json') if phase == 'expression' else None
    binding = read(directory/'binding.json')
    context = {'candidate_sha256': body_digest(body), 'contract_sha256': policy.contract_digest(contract),
               'book_contract_sha256': binding['book_contract_sha256']}
    report = bind_audit_contract_echo(report, context)
    facts = bind_audit_contract_echo(facts, context)
    if binding.get('combined_precheck'):
        if not isinstance(report.get('issues'),list) or any(
                not isinstance(row,dict) or ('advisory' in row and type(row['advisory']) is not bool)
                for row in report['issues']):
            raise ValueError('预审问题的建议标记或报告格式无效')
        if phase == 'facts':
            # The unchanged body proceeds to expression validation using this same reply.
            report={**report,'issues':[row for row in report['issues'] if row.get('category') in policy.HARD]}
    if phase == 'expression':
        goals = source['book_contract'].get('reading_contract', {})
        reading = book_policy.reading()
        report = reading.without_unrequested_checks(report, goals)
    issues = policy.audit_issues(report, body, contract, phase, arithmetic=arithmetic,
                                facts_audit=facts, narrative_pov=source.get('narrative_pov'))
    if phase == 'expression':
        resolved = policy.audit_evidence.resolve_report(report, body, policy.evidence_unit_names(contract))
        reading.validate_checks(resolved, body, goals)
        policy.expression_rules.validate_guard_checks(resolved,body,source['source_constraints'],
                                                       issues_only=binding.get('combined_precheck',False))
        expression_source=read(directory/'expression-input.json')['source_body']
        edits = []
        if binding.get('inspect_first') and body!=expression_source:
            edits=read(directory/'expression-draft.json')['edits']
            if report.get('edits_sha256')!=packet.digest(edits):
                raise ValueError('核验报告未绑定当前补丁及分组，请从最新输入复制 edits_sha256 并重新对读。')
            for row in revision.review_changes(edits,resolved.get('change_reviews'),source=expression_source,candidate=body):
                issues.append({'category':'expression_regression','reason':row['reason'],
                               'excerpts':[row['before_excerpt']],
                               'goal':'结合整场恢复这组补丁损失的作用，撤回无净改善的独立改动。'})
        prior_goals = [] if precheck else expression_goals(directory)
        scene_goals = [row for row in prior_goals if 'scene_anchor' in row]
        for index, issue in enumerate(issues):
            offset = policy.expression_rules.scene_focus_position(issue, body)
            if offset is None:
                continue
            issues[index] = revision.bind_scene_goal(expression_source, edits, body, issue, offset, assign_id=True)
        outcomes = resolved.get('issue_outcomes')
        if scene_goals:
            scene_ids = {row['id'] for row in scene_goals}
            expected = {row['id'] for row in prior_goals}
            if (not isinstance(outcomes, list) or any(not isinstance(row,dict) for row in outcomes)
                    or len(outcomes)!=len(expected) or {row.get('id') for row in outcomes}!=expected):
                raise ValueError('整场表达和增写问题须按原编号逐条复核')
            by_id = {row['id']:row for row in outcomes}
            for row in scene_goals:
                reason = revision.scene_outcome_problem(expression_source, edits, body, row, by_id[row['id']])
                if reason:
                    issues.append({**row,'recheck_reason':reason})
            outcomes = [row for row in outcomes if row['id'] not in scene_ids]
        if binding.get('added_text_review'):
            options={'include_mixed':True} if binding.get('mixed_added_text_review') else {}
            issues.extend(revision.review_additions(expression_source, edits, resolved.get('added_text_reviews'), **options))
            issues.extend(revision.review_addition_outcomes(
                expression_source, edits, [row for row in prior_goals if 'scene_anchor' not in row], outcomes, candidate=body))
    return issues


def restore_expression_commit(root, project, chapter, seed, source_path, directory, contract, binding):
    recovery=load('expression_commit_checkpoint',BASE/'console_service/draft_review_checkpoint.py')
    native=load('expression_commit_runtime',BASE/'production_guard/production_guard.py')
    source_id=seed['resume_expression_commit']
    if source_id==binding['task_id']:
        raise ValueError('表达审核不能从当前任务自身恢复')
    source=native._native(root,os.environ['WORKFLOW_ID'],source_id)
    checkpoint=recovery.prepare(root,project,source,chapter)
    if (checkpoint['selected_node_ids']!=recovery.EXPRESSION_COMMIT
            or length.safe_path(root,checkpoint['source_file'])!=source_path):
        raise ValueError('无法核对原任务表达审核与恢复种子')
    recovery.validate(root,project,checkpoint)
    previous=length.safe_path(root,f'cache/draft-guard/{source_id}')
    for name in recovery.expression_files(previous):
        original=(previous/name).read_bytes()
        target=directory/name
        if target.exists() and target.read_bytes()!=original:
            raise ValueError('表达审核恢复文件已有变化：'+name)
        if not target.exists():
            length.atomic_text(target,original.decode('utf-8'))
    save(directory/'expression-model.json',packet.local(read(directory/'expression-input.json'),'draft-writer'))
    audit_context(directory,'expression',seed['body'],contract,binding)


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


def tracked_issue(row):
    return 'scene_anchor' in row or row.get('source') == 'added_text_review'


def propose_repairs(issues):
    repairs=[];advice=[]
    for issue in issues:
        if issue.get('advisory') or (issue['category'] not in (*policy.HARD,'expression_regression')
                                    and not tracked_issue(issue)):
            advice.append(issue)
        else:
            repairs.append(issue)
    return repairs,advice


def save_advice(directory,body,advice,measurement):
    save(directory/'expression-advice.json',{'body_sha256':body_digest(body),'issues':advice,
        'length':measurement if measurement and measurement['status'] in ('short','long')
        and not length.is_blocking(measurement) else None})


def publish_expression(root,directory,receipt):
    save(directory/'expression-approved.json',receipt)
    save(directory/'final-receipt.json',receipt)
    save(length.safe_path(root,'cache/si/chapter.json'),{'body':receipt['body']})


def reject_candidate(directory,phase,binding,body,issues,*,retry=True):
    if phase == 'expression' and (binding.get('added_text_review') or any(map(tracked_issue,issues))):
        prior = expression_goals(directory)
        findings = [row for row in issues if tracked_issue(row)]
        goals = revision.merge_addition_issues(prior, findings)
        if goals != prior:
            source_sha = read(directory/'expression-input.json')['source_sha256']
            save(directory/ADDITION_GOALS_FILE, {'source_sha256': source_sha, 'goals': goals})
        if goals:
            issues = [row for row in issues if not tracked_issue(row)] + goals
    hard_bounds=length.required_bounds(binding.get('target_policy',length.target_range(binding['target'])))
    count_note=f'程序实测当前候选{length.count_prose(body)}实字。'
    if hard_bounds:
        count_note+=f'适用交付范围为{hard_bounds[0]}—{hard_bounds[1]}实字。'
    text=('按本书文风与世界规则修正有据的问题，保留其他已成立内容。\n'
          +count_note+'\n'+json.dumps(issues,ensure_ascii=False,indent=2))
    if phase=='expression' and binding.get('expression_format')=='patches' and (directory/'expression-input.json').is_file():
        source=read(directory/'expression-input.json')['source_body']
        text+=('\n本轮edits完整替换上一组补丁，仍应用于source_sha256绑定的冻结原文，不累计上轮候选修改。'
               '按冻结原文计算整组补丁净增删实字，不把上轮候选剩余缺口误作本轮净增量。'
               '只补有功能内容或删无功能复述，不改既定事实；下列预算由程序实测：\n'+
               json.dumps(patch_length_budget(source,binding['target'],binding.get('target_policy')),ensure_ascii=False,indent=2))
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
    if retry:
        reject('agent_guard_'+phase+'_repair',text.replace('\n',' '))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','precheck','approved','candidate','commit','finish','unprepared'))
    parser.add_argument('--phase',choices=('facts','expression'),default='facts')
    parser.add_argument('--multi-dir',required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--pov',choices=('first_person','third_person'),required=True)
    parser.add_argument('--expression-format',choices=('body','patches'),default='body')
    parser.add_argument('--source-file',default='cache/si/chapter.json')
    parser.add_argument('--inspect-first',action='store_true')
    parser.add_argument('--combined-precheck',action='store_true')
    parser.add_argument('--advisory-length',action='store_true')
    args=parser.parse_args();root=Path.cwd();task=os.environ.get('TASK_ID','')
    if args.action=='unprepared':raise ValueError('未准备事实核验，不能跳过检查发布正文')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',task):raise ValueError('修稿需要有效任务标识')
    current_book=book_policy.freeze(root,task)['contract']
    composer=load('draft_composition',BASE/'composition_plan/composition_plan.py')
    project=read(root/'.novel-project.json') if (root/'.novel-project.json').is_file() else {}
    number=str(project.get('values',{}).get('chapter_number','0001')).zfill(4)
    quota=(composer.reference if args.advisory_length else composer.current)(root,number)
    quota_sha=digest(root/f'planning/length/{number}.json') if quota else ''
    bounds=length.target_range(args.target)
    if not bounds and not args.advisory_length:raise ValueError('修稿需要有效成品字数范围')
    multi=length.safe_path(root,args.multi_dir);plan=read(multi/'plan.json')
    directory=length.safe_path(root,f'cache/draft-guard/{task}')
    plan_sha=digest(multi/'plan.json');source_sha=digest(multi/'planning-sources.md')
    if args.action=='prepare':
        if (multi/'allocation.json').exists():allocation.read_allocation(multi,bounds or length.target_range(length.DEFAULT_PLANNING_TARGET))
        contract=policy.validate_contract(plan.get('continuity'),(multi/'planning-sources.md').read_text(encoding='utf-8-sig'),len(plan['scenes']))
        source_path=length.safe_path(root,args.source_file)
        assembled=read(source_path)
        if not isinstance(assembled,dict) or not isinstance(assembled.get('body'),str) or not assembled['body'].strip():raise ValueError('缺少待核验完整初稿')
        source_body=assembled['body'].strip()
        file=directory/'binding.json'
        existing=read(file) if file.is_file() else None
        binding={'schema':1,'task_id':task,'plan_sha256':plan_sha,'sources_sha256':source_sha,
                 'composition_quota_sha256':quota_sha,
                 'expression_format':args.expression_format,
                 **({'facts_from_confirmed_sources':True} if existing is None or existing.get('facts_from_confirmed_sources') else {}),
                 'model_view':packet.PROTOCOL,
                 'book_contract_sha256':book_policy.digest(current_book),
                 'contract_sha256':policy.contract_digest(contract),'source_sha256':body_digest(source_body),
                 'target':args.target,'pov':args.pov}
        review_binding = existing
        if assembled.get('resume_expression_commit'):
            previous_dir = length.safe_path(root, 'cache/draft-guard/'+assembled['resume_expression_commit'])
            review_binding = read(previous_dir/'binding.json')
        if args.advisory_length or review_binding is None or 'target_policy' in review_binding:
            target_policy=length.resolve_length(root,args.target,chapter=number,task_id=task,advisory=args.advisory_length)
            if target_policy['ownership']!='legacy':
                binding['target_policy']=target_policy
        if args.inspect_first:
            binding['inspect_first']=True
            if args.expression_format == 'patches' and (review_binding is None or review_binding.get('added_text_review')):
                binding['added_text_review'] = True
                if review_binding is None or review_binding.get('mixed_added_text_review'):
                    binding['mixed_added_text_review'] = True
        if args.combined_precheck and (review_binding is None or review_binding.get('combined_precheck')):
            binding['combined_precheck']=True
        if existing is not None and existing!=binding:raise ValueError('修稿来源或契约已有变化，请创建新任务')
        save(file,binding);save(directory/'contract.json',contract)
        save(directory/'facts-input.json',{'phase':'facts','source_body':source_body,'continuity_contract':contract,
             'book_contract':current_book,
             'source_constraints':(multi/'planning-sources.md').read_text(encoding='utf-8-sig'),
             'narrative_pov':args.pov,'target_word_count':args.target})
        save(directory/'facts-model.json',packet.local(read(directory/'facts-input.json'),'draft-writer'))
        if binding.get('inspect_first'):
            audit_context(directory,'facts',source_body,contract,binding)
        if assembled.get('resume_expression_commit'):
            restore_expression_commit(root,project,number,assembled,source_path,directory,contract,binding)
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
    phase=args.phase;repair='agent_guard_'+phase+'_repair';precheck=args.action=='precheck'
    auditor='agent_guard_'+phase+('_inspect' if precheck else '_audit')
    combined = binding.get('combined_precheck',False)
    if combined and precheck and phase=='expression' and read(directory/'facts-approved.json').get('combined_precheck'):
        auditor='agent_guard_facts_inspect'
    if precheck and not binding.get('inspect_first'):
        raise ValueError('初稿预审缺少冻结的工作流绑定')
    if args.action=='approved':
        source=read(directory/f'{phase}-input.json')['source_body']
        approved=read(directory/f'{phase}-approved.json')
        report_path=directory/f'{phase}-audit.json'
        if (approved['body']!=source or approved['body_sha256']!=body_digest(source)
                or approved['contract_sha256']!=binding['contract_sha256']
                or approved['audit_sha256']!=digest(report_path)
                or read(report_path)['candidate_sha256']!=approved['body_sha256']):
            raise ValueError('原样通过的稿件与核验凭据已有变化')
        return
    if binding.get('model_view'):
        packet.verify(read(directory/f'{phase}-model.json'),read(directory/f'{phase}-input.json'),'draft-writer')
    if args.action=='finish':
        receipt=read(directory/'final-receipt.json');current=read(length.safe_path(root,'cache/si/chapter.json'))
        if (receipt['body_sha256']!=body_digest(current['body']) or receipt['body_sha256']!=body_digest(receipt['body'])
                or receipt['contract_sha256']!=binding['contract_sha256'] or receipt['audit_sha256']!=digest(directory/'expression-audit.json')
                or receipt['body_sha256']!=read(directory/'expression-audit.json')['candidate_sha256']):
            raise ValueError('最终采用稿与核验凭据已有变化，不能发布')
        return
    if phase=='expression':
        approved=read(directory/'facts-approved.json');expression=read(directory/'expression-input.json')
        if (approved['body_sha256']!=body_digest(approved['body']) or approved['contract_sha256']!=binding['contract_sha256']
                or expression['source_body']!=approved['body'] or expression['continuity_contract']!=contract
                or expression.get('book_contract')!=facts_source['book_contract']
                or expression.get('source_constraints')!=facts_source['source_constraints']
                or approved['audit_sha256']!=digest(directory/'facts-audit.json')
                or read(directory/'facts-audit.json')['candidate_sha256']!=approved['body_sha256']):
            raise ValueError('已通过的硬事实原文或表达修订输入已有变化')
        payload={} if precheck else read(directory/'expression-draft.json')
        if payload.get('status')=='needs_replan':
            if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:raise ValueError('初稿冲突不能夹带正文修改')
            save(directory/'composition-conflict.json',draft_conflict(root,directory,binding,payload,payload.get('reason'),payload.get('evidence')))
            raise ValueError('CONTENT_LENGTH_CONFLICT：初稿表达须重排分场或篇幅，未发布。')
    try:
        body=read(directory/f'{phase}-input.json')['source_body'] if precheck else candidate(directory,phase)
    except (ValueError,FileNotFoundError) as exc:
        reject(repair,str(exc));return
    if phase=='expression' and not precheck and 'target_policy' not in binding:
        actual=length.count_prose(body);lower,upper=length.target_range(args.target)
        if not lower<=actual<=upper:
            reject_candidate(directory,phase,binding,body,[{'category':'length','reason':f'实测{actual}，目标{lower}—{upper}',
                'goal':'保留有效表达和事实，补充有作用的场景、反应或后果。'}]);return
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
        reject(auditor,'draft_audit_refresh: 候选已更新，读取最新核验输入重新审查，旧核验不可复用');return
    if report_path.is_file():
        try:
            prior = read(report_path)
        except ValueError:
            prior = None
        if isinstance(prior, dict) and prior.get('candidate_sha256') != context['candidate_sha256']:
            reject(auditor,'draft_audit_refresh: 报告未绑定当前候选；直接从最新输入复制 candidate_sha256、contract_sha256 和 book_contract_sha256，并重做实际核验。');return
    try:
        report=read(report_path)
        if binding['expression_format']=='patches' and report.get('book_contract_sha256')!=binding['book_contract_sha256']:
            raise ValueError('核验报告与本书世界/文风契约不匹配')
        arithmetic, journal, arithmetic_scope = arithmetic_for(
            root, binding, phase, approved if phase == 'expression' else None)
        issues=audit_candidate(directory,report,body,contract,phase,arithmetic=arithmetic,precheck=precheck)
    except (ValueError,FileNotFoundError,TypeError,KeyError) as exc:
        reject(auditor,'核验凭据无效，请按最新正文重做完整核验：'+str(exc));return
    advice=[]
    if combined:
        issues,advice=propose_repairs(issues)
    hard=[i for i in issues if i['category'] in policy.HARD]
    if hard:
        issues=hard + [i for i in issues if tracked_issue(i)]
    measured=None
    if phase=='expression' and (combined or not issues):
        measured=length.measurement(body.encode(),number,binding.get('target_policy',length.target_range(args.target)))
        if not hard and length.is_blocking(measured):
            actual=measured['actual'];lower,upper=measured['lower'],measured['upper']
            issues.append({'category':'length','reason':f'最终正文实测{actual}，目标{lower}—{upper}，按实字复核后交付',
                         'goal':'保留已通过的表达、事实和顺序。篇幅不足时找一处尚未表现的反应、行动或选择的后果再补；无有用内容可补时反馈篇幅冲突。'})
    if combined and phase=='expression':
        original_path=directory/'expression-original-review.json'
        if precheck:
            save_advice(directory,body,advice,measured)
            if not hard and not length.is_blocking(measured) and issues:
                save(original_path,{'audit':report,'open_issues':issues,'advice':advice})
        elif issues and original_path.is_file():
            # The only automatic expression attempt may be discarded if the original
            # was already checked and independently fits the hard delivery constraints.
            original=read(original_path)
            source=read(directory/'expression-input.json')['source_body']
            base=length.measurement(source.encode(),number,binding.get('target_policy',length.target_range(args.target)))
            if (original['audit']['candidate_sha256']!=body_digest(source)
                    or original['audit']['book_contract_sha256']!=context['book_contract_sha256']
                    or not original['open_issues'] or length.is_blocking(base)):
                raise ValueError('原稿通过凭据与当前正文或交付范围不一致')
            save(directory/'expression-discarded-audit.json',report)
            save(report_path,original['audit'])
            receipt={'body':source,'body_sha256':body_digest(source),'source_sha256':body_digest(source),
                'contract_sha256':binding['contract_sha256'],'book_contract_sha256':binding['book_contract_sha256'],
                'audit_sha256':digest(report_path),'phase':phase,'retained_original':True}
            save_advice(directory,source,original['advice']+original['open_issues'],base)
            publish_expression(root,directory,receipt)
            return
        else:
            save_advice(directory,body,advice,measured)
    if issues:
        reject_candidate(directory,phase,binding,body,issues,retry=not precheck)
        if precheck:
            print(f'<WF_VAR>guard_{phase}_needs_repair:yes</WF_VAR>')
        return
    receipt={'body':body,'body_sha256':body_digest(body),'contract_sha256':binding['contract_sha256'],
             'book_contract_sha256':binding['book_contract_sha256'],
             'source_sha256':body_digest(read(directory/f'{phase}-input.json')['source_body']),
             'audit_sha256':digest(report_path),'phase':phase}
    if bind_audit_contract_echo(report, context) is not report:
        receipt['audit_contract_echo_corrected'] = True
    if journal is not None and arithmetic.values:
        details = {'task_id': task, 'scope': arithmetic_scope, 'phase': phase,
                   'body_sha256': receipt['body_sha256'], 'audit_sha256': receipt['audit_sha256'],
                   'hits': arithmetic.hits, 'misses': arithmetic.misses}
        if phase == 'facts':
            journal.event(root, 'verified_arithmetic', {**details, 'values': arithmetic.values})
        else:
            journal.event(root, 'arithmetic_reuse', details)
    if phase=='facts':
        if combined and precheck:
            if report.get('checks',{}).get('repetition') is not True:
                reject(auditor,'合并预审须完成事实和表达检查。表达没有问题时可使用空列表。');return
            receipt['combined_precheck']=True
        save(directory/'facts-approved.json',receipt)
        save(directory/'expression-input.json',{'phase':'expression','source_body':body,'continuity_contract':contract,
             'book_contract':facts_source['book_contract'],
             'source_sha256':body_digest(body),'paragraphs':revision.paragraphs(body),'actual_word_count':length.count_prose(body),
             'length_edit_budget':patch_length_budget(body,args.target,binding.get('target_policy')),
             **({'growth_guidance':revision.GROWTH_GUIDANCE} if binding.get('added_text_review') else {}),
             'source_constraints':facts_source['source_constraints'],
             'narrative_pov':args.pov,'target_word_count':args.target})
        save(directory/'expression-model.json',packet.local(read(directory/'expression-input.json'),'draft-writer'))
        if binding.get('inspect_first'):
            audit_context(directory,'expression',body,contract,binding)
        if receipt.get('combined_precheck'):
            save(directory/'expression-audit.json',report)
    else:
        publish_expression(root,directory,receipt)
    if precheck:
        print(f'<WF_VAR>guard_{phase}_needs_repair:no</WF_VAR>')


if __name__=='__main__':main()
