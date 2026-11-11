"""Task-bound independent reading and permission-aware review publication."""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
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
_packet_spec=importlib.util.spec_from_file_location('reader_model_view',Path(__file__).resolve().parents[1]/'prose_policy/context_packet.py')
packet=importlib.util.module_from_spec(_packet_spec);_packet_spec.loader.exec_module(packet)


class InvalidReviewReport(ValueError):
    """Model report needs repair; source-integrity failures remain fatal."""



def _guarded_rejection(message):
    spec=importlib.util.spec_from_file_location('plugin_rejection_transport',Path(__file__).resolve().parents[1]/'production_guard/rejections.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.emit(message)

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


def revision_context(root):
    state_path=_path(root,'.novel-project.json');state=_load(state_path) if state_path.is_file() else {}
    values=state.get('values',{});feedback=str(values.get('author_feedback_file') or '').strip()
    author=advice='';sources={}
    if feedback:
        if not _path(root,feedback).is_file():raise ValueError('本次作者意见来源缺失')
        spec=importlib.util.spec_from_file_location('reader_feedback_layers',Path(__file__).resolve().parents[1]/'local_revision/local_revision.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        author,advice,sources=module.feedback_layers(root,feedback)
        origin=(Path(feedback).parent/'automatic-origin.json').as_posix();origin_file=_path(root,origin)
        sources={**sources,origin:_digest(origin_file.read_bytes()) if origin_file.is_file() else None}
    return {'author_feedback':author,'human_intent':str(values.get('human_intent') or ''),
        'automatic_revision_advice':advice,'source_hashes':sources,
        'scope_policy':'只有真实作者要求可以限定本次局部修改权限；自动建议、旧报告和旧段落锚点不能创建禁改范围。没有作者局部限制时按整章处理，但始终保留本书风格、世界规则及既定事实。'}


def validate_revision_scope(root,report):
    context=revision_context(root);scope=report.get('revision_scope') or {}
    if not context['author_feedback'].strip() and not context['human_intent'].strip():
        if scope.get('mode') in ('restricted','unclear') or any(r.get('status') in ('outside_scope','unclear') for r in scope.get('assessments',[])):
            raise InvalidReviewReport('没有已确认的局部修改限制；自动建议及旧报告不能创建作者禁改范围，请按整章权限重新分类，保留实际质量问题及本书规则。')


def _scope_source(root,contract=None,chapter=None):
    project = _path(root, '.novel-project.json')
    state = _load(project) if project.is_file() else {}
    values = state.get('values', {})
    feedback = str(values.get('author_feedback_file') or '').strip()
    feedback_file = _path(root, feedback) if feedback else None
    number=chapter or str(values.get('chapter_number','0001')).zfill(4)
    budget_files=['meta/length_policy.json',f'planning/length/{number}.json']
    return {'feedback_path': feedback,'feedback_sources':revision_context(root)['source_hashes'],
            'composition_sources':{p:_digest(_path(root,p).read_bytes()) if _path(root,p).is_file() else None for p in budget_files},
            'book_contract_sha256':book_contract.digest(book_contract.resolve(root) if contract is None else contract),
            'feedback_sha256': _digest(feedback_file.read_bytes()) if feedback_file and feedback_file.is_file() else None,
            'human_intent': values.get('human_intent', ''),
            'target_word_count': values.get('target_word_count', ''),
            'narrative_pov': values.get('narrative_pov', 'third_person')}


def prepare(root, chapter, task_id,parallel=False):
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
    outputs = {'reader_revision_context':folder+'/revision-context.json','reader_blind_model':folder+'/blind-model.json',
               'reader_preflight_raw_path':folder+'/context-preflight-raw.json','reader_preflight_path':folder+'/context-preflight.json',
               'reader_preflight_feedback':folder+'/context-preflight-feedback.md','reader_parallel_sources':folder+'/parallel-sources.json',
               'reader_blind_input': folder + '/blind-input.json',
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
    context=revision_context(root)
    binding = {'schema': 1, 'task_id': task_id, 'chapter_number': chapter,
               'body_sha256': _digest(raw), 'scope_source': _scope_source(root,frozen_contract,chapter), 'outputs': outputs,
               'input_sha256': _digest((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')),
               'revision_context_digest':_digest(json.dumps(context,ensure_ascii=False,sort_keys=True).encode())}
    if parallel:binding.update(schema=2,parallel_required=True)
    binding_path = _path(root, outputs['reader_review_binding'])
    if binding_path.is_file() and _load(binding_path) != binding:
        raise ValueError('同任务独立审稿输入已有变化，请新建审稿任务')
    input_path = _path(root, outputs['reader_blind_input'])
    if input_path.is_file() and _digest(input_path.read_bytes()) != binding['input_sha256']:
        raise ValueError('同任务冻结原文输入已有变化')
    _save(input_path, payload)
    view_path=_path(root,outputs['reader_blind_model']);view=packet.blind(payload)
    if view_path.is_file() and _load(view_path)!=view:raise ValueError('同任务盲读模型输入已有变化')
    _save(view_path,view)
    context_path=_path(root,outputs['reader_revision_context'])
    if context_path.is_file() and _load(context_path)!=context:raise ValueError('同任务作者范围分层已有变化')
    _save(context_path,context)
    _save(binding_path, binding)
    for key in ('reader_context_feedback','reader_blind_feedback','reader_preflight_feedback'):
        feedback=_path(root,outputs[key])
        if not feedback.exists():quality().atomic_text(feedback,'')
    return {**outputs, 'reader_review_binding_sha': _digest(binding_path.read_bytes())}


def _bound(root, binding_path, expected_sha,*,allow_unfrozen=False):
    path = _path(root, binding_path)
    if not expected_sha or _digest(path.read_bytes()) != expected_sha:
        raise ValueError('独立审稿任务凭证已有变化')
    binding = _load(path)
    verify_parallel(root,binding,allow_unfrozen=allow_unfrozen)
    chapter = quality().chapter_number(binding['chapter_number'])
    raw = _path(root, f'story/{chapter}/chapter.md').read_bytes()
    context=revision_context(root)
    if binding['outputs'].get('reader_blind_model'):
        packet.verify(_load(_path(root,binding['outputs']['reader_blind_model'])),
            _load(_path(root,binding['outputs']['reader_blind_input'])),'blind-reader')
    if (_digest(raw) != binding['body_sha256'] or _scope_source(root,chapter=chapter) != binding['scope_source']
            or _digest(json.dumps(context,ensure_ascii=False,sort_keys=True).encode())!=binding.get('revision_context_digest')
            or _load(_path(root,binding['outputs']['reader_revision_context']))!=context
            or _digest(_path(root, binding['outputs']['reader_blind_input']).read_bytes()) != binding['input_sha256']):
        raise ValueError('正文或作者修改要求在审稿过程中有变化')
    return binding, raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')


def parallel_support():
    path=Path(__file__).resolve().parents[1]/'local_revision/local_revision.py'
    spec=importlib.util.spec_from_file_location('parallel_local_sources',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def parallel_profile():
    here=Path(__file__).resolve().parents[1];resources=here.parent.parent
    scripts=[Path(__file__),*sorted((here/'prose_policy').glob('*.py')),*sorted((here/'local_revision').glob('*.py'))]
    files={str(Path('script-library/xs2')/p.relative_to(here)):p for p in scripts}
    spec=importlib.util.spec_from_file_location('reader_resources',here/'production_guard/production_guard.py')
    locator=importlib.util.module_from_spec(spec);spec.loader.exec_module(locator)
    configs={str(Path(name)):locator.resource(here,name) for name in ('prompts.json','workflows/reader-sim/definition.json')}
    return _digest(json.dumps({name:_digest(p.read_bytes()) for name,p in {**files,**configs}.items()},sort_keys=True).encode())


def parallel_sources(root,binding,context_path,runtime_path=''):
    if not _path(root,context_path).is_file():raise ValueError('并行资料审查缺少实际冻结上下文文件')
    m=parallel_support();sources=m.source_files(root,binding['chapter_number'],context_path,'')
    if runtime_path:
        directory=_path(root,runtime_path)
        if not directory.is_dir():raise ValueError('本书动态文风资料目录缺失')
        for p in sorted(directory.rglob('*')):
            if p.is_file():sources[p.relative_to(Path(root).resolve()).as_posix()]=_digest(p.read_bytes())
    return sources


def freeze_parallel(root,binding_path,expected_sha,context_path='cache/story-support/context.md',runtime_path=''):
    runtime_path=str(runtime_path or '').strip()
    binding,_=_bound(root,binding_path,expected_sha,allow_unfrozen=True);m=parallel_support()
    sources=parallel_sources(root,binding,context_path,runtime_path)
    value={'binding_sha256':expected_sha,'sources':sources,'context_path':context_path,'runtime_path':runtime_path,'profile':parallel_profile()}
    relative=binding['outputs']['reader_parallel_sources'];path=_path(root,relative)
    if path.exists():
        if _load(path)!=value:raise ValueError('并行审稿冻结来源变化')
    else:
        s=m.pending.support()
        s.archive_store().publish_views(root,lambda write:write(root,relative,value),lambda:{p:h or '' for p,h in sources.items()})
    verify_parallel(root,binding)
    return {}


def verify_parallel(root,binding,*,allow_unfrozen=False):
    relative=binding['outputs'].get('reader_parallel_sources')
    if not relative:
        if binding.get('parallel_required'):raise ValueError('并行审稿缺少冻结来源路径')
        return
    m=parallel_support();s=m.pending.support();store=s.archive_store();store.recover(root)
    if not _path(root,relative).is_file():
        if not binding.get('parallel_required'):return
        if allow_unfrozen:
            if not _path(root,'archive/longform.sqlite3').is_file():return
            with closing(store.connect(root)) as db:
                if not db.execute('SELECT id FROM publications WHERE instr(content,?)>0 LIMIT 1',(relative,)).fetchone():return
        raise ValueError('本任务的并行冻结凭据缺失，不能降级或重新绑定已开始的审稿')
    value=s.serial()._signed_output(root,relative)
    sources=parallel_sources(root,binding,value['context_path'],value.get('runtime_path',''))
    if (sources!=value['sources'] or value['profile']!=parallel_profile()
            or value['binding_sha256']!=_digest(_path(root,binding['outputs']['reader_review_binding']).read_bytes())):
        raise ValueError('并行审稿资料或版本变化，不能合并旧结果')


def commit_context(root,binding_path,expected_sha):
    binding,body=_bound(root,binding_path,expected_sha)
    try:
        report=_load(_path(root,binding['outputs']['reader_preflight_raw_path']))
        if report.get('blind_resolutions')!=[]:raise ValueError('独立资料审查不能猜测或裁决尚未看见的盲读问题')
        validate_revision_scope(root,report)
        empty={'verdict':'pass','summary':'独立资料审查尚未读取盲读结论。','issues':[],'decisions':[]}
        validated=merge_review(report,empty,body,book_contract.resolve(root).get('reading_contract',{}))
    except (ValueError,TypeError,KeyError) as exc:raise InvalidReviewReport(str(exc)) from exc
    path=_path(root,binding['outputs']['reader_preflight_path']);_save(path,validated)
    return {'reader_preflight_sha':_digest(path.read_bytes())}


def join(root,binding_path,expected_sha,blind_sha,context_sha):
    binding,body=_bound(root,binding_path,expected_sha)
    blind_path=_path(root,binding['outputs']['reader_blind_report']);context_path=_path(root,binding['outputs']['reader_preflight_path'])
    if not blind_sha or _digest(blind_path.read_bytes())!=blind_sha or not context_sha or _digest(context_path.read_bytes())!=context_sha:
        raise ValueError('并行审稿分支缺失或已变化，不能合并')
    blind=validate_blind(_load(blind_path),body);context=_load(context_path)
    # Preserve dependent reasoning whenever there is anything to reconcile.
    required=bool(blind['issues'] or any(d['assessment']!='supported' for d in blind['decisions']))
    if not required:_save(_path(root,binding['outputs']['reader_context_report_path']),context)
    return {'reader_reconcile_required':'yes' if required else 'no'}


def validate_blind(report, body,reading_contract=None):
    report=evidence.resolve_report(report,body)
    report=book_contract.reading().apply(report,body,reading_contract)
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
        expression_rules.validate_narrative_issue(issue)
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
        public=_load(_path(root,binding['outputs']['reader_blind_input']))['style_contract'].get('reading_contract',{})
        report = validate_blind(_load(_path(root, binding['outputs']['reader_blind_raw_path'])), body,public)
    except (ValueError,TypeError,KeyError) as exc:
        raise InvalidReviewReport(str(exc)) from exc
    report.update(chapter_number=binding['chapter_number'], body_sha256=binding['body_sha256'])
    path = _path(root, binding['outputs']['reader_blind_report'])
    _save(path, report)
    return {'reader_blind_report_sha': _digest(path.read_bytes())}


def _issue_id(issue):
    fields = {key: issue.get(key) for key in ('location', 'excerpts', 'impact', 'goal')}
    return 'final-' + _digest(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8'))[:12]


def gate_review(report, body,reading_contract=None):
    if 'reader_review_version' not in report:
        return copy.deepcopy(report)
    result = book_contract.reading().apply(report,body,reading_contract)
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
    # Contextual reading goals are independently rechecked below. Blind goal
    # findings are preserved as independent issues, not duplicate expressions.
    initial_expression = [dict(item, initial_review_issue_id=item['id']) for item in blind['issues']
                          if item['kind'] == 'expression' and item['id'] not in resolved and item.get('source')!='reading_contract']
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
    base_issues += [dict(i, source='blind_review',id=('blind-'+i['id'] if i.get('source')=='reading_contract' else i['id'])) for i in blind['issues']
                   if i['id'] not in resolved and (i['kind'] != 'expression' or i.get('source')=='reading_contract')]
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
    if binding.get('scope_source') != _scope_source(root,chapter=report.get('chapter_number')):
        raise ValueError('作者修改范围或要求已有变化，请重新评估')
    if binding.get('body_sha256') != report.get('body_sha256'):
        raise ValueError('整篇审稿来源与当前正文绑定不同，请重新评估')


def merge_review(final, blind, body,reading_contract=None):
    result = evidence.resolve_report(final,body)
    result.update(reader_review_version=1, assessment_scope='whole_chapter', blind_review=validate_blind(blind, body))
    return gate_review(result, body,reading_contract)


def commit(root, binding_path, expected_sha, blind_sha,context_sha=''):
    binding, body = _bound(root, binding_path, expected_sha)
    blind_path = _path(root, binding['outputs']['reader_blind_report'])
    if not blind_sha or _digest(blind_path.read_bytes()) != blind_sha:
        raise ValueError('独立审稿报告在复评过程中有变化')
    blind=_load(blind_path)
    parallel=binding['outputs'].get('reader_parallel_sources')
    if binding.get('parallel_required') or (parallel and _path(root,parallel).is_file()):
        preflight=_path(root,binding['outputs']['reader_preflight_path'])
        if not context_sha or _digest(preflight.read_bytes())!=context_sha:raise ValueError('独立资料分支的实际报告绑定已变化')
        required=bool(blind['issues'] or any(d['assessment']!='supported' for d in blind['decisions']))
        if not required and _load(_path(root,binding['outputs']['reader_context_report_path']))!=_load(preflight):
            raise ValueError('快速汇合报告不属于已核验的独立资料分支')
    try:
        contextual=_load(_path(root, binding['outputs']['reader_context_report_path']))
        validate_revision_scope(root,contextual)
        report = merge_review(contextual, _load(blind_path), body,book_contract.resolve(root).get('reading_contract',{}))
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
    parser.add_argument('action', choices=['prepare', 'freeze-parallel', 'commit-context', 'join', 'bypass', 'commit-blind', 'commit'])
    parser.add_argument('--chapter', default='0001')
    parser.add_argument('--binding', default='')
    parser.add_argument('--binding-sha', default='')
    parser.add_argument('--blind-sha', default='')
    parser.add_argument('--context-sha',default='')
    parser.add_argument('--context',default='cache/story-support/context.md')
    parser.add_argument('--parallel',action='store_true')
    parser.add_argument('--runtime',default='')
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == 'prepare':
        outputs = prepare(root, args.chapter, os.environ.get('TASK_ID', ''),args.parallel)
    elif args.action=='freeze-parallel':outputs=freeze_parallel(root,args.binding,args.binding_sha,args.context,args.runtime)
    elif args.action=='join':outputs=join(root,args.binding,args.binding_sha,args.blind_sha,args.context_sha)
    elif args.action=='bypass':_bound(root,args.binding,args.binding_sha);outputs={}
    elif args.action=='commit-context':
        try:outputs=commit_context(root,args.binding,args.binding_sha)
        except InvalidReviewReport as exc:
            binding,_=_bound(root,args.binding,args.binding_sha)
            quality().atomic_text(_path(root,binding['outputs']['reader_preflight_feedback']),'只修正独立资料审稿报告，不改正文或猜测盲读结论：'+str(exc))
            _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_context_reader">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>');return
    elif args.action == 'commit-blind':
        try:
            outputs = commit_blind(root, args.binding, args.binding_sha)
        except InvalidReviewReport as exc:
            binding,_=_bound(root,args.binding,args.binding_sha)
            feedback=binding['outputs'].get('reader_blind_feedback')
            if feedback:
                quality().atomic_text(_path(root,feedback),'本轮审稿报告未被采用：'+str(exc)+'\n只修正审稿报告，保持待审正文不变；不要为满足格式虚构问题。没有中高优先级问题时可给pass。\n')
            _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_blind_reader">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>')
            return
    else:
        try:
            commit(root, args.binding, args.binding_sha, args.blind_sha,args.context_sha)
        except InvalidReviewReport as exc:
            binding,_=_bound(root,args.binding,args.binding_sha)
            blind=_load(_path(root,binding['outputs']['reader_blind_report']))
            required=bool(blind['issues'] or any(d['assessment']!='supported' for d in blind['decisions']))
            fast=bool(binding['outputs'].get('reader_parallel_sources') and _path(root,binding['outputs']['reader_parallel_sources']).is_file() and not required)
            feedback=binding['outputs'].get('reader_preflight_feedback' if fast else 'reader_context_feedback')
            if feedback:
                quality().atomic_text(_path(root,feedback),'本轮审稿报告未被采用：'+str(exc)+'\n只修正报告，保持正文和独立初审不变。每个复评表达问题须有唯一id，范围分类只引用实际存在的问题id。\n')
            _guarded_rejection('<WF_REJECT_UPSTREAM target="'+('agent_context_reader' if fast else 'agent_reader')+'">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>')
            return
        outputs = {}
    for key, value in outputs.items():
        print(f'<WF_VAR>{key}:{value}</WF_VAR>')
    print(json.dumps({'status': 'completed', 'action': args.action}, ensure_ascii=False))


if __name__ == '__main__':
    main()
