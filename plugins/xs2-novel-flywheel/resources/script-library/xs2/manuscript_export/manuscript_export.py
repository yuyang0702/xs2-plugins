"""Assemble chapter markdown files into a portable manuscript artifact."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from html import escape
from pathlib import Path

APPROVED_LEAD_PATH = 'planning/opening_lead.md'


class LeadRevisionNeeded(ValueError):
    """The current draft or its handoff review needs another attempt."""

    def __init__(self, reason, target='agent_opening_lead'):
        super().__init__(reason)
        self.target = target


def chapter_key(path: Path) -> tuple[int, str]:
    stem = path.parent.name
    try:
        return int(stem), stem
    except ValueError:
        return 10**9, stem


def _execution_guard():
    entry=Path(__file__).resolve().parents[1]/'production_guard/production_guard.py'
    spec=importlib.util.spec_from_file_location('export_execution_guard',entry)
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    return guard


def _artifact_path(root,relative):
    requested=Path(relative);path=(root/requested).resolve()
    if requested.is_absolute() or not path.is_relative_to(root):
        raise ValueError('导出路径不能离开当前作品工作区')
    return path


def _atomic_text(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.export-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def _project(root):
    path = _artifact_path(root, '.novel-project.json')
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}


def _lead_mode(project, mode):
    if mode in ('', 'book'):
        saved = project.get('values', {}).get('opening_lead')
        mode = 'omit' if saved in (None, '', 'book') else saved
    if mode not in {'include', 'omit'}:
        raise ValueError('独立导语须选择添加或省略')
    return mode


def _lead_paths(task_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', task_id):
        raise ValueError('独立导语需要有效导出任务编号')
    prefix = f'cache/opening-lead/{task_id}'
    return {key: f'{prefix}/{name}' for key, name in (
        ('binding', 'binding.json'), ('context', 'context.json'), ('draft', 'draft.json'),
        ('review_input', 'review-input.json'), ('review', 'review.json'), ('feedback', 'feedback.md'))}


def _lead_context(root, first, project, raw):
    book = _execution_guard().load('export_opening_style',
        Path(__file__).resolve().parents[1] / 'prose_policy/book_contract.py')
    values = project.get('values', {})
    context = {'source': first.relative_to(root).as_posix(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
               'book_mode': project.get('mode', ''), 'title': project.get('title', ''),
               'book_style': book.public_style(book.resolve(root)),
               'adopted_advice': values.get('advisor_guidance', ''),
               'first_chapter': raw.decode('utf-8-sig')}
    source = _artifact_path(root, APPROVED_LEAD_PATH)
    if source.exists():
        approved = source.read_bytes()
        value = approved.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').strip()
        context['approved_lead'] = {'text': value, 'sha256': hashlib.sha256(approved).hexdigest()}
        _validated_lead({'lead': value}, context['first_chapter'], reviewed=True)
    return context


def _lead_binding(mode, context):
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return {'mode': mode, 'context_sha256': hashlib.sha256(payload).hexdigest()}


def prepare_lead(root, mode, task_id):
    root = Path(root).resolve()
    project = _project(root)
    if _lead_mode(project, mode) == 'omit':
        return {}
    paths = _lead_paths(task_id)
    chapters = sorted((root / 'story').glob('*/chapter.md'), key=chapter_key)
    if not chapters:
        raise ValueError('请先完成正文，再生成独立导语')
    first = _artifact_path(root, chapters[0].relative_to(root))
    raw = first.read_bytes()
    if not raw.decode('utf-8-sig').strip():
        raise ValueError('首章正文为空，无法生成独立导语')
    context = _lead_context(root, first, project, raw)
    for key, value in [('binding', _lead_binding(mode, context)), ('context', context)]:
        path = _artifact_path(root, paths[key])
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != value:
                raise ValueError('导语生成资料已有变化，请重新导出')
        else:
            _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if 'approved_lead' in context:
        draft = _artifact_path(root, paths['draft'])
        value = {'lead': context['approved_lead']['text']}
        if draft.exists():
            if json.loads(draft.read_bytes()) != value:
                raise ValueError('任务草稿与需保留的导语不一致')
        else:
            _atomic_text(draft, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    feedback = _artifact_path(root, paths['feedback'])
    if not feedback.exists():
        _atomic_text(feedback, '')
    return paths


def _validated_lead(value, first_body, *, reviewed=False):
    text = value.get('lead') if isinstance(value, dict) and set(value) == {'lead'} else None
    if not isinstance(text, str) or not text.strip() or len(text) > 6000:
        raise ValueError('独立导语须提供有效的导语正文')
    text = text.strip()
    heading = (r'^[ \t]*(?:#{1,6}(?:[ \t]|$)|```|[0-9]{1,3}(?:[.．、](?![0-9])|[ \t]*$)'
               r'|第[0-9一二三四五六七八九十百]+[章回节卷](?=[ \t·：:、.]|$))')
    if re.search(heading, text, re.M):
        raise ValueError('独立导语不能包含章节标题、编号或代码围栏')
    if not reviewed and text in first_body:
        raise ValueError('独立导语不能直接复用首章原文')
    return text


def _handoff_input(context, lead, raw_draft):
    # The writer already sees the whole chapter. The handoff reviewer needs
    # the beginning and the book's stated purpose for the optional lead.
    opening = context['first_chapter'].replace('\r\n', '\n').replace('\r', '\n')
    result = {
        'lead': lead, 'opening': opening[:3000],
        'first_chapter_sha256': context['source_sha256'],
        'draft_sha256': hashlib.sha256(raw_draft).hexdigest(),
        'book_style': context['book_style'], 'adopted_advice': context['adopted_advice'],
    }
    if 'approved_lead' in context:
        if json.loads(raw_draft) != {'lead': context['approved_lead']['text']}:
            raise ValueError('任务草稿与需保留的导语不一致')
        result['approved_lead_sha256'] = context['approved_lead']['sha256']
    return result


def prepare_lead_review(root, task_id):
    root = Path(root).resolve()
    paths = _lead_paths(task_id)
    context = json.loads(_artifact_path(root, paths['context']).read_bytes())
    raw_draft = _artifact_path(root, paths['draft']).read_bytes()
    try:
        lead = _validated_lead(json.loads(raw_draft), context['first_chapter'], reviewed=True)
    except ValueError as exc:
        if 'approved_lead' in context:
            raise ValueError('需保留的导语草稿有变动') from exc
        raise LeadRevisionNeeded(str(exc)) from exc
    request = _handoff_input(context, lead, raw_draft)
    _artifact_path(root, paths['review']).unlink(missing_ok=True)
    _atomic_text(_artifact_path(root, paths['review_input']),
                 json.dumps(request, ensure_ascii=False, indent=2) + '\n')
    return paths['review_input']


def _validated_handoff(value, lead, opening):
    fields = {'verdict', 'lead_quote', 'opening_quote', 'reason'}
    if (not isinstance(value, dict) or set(value) != fields
            or value['verdict'] not in ('pass', 'revise')
            or any(not isinstance(value[key], str) or not value[key].strip()
                   for key in fields - {'verdict'})):
        raise LeadRevisionNeeded('导语衔接复核缺少有效结论、理由或引文', 'agent_opening_lead_review')
    if value['lead_quote'] not in lead or value['opening_quote'] not in opening:
        raise LeadRevisionNeeded('复核须分别引用当前导语和开篇正文中的原文', 'agent_opening_lead_review')
    return value


def build_manuscript(output: str, manifest: str, *, mode='book', binding='', task_id='',
                     lead_review='') -> dict[str, object]:
    root = Path.cwd().resolve()
    target=_artifact_path(root,output);manifest_path=_artifact_path(root,manifest)
    if target==manifest_path:raise ValueError('正文导出与清单不能使用同一目标文件')
    if _artifact_path(root, APPROVED_LEAD_PATH) in (target, manifest_path):
        raise ValueError('导出文件不能覆盖作者确认的导语')
    boundary=(_execution_guard().publication(root)
              if os.environ.get('TASK_ID') and os.environ.get('WORKFLOW_ID') else nullcontext(None))
    with boundary as proof:
        project = _project(root)
        include_lead = _lead_mode(project, mode) == 'include'
        chapters = sorted((root / "story").glob("*/chapter.md"), key=chapter_key)
        if any(not path.resolve().is_relative_to(root) for path in chapters):
            raise ValueError('章节来源不能离开当前作品工作区')
        if any(path.resolve() in (target,manifest_path) for path in chapters):
            raise ValueError('导出文件不能覆盖章节来源')
        lead = ''
        handoff = None
        lead_sources = {}
        if include_lead:
            task_id = task_id or os.environ.get('TASK_ID', '')
            if proof and task_id != os.environ['TASK_ID']:
                raise ValueError('导语资料必须属于当前导出任务')
            paths = _lead_paths(task_id)
            if binding != paths['binding'] or not chapters:
                raise ValueError('缺少本次导出所需的独立导语，请先生成')
            reviewed = bool(lead_review or proof)
            if reviewed and lead_review != paths['review']:
                raise ValueError('缺少当前导语与开篇的独立复核')
            keys = ('binding', 'context', 'draft', 'review_input', 'review') if reviewed else ('binding', 'context', 'draft')
            for key in keys:
                path = _artifact_path(root, paths[key])
                if path in (target, manifest_path):
                    raise ValueError('导出文件不能覆盖导语来源')
                lead_sources[key] = (path, path.read_bytes())
            first = chapters[0].resolve()
            first_raw = first.read_bytes()
            context = _lead_context(root, first, project, first_raw)
            if (json.loads(lead_sources['binding'][1]) != _lead_binding(mode, context)
                    or json.loads(lead_sources['context'][1]) != context):
                raise ValueError('首章正文或导语规则已有变化，请重新导出')
            if 'approved_lead' in context and not reviewed:
                raise ValueError('保留的导语需要与当前开篇复核')
            raw_draft = lead_sources['draft'][1]
            lead = _validated_lead(json.loads(raw_draft), context['first_chapter'], reviewed=reviewed)
            if reviewed:
                review_input = _handoff_input(context, lead, raw_draft)
                if json.loads(lead_sources['review_input'][1]) != review_input:
                    raise ValueError('导语或开篇已经变化，请重新复核')
                handoff = _validated_handoff(json.loads(lead_sources['review'][1]), lead, review_input['opening'])
                if handoff['verdict'] == 'revise':
                    if 'approved_lead' in context:
                        raise ValueError('需保留的导语与当前开篇未通过复核：' + handoff['reason'])
                    raise LeadRevisionNeeded('请按衔接复核改写导语：' + handoff['reason'])
        elif binding or lead_review:
            raise ValueError('导语设置已有变化，请重新导出')
        sections: list[str] = [];exported: list[dict[str, object]] = [];sources={}
        for path in chapters:
            raw=path.read_bytes();sources[path]=raw
            content=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n').strip()
            if not content:continue
            chapter = path.parent.name
            first = content.splitlines()[0].strip()
            heading = re.sub(r'^#{1,6}\s*', '', first)
            has_title = bool(re.match(r'^第[一二三四五六七八九十百千零〇两0-9]+[章回节卷](?:\s|[·：:、.]|$)', heading))
            if has_title:sections.append(content if first.startswith('#') else '# ' + content)
            elif lead and len(chapters) == 1 and project.get('mode') == 'short':sections.append(content)
            else:sections.append(f"# 第{chapter}章\n\n{content}")
            exported.append({"chapter": chapter, "path": path.relative_to(root).as_posix(), "characters": len(content)})
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "output": target.relative_to(root).as_posix(),"chapter_count": len(exported),"chapters": exported}
        if proof:report['execution_fence']=proof
        if lead:
            report['opening_lead'] = {'characters': len(lead), 'source_sha256': context['source_sha256']}
            if 'approved_lead' in context:
                report['opening_lead'].update(preserved=True, approved_sha256=context['approved_lead']['sha256'])
            if handoff:
                report['opening_lead']['handoff_review'] = {
                    **handoff, 'draft_sha256': review_input['draft_sha256']}
            if (sources.get(chapters[0]) != first_raw
                    or _lead_context(root, chapters[0].resolve(), _project(root), first_raw) != context
                    or any(path.read_bytes() != raw for path, raw in lead_sources.values())):
                raise ValueError('导语生成资料已有变化，未发布')
        if _lead_mode(_project(root), mode) != ('include' if include_lead else 'omit'):
            raise ValueError('导语设置已有变化，未发布')
        if (sorted((root/'story').glob('*/chapter.md'),key=chapter_key)!=chapters
                or any(path.read_bytes()!=raw for path,raw in sources.items())):
            raise ValueError('导出期间章节来源已有变化，未发布')
        manuscript = "\n\n---\n\n".join(sections) + ("\n" if sections else "")
        _atomic_text(target, lead + '\n\n' + manuscript if lead else manuscript)
        _atomic_text(manifest_path,json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", default="export/manuscript.md")
    build.add_argument("--manifest", default="export/manifest.json")
    build.add_argument("--opening-lead", choices=('', 'book', 'include', 'omit'), default='book')
    build.add_argument("--lead-binding", default='')
    build.add_argument("--lead-review", default='')
    prepare = sub.add_parser("prepare-lead")
    prepare.add_argument("--opening-lead", choices=('', 'book', 'include', 'omit'), default='book')
    review = sub.add_parser("prepare-lead-review")
    for command in (build, prepare, review):
        command.add_argument("--task-id", default=os.environ.get('TASK_ID', ''))
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        if args.command == "build":
            report = build_manuscript(args.output, args.manifest, mode=args.opening_lead,
                                      binding=args.lead_binding, task_id=args.task_id, lead_review=args.lead_review)
            print(json.dumps(report, ensure_ascii=False))
        elif args.command == 'prepare-lead':
            prepared = prepare_lead(root, args.opening_lead, args.task_id)
            mode = 'no'
            if prepared:
                frozen = json.loads(_artifact_path(root, prepared['context']).read_bytes())
                mode = 'preserve' if 'approved_lead' in frozen else 'yes'
            print('<WF_VAR>opening_lead_required:' + mode + '</WF_VAR>')
            for key, path in prepared.items():
                print(f'<WF_VAR>opening_lead_{key}:{path}</WF_VAR>')
        else:
            prepare_lead_review(root, args.task_id)
    except LeadRevisionNeeded as exc:
        transport = _execution_guard().load('opening_lead_rejection',
            Path(__file__).resolve().parents[1] / 'production_guard/rejections.py')
        if exc.target == 'agent_opening_lead':
            _atomic_text(_artifact_path(root, _lead_paths(args.task_id)['feedback']), str(exc) + '\n')
        transport.emit(f'<WF_REJECT_UPSTREAM target="{exc.target}">{escape(str(exc))}</WF_REJECT_UPSTREAM>')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
