"""Task-bound independent reading and permission-aware review publication."""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from contextlib import closing
from difflib import SequenceMatcher
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


def revision_context(root, chapter=None, contract=None):
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
    result = {'author_feedback':author,'human_intent':str(values.get('human_intent') or ''),
        'automatic_revision_advice':advice,'source_hashes':sources,
        'scope_policy':'只有真实作者要求可以限定本次局部修改权限；自动建议、旧报告和旧段落锚点不能创建禁改范围。没有作者局部限制时按整章处理，但始终保留本书风格、世界规则及既定事实。'}
    if chapter is not None:
        reading = book_contract.reading()
        contract = (contract if contract is not None else book_contract.resolve(root)).get('reading_contract', {})
        delivered = set(reading.delivered_candidates(root, chapter, contract))
        goals = [goal for goal in contract.get('objectives', []) if goal.get('source_dimension')
                 and goal['source_candidate_id'] in delivered]
        choices = book_contract.references().selected_guidance(root, chapter)
        if choices:
            result['optional_scene_references'] = {'guidance': choices, 'review': '仅评价本章实际使用的效果；未采用或另写不构成缺陷。'}
        if goals:
            result['applied_reference_review'] = {'objectives': goals, 'guidance': reading.GUIDANCE}
    return result


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


def _addition_refs(root, chapter, raw, contract_sha):
    """Identify changed prose from a matching, accepted local revision."""
    current_sha = _digest(raw)
    previous = set()
    for receipt_path in _path(root, 'cache/local-revision').glob('*/receipt.json'):
        folder = receipt_path.parent.relative_to(Path(root).resolve()).as_posix()
        try:
            receipt = _load(_path(root, folder + '/receipt.json'))
            if (receipt.get('accepted') is not True or receipt.get('after_sha256') != current_sha
                    or receipt.get('book_contract_sha256') != contract_sha):
                continue
            binding = _load(_path(root, folder + '/source-binding.json'))
            old = _path(root, folder + '/source.md').read_bytes()
            if (receipt.get('task_id') == binding.get('task_id') == receipt_path.parent.name
                    and binding.get('body_path') == f'story/{chapter}/chapter.md'
                    and receipt.get('before_sha256') == binding.get('body_sha256') == _digest(old)):
                previous.add(old.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n'))
        except (OSError, ValueError, AttributeError):
            continue
    if len(previous) != 1:
        return []
    old = [row['text'] for row in packet.prose(previous.pop())['paragraphs']]
    body = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    current = packet.prose(body)['paragraphs']
    matches = SequenceMatcher(None, old, [row['text'] for row in current], autojunk=False)
    return [row['id'] for kind, start, end, first, last in matches.get_opcodes()
            if kind == 'insert' or (kind == 'replace' and
                sum(len(row['text']) for row in current[first:last]) > sum(map(len, old[start:end])))
            for row in current[first:last]]


def prepare(root, chapter, task_id,parallel=False,*,protocol=1):
    chapter = quality().chapter_number(chapter)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
        raise ValueError('独立审稿缺少有效任务编号')
    if protocol not in (1, 2) or (protocol == 2 and not parallel):
        raise ValueError('审稿协议与任务执行方式不匹配')
    frozen_contract=book_contract.freeze(root,task_id,chapter=chapter)['contract']
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
               'style_contract':book_contract.public_style(book_contract.chapter_view(root,chapter,frozen_contract)),
               'evidence_catalog':[{k:r[k] for k in ('id','kind','text')} for r in evidence.catalog(body)],
               'genre': values.get('genre', ''), 'language': values.get('language', '中文'),
               'narrative_pov': values.get('narrative_pov', 'third_person'),
               'story_scope': 'short_full' if state.get('mode') == 'short' else values.get('conflict_plan_mode', 'serial_chapter')}
    context=revision_context(root,chapter,frozen_contract)
    binding = {'schema': 1, 'task_id': task_id, 'chapter_number': chapter,
               'body_sha256': _digest(raw), 'scope_source': _scope_source(root,frozen_contract,chapter), 'outputs': outputs,
               'input_sha256': _digest((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')),
               'revision_context_digest':_digest(json.dumps(context,ensure_ascii=False,sort_keys=True).encode())}
    if parallel:binding.update(schema=2,parallel_required=True)
    binding_path = _path(root, outputs['reader_review_binding'])
    if protocol == 2:
        outputs.update(reader_fact_sources=folder+'/fact-sources.json', reader_fact_conflicts=folder+'/fact-conflicts.json')
        input_path = _path(root, outputs['reader_blind_input'])
        # Re-entered prepare must use the original neutral scope even if a later
        # receipt now exists for the same unchanged prose.
        if binding_path.is_file() and input_path.is_file():
            additions = _load(input_path).get('new_passage_refs', [])
        else:
            additions = _addition_refs(root, chapter, raw, book_contract.digest(frozen_contract))
        payload['new_passage_refs'] = additions
        binding.update(reader_protocol=2,
                       input_sha256=_digest((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')))
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
    context=revision_context(root,chapter)
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
    scripts=[Path(__file__),here/'reference_distill/reference_choices.py',*sorted((here/'prose_policy').glob('*.py')),*sorted((here/'local_revision').glob('*.py'))]
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
    if binding.get('reader_protocol') == 2:
        _save(_path(root, binding['outputs']['reader_fact_sources']), _fact_sources(root, binding, sources))
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


def _validate_expression_dimensions(report):
    rows = report.get('expression_checks') if isinstance(report, dict) else None
    if not isinstance(rows, list):
        raise ValueError('expression_checks 必须包含每个表达检查维度')
    dimensions = expression_rules.DIMENSIONS
    counts = Counter()
    for index, row in enumerate(rows):
        dimension = row.get('dimension') if isinstance(row, dict) else None
        if dimension not in dimensions:
            raise ValueError(f'expression_checks[{index}].dimension 不在审稿维度中')
        if row.get('status') in ('pass', 'not_applicable'):
            row.setdefault('issue_ids', [])
        counts[dimension] += 1
    repeated = [key for key in dimensions if counts[key] > 1]
    missing = [key for key in dimensions if counts[key] == 0]
    if repeated or missing:
        details = [f'重复 {", ".join(repeated)}'] if repeated else []
        if missing:
            details.append(f'缺少 {", ".join(missing)}')
        raise ValueError('expression_checks 每个维度只写一项，' + '；'.join(details))


def _normalize_contextual_report(report):
    _validate_expression_dimensions(report)
    general_issues = report['issues']
    expression_issues = report['expression_review']['issues']
    general_by_id = {}
    for index, issue in enumerate(general_issues):
        key = issue.get('id') if isinstance(issue, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r'context-[A-Za-z0-9_-]+', key):
            raise ValueError(f'issues[{index}].id 须使用 context- 开头的问题编号')
        if key in general_by_id:
            raise ValueError(f'issues[{index}].id 重复使用问题编号 {key}')
        general_by_id[key] = issue
    expression_ids = set()
    for index, issue in enumerate(expression_issues):
        key = issue.get('id') if isinstance(issue, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r'context-[A-Za-z0-9_-]+', key):
            raise ValueError(f'expression_review.issues[{index}].id 须使用 context- 开头的问题编号')
        if key in expression_ids or (key in general_by_id and general_by_id[key] != issue):
            raise ValueError(f'expression_review.issues[{index}].id 重复使用问题编号 {key}，两个问题列表共用同一编号空间')
        expression_ids.add(key)
    # A literal copy needs only one scope assessment. Keep its evidence-bearing form.
    report['issues'] = [issue for issue in general_issues if issue['id'] not in expression_ids]


def _fact_sources(root, binding, sources):
    chapters, _ = parallel_support().pending.support().confirmed(root, before=int(binding['chapter_number']))
    files = ['meta/world_foundation.md', 'meta/character_profiles.md']
    files.extend(f"story/{chapter['chapter']}/confirmed_state.json" for chapter in chapters)
    view = book_contract.chapter_view(root, binding['chapter_number'], book_contract.resolve(root))
    result = {'book_contract': json.dumps(view, ensure_ascii=False, indent=2)}
    for name in files:
        if sources.get(name):
            raw = _path(root, name).read_bytes()
            if _digest(raw) != sources[name]:
                raise ValueError('资料审稿来源已有变化')
            result[name] = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    return result


def _fact_packet(root, binding):
    source = _load(_path(root, binding['outputs']['reader_parallel_sources']))
    expected = _fact_sources(root, binding, source['sources'])
    if _load(_path(root, binding['outputs']['reader_fact_sources'])) != expected:
        raise ValueError('资料审稿可核对事实的冻结文本已有变化')
    return expected


def _claim_position(body, claim):
    if isinstance(claim, str):
        if not claim.strip() or body.find(claim) < 0 or body.find(claim, body.find(claim) + 1) >= 0:
            raise ValueError('事实引文须唯一定位，重复用段落或出现次数定位')
        start = body.index(claim)
        return start, start + len(claim)
    return evidence.position(body, claim)


def _normalize_fact_claim(item, body, sources, path):
    if not isinstance(item, dict):
        raise ValueError(f'{path} 须为事实凭据对象')
    quote = item.get('source_quote')
    if (not isinstance(quote, str) or not quote.strip() or quote not in sources.get(item.get('source_path'), '')):
        raise ValueError(f'{path}.source_quote 须逐字来自对应冻结事实来源')
    start, end = _claim_position(body, item.get('claim'))
    return body[start:end]


def _commit_context_v2(root, binding, raw, body):
    sources = _fact_packet(root, binding)
    if not isinstance(raw, dict) or set(raw) - {'summary', 'fact_review', 'issues', 'revision_scope', 'fact_support'}:
        raise ValueError('独立资料审稿只接收事实、权限和对应凭据')
    result = evidence.resolve_report(raw, body, reader_excerpts=True)
    _text(result, ['summary'])
    ids = set()
    for index, item in enumerate(result['issues']):
        path = f'issues[{index}]'
        excerpt = _normalize_fact_claim(item, body, sources, path)
        _text(item, ['id', 'location', 'impact', 'goal'])
        if (not re.fullmatch(r'context-[A-Za-z0-9_-]+', item['id']) or item['id'] in ids
                or item.get('priority') not in ('low', 'medium', 'high')):
            raise ValueError(f'{path} 须使用独立资料分支有效的问题编号和优先级')
        ids.add(item['id'])
        item.update(kind='fact', excerpts=[excerpt])
    for index, item in enumerate(result.get('fact_support', [])):
        _normalize_fact_claim(item, body, sources, f'fact_support[{index}]')
        _text(item, ['reason'])
    scope = result['revision_scope']
    scope.setdefault('assessments', [])
    validate_revision_scope(root, result)
    status = 'revise' if any(item['priority'] != 'low' for item in result['issues']) else 'pass'
    fact_summary = result.get('fact_review', {}).get('summary', result['summary'])
    result.update(verdict=status, fact_review={'verdict':status, 'summary':fact_summary},
                  expression_review={'verdict':'pass', 'summary':'表达以独立盲读为准。', 'issues':[]})
    empty = {'verdict':'pass', 'summary':'独立资料审稿尚未读取盲读结论。', 'issues':[], 'decisions':[]}
    return merge_review(result, empty, body)


def commit_context(root,binding_path,expected_sha):
    binding,body=_bound(root,binding_path,expected_sha)
    try:
        report=_load(_path(root,binding['outputs']['reader_preflight_raw_path']))
        if binding.get('reader_protocol') == 2:
            validated = _commit_context_v2(root, binding, report, body)
        else:
            if not isinstance(report, dict) or report.setdefault('blind_resolutions', []) != []:
                raise ValueError('blind_resolutions 只能省略或为 []，独立资料审查不能裁决尚未看见的盲读问题')
            _normalize_contextual_report(report)
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
    context = _load(context_path)
    if binding.get('reader_protocol') == 2:
        blind = _validate_blind_v2(_load(blind_path), body)
        conflicts = _factual_conflicts(blind, context, body)
        required = bool(conflicts)
        if required:
            _save(_path(root, binding['outputs']['reader_fact_conflicts']), {'conflicts': conflicts})
    else:
        blind = validate_blind(_load(blind_path), body)
        required = _legacy_reconciliation(blind)
    if not required:_save(_path(root,binding['outputs']['reader_context_report_path']),context)
    return {'reader_reconcile_required':'yes' if required else 'no'}


def _legacy_reconciliation(blind):
    return bool(blind['issues'] or any(row['assessment'] != 'supported' for row in blind['decisions']))


def paragraph_coverage(report, body, paragraph_id):
    """Read a coverage receipt or a directly identifiable legacy citation."""
    body = body.replace('\r\n', '\n').replace('\r', '\n')
    report = report.get('blind_review', report)
    if 'coverage' in report:
        found = any(paragraph_id in refs for refs in report['coverage'].values())
        return 'covered' if found else 'not_separately_covered'
    paragraph = next((row for row in evidence.catalog(body) if row['id'] == paragraph_id
                      and row['kind'] == 'paragraph'), None)
    if paragraph is None:
        return 'not_separately_covered'
    for name in ('expression_checks', 'issues', 'decisions'):
        for issue in report.get(name, []):
            for quote in issue.get('excerpts', []):
                try:
                    anchor = evidence.resolve_report(quote, body) if isinstance(quote, dict) else quote
                    start, end = _claim_position(body, anchor)
                except (KeyError, TypeError, ValueError):
                    continue
                if paragraph['start'] <= start < end <= paragraph['end']:
                    return 'covered'
    return 'not_separately_covered'


def _validate_blind_v2(report, body, reading_contract=None, addition_refs=None):
    report = evidence.resolve_report(report, body, reader_excerpts=True)
    coverage = report.get('coverage')
    targets = {'first_exchange', 'key_turn'}
    if (not isinstance(coverage, dict) or not targets <= coverage.keys()
            or coverage.keys() - (targets | {'additions'})):
        raise ValueError('coverage 须给首场交谈和关键转折的实际段号')
    paragraphs = {row['id']: index for index, row in enumerate(packet.prose(body)['paragraphs'])}
    for name, refs in coverage.items():
        if not isinstance(refs, list) or any(ref not in paragraphs for ref in refs):
            raise ValueError(f'coverage.{name} 只能用实际检查的当前正文段号')
        indices = [paragraphs[ref] for ref in refs]
        if indices != sorted(set(indices)):
            raise ValueError(f'coverage.{name} 段号须按正文顺序且不重复')
        if name == 'additions' and addition_refs is not None and not set(refs) <= set(addition_refs):
            raise ValueError('coverage.additions 只能标记实际提供的新增正文')
    material = set()
    for issue in report['issues']:
        proof = issue.get('contradiction')
        if issue.get('kind') == 'expression':
            issue['priority'] = 'low'
            actionability = issue.setdefault('actionability', 'advisory')
            if actionability not in ('targeted', 'advisory'):
                raise ValueError('表达意见的 actionability 须为 targeted 或 advisory')
            if actionability == 'targeted':
                start = expression_rules.scene_focus_position(issue, body)
                if start is None:
                    raise ValueError('可局部处理的表达意见须提供 scene_focus 和相邻真实依据')
                target = issue['scene_focus']
                end = start + len(target['quote'])
                if any(start < match.end() and match.start() < end for match in packet.SPEECH.finditer(body)):
                    _text(target, ['addressee'])
        elif proof is None:
            issue['priority'] = 'low'
        else:
            claim = _claim_position(body, proof.get('claim'))
            against = _claim_position(body, proof.get('against'))
            if max(claim[0], against[0]) < min(claim[1], against[1]):
                raise ValueError('事实矛盾的主张和反证须是两处独立原文')
            issue['excerpts'] = list(dict.fromkeys([*issue.get('excerpts', []),
                body[slice(*claim)], body[slice(*against)]]))
            if issue.get('priority') in ('medium', 'high') and issue.get('kind') == 'causality':
                material.add(issue.get('decision_id'))
    for decision in report['decisions']:
        if decision.get('assessment') == 'gap' and decision.get('id') not in material:
            decision['assessment'] = 'uncertain'
    report['verdict'] = 'pass'
    return validate_blind(report, body, reading_contract)


def _factual_conflicts(blind, context, body):
    supported = {}
    for row in context.get('fact_support', []):
        claim = _claim_position(body, row['claim'])
        supported.setdefault(claim, []).append(row)
    result = []
    for issue in blind['issues']:
        if issue.get('kind') not in ('fact', 'causality') or issue.get('priority') not in ('medium', 'high'):
            continue
        claim_start, claim_end = _claim_position(body, issue['contradiction']['claim'])
        # The independent branches may cite a sentence and a clause within it.
        matching_support = [
            row for (start, end), rows in supported.items()
            if start <= claim_start < claim_end <= end or claim_start <= start < end <= claim_end
            for row in rows
        ]
        if matching_support:
            result.append({'issue': issue, 'book_support': matching_support})
    return result


def _validate_resolution_anchor(item, issue, body):
    claim_start, claim_end = _claim_position(body, issue['contradiction']['claim'])
    positions = [evidence.position(body, anchor) for anchor in item['evidence_anchors']]
    if (not any(start <= claim_start < claim_end <= end for start, end in positions)
            or not any(end <= claim_start or start >= claim_end for start, end in positions)):
        raise ValueError('事实复核须分别引用该主张的确切位置和另一处当前正文反证')
    if item['excerpts'] != [body[start:end] for start, end in positions]:
        raise ValueError('事实复核引文与定位不一致')


def _apply_factual_resolutions(raw, contextual, conflicts, body):
    if not isinstance(raw, dict) or set(raw) != {'blind_resolutions'} or not isinstance(raw['blind_resolutions'], list):
        raise ValueError('事实复核只返回 blind_resolutions 数组')
    choices = []
    targets = {row['issue']['id']: row['issue'] for row in conflicts}
    seen = set()
    for item in raw['blind_resolutions']:
        _text(item, ['issue_id', 'reason'])
        issue_id = item['issue_id']
        if issue_id not in targets or issue_id in seen:
            raise ValueError('事实复核只能裁决已定位的冲突编号且不得重复')
        anchors = []
        for index, raw_quote in enumerate(item['excerpts']):
            resolved = evidence.resolve_report(raw_quote, body) if isinstance(raw_quote, dict) else raw_quote
            try:
                start, end = _claim_position(body, resolved)
            except ValueError as exc:
                raise ValueError(f'blind_resolutions[{len(choices)}].excerpts[{index}] 无法定位当前原文') from exc
            if isinstance(resolved, str):
                resolved = {'text':body[start:end], 'occurrence':1}
            anchors.append(resolved)
        normalized = {**item, 'excerpts':[anchor['text'] for anchor in anchors], 'evidence_anchors':anchors}
        _validate_resolution_anchor(normalized, targets[issue_id], body)
        choices.append(normalized)
        seen.add(issue_id)
    return {**contextual, 'blind_resolutions': choices}


def validate_decision_evidence(decision,body):
    # Historical reports only carry free-text excerpts. New model output
    # supplies independent anchors for the trigger and the response.
    if 'causal_evidence' not in decision:
        return
    proof=decision['causal_evidence']
    if not isinstance(proof,dict) or proof.get('order') not in {'continuous','nonlinear','missing'}:
        raise ValueError('关键决定缺少有效知情顺序凭据')
    reaction,_=evidence.position(body,proof.get('reaction'))
    knowledge=proof.get('knowledge')
    if proof['order']=='missing':
        if knowledge is not None or decision['assessment']=='supported':
            raise ValueError('知情顺序缺少触发依据时不能判定成立')
        return
    _,knowledge_end=evidence.position(body,knowledge)
    if proof['order']=='continuous' and knowledge_end>reaction:
        raise ValueError('知情顺序无效：同一连续场景中先定位人物实际获知的最小分句，再定位其反应。若没有先行依据，按影响报告缺口或存疑。')
    if proof['order']=='nonlinear':
        _text(proof,['reason'])


def validate_blind(report, body,reading_contract=None):
    if reading_contract is not None:
        report=book_contract.reading().without_unrequested_checks(report,reading_contract)
    report=evidence.resolve_report(report,body,reader_excerpts=True)
    report=book_contract.reading().advisory_report(report)
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
        validate_decision_evidence(decision,body)
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
        if 'scene_focus' in issue:
            if issue['kind'] != 'expression':
                raise ValueError('整场表达定位只用于表达问题')
            expression_rules.scene_focus_position(issue,body)
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
        frozen = _load(_path(root,binding['outputs']['reader_blind_input']))
        public=frozen['style_contract'].get('reading_contract',{})
        raw = _load(_path(root, binding['outputs']['reader_blind_raw_path']))
        if binding.get('reader_protocol') == 2:
            report = _validate_blind_v2(raw, body, public, frozen.get('new_passage_refs', []))
        else:
            _validate_expression_dimensions(raw)
            report = validate_blind(raw, body,public)
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
    report=book_contract.reading().advisory_report(report)
    result = book_contract.reading().apply(report,body,reading_contract)
    version = result['reader_review_version']
    if version not in (1, 2) or result.get('assessment_scope') != 'whole_chapter':
        raise ValueError('整篇独立审稿版本或范围无效')
    validate = _validate_blind_v2 if version == 2 else validate_blind
    blind = validate(result.get('blind_review'), body)
    result['blind_review'] = blind
    findings = {i['id']: i for i in blind['issues']}
    resolvable = findings
    if version == 2:
        resolvable = {row['issue']['id'] for row in _factual_conflicts(blind, result, body)}
    resolutions = result.get('blind_resolutions', [])
    if not isinstance(resolutions, list):
        raise ValueError('初审问题复核结构无效')
    resolved = set()
    for item in resolutions:
        if not isinstance(item, dict) or item.get('issue_id') not in resolvable or item['issue_id'] in resolved:
            raise ValueError('初审复核引用了无效或重复的问题编号')
        _text(item, ['reason']); _quotes(item, body)
        if version == 2:
            _validate_resolution_anchor(item, findings[item['issue_id']], body)
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
    for index, item in enumerate(scope['assessments']):
        path = f'revision_scope.assessments[{index}]'
        if not isinstance(item, dict):
            raise ValueError(f'{path} 须为修改范围分类对象')
        key = item.get('issue_id')
        if not isinstance(key, str) or key not in known:
            raise ValueError(f'{path}.issue_id 须与实际问题编号完全一致')
        if key in assessments:
            raise ValueError(f'{path}.issue_id 重复分类问题编号 {key}')
        if item.get('status') not in ('editable', 'outside_scope', 'unclear'):
            raise ValueError(f'{path}.status 须为 editable、outside_scope 或 unclear')
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
    if report.get('reader_review_version') == 2 and report.get('book_contract_sha256') != binding['scope_source']['book_contract_sha256']:
        raise ValueError('整篇审稿的本书契约来源凭据不一致')


def merge_review(final, blind, body,reading_contract=None, *, protocol=1):
    if reading_contract is not None:
        final=book_contract.reading().without_unrequested_checks(final,reading_contract)
    result = evidence.resolve_report(final,body,reader_excerpts=True)
    result.update(reader_review_version=protocol, assessment_scope='whole_chapter', blind_review=blind)
    if protocol == 2:
        result['expression_review']['summary'] = blind['summary']
    return gate_review(result, body,reading_contract)


def retain_context_findings(report, preflight, blind, body):
    """Retain every validated parallel finding unless the reconciler accounts for it."""
    prior = {item['id']: item for item in preflight['issues'] if item['id'].startswith('context-')}
    expression = report['expression_review']['issues']
    new = {item['id']: item for item in [*report['issues'], *expression]}
    if prior.keys() & new.keys():
        raise ValueError('最终审查的新问题不能复用独立资料分支的问题编号')
    resolved_blind = {item['issue_id'] for item in report.get('blind_resolutions', [])}
    destinations = {**prior, **new, **{item['id']: item for item in blind['issues'] if item['id'] not in resolved_blind}}
    dispositions = report.get('context_resolutions', [])
    if not isinstance(dispositions, list):
        raise ValueError('独立资料问题裁决须为数组')
    closed = set()
    for item in dispositions:
        if not isinstance(item, dict):
            raise ValueError('独立资料问题裁决须为对象')
        _text(item, ['issue_id', 'reason'])
        finding = prior.get(item['issue_id'])
        if finding is None or item['issue_id'] in closed:
            raise ValueError('独立资料问题裁决引用了未验证或重复的问题编号')
        _quotes(item, body)
        focus = finding.get('scene_focus')
        grounded = (any(focus['quote'] in quote for quote in item['excerpts']) if focus else
                    any(a in b or b in a for a in item['excerpts'] for b in finding['excerpts']))
        if not grounded:
            raise ValueError('独立资料问题裁决须引用该问题所在的原文')
        closed.add(item['issue_id'])
    priorities = {'low': 0, 'medium': 1, 'high': 2}
    for item in dispositions:
        if 'duplicate_of' not in item:
            continue
        destination = destinations.get(item['duplicate_of'])
        origin = prior[item['issue_id']]
        if destination is not None and ('scene_focus' in origin or 'scene_focus' in destination):
            first, second = (row.get('scene_focus') for row in (origin,destination))
            if (not first or not second or first['quote']!=second['quote']
                    or first.get('occurrence',1)!=second.get('occurrence',1)):
                raise ValueError('不同位置的整场表达问题须分别保留原编号')
            if item['duplicate_of'] not in prior:
                raise ValueError('同句已在资料分支核实，须沿用原编号并去掉汇总时新编的重复项')
        if (destination is None or item['duplicate_of'] in closed
                or priorities.get(destination.get('priority'), -1) < priorities[origin['priority']]
                or not any(a in b or b in a for a in origin['excerpts'] for b in destination.get('excerpts', []))):
            raise ValueError('合并目标须是仍保留、优先级不低且引用同处原文的问题')

    scope = report['revision_scope']
    source_scope = preflight['revision_scope']
    prior_scope = {item['issue_id']: item for item in source_scope['assessments']}
    scope['assessments'] = [item for item in scope['assessments'] if item['issue_id'] not in prior]
    for key, item in prior.items():
        if key in closed:
            continue
        (expression if item.get('source') == 'expression_review' else report['issues']).append(copy.deepcopy(item))
        prior_assessment = prior_scope.get(key) or {
            'issue_id': key, 'status': item['editability'], 'reason': source_scope['summary'],
        }
        scope['assessments'].append(copy.deepcopy(prior_assessment))
    report['context_resolutions'] = dispositions
    return report


def commit(root, binding_path, expected_sha, blind_sha,context_sha=''):
    binding, body = _bound(root, binding_path, expected_sha)
    blind_path = _path(root, binding['outputs']['reader_blind_report'])
    if not blind_sha or _digest(blind_path.read_bytes()) != blind_sha:
        raise ValueError('独立审稿报告在复评过程中有变化')
    blind=_load(blind_path)
    protocol = binding.get('reader_protocol', 1)
    parallel=binding['outputs'].get('reader_parallel_sources')
    fast_join = False
    context_preflight = None
    conflicts = []
    if binding.get('parallel_required') or (parallel and _path(root,parallel).is_file()):
        preflight=_path(root,binding['outputs']['reader_preflight_path'])
        if not context_sha or _digest(preflight.read_bytes())!=context_sha:raise ValueError('独立资料分支的实际报告绑定已变化')
        context_preflight = _load(preflight)
        if protocol == 2:
            conflicts = _factual_conflicts(blind, context_preflight, body)
            fast_join = not conflicts
            if conflicts and _load(_path(root, binding['outputs']['reader_fact_conflicts'])) != {'conflicts': conflicts}:
                raise ValueError('事实复核输入与已验证并行分支不同')
        else:
            fast_join = not _legacy_reconciliation(blind)
        if fast_join and _load(_path(root,binding['outputs']['reader_context_report_path']))!=context_preflight:
            raise ValueError('快速汇合报告不属于已核验的独立资料分支')
    try:
        contextual=_load(_path(root, binding['outputs']['reader_context_report_path']))
        if protocol == 2 and not fast_join:
            contextual = _apply_factual_resolutions(contextual, context_preflight, conflicts, body)
        elif not fast_join:
            _normalize_contextual_report(contextual)
            if context_preflight is not None:
                contextual = evidence.resolve_report(contextual, body, reader_excerpts=True)
                retain_context_findings(contextual, context_preflight, blind, body)
        validate_revision_scope(root,contextual)
        contract = book_contract.resolve(root).get('reading_contract', {})
        report = merge_review(contextual, blind, body, contract, protocol=protocol)
        usage = book_contract.reading().application_receipt(root, binding['chapter_number'], body, report, contract)
        if usage:
            report['reference_application'] = usage
    except (ValueError,TypeError,KeyError) as exc:
        raise InvalidReviewReport(str(exc)) from exc
    report.update(chapter_number=binding['chapter_number'], body_sha256=binding['body_sha256'])
    if protocol == 2:
        report['book_contract_sha256'] = binding['scope_source']['book_contract_sha256']
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
    parser.add_argument('--protocol', type=int, choices=[1, 2], default=1)
    parser.add_argument('--runtime',default='')
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == 'prepare':
        outputs = prepare(root, args.chapter, os.environ.get('TASK_ID', ''),args.parallel,protocol=args.protocol)
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
            binding,body=_bound(root,args.binding,args.binding_sha)
            blind=_load(_path(root,binding['outputs']['reader_blind_report']))
            if binding.get('reader_protocol') == 2:
                preflight = _load(_path(root, binding['outputs']['reader_preflight_path']))
                required = bool(_factual_conflicts(blind, preflight, body))
            else:
                required = _legacy_reconciliation(blind)
            fast=bool(binding['outputs'].get('reader_parallel_sources') and _path(root,binding['outputs']['reader_parallel_sources']).is_file() and not required)
            feedback=binding['outputs'].get('reader_preflight_feedback' if fast else 'reader_context_feedback')
            if feedback:
                quality().atomic_text(_path(root,feedback),'本轮审稿报告未被采用：'+str(exc)+'\n只修正报告，保持正文和独立初审不变。两个复评问题列表共用唯一的 context- 编号；范围分类引用同一个实际问题的编号。\n')
            _guarded_rejection('<WF_REJECT_UPSTREAM target="'+('agent_context_reader' if fast else 'agent_reader')+'">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>')
            return
        outputs = {}
    for key, value in outputs.items():
        print(f'<WF_VAR>{key}:{value}</WF_VAR>')
    print(json.dumps({'status': 'completed', 'action': args.action}, ensure_ascii=False))


if __name__ == '__main__':
    main()
