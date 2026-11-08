"""Task-bound independent reading and permission-aware review publication."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from xml.sax.saxutils import escape

_contract_spec=importlib.util.spec_from_file_location('reader_book_contract',Path(__file__).resolve().parents[1]/'prose_policy/book_contract.py')
book_contract=importlib.util.module_from_spec(_contract_spec);_contract_spec.loader.exec_module(book_contract)
_evidence_spec=importlib.util.spec_from_file_location('reader_audit_evidence',Path(__file__).resolve().parents[1]/'multi_scene/audit_evidence.py')
evidence=importlib.util.module_from_spec(_evidence_spec);_evidence_spec.loader.exec_module(evidence)
_expression_spec=importlib.util.spec_from_file_location('reader_expression_evidence',Path(__file__).resolve().parents[1]/'prose_policy/expression_review.py')
expression_rules=importlib.util.module_from_spec(_expression_spec);_expression_spec.loader.exec_module(expression_rules)


class InvalidReviewReport(ValueError):
    """Model report needs repair; source-integrity failures remain fatal."""


def quality():
    path = Path(__file__).resolve().parents[1] / 'console_service/length_quality.py'
    spec = importlib.util.spec_from_file_location('reader_length_quality', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path(root, relative):
    root = Path(root).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('审稿路径超出本书工作区')
    return result


def _load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _save(path, data):
    quality().atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def _text(data, keys):
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in keys):
        raise ValueError('审稿缺少有效文字字段：' + ','.join(keys))


def _quotes(data, body):
    quotes = data.get('excerpts')
    if (not isinstance(quotes, list) or not quotes
            or any(not isinstance(q, str) or not q.strip() or q not in body for q in quotes)):
        raise ValueError('审稿引用须为当前原文中连续存在的原句')


def _scope_source(root,contract=None):
    project = _path(root, '.novel-project.json')
    state = _load(project) if project.is_file() else {}
    values = state.get('values', {})
    feedback = str(values.get('author_feedback_file') or '').strip()
    feedback_file = _path(root, feedback) if feedback else None
    return {'feedback_path': feedback,
            'book_contract_sha256':book_contract.digest(book_contract.resolve(root) if contract is None else contract),
            'feedback_sha256': _digest(feedback_file.read_bytes()) if feedback_file and feedback_file.is_file() else None,
            'human_intent': values.get('human_intent', ''),
            'target_word_count': values.get('target_word_count', ''),
            'narrative_pov': values.get('narrative_pov', 'third_person')}


def prepare(root, chapter, task_id):
    chapter = quality().chapter_number(chapter)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
        raise ValueError('独立审稿缺少有效任务编号')
    frozen_contract=book_contract.freeze(root,task_id)['contract']
    raw = _path(root, f'story/{chapter}/chapter.md').read_bytes()
    body = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    if not body.strip():
        raise ValueError('独立审稿需要完整正文')
    project = _path(root, '.novel-project.json')
    state = _load(project) if project.is_file() else {}
    values = state.get('values', {})
    folder = f'cache/reader-review/{chapter}/{task_id}'
    outputs = {'reader_blind_input': folder + '/blind-input.json',
               'reader_blind_raw_path': folder + '/blind-raw.json',
               'reader_blind_report': folder + '/blind-report.json',
               'reader_blind_feedback': folder + '/blind-feedback.md',
               'reader_context_report_path': folder + '/context-report.json',
               'reader_context_feedback': folder + '/context-feedback.md',
               'reader_review_binding': folder + '/binding.json'}
    payload = {'chapter_number': chapter, 'manuscript': body,
               'style_contract':book_contract.public_style(frozen_contract),
               'evidence_catalog':[{k:r[k] for k in ('id','kind','text')} for r in evidence.catalog(body)],
               'genre': values.get('genre', ''), 'language': values.get('language', '中文'),
               'narrative_pov': values.get('narrative_pov', 'third_person'),
               'story_scope': 'short_full' if state.get('mode') == 'short' else values.get('conflict_plan_mode', 'serial_chapter')}
    binding = {'schema': 1, 'task_id': task_id, 'chapter_number': chapter,
               'body_sha256': _digest(raw), 'scope_source': _scope_source(root,frozen_contract), 'outputs': outputs,
               'input_sha256': _digest((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))}
    binding_path = _path(root, outputs['reader_review_binding'])
    if binding_path.is_file() and _load(binding_path) != binding:
        raise ValueError('同任务独立审稿输入已有变化，请新建审稿任务')
    input_path = _path(root, outputs['reader_blind_input'])
    if input_path.is_file() and _digest(input_path.read_bytes()) != binding['input_sha256']:
        raise ValueError('同任务冻结原文输入已有变化')
    _save(input_path, payload)
    _save(binding_path, binding)
    for key in ('reader_context_feedback','reader_blind_feedback'):
        feedback=_path(root,outputs[key])
        if not feedback.exists():quality().atomic_text(feedback,'')
    return {**outputs, 'reader_review_binding_sha': _digest(binding_path.read_bytes())}


def _bound(root, binding_path, expected_sha):
    path = _path(root, binding_path)
    if not expected_sha or _digest(path.read_bytes()) != expected_sha:
        raise ValueError('独立审稿任务凭证已有变化')
    binding = _load(path)
    chapter = quality().chapter_number(binding['chapter_number'])
    raw = _path(root, f'story/{chapter}/chapter.md').read_bytes()
    if (_digest(raw) != binding['body_sha256'] or _scope_source(root) != binding['scope_source']
            or _digest(_path(root, binding['outputs']['reader_blind_input']).read_bytes()) != binding['input_sha256']):
        raise ValueError('正文或作者修改要求在审稿过程中有变化')
    return binding, raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')


def validate_blind(report, body):
    report=evidence.resolve_report(report,body)
    if (not isinstance(report, dict) or report.get('verdict') not in {'pass', 'revise', 'reject'}
            or not isinstance(report.get('issues'), list) or not isinstance(report.get('decisions'), list)):
        raise ValueError('独立审稿缺少有效结论、问题或关键决定检查')
    result = copy.deepcopy(report)
    _text(result, ['summary'])
    decisions = {}
    for decision in result['decisions']:
        if not isinstance(decision, dict):
            raise ValueError('因果检查结构无效')
        _text(decision, ['id', 'actor', 'choice', 'known_before', 'leverage', 'consequence'])
        alternatives = decision.get('alternatives')
        if not ((isinstance(alternatives, str) and alternatives.strip()) or
                (isinstance(alternatives, list) and alternatives
                 and all(isinstance(choice, str) and choice.strip() for choice in alternatives))):
            raise ValueError('因果检查可选行为须为有效文字或非空文字列表')
        if decision['id'] in decisions or decision.get('assessment') not in {'supported', 'gap', 'uncertain'}:
            raise ValueError('因果检查编号或结论无效')
        _quotes(decision, body)
        decisions[decision['id']] = decision
    ids = set()
    for index, issue in enumerate(result['issues'], 1):
        if not isinstance(issue, dict):
            raise ValueError('独立审稿问题结构无效')
        issue.setdefault('id', f'blind-{index}')
        _text(issue, ['id', 'location', 'impact', 'goal'])
        if (issue['id'] in ids or issue.get('kind') not in {'fact', 'expression', 'causality'}
                or issue.get('priority') not in {'low', 'medium', 'high'}):
            raise ValueError('独立审稿问题编号、类别或等级无效')
        ids.add(issue['id'])
        _quotes(issue, body)
        if issue['kind'] == 'causality' and issue.get('decision_id') not in decisions:
            raise ValueError('因果问题缺少对应的关键决定检查')
    for key, decision in decisions.items():
        if decision['assessment'] == 'gap' and not any(
                i.get('decision_id') == key and i['kind'] == 'causality' and i['priority'] in {'medium', 'high'}
                for i in result['issues']):
            raise ValueError('因果缺口必须保留有原文依据的实质问题')
    blocking = any(i['priority'] in {'medium', 'high'} for i in result['issues'])
    if result['verdict'] != 'pass' and not blocking:
        raise ValueError('独立审稿返修结论缺少实质问题')
    if blocking and result['verdict'] == 'pass':
        result['verdict'] = 'revise'
    expression_rules.validate_checks(result,body)
    return result


def commit_blind(root, binding_path, expected_sha):
    binding, body = _bound(root, binding_path, expected_sha)
    try:
        report = validate_blind(_load(_path(root, binding['outputs']['reader_blind_raw_path'])), body)
    except (ValueError,TypeError,KeyError) as exc:
        raise InvalidReviewReport(str(exc)) from exc
    report.update(chapter_number=binding['chapter_number'], body_sha256=binding['body_sha256'])
    path = _path(root, binding['outputs']['reader_blind_report'])
    _save(path, report)
    return {'reader_blind_report_sha': _digest(path.read_bytes())}


def _issue_id(issue):
    fields = {key: issue.get(key) for key in ('location', 'excerpts', 'impact', 'goal')}
    return 'final-' + _digest(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8'))[:12]


def gate_review(report, body):
    if 'reader_review_version' not in report:
        return copy.deepcopy(report)
    result = copy.deepcopy(report)
    if result['reader_review_version'] != 1 or result.get('assessment_scope') != 'whole_chapter':
        raise ValueError('整篇独立审稿版本或范围无效')
    blind = validate_blind(result.get('blind_review'), body)
    result['blind_review'] = blind
    findings = {i['id']: i for i in blind['issues']}
    resolutions = result.get('blind_resolutions', [])
    if not isinstance(resolutions, list):
        raise ValueError('初审问题复核结构无效')
    resolved = set()
    for item in resolutions:
        if not isinstance(item, dict) or item.get('issue_id') not in findings or item['issue_id'] in resolved:
            raise ValueError('初审复核引用了无效或重复的问题编号')
        _text(item, ['reason']); _quotes(item, body)
        resolved.add(item['issue_id'])
    expression = result.get('expression_review')
    if not isinstance(expression, dict) or not isinstance(expression.get('issues'), list):
        raise ValueError('表达审稿缺少具体问题列表')
    contextual_expression = []
    for item in expression['issues']:
        if not isinstance(item, dict):
            raise ValueError('表达审稿问题结构无效')
        if item.get('id') in findings:
            if item.get('initial_review_issue_id') == item['id']:
                continue  # Rebuild canonical findings from the independent source.
            raise ValueError('初审与复评问题编号重复冲突，不能共用修改权限')
        contextual_expression.append(item)
    initial_expression = [dict(item, initial_review_issue_id=item['id']) for item in blind['issues']
                          if item['kind'] == 'expression' and item['id'] not in resolved]
    expression['issues'] = contextual_expression + initial_expression
    if any(i.get('priority') in {'medium', 'high'} for i in expression['issues']):
        if expression.get('verdict') == 'pass':
            expression['verdict'] = 'revise'
    # Attach the independent evidence before validating a contextual verdict
    # which deliberately refers to it instead of duplicating those findings.
    quality().expression_gate(result, body)
    scope = result.get('revision_scope')
    if (not isinstance(scope, dict) or scope.get('mode') not in {'unrestricted', 'restricted', 'unclear'}
            or not isinstance(scope.get('assessments'), list)):
        raise ValueError('整篇质量结论必须与本次修改范围分别给出')
    _text(scope, ['summary'])
    base_issues = [i for i in result.get('issues', []) if i.get('source') != 'blind_review']
    base_issues += [dict(i, source='blind_review') for i in blind['issues']
                   if i['id'] not in resolved and i['kind'] != 'expression']
    # Expression gating may append a finding later; classify it on every read.
    for issue in base_issues:
        issue.setdefault('id', _issue_id(issue))
    issue_ids = [i['id'] for i in base_issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise ValueError('初审与复评问题编号重复冲突，不能共用修改权限')
    known = {i['id'] for i in base_issues} | set(findings)
    assessments = {}
    for item in scope['assessments']:
        if (not isinstance(item, dict) or item.get('issue_id') not in known
                or item['issue_id'] in assessments or item.get('status') not in {'editable', 'outside_scope', 'unclear'}):
            raise ValueError('修改范围分类缺少有效问题编号或状态')
        _text(item, ['reason'])
        assessments[item['issue_id']] = item
    requires_scope = False
    for issue in base_issues:
        item = assessments.get(issue['id'])
        issue['editability'] = item['status'] if item else 'editable' if scope['mode'] == 'unrestricted' else 'unclear'
        if item:
            issue['scope_reason'] = item['reason']
        requires_scope |= issue.get('priority') in {'medium', 'high'} and issue['editability'] != 'editable'
    result['issues'] = base_issues
    verdicts = {result.get('verdict'), result.get('fact_review', {}).get('verdict'),
                result.get('expression_review', {}).get('verdict')}
    if any(i.get('priority') in {'medium', 'high'} for i in base_issues):
        verdicts.add('revise')
    result['verdict'] = 'reject' if 'reject' in verdicts else 'revise' if 'revise' in verdicts else 'pass'
    if result['verdict'] != 'pass' and not any(i.get('priority') in {'medium', 'high'} for i in base_issues):
        raise ValueError('整篇返修结论缺少可定位且有依据的实质问题')
    result['quality_verdict'] = result['verdict']
    result['requires_scope_confirmation'] = bool(requires_scope)
    expression_rules.validate_checks(result,body)
    return result


def verify_report_scope(root, report):
    """A published permission decision expires when its source instructions change."""
    binding = report.get('review_binding')
    if not isinstance(binding, dict) or not binding.get('task_id'):
        raise ValueError('整篇审稿缺少修改范围来源凭证，请重新评估')
    if binding.get('scope_source') != _scope_source(root):
        raise ValueError('作者修改范围或要求已有变化，请重新评估')
    if binding.get('body_sha256') != report.get('body_sha256'):
        raise ValueError('整篇审稿来源与当前正文绑定不同，请重新评估')


def merge_review(final, blind, body):
    result = evidence.resolve_report(final,body)
    result.update(reader_review_version=1, assessment_scope='whole_chapter', blind_review=validate_blind(blind, body))
    return gate_review(result, body)


def commit(root, binding_path, expected_sha, blind_sha):
    binding, body = _bound(root, binding_path, expected_sha)
    blind_path = _path(root, binding['outputs']['reader_blind_report'])
    if not blind_sha or _digest(blind_path.read_bytes()) != blind_sha:
        raise ValueError('独立审稿报告在复评过程中有变化')
    try:
        report = merge_review(_load(_path(root, binding['outputs']['reader_context_report_path'])), _load(blind_path), body)
    except (ValueError,TypeError,KeyError) as exc:
        raise InvalidReviewReport(str(exc)) from exc
    report.update(chapter_number=binding['chapter_number'], body_sha256=binding['body_sha256'])
    report['review_binding'] = {key: copy.deepcopy(binding[key]) for key in
                               ('task_id', 'scope_source', 'body_sha256', 'input_sha256')}
    report = quality().gate_report(root, binding['chapter_number'], '', report)
    _save(_path(root, f"story/{binding['chapter_number']}/reader_report.json"), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'commit-blind', 'commit'])
    parser.add_argument('--chapter', default='0001')
    parser.add_argument('--binding', default='')
    parser.add_argument('--binding-sha', default='')
    parser.add_argument('--blind-sha', default='')
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == 'prepare':
        outputs = prepare(root, args.chapter, os.environ.get('TASK_ID', ''))
    elif args.action == 'commit-blind':
        try:
            outputs = commit_blind(root, args.binding, args.binding_sha)
        except InvalidReviewReport as exc:
            binding,_=_bound(root,args.binding,args.binding_sha)
            feedback=binding['outputs'].get('reader_blind_feedback')
            if feedback:
                quality().atomic_text(_path(root,feedback),'本轮审稿报告未被采用：'+str(exc)+'\n只修正审稿报告，保持待审正文不变；不要为满足格式虚构问题。没有中高优先级问题时可给pass。\n')
            print('<WF_REJECT_UPSTREAM target="agent_blind_reader">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>')
            return
    else:
        try:
            commit(root, args.binding, args.binding_sha, args.blind_sha)
        except InvalidReviewReport as exc:
            binding,_=_bound(root,args.binding,args.binding_sha)
            feedback=binding['outputs'].get('reader_context_feedback')
            if feedback:
                quality().atomic_text(_path(root,feedback),'本轮审稿报告未被采用：'+str(exc)+'\n只修正报告，保持正文和独立初审不变。每个复评表达问题须有唯一id，范围分类只引用实际存在的问题id。\n')
            print('<WF_REJECT_UPSTREAM target="agent_reader">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>')
            return
        outputs = {}
    for key, value in outputs.items():
        print(f'<WF_VAR>{key}:{value}</WF_VAR>')
    print(json.dumps({'status': 'completed', 'action': args.action}, ensure_ascii=False))


if __name__ == '__main__':
    main()
