"""Task-bound local content revision; only reviewed exact patches publish prose."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys
from collections import Counter
from xml.sax.saxutils import escape

HERE=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
quality=load('local_revision_length',HERE/'console_service/length_quality.py')
book=load('local_revision_book',HERE/'prose_policy/book_contract.py')
patches=load('local_revision_patch',HERE/'draft_guard/revision_patch.py')
expression=load('local_revision_expression',HERE/'prose_policy/expression_review.py')
evidence=load('local_revision_evidence',HERE/'multi_scene/audit_evidence.py')
packet=load('local_revision_model_view',HERE/'prose_policy/context_packet.py')
wire=load('local_revision_wire',HERE/'prose_policy/review_wire.py')
pending=load('local_revision_pending',HERE/'local_revision/pending_revision.py')
guard=load('local_revision_execution_guard',HERE/'production_guard/production_guard.py')
report_repair=load('local_revision_report_repair',HERE/'prose_policy/report_repair.py')
tone=load('local_revision_tone',HERE/'local_revision/tone_review.py')
blind=load('local_revision_blind',HERE/'local_revision/blind_scene.py')
zhuque=load('local_revision_zhuque',HERE/'local_revision/zhuque_review.py')
continuity=load('local_revision_continuity',HERE/'manuscript_continuity/manuscript_continuity.py')
SCOPED_REVIEW='local-review-v3'


class Retry(ValueError):
    def __init__(self,target,reason):super().__init__(reason);self.target=target


class CompositionConflict(ValueError):pass


def refresh_retry_budget(root,target):
    if os.environ.get('TASK_ID') and os.environ.get('WORKFLOW_ID'):
        guard.request_budget(root,target)


def conflict_packet(b,source,payload,reason,quotes,measured=None):
    if payload.get('source_sha256')!=b['body_sha256'] or not isinstance(reason,str) or not reason.strip():
        raise ValueError('重规划冲突缺少冻结原文和逐字证据')
    quotes=patches.exact_evidence(source['source_body'],quotes)
    return {'schema':1,'kind':'content_length_conflict','task_id':b['task_id'],'chapter':b['chapter_number'],
        'source_sha256':b['body_sha256'],'binding_digest':digest(b),'patch_digest':digest(payload),
        'reason':reason,'evidence':quotes,'measurement':measured,'no_publication':True}


def raise_conflict(root,b,source,payload,reason,quotes,measured=None,extras=None):
    packet=conflict_packet(b,source,payload,reason,quotes,measured)
    if extras:packet.update(extras)
    save(safe(root,b['outputs']['revision_dir']+'/composition-conflict.json'),packet)
    raise CompositionConflict('CONTENT_LENGTH_CONFLICT：已保留来源，须重新规划阅读作用与篇幅，不能向同一写手要求补字。')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(data):return sha(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,data):quality.atomic_text(p,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def model_view(data,role):
    view=packet.local(data,role)
    view.pop('zhuque_review', None)
    detection = data.get('zhuque_review', {})
    if role in ('critic', 'writer') and detection.get('status') == 'success':
        view['zhuque_review'] = {key: detection[key] for key in ('attention', 'reference_paragraphs')}
        if 'reference_excerpts' in detection:
            view['zhuque_review']['reference_excerpts'] = detection['reference_excerpts']
        view['zhuque_review']['guidance'] = zhuque.GUIDANCE
        if detection.get('required'):
            view['zhuque_review'].update(rewrite_units=detection['rewrite_units'], guidance=zhuque.REWRITE_GUIDANCE)
    if role != 'critic':
        view.pop('tone_review', None)
    if role in ('critic', 'writer') and 'local_tone' in data:
        view['local_tone'] = data['local_tone']
    if data.get('review_protocol')==SCOPED_REVIEW:
        if role=='writer':
            by_id={row['id']:row for row in data['goals']}
            for row in view['goals']:
                goal=by_id[row['id']]
                row.update({key:copy.deepcopy(goal[key]) for key in ('source','level','required_source') if key in goal})
                row['evidence']=copy.deepcopy(goal.get('excerpts',[]))
        elif role=='reviewer':
            view.pop('reader_report',None)
            view.pop('critique',None)
            if data.get('whole_review_phase')=='signoff':
                view['whole_review_phase']='signoff'
                view['signoff_instructions']=(
                    '本次是撤回后的整稿签发。通读完整候选并逐场与冻结原稿对比，核对每处修改、删句、新增、前后衔接及作者要求。'
                    '当前任务以此协议为准：change_reviews 和 added_text_reviews 均填 []。issue_outcomes 覆盖 goals 的全部编号。'
                    'final- 开头的是必须独立作出的签发判断；逐场说明具体理由，引用该场实际变动处的候选原句或候选段号对象，例如 {"ref_id":"p0002"}。'
                    '对于其他目标，填写原目标结论。客观矛盾同时填 issues；实质问题由写手修订。'
                    '允许保留尚有别种写法、但合乎情节与本书文风的句子。')
                view['signoff_evidence']=signoff_evidence(data)
    return view


def signoff_evidence(context):
    rows=patches.paragraphs(context['source_body'])
    edits=context['edits']
    locators=packet.focused_goals(context['goals'],context['source_body'],packet.prose(context['source_body']))
    changed={e['paragraph_id'] for e in edits}
    result={}
    for goal in locators:
        ids=set(goal['paragraph_ids'])
        regions=[]
        for i,row in enumerate(rows):
            if row['id'] not in ids:continue
            text=patches._scoped_paragraph(row,edits)
            if text.strip():
                regions.append(text)
            elif row['id'] in changed:
                for step in (-1,1):
                    j=i+step
                    while 0<=j<len(rows):
                        neighbor=patches._scoped_paragraph(rows[j],edits)
                        if neighbor.strip():
                            regions.append(neighbor)
                            break
                        j+=step
        result[goal['id']]=list(dict.fromkeys(regions))
    return result


def verify_model(actual,data,role):
    if actual!=model_view(data,role):
        raise ValueError('模型所见输入与冻结的完整资料不一致，核验未复用或发布')


def save_model(p,data,role):
    view=model_view(data,role)
    if (data.get('writer_view_version')==packet.FOCUSED_WRITER_VERSION
            or data.get('critic_view_version')==packet.COMPACT_CRITIC_VERSION):
        quality.atomic_text(p,json.dumps(view,ensure_ascii=False,separators=(',',':'))+'\n')
    else:
        save(p,view)
def safe(root,path):return quality.safe_path(root,path)


def state(root):
    p=safe(root,'.novel-project.json');s=read(p) if p.is_file() else {};v=s.get('values',{})
    return {'chapter_number':str(v.get('chapter_number','0001')).zfill(4),
            'author_feedback_file':str(v.get('author_feedback_file') or '').strip(),
            'target_word_count':str(v.get('target_word_count') or '')}


def feedback_layers(root,path):
    if not path:return '', '', {}
    raw=safe(root,path).read_bytes();text=raw.decode('utf-8-sig')
    origin_path=(Path(path).parent/'automatic-origin.json').as_posix();p=safe(root,origin_path)
    origin=read(p) if p.is_file() else {}
    if origin.get('origin')!='automatic' or origin.get('feedback_sha256')!=sha(raw):return text,'',{}
    rows=origin.get('retained_feedback_sources')
    if not isinstance(rows,list):raise ValueError('自动建议缺少原作者意见来源')
    guards={origin_path:sha(p.read_bytes())}
    for row in rows:
        file=safe(root,row['source_id'])
        if not file.is_file() or sha(file.read_bytes())!=row['sha256'] or file.read_text(encoding='utf-8-sig')!=row['text']:
            raise ValueError('原作者意见来源已经变化')
        guards[row['source_id']]=row['sha256']
    return '\n\n'.join(row['text'] for row in rows),text,guards


def retained_feedback_sources(root,path):
    _,_,sources=feedback_layers(root,path)
    paths=[source for source in sources if not source.endswith('/automatic-origin.json')] if sources else ([path] if path else [])
    return [{'source_id':source,'sha256':sha(safe(root,source).read_bytes()),'text':safe(root,source).read_text(encoding='utf-8-sig')}
            for source in paths]


def source_files(root,chapter,context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None,reader_paths=()):
    paths={safe(root,f'story/{chapter}/chapter.md')}
    for folder in ('meta','outline'):
        paths.update(p for p in safe(root,folder).rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for directory in safe(root,'story').glob('[0-9][0-9][0-9][0-9]'):
        if int(directory.name)<=int(chapter):
            paths.update(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for name in (context_path,f'story/{chapter}/reader_report.json',f'planning/chapters/{chapter}.json',
                 f'planning/length/{chapter}.json','meta/length_policy.json',
                 'learning/active_context.md','learning/character_center/preferences.json','learning/prose_policy/policy.json'):
        paths.add(safe(root,name))
    if reference_path:paths.add(safe(root,reference_path))
    paths.update(safe(root,path) for path in reader_paths)
    feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback:
        p=safe(root,feedback)
        if not p.is_file():raise ValueError('作者意见文件缺失，不能忽略后继续修订')
        paths.add(p)
        for relative in feedback_layers(root,feedback)[2]:paths.add(safe(root,relative))
    result={}
    for p in sorted(paths):
        relative=p.relative_to(Path(root).resolve()).as_posix();p=safe(root,relative)
        result[relative]=sha(p.read_bytes()) if p.is_file() else None
    return result


def locations(folder):
    return {'revision_dir':folder,'revision_source_file':folder+'/source.md','revision_source_input':folder+'/source-input.json',
            'revision_input':folder+'/editor-input.json','revision_patch_path':folder+'/patches.json',
            'revision_review_input':folder+'/review-input.json','revision_review_path':folder+'/review.json',
            'revision_feedback_file':folder+'/feedback.md','revision_source_model':folder+'/source-model.json',
            'revision_editor_model':folder+'/editor-model.json','revision_review_model':folder+'/review-model.json',
            'revision_review_expanded':folder+'/review-expanded.json','revision_review_repair':folder+'/review-repair.json'}


def confirmed_reader(root,chapter,source):
    report=source['reader_report']
    if (not isinstance(report,dict) or report.get('reader_review_version')!=2
            or report.get('chapter_number')!=chapter or report.get('body_sha256')!=source['source_sha256']
            or report.get('book_contract_sha256')!=source['book_contract_sha256']):
        return None
    receipt=report.get('review_binding')
    if not isinstance(receipt,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(receipt.get('task_id',''))):
        return None
    folder=f'cache/reader-review/{chapter}/{receipt["task_id"]}'
    relative=folder+'/binding.json'
    path=safe(root,relative)
    if not path.is_file():return None
    try:binding=read(path)
    except (ValueError,OSError):return None
    if (not isinstance(binding,dict) or binding.get('chapter_number')!=chapter
            or binding.get('reader_protocol')!=2
            or {key:binding.get(key) for key in ('task_id','scope_source','body_sha256','input_sha256')}!=receipt
            or receipt.get('body_sha256')!=source['source_sha256']
            or not isinstance(receipt.get('scope_source'),dict)
            or receipt['scope_source'].get('book_contract_sha256')!=source['book_contract_sha256']
            or not isinstance(report.get('revision_scope'),dict) or report['revision_scope'].get('mode')!='unrestricted'
            or report.get('requires_scope_confirmation')):
        return None
    input_path=folder+'/blind-input.json'
    original=source['source_body'].removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n')
    try:
        frozen_input=safe(root,input_path).read_bytes()
        if sha(frozen_input)!=binding['input_sha256'] or json.loads(frozen_input).get('manuscript')!=original:
            return None
    except (ValueError,OSError,TypeError,AttributeError):return None
    rows=book.reading().advisory_report(report).get('issues')
    if not isinstance(rows,list):return None
    result=[]
    seen=set()
    body=source['source_body'].replace('\r\n','\n').replace('\r','\n')
    try:
        for row in rows:
            if row.get('priority') not in ('medium','high') and not (
                    row.get('kind')=='expression' and row.get('actionability')=='targeted'
                    and row.get('scene_focus') and row.get('editability')=='editable'):
                continue
            key=row['id']; excerpts=row['excerpts']; preserve=row.get('preserve',[])
            if (not isinstance(key,str) or not key.strip() or key in seen or row.get('editability')!='editable'
                    or not isinstance(row.get('goal'),str) or not row['goal'].strip()
                    or not isinstance(excerpts,list) or not excerpts
                    or any(not isinstance(q,str) or not q.strip() or q not in body for q in excerpts)
                    or not isinstance(preserve,list) or any(not isinstance(q,str) or not q.strip() for q in preserve)):
                return None
            seen.add(key)
            hard=(row.get('kind')=='fact' and row.get('source_quote')
                  or row.get('kind') in ('fact','causality') and row.get('contradiction'))
            goal={**row,'source':row.get('source','reader_review'),'origin':'reader_review',
                  'level':'hard' if hard else 'advisory',
                  'preserve':preserve}
            if 'scene_focus' in row:
                offset=expression.scene_focus_position(row,source['source_body'])
                goal=patches.bind_scene_goal(source['source_body'],[],source['source_body'],goal,offset)
            result.append(goal)
    except (ValueError,KeyError,TypeError,AttributeError):return None
    if report.get('verdict')!='pass' and not result:return None
    return {'binding_path':relative,'source_paths':[relative,input_path],'goals':result}


def local_tone_policy(source, whole_chapter_review=False):
    protected = source['book_contract']['protected_phrases']
    authored = source.get('author_feedback', '')
    fixed = source.get('fixed_edit')
    marks = {p['id']: hits for p in source['paragraphs']
             if (hits := tone.mandatory(p['text'], protected))}
    if fixed:
        marks = {}
    elif 'confirmed_reader' in source:
        quotes = [q for goal in source['confirmed_reader']['goals'] for q in goal['excerpts']]
        marks = {p['id']: marks[p['id']] for p in source['paragraphs']
                 if p['id'] in marks and any(q in p['text'] for q in quotes)}
    edited_only = bool(fixed or (authored.strip() and not whole_chapter_review))
    instruction = tone.REPHRASE
    if edited_only:
        if len(source['paragraphs']) > 1:
            marks = {key:[hit for hit in hits if hit in authored] for key, hits in marks.items()}
            marks = {key:hits for key, hits in marks.items() if hits}
        instruction += '仅处理作者指定片段内的命中，段外原句仅供定位。'
    return {'revision':tone.REVISION, 'instruction':instruction, 'marks':marks, 'edited_only':edited_only}


def prepare(root,chapter,task_id,target='',context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None,*,dialogue_check=False,dialogue_check_version=1,scoped_review=False,whole_chapter_review=False,advisory=False,blind_scenes=False,whole_text_detection=False):
    root=Path(root).resolve();chapter=quality.chapter_number(chapter)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',task_id or ''):raise ValueError('局部修订缺少有效任务编号')
    frozen=book.freeze(root,task_id);folder=f'cache/local-revision/{task_id}';out=locations(folder)
    body_path=f'story/{chapter}/chapter.md';raw=safe(root,body_path).read_bytes();body=raw.decode('utf-8')
    if not body.strip():raise ValueError('局部修订需要非空原文')
    planner=load('local_composition',HERE/'composition_plan/composition_plan.py')
    fixed=None if advisory else planner.fixed_edit(root,chapter,task_id)
    previous=safe(root,folder+'/source-binding.json')
    prior_binding=read(previous) if previous.exists() else None
    previous_source=read(safe(root,out['revision_source_input'])) if prior_binding is not None else None
    round_options = None
    if prior_binding is not None:
        round_options = prior_binding.get('zhuque_options')
    elif whole_text_detection:
        round_options = zhuque.options(root)
    target_policy=quality.resolve_length(root,target,chapter=chapter,task_id=task_id,advisory=advisory)
    bounds=target_policy['bounds']
    policy_bound=(prior_binding is None and target_policy['ownership']!='legacy'
                  or prior_binding is not None and 'target_policy' in prior_binding)
    scoped_review=previous_source.get('review_protocol')==SCOPED_REVIEW if previous_source is not None else scoped_review
    report_path=safe(root,f'story/{chapter}/reader_report.json')
    try:report=read(report_path) if report_path.is_file() else None
    except ValueError:
        if not scoped_review:raise
        report=None
    if report and (not isinstance(report,dict) or report.get('body_sha256')!=sha(raw)):report=None
    shared=safe(root,context_path);feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback and not safe(root,feedback).is_file():raise ValueError('本次作者意见文件缺失，不能忽略后继续修订')
    if fixed and feedback!=fixed['feedback_path']:raise ValueError('本轮作者意见与单句删除的篇幅凭据不同')
    confirmed=shared.read_text(encoding='utf-8-sig') if shared.is_file() else ''
    for title,path in (('本书已确认人物对白适配','meta/character_voice_adaptations.md'),('本次已采用抽象参考',reference_path)):
        if path and safe(root,path).is_file():confirmed+='\n\n## '+title+'\n'+book.policy().effective_text(root,path)
    authored,automatic,_=feedback_layers(root,feedback)
    composition=None if fixed else (planner.reference if advisory else planner.current)(root,chapter)
    prior=(composition or {}).get('prior_revision')
    if prior and (prior.get('source_sha256')!=sha(raw) or prior.get('book_contract_sha256')!=frozen['sha256']):prior=None
    if composition:composition={k:v for k,v in composition.items() if k!='prior_revision'}
    source={'source_body':body,'source_sha256':sha(raw),'paragraphs':patches.paragraphs(body),
            'book_contract':frozen['contract'],'book_contract_sha256':frozen['sha256'],
            'author_feedback':authored,'automatic_revision_advice':automatic,'composition_plan':composition,'prior_revision':prior,
            'confirmed_context':confirmed,
            'reader_report':report,'length':quality.measurement(raw,chapter,target_policy if policy_bound else bounds)}
    if scoped_review:
        source['review_protocol']=SCOPED_REVIEW
        source['whole_chapter_review']=(bool(previous_source['whole_chapter_review']) if previous_source is not None
                                        else bool(whole_chapter_review or authored.strip()))
        if not source['whole_chapter_review']:
            confirmed=confirmed_reader(root,chapter,source)
            if confirmed:source['confirmed_reader']=confirmed
    if not scoped_review and dialogue_check and not fixed and (previous_source is None or previous_source.get('dialogue_check')):
        source['dialogue_check']=True
        version=dialogue_check_version if previous_source is None else previous_source.get('dialogue_check_version',1)
        if version>1:source['dialogue_check_version']=version
    if not previous.exists() or read(safe(root,out['revision_source_input'])).get('critic_view_version')==packet.COMPACT_CRITIC_VERSION:
        source['critic_view_version']=packet.COMPACT_CRITIC_VERSION
    if not fixed and (previous_source is None or previous_source.get('added_text_review')):
        source['added_text_review']=True
        if previous_source is None or previous_source.get('mixed_added_text_review'):
            source['mixed_added_text_review']=True
    if fixed:source['fixed_edit']=fixed['edit']
    elif not scoped_review and (previous_source is None or previous_source.get('precision_review_version')==2):
        candidates=packet.precision().review_candidates(body, source['paragraphs'])
        source['precision_review_version']=2
        if candidates:source['precision_candidates']=candidates
    elif previous_source and 'precision_candidates' in previous_source:
        source['precision_candidates']=previous_source['precision_candidates']
    before_tone = None
    if previous_source is not None:
        # Preserve inputs for attempts frozen before or after this detector was installed.
        if 'tone_review' in previous_source:
            source['tone_review'] = previous_source['tone_review']
        if 'zhuque_review' in previous_source:
            source['zhuque_review'] = previous_source['zhuque_review']
    elif scoped_review and not fixed and 'confirmed_reader' not in source:
        key_path = os.environ.get('XS2_ZHUQUE_KEY_FILE')
        if blind_scenes and key_path and round_options is None and zhuque.options(root)['enabled']:
            detection = zhuque.analyze(body, patches.paragraphs, key_path)
            if not authored.strip():
                if detection.get('status') != 'success':
                    raise ValueError('朱雀检测未完成，无法确定必改范围：'+str(detection.get('reason')))
                if 'rewrite_units' in detection:
                    tone.annotate_rewrites(detection, patches.paragraphs(body))
                    if detection['rewrite_units'] and not (detection['reference_paragraphs'] or detection['reference_excerpts']):
                        raise ValueError('本篇未检出可用的人工参考，无法执行同篇参照必改。')
                    detection['required'] = True
            source['zhuque_review'] = detection
        before_tone = tone.scan(body)
        source['tone_review'] = {
            **tone.critic_view(before_tone, body, source['paragraphs']),
            'scene_edit_version':1,
            'optional_scene_trials':True,
            **({'whole_signoff_version':2} if whole_chapter_review or not authored.strip() else {}),
            'scene_commission':tone.SCENE_COMMISSION,
            'writer_commission':tone.WRITER_COMMISSION,
            'compare_scene_trials':bool(whole_chapter_review or not authored.strip()),
            'snapshot_digest': digest(before_tone),
        }
    if previous_source is None:
        source['local_tone'] = local_tone_policy(source, whole_chapter_review)
    elif 'local_tone' in previous_source:
        source['local_tone'] = previous_source['local_tone']
    binding={'schema':1,'task_id':task_id,'chapter_number':chapter,'body_path':body_path,'body_sha256':sha(raw),
             'book_contract_sha256':frozen['sha256'],'state':state(root),'context_path':context_path,'reference_path':reference_path,'feedback_path':feedback,
             'files':source_files(root,chapter,context_path,reference_path,feedback,(source.get('confirmed_reader') or {}).get('source_paths',())),
             'source_digest':digest(source),'bounds':bounds,'outputs':out}
    if policy_bound:binding['target_policy']=target_policy
    if round_options is not None:
        binding['zhuque_options'] = round_options
    if (prior_binding or {}).get('blind_seed') or (blind_scenes and prior_binding is None and
            scoped_review and 'tone_review' in source and not fixed):
        binding['blind_seed']=(prior_binding or {}).get('blind_seed') or secrets.token_hex(32)
        out.update(revision_blind_packet=folder+'/blind-packet.json',revision_blind_path=folder+'/blind-vote.json')
    if prior_binding is not None and prior_binding!=binding:raise ValueError('同任务修订来源已有变化，请新建任务')
    if before_tone is not None:
        save(safe(root,folder+'/tone-before.json'), before_tone)
    save(safe(root,out['revision_source_input']),source);save(safe(root,out['revision_input']),source)
    save_model(safe(root,out['revision_source_model']),source,'critic')
    quality.atomic_text(safe(root,out['revision_source_file']),body);save(previous,binding)
    p=safe(root,out['revision_feedback_file'])
    if not p.exists():quality.atomic_text(p,'')
    if not safe(root,out['revision_review_repair']).exists():save(safe(root,out['revision_review_repair']),{})
    if scoped_review:
        confirmed='confirmed_reader' in source
        if round_options is not None:
            out = {**out, 'zhuque_round_mode':'yes' if round_options['enabled'] else 'no'}
        return {**out,'revision_blind_mode':'yes' if 'blind_seed' in binding else 'no','revision_critique_mode':'confirmed' if confirmed else 'critic',
                'revision_checkpoint_source':f'story/{chapter}/reader_report.json' if confirmed else 'cache/sc/critique.json'}
    return out


def bound(root,folder,accepted_sha=None):
    b=read(safe(root,folder+'/source-binding.json'));source=read(safe(root,b['outputs']['revision_source_input']))
    if digest(source)!=b['source_digest'] or sha(safe(root,b['outputs']['revision_source_file']).read_bytes())!=b['body_sha256']:
        raise ValueError('冻结原文或本书规则上下文已变化，未发布')
    if b['outputs'].get('revision_source_model'):
        verify_model(read(safe(root,b['outputs']['revision_source_model'])),source,'critic')
    if state(root)!=b['state'] or book.digest(book.resolve(root))!=b['book_contract_sha256']:
        raise ValueError('本书规则、作者意见选择或目标已变化，未发布')
    current=source_files(root,b['chapter_number'],b['context_path'],b['reference_path'],b['feedback_path'],
                         (source.get('confirmed_reader') or {}).get('source_paths',()))
    if accepted_sha and current.get(b['body_path'])==accepted_sha:current[b['body_path']]=b['body_sha256']
    if current!=b['files']:raise ValueError('正文、作者意见或已确认资料已有变化，未发布')
    if source.get('fixed_edit'):
        planner=load('local_composition',HERE/'composition_plan/composition_plan.py')
        fixed=planner.fixed_edit(root,b['chapter_number'],b['task_id'],accepted_sha)
        if not fixed or fixed['edit']!=source['fixed_edit']:raise ValueError('作者指定删句的篇幅凭据已有变化')
    book.freeze(root,b['task_id'])
    return b,source


def goals(source,critique):
    rows=[]
    for row in book.reading().advisory_report(source.get('reader_report') or {}).get('issues',[]):
        if row.get('priority') in ('medium','high') and row.get('editability') not in ('outside_scope','unclear'):
            goal={'id':row.get('id') or f'reader-{len(rows)}', 'source':'reader_review',
                  'goal':row.get('goal',''), 'excerpts':row.get('excerpts',[]),
                  'category':row.get('category',''), 'impact':row.get('impact',''),
                  'preserve':row.get('preserve',[])}
            if 'scene_focus' in row:goal['scene_focus']=row['scene_focus']
            rows.append(goal)
    indices=set(critique.get('blocking_issues',[]))
    indices.update(i for i,r in enumerate(critique.get('issues',[])) if r.get('severity') in ('medium','high'))
    for i in sorted(indices):
        row=critique['issues'][i]
        if 'scene_focus' in row and row.get('evidence_status')=='unverified':
            continue
        goal={'id':f'critic-{i}','goal':row.get('suggestion') or row.get('description',''),
            'excerpts':row.get('evidence',[])}
        if 'scene_focus' in row:
            goal.update(scene_focus=row['scene_focus'],impact=row.get('impact',''),dimension=row.get('dimension'))
        rows.append(goal)
    prior=source.get('prior_revision') or {}
    for i,row in enumerate(prior.get('remaining_issues',[])):
        excerpts=[q for q in row.get('excerpts',[]) if isinstance(q,str) and q and q in source.get('source_body','')]
        if excerpts and row.get('goal'):
            rows.append({'id':f'prior-{i}','goal':row['goal'],'excerpts':excerpts})
    bound_goals = []
    positions = set()
    for row in rows:
        if 'scene_focus' in row:
            body = source['source_body']
            offset = expression.scene_focus_position(row,body)
            identity = (offset,row['scene_focus']['quote'])
            if identity in positions:
                continue
            positions.add(identity)
            row = patches.bind_scene_goal(body,[],body,row,offset)
        bound_goals.append(row)
    return bound_goals


def precision_goals(source,checks):
    expected={row['paragraph_id']:row['details'] for row in source['precision_candidates']}
    paragraphs={row['id']:row for row in source['paragraphs']}
    if not isinstance(checks,list) or any(not isinstance(row,dict) for row in checks):
        raise ValueError('报数候选须逐项提交判断')
    ids=[row.get('paragraph_id') for row in checks]
    if any(not isinstance(key,str) for key in ids) or len(ids)!=len(set(ids)) or not expected.keys()<=set(ids):
        raise ValueError('报数候选须逐项提交判断：'+', '.join(expected))
    result=[]
    for row in checks:
        key=row['paragraph_id'];action=row.get('action');remove=row.get('remove');reason=row.get('reason')
        if (key not in paragraphs or action not in ('keep','revise','outside_scope') or not isinstance(reason,str) or not reason.strip()
                or not isinstance(remove,list) or any(not isinstance(item,str) or item not in paragraphs[key]['text']
                    or not packet.precision().detail_keys(item) for item in remove)
                or (action=='revise')!=bool(remove)):
            raise ValueError('报数候选判断不完整：'+key)
        if (source.get('precision_review_version')==2 and action=='outside_scope'
                and not (source.get('author_feedback') or '').strip()):
            raise ValueError('本轮没有范围限制，不能跳过数字验收：'+key)
        if action=='revise':
            paragraph=paragraphs[key]
            result.append({'id':'precision-'+key,'goal':'省去可替代的精确值 '+ '、'.join(remove)+'。'+reason,
                           'excerpts':[paragraph['text']],'paragraph_id':key,'remove':remove})
    return result


def check_precision_goals(source,edits,goals):
    rows={row['id']:row['text'] for row in source['paragraphs']}
    precision=packet.precision()
    removed=[]
    for goal in goals:
        if not goal['id'].startswith('precision-'):continue
        key=goal['paragraph_id']
        paragraph=rows[key]
        # Apply only the edits that belong to the frozen source paragraph. Other
        # speakers and unrelated scenes may legitimately use the same values.
        scoped=[{**edit,'paragraph_id':'p0001'} for edit in edits if edit['paragraph_id']==key]
        if scoped and not (len(scoped)==1 and scoped[0]['old']==paragraph and not scoped[0]['replacement'].strip()):
            paragraph=patches.apply_patches(paragraph,{'source_sha256':sha(paragraph.encode()),'edits':scoped})
        elif scoped:
            paragraph=''
        keys=precision.detail_keys(' '.join(goal['remove']))
        if keys & precision.detail_keys(paragraph):
            raise ValueError('返修目标 '+goal['id']+' 的确数仍在：'+'、'.join(goal['remove'])+'。'+goal['goal'])
        removed.append((rows[key],goal['remove']))
    if removed and source.get('precision_review_version')==2:
        body=source['source_body']
        after=patches.apply_patches(body,{'source_sha256':sha(body.encode()),'edits':edits})
        precision.check_removed(body,after,removed)


def compact_exchange_revisions(review, exchanges):
    if not isinstance(review, dict) or not isinstance(review.get('passed'), list) or not isinstance(review.get('revisions'), list):
        raise ValueError('连续对白须提交 exchange_review，含 passed 和 revisions 两个数组。')
    revisions = review['revisions']
    if any(not isinstance(row, dict) for row in revisions):
        raise ValueError('连续对白 revisions 须提交返修对象。')
    coverage = review['passed'] + [row.get('exchange_id') for row in revisions]
    if any(not isinstance(key, str) for key in coverage):
        raise ValueError('连续对白验收须引用连续对白段编号。')
    counts = Counter(coverage)
    errors = []
    for label, keys in (
        ('缺少', [key for key in exchanges if key not in counts]),
        ('重复', [key for key, count in counts.items() if count > 1]),
        ('未知', [key for key in counts if key not in exchanges]),
    ):
        if keys:
            errors.append(label + ' ' + ', '.join(keys))
    if errors:
        raise ValueError('连续对白编号须逐段且仅出现一次：' + '；'.join(errors))

    checks = []
    for row in revisions:
        exchange_id = row['exchange_id']
        if len(exchanges[exchange_id]['turn_ids']) < 2:
            raise ValueError(f'连续对白 {exchange_id} 修订须有至少两处实际话轮。')
        phase = row.get('phase')
        if phase not in ('opening', 'later'):
            raise ValueError(f'连续对白 {exchange_id} 返修须区分开场 opening 与后续 later。')
        turns = row.get('turns')
        if phase == 'opening':
            if 'turns' in row:
                raise ValueError(f'连续对白 {exchange_id} 开场依据由正文绑定，省略 turns。')
            turns = [{'turn_id': key} for key in exchanges[exchange_id]['turn_ids'][:2]]
        checks.append({**row, 'focus': 'checklist_exchange', 'status': 'revise', 'turns': turns})
    return checks


def dialogue_goals(source, checks, exchange_review=None):
    if not isinstance(checks,list) or not checks or any(not isinstance(row,dict) for row in checks):
        raise ValueError('须提交对白验收结论，有对白时逐字引出接话，有范围限制时说明')
    version=source.get('dialogue_check_version',1)
    focused=version>=2
    required={'literal_echo','situational_speech'}
    new_checks={'checklist_exchange','scripted_delivery'}
    if version>=4:new_checks.add('voice_contrast')
    if version>=3:required.update(new_checks)
    paragraphs=source['paragraphs']
    exchange_checks = version >= 6
    compact_exchanges = version >= packet.COMPACT_EXCHANGE_REVIEW_VERSION
    turns_by_id, exchanges = packet.dialogue_exchanges(paragraphs) if exchange_checks else ({}, {})
    non_turn_ids = set()
    excluded = {}
    if exchange_checks:
        required.remove('checklist_exchange')
    if compact_exchanges:
        if any(row.get('focus') == 'checklist_exchange' for row in checks):
            raise ValueError('连续对白逐段验收须填写 exchange_review。')
        if isinstance(exchange_review, dict) and 'non_turn_ids' in exchange_review:
            candidates = turns_by_id
            turns_by_id, exchanges = packet.confirmed_dialogue(candidates, exchanges, exchange_review['non_turn_ids'])
            non_turn_ids = set(exchange_review['non_turn_ids'])
            for turn_id in non_turn_ids:
                turn = candidates[turn_id]
                left = turn['offset']
                excluded.setdefault(turn['paragraph_id'], []).append((left, left + len(turn['quote'])))
        checks = checks + compact_exchange_revisions(exchange_review, exchanges)
    elif exchange_checks:
        if len(exchanges) == 1:
            # With only one frozen exchange the older single verdict is unambiguous.
            only = next(iter(exchanges))
            checks = [row | {'exchange_id': only} if row.get('focus') == 'checklist_exchange'
                      and 'exchange_id' not in row and row.get('status') in {'pass', 'revise'} else row for row in checks]
        coverage = [row.get('exchange_id') for row in checks if row.get('focus') == 'checklist_exchange']
        expected = list(exchanges) or [None]
        if len(coverage) != len(expected) or any(coverage.count(key) != 1 for key in expected):
            raise ValueError('连续对白须按 dialogue_exchanges 逐段验收：'+', '.join(exchanges))
    if focused:
        labels=[row.get('focus') for row in checks]
        if (any(label not in (*required,'other','checklist_exchange') for label in labels)
                or any(labels.count(label)!=1 for label in required)):
            raise ValueError('须逐项提交对白验收：'+', '.join(sorted(required)))
    indices={row['id']:index for index,row in enumerate(paragraphs)}
    targets=[]
    seen=set()
    for number,check in enumerate(checks,1):
        status,reason,goal,turns=(check.get(key) for key in ('status','reason','goal','turns'))
        focus=check.get('focus')
        exchange = exchanges.get(check.get('exchange_id')) if exchange_checks and focus == 'checklist_exchange' else None
        if (status not in ('pass','revise','not_applicable') or not isinstance(reason,str) or not reason.strip()
                or not isinstance(goal,str) or not isinstance(turns,list) or (status=='revise')!=bool(goal.strip())):
            raise ValueError('对白验收须有判断与具体理由，返修项须给出可执行目标')
        if exchange_checks and focus == 'checklist_exchange' and bool(exchange) == (status == 'not_applicable'):
            raise ValueError('连续对白存在时必须给出 pass 或 revise；无连续对白时填 not_applicable')
        if exchange and version == 8:
            opening_status = check.get('opening_status')
            opening_reason = check.get('opening_reason')
            if opening_status not in ('pass', 'revise') or not isinstance(opening_reason, str) or not opening_reason.strip():
                raise ValueError('交锋开场须独立给出 opening_status 和 opening_reason 结论。')
            if opening_status == 'revise' and status != 'revise':
                raise ValueError('交锋开场需要返修，整段须填 revise 并给开场返修目标。')
            if (opening_status == 'revise' or status == 'pass') and [
                item.get('turn_id') for item in turns[:2] if isinstance(item, dict)
            ] != exchange['turn_ids'][:2]:
                raise ValueError('交锋开场的结论须引用该段开头两个连续对白编号。')
        if status=='not_applicable':
            if turns or (not focused and len(checks)!=1):raise ValueError('不适用仅用于当前范围没有可核对的对白')
            continue
        minimum=1 if version>=3 and focus=='scripted_delivery' else 2
        maximum = len(exchange['turn_ids']) if exchange else len(turns_by_id) if version >= 7 else 3
        if not minimum<=len(turns)<=maximum or any(not isinstance(turn,dict) for turn in turns):
            raise ValueError('须引用当前对白；单向讲话可引用一段原话，其余须对照两到三处。')
        offsets=[];quotes=[];scope=[]
        resolved_turns = []
        exchange_indices = []
        for turn in turns:
            if exchange_checks and 'turn_id' in turn:
                turn_id = turn['turn_id']
                resolved = turns_by_id.get(turn_id) if isinstance(turn_id, str) else None
                if compact_exchanges and isinstance(turn_id, str) and turn_id in non_turn_ids:
                    raise ValueError('已标记为非对白的引号内容不能作为话轮证据。')
                if not resolved or (exchange and turn_id not in exchange['turn_ids']):
                    raise ValueError('对白编号必须来自当前冻结正文及指定连续对白段')
                if exchange:
                    exchange_indices.append(exchange['turn_ids'].index(turn_id))
                turn = {key: resolved[key] for key in ('paragraph_id', 'quote')}
                row = paragraphs[resolved['paragraph_index']]
                start = row['start'] + resolved['offset']
                if offsets and start < offsets[-1]:
                    raise ValueError('对白编号须按正文顺序，且不可重复')
                offsets.append(start + len(turn['quote']))
                quotes.append(turn['quote'])
                scope.append(resolved['paragraph_index'])
                resolved_turns.append(turn)
                continue
            if exchange:
                raise ValueError('连续对白证据只用 turn_id 引用，保留真实台词及顺序')
            key,quote=turn.get('paragraph_id'),turn.get('quote')
            if not isinstance(key,str) or key not in indices or not isinstance(quote,str) or not quote.strip():
                raise ValueError('对白引文须绑定冻结原文段落')
            index=indices[key];row=paragraphs[index]
            speech=re.finditer(r'“[^”]+”|「[^」]+」|『[^』]+』|"[^"\r\n]+"|(?m:^\s*[—–-]+[^\r\n]+)',row['text'])
            positions=[match.start()+match[0].find(quote) for match in speech if quote in match[0]]
            positions = [pos for pos in positions if not any(max(pos, left) < min(pos + len(quote), right)
                         for left, right in excluded.get(key, []))]
            start=next((row['start']+pos for pos in positions if not offsets or row['start']+pos>=offsets[-1]),None)
            if not positions:raise ValueError('对白引文须逐字出自指定段落的台词')
            if start is None:raise ValueError('对白引文须按正文顺序，且不可重叠')
            offsets.append(start+len(quote));quotes.append(quote);scope.append(index)
            resolved_turns.append(turn)
        if exchange and exchange_indices != list(range(exchange_indices[0], exchange_indices[0] + len(turns))):
            valid = ', '.join(exchange['turn_ids'])
            if version < 7:
                raise ValueError(f'连续对白 {check["exchange_id"]} 须引用至少两处紧接的话轮，收到的索引为 {exchange_indices}。可用编号按序为 {valid}。')
            # In v7 these ordinal references bound a continuous source range.
            # Fill gaps with the exact intervening lines while retaining the model's target index.
            requested = resolved_turns
            resolved_turns = [{k: turns_by_id[turn_id][k] for k in ('paragraph_id','quote')}
                              for turn_id in exchange['turn_ids'][exchange_indices[0]:exchange_indices[-1]+1]]
            quotes = [turn['quote'] for turn in resolved_turns]
        else:
            requested = resolved_turns
        identity=(focus,tuple(offsets)) if version>=3 else tuple(offsets)
        # Identical language in different turns is evidence of a shared
        # template. The ordered offsets above still reject reusing one span.
        if identity in seen or (version<4 and not expression._distinct_quotes(quotes)):
            raise ValueError('对白验收须引用不同的原文位置，同一组只提交一次')
        seen.add(identity)
        if status=='revise':
            anchors = exchange['paragraph_ids'] if exchange else [row['id'] for row in paragraphs[scope[0]:scope[-1]+1]]
            identifier = f'dialogue-{check["exchange_id"]}' if compact_exchanges and exchange else f'dialogue-{number}'
            target={'id':identifier,'goal':goal,'excerpts':quotes,
                    'paragraph_ids':anchors,'turns':resolved_turns}
            if exchange:
                target['exchange_id'] = check['exchange_id']
            if focused:
                index=check.get('target_turn')
                if type(index) is not int or not 0<=index<len(turns):raise ValueError('对白返修须标明要改的目标原话')
                if compact_exchanges and exchange and check['phase'] == 'later' and exchange_indices[index] < 2:
                    raise ValueError(f'连续对白 {check["exchange_id"]} 的开场返修须填 phase=opening。')
                target.update(focus=focus,target=requested[index])
            if version>=3 and focus in new_checks:
                preserve=check.get('preserve')
                if not isinstance(preserve,list) or not preserve or any(not isinstance(s,str) or not s.strip() for s in preserve):
                    raise ValueError('新对白返修目标须说明需要保留的信息、交际用途或有效口气。')
                target['preserve']=preserve
            targets.append(target)
    return targets


def goal_paragraph_ids(goal):
    return goal.get('paragraph_ids') or [goal['target']['paragraph_id']]


def scope_edits(edits, goal):
    if goal['id'].startswith('scene-'):
        return [edit for edit in edits if edit.get('group_id') == goal['id']]
    ids = set(goal_paragraph_ids(goal))
    return [edit for edit in edits if edit['paragraph_id'] in ids]


def check_scoped_edit(edits, goal, paragraphs, label):
    ids = set(goal_paragraph_ids(goal))
    scoped = scope_edits(edits, goal)
    edited_ids = {edit['paragraph_id'] for edit in scoped}
    if edited_ids <= ids:
        changed = [patches._scoped_paragraph(paragraphs[key], scoped) != paragraphs[key]['text']
                   for key in edited_ids]
        if any(changed):
            return
    raise ValueError(f"{label}{goal['id']} 须在定位范围内交付逐字原文补丁：{goal['goal']}")


def check_dialogue_goals(edits, goals, source):
    paragraphs = {row['id']: row for row in source['paragraphs']}
    for goal in goals:
        if goal['id'].startswith('dialogue-') and 'scene_anchor' not in goal:
            check_scoped_edit(edits, goal, paragraphs, '对白返修目标 ')


def scene_goals(source, checks):
    if not isinstance(checks, list) or not checks:
        raise ValueError('须提交场景因果检查。')
    paragraphs = source['paragraphs']
    narration_review = source.get('dialogue_check_version', 1) >= 7
    if narration_review and (any(not isinstance(row, dict) for row in checks)
            or not any(row.get('focus') in ('narration', 'both') for row in checks)):
        raise ValueError('整段叙述须在 scene_checks 给出 focus=narration 或 both 的结论。')
    indices = {row['id']: index for index, row in enumerate(paragraphs)}
    targets = []
    seen = set()
    for number, row in enumerate(checks, 1):
        status, reason, goal, anchors = (row.get(key) for key in ('status', 'reason', 'goal', 'anchors'))
        preserve = row.get('preserve', [])
        focus = row.get('focus', 'causality')
        if narration_review and focus not in ('narration', 'causality', 'both'):
            raise ValueError('场景检查的 focus 必须对应叙述或因果。')
        if (status not in ('pass', 'revise', 'not_applicable') or not isinstance(reason, str) or not reason.strip()
                or not isinstance(goal, str) or not isinstance(anchors, list) or not isinstance(preserve, list)
                or any(not isinstance(value, str) or not value.strip() for value in preserve)
                or (status == 'revise') != bool(goal.strip() and preserve)):
            raise ValueError('场景检查须说明判断；返修须给目标与须保留的事实或结局。')
        if status == 'not_applicable':
            if len(checks) != 1 or anchors or goal or preserve:
                raise ValueError('没有可核对的场景时，单独说明不适用。')
            continue
        if len(anchors) != 3:
            raise ValueError('场景检查须引用起因、中间反应和后果三处原文。')
        scope, excerpts = [], []
        resolved = []
        for anchor in anchors:
            key, quote = anchor.get('paragraph_id'), anchor.get('quote')
            if (set(anchor)=={'paragraph_id'} or narration_review) and isinstance(key, str) and key in indices:
                quote = paragraphs[indices[key]]['text']
            if (not isinstance(key, str) or key not in indices or not isinstance(quote, str)
                    or not quote.strip() or quote not in paragraphs[indices[key]]['text']):
                raise ValueError('场景证据须逐字出自冻结原文的指定段落。')
            scope.append(indices[key])
            excerpts.append(quote)
            resolved.append({'paragraph_id': key, 'quote': quote})
        if scope != sorted(set(scope)) or (scope[0], scope[-1]) in seen:
            raise ValueError('场景证据须按正文顺序来自不同段落，同一范围只提交一次。')
        seen.add((scope[0], scope[-1]))
        if status == 'revise':
            targets.append({'id': f'scene-{number}', 'goal': goal, 'excerpts': excerpts, 'anchors': resolved,
                            **({'focus': focus} if narration_review else {}),
                            'paragraph_ids': [p['id'] for p in paragraphs[scope[0]:scope[-1] + 1]],
                            'preserve': preserve})
    return targets


def check_scene_goals(edits, goals, source):
    paragraphs = {row['id']: row for row in source['paragraphs']}
    for goal in goals:
        if goal['id'].startswith('scene-') and 'scene_anchor' not in goal:
            check_scoped_edit(edits, goal, paragraphs, '场景返修目标 ')


def writer_input(root,folder,critique_path):
    b,source=bound(root,folder)
    confirmed=source.get('confirmed_reader')
    if confirmed:
        p=safe(root,f'story/{b["chapter_number"]}/reader_report.json')
        critique={'issues':[],'source':'reader_review','reader_binding':confirmed['binding_path']}
    else:
        p=safe(root,critique_path)
        critique=read(p)
    exchange_retry_path = safe(root, folder+'/critic-exchange-repair.json')
    exchange_retry = read(exchange_retry_path) if exchange_retry_path.is_file() else None
    if exchange_retry and not confirmed:
        critique = report_repair.apply_exchange_retry(critique, exchange_retry, b['body_sha256'])
        p = safe(root, folder+'/critique-accepted.json')
    try:
        if confirmed:targets=confirmed['goals']
        elif source.get('review_protocol')==SCOPED_REVIEW:
            if source.get('tone_review',{}).get('scene_edit_version')==1:
                verified=tone.verified_scenes(critique.get('scene_pass',[]),source['paragraphs'])
                if critique.get('scene_pass') and not verified:
                    raise ValueError('逐场审读意见没有可定位的引文。请引用单段中连续的一小句。')
                critique={**critique,'scene_pass':verified}
            targets=scoped_critic_goals(source,critique)
        else:targets=goals(source,critique)
    except ValueError as exc:
        reason='整场表达目标复查：'+str(exc)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
        raise Retry('agent_sc',reason) from exc
    if source.get('precision_candidates'):
        try:targets+=precision_goals(source,critique.get('precision_checks',[]))
        except ValueError as exc:
            reason='precision_review_format: '+str(exc)
            guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
            raise Retry('agent_sc',reason) from exc
    if source.get('dialogue_check'):
        try:targets+=dialogue_goals(source,critique.get('dialogue_checks'),critique.get('exchange_review'))
        except ValueError as exc:
            reason='dialogue_review_format: '+str(exc)
            if exchange_retry is None and '指定连续对白段' in str(exc) and source.get('dialogue_check_version',1)>=packet.COMPACT_EXCHANGE_REVIEW_VERSION:
                turns, exchanges = packet.dialogue_exchanges(source['paragraphs'])
                _, exchanges = packet.confirmed_dialogue(turns, exchanges, critique['exchange_review'].get('non_turn_ids', []))
                repair = report_repair.exchange_request(critique, b['body_sha256'], exchanges)
                if repair:
                    save(exchange_retry_path, repair)
            guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
            raise Retry('agent_sc',reason) from exc
    if source.get('dialogue_check_version', 1) >= 5:
        try:
            targets += scene_goals(source, critique.get('scene_checks'))
        except (AttributeError, ValueError) as exc:
            reason = 'scene_review_format: ' + str(exc)
            guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
            raise Retry('agent_sc',reason) from exc
    data={**source,'critique':critique,'goals':targets,
          'length_edit_budget':patches.length_edit_budget(quality.count_prose(source['source_body']),quality.required_bounds(b.get('target_policy',b['bounds'])))}
    if source.get('tone_review',{}).get('compare_scene_trials'):
        scenes=critique.get('scene_pass',[])
        data['scene_trial_windows']=tone.trial_windows(scenes,source['paragraphs'])
        detection = source.get('zhuque_review', {})
        if (detection.get('trial_version') == 1 and detection['attention'] and detection['reference_paragraphs']
                and not source['author_feedback'].strip()):
            targets.append({'id':'trial-zhuque', 'source':'scene_trial', 'level':'advisory',
                            'goal':'做一次同篇写法对照。选值得试写的标记处，对照合适的参考原句，交付可匿名比较的正文补丁。'
                                   '可以重构这段怎样被说出或被看见；沿用本书事实、叙述权限和人物用词。原文更好时可保留。',
                            'excerpts':[]})
        for i,scene in enumerate(scenes):
            if source['tone_review'].get('optional_scene_trials') and scene['decision']=='keep':
                continue
            alternative=scene.get('alternative')
            if not isinstance(alternative,str) or not alternative.strip():
                continue
            targets.append({'id':f'trial-{i}','source':'scene_trial','level':'advisory',
                           'paragraph_id':scene['paragraph_id'],'excerpts':[scene['quote']],
                           'goal':'试写并提交这个场面的另一种演法：'+alternative+' 原场需要保住的作用：'+scene['impact']})
    if source.get('added_text_review'):
        data['growth_guidance']=patches.GROWTH_GUIDANCE
    prior=safe(root,folder+'/editor-binding.json')
    previous=read(prior) if prior.is_file() else None
    if previous is None or previous['input_sha256']!=digest(data):
        data['writer_view_version']=packet.FOCUSED_WRITER_VERSION
        references=('meta/story_plan.md','meta/character_profiles.md','meta/character_voice_adaptations.md',b['reference_path'])
        data['writer_references']={path:book.policy().effective_text(root,path) for path in dict.fromkeys(references)
                                   if path and safe(root,path).is_file()}
    review_version=packet.COMPACT_REVIEW_VERSION if previous is None else previous.get('reviewer_view_version')
    if review_version is not None:data['reviewer_view_version']=review_version
    if exchange_retry and not confirmed:
        if p.is_file() and read(p) != critique:
            raise ValueError('已经采用的对白补审结果发生变化，请新建任务')
        if not p.is_file():
            save(p, critique)
    receipt={'critique_path':p.relative_to(root).as_posix(),'critique_sha256':sha(p.read_bytes()),'input_sha256':digest(data)}
    if 'reviewer_view_version' in data:receipt['reviewer_view_version']=data['reviewer_view_version']
    if previous is not None and previous!=receipt:raise ValueError('本轮自审或编辑输入已有变化，请新建任务')
    save(safe(root,b['outputs']['revision_input']),data);save(prior,receipt)
    if b['outputs'].get('revision_editor_model'):save_model(safe(root,b['outputs']['revision_editor_model']),data,'writer')
    return b['outputs']


def critic_source_excerpts(row, body):
    quotes = row.get('evidence', [])
    if isinstance(quotes, str):
        quotes = [quotes]
    if not isinstance(quotes, list):
        return []
    wrapped = {r.get('index') for r in row.get('evidence_repairs', [])
               if isinstance(r, dict) and r.get('repair') == 'paired_outer_quote'}
    excerpts = []
    for index, quote in enumerate(quotes):
        if not isinstance(quote, str) or not quote.strip():
            return []
        if quote in body:
            excerpts.append(quote)
            continue
        if row.get('evidence_status') != 'verified':
            return []
        text = quote.strip()
        if index in wrapped and {'“':'”','‘':'’','"':'"',"'":"'"}.get(text[0]) == text[-1]:
            text = text[1:-1].strip()
        # Apply only the normalizer's whitespace equivalence; retain the actual source bytes.
        words = text.split()
        match = re.search(r'\s+'.join(re.escape(word) for word in words), body) if words else None
        if match is None:
            return []
        excerpts.append(match.group())
    return excerpts


def scoped_critic_goals(source,critique):
    result=[]
    for index,row in enumerate(critique['issues']):
        quotes=critic_source_excerpts(row,source['source_body'])
        impact = row.get('impact')
        minor_edit = (row.get('severity') == 'low' and source.get('tone_review', {}).get('handoff_version') == 2
                      and isinstance(impact, str) and bool(impact.strip())
                      and isinstance(row.get('suggestion'), str) and bool(row['suggestion'].strip()))
        if ((not minor_edit and row.get('severity') not in ('medium','high')) or row.get('evidence_status')=='unverified'
                or not quotes):
            continue
        goal={'id':f'critic-{index}','source':'local_critic','level':'advisory',
              'goal':row['suggestion'],'excerpts':quotes,'preserve':row.get('preserve',[])}
        if minor_edit:
            goal['goal'] += ' 阅读影响：' + impact.strip()
        required=row.get('required_source')
        if required:
            if required not in source['author_feedback']:
                raise ValueError('作者必改目标须逐字引用本轮真实作者要求')
            goal.update(level='mandatory',required_source=required)
        source_quote=row.get('source_quote')
        if source_quote and not required:
            confirmed=source['confirmed_context']+'\n'+book.prompt(source['book_contract'])+'\n'+source['source_body']
            if source_quote not in confirmed:
                raise ValueError('客观事实矛盾须有冻结资料的逐字依据')
            goal.update(level='hard',source_quote=source_quote)
        if 'scene_focus' in row:
            goal['scene_focus']=row['scene_focus']
            try:
                offset=expression.scene_focus_position({**row,'excerpts':quotes},source['source_body'])
            except ValueError:
                if goal['level']!='advisory' or not source.get('tone_review',{}).get('scene_edit_version'):
                    raise
                # A malformed optional focus is not evidence for a rewrite.
                # Other grounded goals and the original critic record are independent.
                continue
            goal=patches.bind_scene_goal(source['source_body'],[],source['source_body'],goal,offset)
        result.append(goal)
    if source.get('tone_review',{}).get('scene_edit_version')==1:
        result.extend(tone.scene_goals(critique.get('scene_pass',[]),result))
    return result


def editor_bound(root,b):
    folder=b['outputs']['revision_dir'];receipt=read(safe(root,folder+'/editor-binding.json'))
    data=read(safe(root,b['outputs']['revision_input']))
    if digest(data)!=receipt['input_sha256'] or sha(safe(root,receipt['critique_path']).read_bytes())!=receipt['critique_sha256']:
        raise ValueError('自审或冻结编辑输入已有变化，未发布')
    if b['outputs'].get('revision_editor_model'):
        verify_model(read(safe(root,b['outputs']['revision_editor_model'])),data,'writer')
    return data


def check_local_tone(source, edits, proposed=()):
    review = source.get('local_tone') or local_tone_policy(source)
    protected = source['book_contract']['protected_phrases']
    pending = {}
    if review['edited_only']:
        touched = {e['paragraph_id'] for e in [*proposed, *edits]}
        for row in source['paragraphs']:
            key, old = row['id'], row['text']
            if key not in touched and key not in review['marks']:
                continue
            def local_spans(items):
                local = [{**e, 'paragraph_id':'p0001'} for e in items if e['paragraph_id'] == key]
                return [(a,b,local[i]['replacement']) for a,b,i in sorted(patches._patch_spans(old, local))]
            original_scope = local_spans(proposed or edits)
            updated = patches._scoped_paragraph(row, edits)
            delta = 0
            new_scope = []
            for start, end, replacement in local_spans(edits):
                new_scope.append((start+delta, start+delta+len(replacement)))
                delta += len(replacement) - (end-start)
            hits = tone.scoped_remaining(old, updated, [(a,b) for a,b,_ in original_scope],
                                         new_scope, review['marks'].get(key, ()), protected)
            if hits:
                pending[key] = hits
    else:
        touched = {e['paragraph_id'] for e in edits}
        for row in source['paragraphs']:
            key = row['id']
            if key in review['marks'] or key in touched:
                text = patches._scoped_paragraph(row, edits)
                hits = tone.remaining(text, review['marks'].get(key, []), protected, original=row['text'])
                if hits:
                    pending[key] = hits
    if pending:
        raise ValueError(tone.REPHRASE + json.dumps(pending, ensure_ascii=False))


def local_rephrases(source, edits):
    return tone.rephrased_indices(source['source_body'], edits, patches, source['book_contract']['protected_phrases'])


def compose(root,b,source,*,before_blind=False):
    data=editor_bound(root,b);payload=read(safe(root,b['outputs']['revision_patch_path']))
    if payload.get('status')=='needs_replan':
        if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:
            raise ValueError('冲突响应不能夹带未审核正文补丁')
        raise_conflict(root,b,source,payload,payload.get('reason'),payload.get('evidence'))
    detection = source.get('zhuque_review', {})
    if detection.get('required'):
        proposed = zhuque.compile_rewrites(detection, payload)
    else:
        if 'rewrites' in payload:
            raise ValueError('当前任务没有朱雀必改清单，请提交正常的 edits。')
        proposed = payload['edits']
    working=pending.current(root,b,digest)
    merged=pending.merge(source['source_body'],(working or {}).get('edits',[]),proposed,patches)
    # A prior equivalent judgment grants only removal, never publication. The
    # native append-only event binds the exact proposals and original review.
    events = guard.store().events(root)
    rechecking_subset=False
    for event in events:
        pruning=event['data']
        if (event['kind'] in ('scene_trial_prune','scene_trial_selection') and pruning.get('task_id')==b['task_id']
                and pruning.get('binding_digest')==digest(b) and pruning.get('merged_digest')==digest(merged)):
            indices=scene_trial_prunes(pruning['review_report'],pruning['review_context'])
            if indices!=pruning['indices']:raise ValueError('逐场候选的撤回依据与原复核不符')
            merged=[edit for i,edit in enumerate(merged) if i not in indices]
            rechecking_subset=True
        if (event['kind']=='equivalent_prune' and pruning.get('task_id')==b['task_id']
                and pruning.get('binding_digest')==digest(b) and pruning.get('merged_digest')==digest(merged)):
            old=pruning['review_context'];raw=pruning['review_report']
            reasons=review_decision(raw,old);expanded=wire.expand(raw,old)
            removable=equivalent_indices(expanded,old,reasons)
            if removable!=pruning['indices']:raise ValueError('等价撤回凭据与原始判断不符')
            merged=[edit for index,edit in enumerate(merged) if index not in removable]
    blind_record=None
    if 'blind_seed' in b and not before_blind:
        public,decoder=blind.packet(source['source_body'],merged,data.get('scene_trial_windows',[]),b['blind_seed'],patches, required=source.get('zhuque_review',{}).get('required',False))
        for event in reversed(events):
            vote=event['data']
            if (event['kind']=='blind_scene_selection' and vote.get('task_id')==b['task_id']
                    and vote['binding_digest']==digest(b) and vote['edits_digest']==digest(merged)
                    and vote['report']['ballot']==public['ballot']):
                merged=blind.select(public,decoder,merged,vote['report'],keep_on_tie=local_rephrases(source, merged))
                blind_record=digest(vote['report'])
                rechecking_subset=True
                break
    candidate=patches.apply_patches(source['source_body'],{'source_sha256':payload['source_sha256'],'edits':merged},protected_phrases=source['book_contract']['protected_phrases'])
    check_local_tone(source, merged, proposed)
    if source.get('review_protocol')!=SCOPED_REVIEW:
        if any(row['id'].startswith('precision-') for row in data['goals']):check_precision_goals(source,merged,data['goals'])
        check_dialogue_goals(merged,data['goals'],source)
        check_scene_goals(merged,data['goals'],source)
    if source.get('fixed_edit') and sha(candidate.encode())!=source['fixed_edit']['candidate_sha256']:
        raise ValueError('候选超出作者指定的单句删除范围')
    if detection.get('required'):
        zhuque.check_coverage(detection, merged)
    measured=quality.measurement(candidate.encode(),b['chapter_number'],b.get('target_policy',b['bounds']))
    if quality.is_blocking(measured):
        path=safe(root,b['outputs']['revision_dir']+'/length-candidates.json');history=read(path) if path.is_file() else []
        key=sha((digest(payload)+':'+str(safe(root,b['outputs']['revision_patch_path']).stat().st_mtime_ns)).encode())
        if key not in [r['key'] for r in history]:history.append({'key':key,'patch_digest':digest(payload),'measurement':measured})
        save(path,history)
        if 'target_policy' not in b:
            raise ValueError('候选篇幅未达作者目标：'+json.dumps(measured,ensure_ascii=False))
    context={'task_id':b['task_id'],'source_body':source['source_body'],'source_sha256':b['body_sha256'],'candidate':candidate,
             'candidate_sha256':sha(candidate.encode()),'book_contract':source['book_contract'],
             'book_contract_sha256':b['book_contract_sha256'],'confirmed_context':source['confirmed_context'],
             'author_feedback':source['author_feedback'],'goals':[g for g in data['goals'] if g.get('source')!='scene_trial'],'edits':merged,
             'patch_digest':digest(payload),'evidence_catalog':evidence.catalog(candidate),'length':measured}
    rephrased = local_rephrases(source, merged)
    if rephrased:
        context['local_rephrased_indices'] = rephrased
    if data.get('writer_view_version')==packet.FOCUSED_WRITER_VERSION:
        context.update(writer_view_version=packet.FOCUSED_WRITER_VERSION,reader_report=source['reader_report'],
                       critique=data['critique'])
    if source.get('precision_review_version')==2:context['precision_review_version']=2
    if 'reviewer_view_version' in data:context['reviewer_view_version']=data['reviewer_view_version']
    if source.get('review_protocol')==SCOPED_REVIEW:context['review_protocol']=SCOPED_REVIEW
    if source.get('tone_review',{}).get('scene_edit_version')==1:
        context['deletion_review_version']=1
    signoff_version=source.get('tone_review',{}).get('whole_signoff_version')
    windows=data.get('scene_trial_windows') or []
    if blind_record:
        context['blind_vote_digest']=blind_record
        if not windows:
            windows=[{'anchor':r[0]['id'],'first':r[0]['id'],'last':r[-1]['id']} for r in blind.scene_ranges(source['paragraphs'],[])]
    if (windows and signoff_version in (1,2)) or blind_record:
        context['whole_review_phase']='signoff' if rechecking_subset else 'selection'
        if rechecking_subset:
            # Stamp each required scene verdict with the exact candidate. A report
            # for an earlier subset cannot approve the current join by accident.
            touched={e['paragraph_id'] for e in merged if e['old']!=e['replacement']}
            for win in windows:
                ids=sorted(p for p in touched if int(win['first'][1:])<=int(p[1:])<=int(win['last'][1:]))
                if ids:
                    if signoff_version==2:
                        for goal in context['goals']:
                            if goal.get('source')=='local_critic' and goal.get('paragraph_id')==win['anchor']:
                                grouped={e['paragraph_id'] for e in merged if e.get('group_id')==goal['id']}
                                goal['paragraph_ids']=sorted({win['anchor']} | grouped.intersection(ids))
                    context['goals'].append({'id':'final-'+context['candidate_sha256'][:12]+'-'+win['anchor'],
                        'source':'scene_signoff','level':'mandatory','paragraph_ids':ids,
                        'goal':'通读当前整稿，核对本场所有改动和前后衔接。事实、视角、人物声音、删去的作用、重复及新写内容都可签发填 resolved；有具体损失或矛盾填 remaining 并说明。'})
    if data.get('scene_trial_windows') and (merged or not blind_record):
        context['untried_scene_windows']=tone.untried_windows(
            data['scene_trial_windows'], merged, first_read=not rechecking_subset,
            require_trials=not source.get('tone_review',{}).get('optional_scene_trials'))
    if source.get('added_text_review'):
        tracked = tracked_addition_goals(events,b)
        additions = [row for row in tracked if 'scene_anchor' not in row]
        mixed = source.get('mixed_added_text_review', False)
        if mixed:context['mixed_added_text_review']=True
        context.update(growth_edit_indices=patches.growth_indices(merged, include_mixed=mixed), addition_goals=additions,
                       goals=[*context['goals'], *tracked])
        if context['growth_edit_indices'] or additions:
            context['growth_review_guidance']=patches.GROWTH_REVIEW_GUIDANCE
    if any('scene_anchor' in row for row in context['goals']):
        context['scene_recheck_guidance']=expression.SCENE_OUTCOME_GUIDANCE
    context['review_input_sha256']=digest(context)
    return context


def candidate(root,folder):
    b,source=bound(root,folder)
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except CompositionConflict:raise
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',str(exc))
        raise Retry('agent_pl',str(exc)) from exc
    if 'blind_seed' in b:
        raw=compose(root,b,source,before_blind=True)
        public,_=blind.packet(source['source_body'],raw['edits'],editor_bound(root,b).get('scene_trial_windows',[]),b['blind_seed'],patches, required=source.get('zhuque_review',{}).get('required',False))
        save(safe(root,b['outputs']['revision_blind_packet']),public)
    save(safe(root,b['outputs']['revision_review_input']),context)
    if b['outputs'].get('revision_review_repair'):
        active=repair_record(root,b,context)
        save(safe(root,b['outputs']['revision_review_repair']),active or {})
    if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),context,'reviewer')
    return b['outputs']


def accept_blind(root,folder,actual):
    b,source=bound(root,folder)
    raw=compose(root,b,source,before_blind=True)
    edits=raw['edits']
    public,decoder=blind.packet(source['source_body'],edits,editor_bound(root,b).get('scene_trial_windows',[]),b['blind_seed'],patches, required=source.get('zhuque_review',{}).get('required',False))
    path=safe(root,b['outputs']['revision_blind_packet'])
    if public!=read(path):
        save(path,public)
        raise Retry('agent_blind_scene','票面已有变化，请重新对读本张票面。')
    report=read(safe(root,b['outputs']['revision_blind_path']))
    if report!=json.loads(actual):
        raise ValueError('匿名选票与本次模型实际输出不符。')
    try:
        chosen=blind.select(public,decoder,edits,report,keep_on_tie=local_rephrases(source, edits))
        patches.apply_patches(source['source_body'],{'source_sha256':b['body_sha256'],'edits':chosen},
                              protected_phrases=source['book_contract']['protected_phrases'])
    except (KeyError,TypeError,ValueError) as exc:
        raise Retry('agent_blind_scene',str(exc)) from exc
    try:
        check_local_tone(source, chosen, edits)
    except ValueError as exc:
        raise Retry('agent_pl', str(exc)) from exc
    if source.get('zhuque_review',{}).get('required'):
        try:
            zhuque.check_coverage(source['zhuque_review'], chosen)
        except ValueError as exc:
            reasons = ' '.join(row['reason'] for row in report['scenes'] if row['prefer'] != 'tie')
            raise Retry('agent_pl',str(exc)+' 对读意见：'+reasons) from exc
    record={'task_id':b['task_id'],'binding_digest':digest(b),'edits_digest':digest(edits),'report':report}
    if not any(e['kind']=='blind_scene_selection' and e['data']==record for e in guard.store().events(root)):
        guard.store().event(root,'blind_scene_selection',record)
    selected=compose(root,b,source)
    save(safe(root,b['outputs']['revision_review_input']),selected)
    save_model(safe(root,b['outputs']['revision_review_model']),selected,'reviewer')


def repair_record(root,b,context):
    rows=[r['data'] for r in guard.store().events(root) if r['kind']=='local_report_repair'
          and r['data'].get('task_id')==b['task_id'] and r['data'].get('binding_digest')==digest(b)
          and r['data'].get('review_input_sha256')==context['review_input_sha256']]
    return rows[-1]['repair'] if rows else None


def save_repair(root,b,context,repair):
    guard.store().event(root,'local_report_repair',{'task_id':b['task_id'],'binding_digest':digest(b),
        'review_input_sha256':context['review_input_sha256'],'repair':repair,
        'ordinal':len(guard.store().events(root))})
    if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),repair or {})


def tracked_addition_goals(events,binding):
    binding_digest = digest(binding)
    return next((event['data']['goals'] for event in reversed(events)
                 if event['kind']=='local_added_text_goals'
                 and event['data'].get('binding_digest')==binding_digest), [])


def growth_findings(context, report):
    if 'growth_edit_indices' not in context:
        return []
    return patches.review_additions(context['source_body'], context['edits'], report.get('added_text_reviews'),
                                    include_mixed=context.get('mixed_added_text_review', False))


def line_findings(context, report):
    source, edits, candidate = (context[key] for key in ('source_body','edits','candidate'))
    result = []
    for row in report['expression_review']['issues']:
        if 'scene_focus' not in row or row['priority'] not in ('medium','high'):
            continue
        offset = expression.scene_focus_position(row,candidate)
        goal = patches.bind_scene_goal(source,edits,candidate,row,offset,assign_id=True)
        focus = goal['scene_focus']
        if any(old.get('paragraph_id')==goal['paragraph_id'] and old.get('scene_focus', {}).get('quote')==focus['quote']
               and old['scene_focus'].get('occurrence',1)==focus.get('occurrence',1) for old in context['goals']):
            continue
        result.append({**goal,'source':'local_scene_review'})
    return result


def scoped_prose(body, rows, edits):
    offset = rows[0]['start']
    pieces = []
    for row in rows:
        pieces.extend((body[offset:row['start']], patches._scoped_paragraph(row, edits)))
        offset = row['end']
    return ''.join(pieces)


def scoped_outcome_problem(context, goal, outcome):
    """Require evidence that brackets a change within the frozen repair scope."""
    key, reason, status = (outcome[field] for field in ('id', 'reason', 'status'))
    if key != goal['id']:
        raise ValueError('对白或场景返修须复查原问题编号。')
    if status == 'remaining':
        return key + ' 原有问题仍未解决：' + reason
    if status == 'not_applicable':
        return key + ' 已定位的对白或场景目标须用候选原文复核：' + reason
    quotes = outcome['excerpts']
    if len(quotes) < 2 or not expression._distinct_quotes(quotes) or not expression._ordered_quotes(context['candidate'], quotes):
        raise ValueError('对白或场景返修须按顺序引两处不同的候选原文，证明反应和下一步行动。')
    source = context['source_body']
    edits = context['edits']
    ids = set(goal_paragraph_ids(goal))
    rows = [row for row in patches.paragraphs(source) if row['id'] in ids]
    goal_edits = scope_edits(edits, goal)
    before = scoped_prose(source, rows, [edit for edit in edits if edit not in goal_edits])
    after = scoped_prose(source, rows, edits)
    for first in re.finditer(re.escape(quotes[0]), after):
        end = first.end()
        for quote in quotes[1:]:
            start = after.find(quote, end)
            if start < 0:
                break
            end = start + len(quote)
        else:
            if after[first.start():end] not in before:
                return ''
    return key + ' 缺少原定位内能体现这次改动的候选依据：' + reason


def expand_review(report,context):
    if context.get('review_protocol')!=SCOPED_REVIEW:
        return wire.expand(report,context)
    required={'protocol','compatible','issues','change_reviews','issue_outcomes'}
    if (not isinstance(report,dict) or set(report)-{'added_text_reviews'}!=required
            or report['protocol']!=SCOPED_REVIEW):
        raise ValueError('局部独立复查须按当前协议提交事实、实际改动和原目标结论')
    # The current wire format keeps only judgments about the local edit. Use
    # the existing exact before/after binding rather than have the model copy it.
    compact={**report,'protocol':wire.PROTOCOL,
             'expression_review':{'verdict':'pass','summary':'仅核对局部改动','issues':[]},'expression_checks':[]}
    expanded=wire.expand(compact,context)
    for key in ('expression_review','expression_checks'):expanded.pop(key)
    return expanded


def scoped_assessment(report,context):
    body=context['source_body']; candidate=context['candidate']; edits=context['edits']
    report=evidence.resolve_report(expand_review(report,context),candidate)
    if (type(report['compatible']) is not bool or not isinstance(report['issues'],list)
            or report['compatible']!= (not report['issues'])):
        raise ValueError('事实复查结论与问题列表不一致')
    sources='\n'.join((body,context['confirmed_context'],context['author_feedback'],book.prompt(context['book_contract'])))
    source_rows=patches.paragraphs(body)
    by_paragraph={row['id']:row for row in source_rows}
    source_positions={row['id']:i for i,row in enumerate(source_rows)}
    changed={edit['paragraph_id'] for edit in edits}
    nearby={source_rows[j]['id'] for i,row in enumerate(source_rows) if row['id'] in changed
            for j in range(max(0,i-1),min(len(source_rows),i+2))}
    scope=[patches._scoped_paragraph(by_paragraph[key],edits) for key in nearby]
    facts=[]
    for issue in report['issues']:
        if (not isinstance(issue,dict) or issue.get('category') not in ('facts','world','pov','continuity')
                or any(not isinstance(issue.get(k),str) or not issue[k].strip()
                       for k in ('id','candidate_quote','source_quote','reason'))
                or not any(issue['candidate_quote'] in region for region in scope)
                or issue['source_quote'] not in sources):
            raise ValueError('事实矛盾须引用本轮受影响候选与冻结资料的逐字依据')
        facts.append(issue['reason'])
    signoff=context.get('whole_review_phase')=='signoff'
    if signoff and (report['change_reviews'] or report.get('added_text_reviews')):
        raise ValueError('整稿签发只提交逐场和原目标的 issue_outcomes，change_reviews 与 added_text_reviews 填 []。')
    changes=[] if signoff else patches.review_changes(edits,report['change_reviews'],source=body,candidate=candidate,
                                                       accept_equivalent=context.get('local_rephrased_indices', ()))
    if context.get('deletion_review_version')==1:
        for row in report['change_reviews']:
            i=row['edit_index']
            judgment=row.get('preservation',{})
            if edits[i]['replacement'] or judgment.get('status')!='lost':
                continue
            loss=judgment.get('lost_function')
            if not isinstance(loss,str) or not loss.strip():
                raise ValueError(f'补丁 {i} 删除后判为 lost，须填写 lost_function，具体说明候选让读者失去了哪项仍需的信息、人物声音或因果。'
                                 '只删去重复表达请判 not_applicable；作用由别处承接请判 preserved 并引用候选。')
    additions=[] if signoff else growth_findings(context,report)
    problems=facts+[row['reason'] for row in changes]+[row['reason'] for row in additions]
    blocked={row['edit_index'] for row in [*changes,*additions]}
    goals_by_id={row['id']:row for row in context['goals']}
    locators={row['id']:set(row['paragraph_ids']) for row in packet.focused_goals(context['goals'],body,packet.prose(body))}
    outcomes=report['issue_outcomes']
    if (not isinstance(outcomes,list) or any(not isinstance(row,dict) for row in outcomes)
            or len(outcomes)!=len(goals_by_id) or {row.get('id') for row in outcomes}!=set(goals_by_id)):
        raise ValueError('须按原编号核对本轮目标')
    addition_goals=context.get('addition_goals',[])
    addition_ids={row['id'] for row in addition_goals}
    pending_additions={row['id']:row['recheck_reason'] for row in patches.review_addition_outcomes(
        body,edits,addition_goals,[row for row in outcomes if row['id'] in addition_ids],candidate=candidate)}
    still_open={}
    touched={}
    hard=[]
    for outcome in outcomes:
        key=outcome['id'];goal=goals_by_id[key];status=outcome.get('status');quotes=outcome.get('excerpts');reason=outcome.get('reason')
        ids=locators[key]
        if 'scene_anchor' in goal:
            ids.update(goal['scene_anchor'].get('supporting',{}))
        touched[key]={i for i,edit in enumerate(edits)
                      if edit['paragraph_id'] in ids and edit['old']!=edit['replacement']}
        regions=[]
        for p in ids.intersection(by_paragraph):
            region=patches._scoped_paragraph(by_paragraph[p],edits)
            if region.strip():
                regions.append(region)
            elif p in changed:
                # A removed paragraph has no candidate text. Only its nearest
                # surviving neighbor on either side can attest to the join.
                for step in (-1,1):
                    pos=source_positions[p]+step
                    while 0<=pos<len(source_rows):
                        neighbor=patches._scoped_paragraph(source_rows[pos],edits)
                        if neighbor.strip():
                            regions.append(neighbor)
                            break
                        pos+=step
        if (status not in ('resolved','remaining','keep') or not isinstance(reason,str) or not reason.strip()
                or not isinstance(quotes,list) or not quotes
                or any(not isinstance(q,str) or not q.strip() or q not in candidate for q in quotes)
                or ids and not any(q in region or region.strip() and region in q for region in regions for q in quotes)):
            raise ValueError(f'{key} 的问题结论须引用原编号所在位置的当前候选原文。'
                             '请核对该编号的定位和候选正文；整稿签发时从 signoff_evidence 同编号条目中逐字引用连续片段。')
        required=goal.get('level') in ('hard','mandatory')
        problem=''
        if key in pending_additions:problem=pending_additions[key]
        elif status=='remaining' or status=='keep' and required:problem=reason
        elif 'scene_anchor' in goal:
            # The established scene validator checks localized support and
            # preserves explicit dialogue. "keep" documents why the line stays.
            local_outcome={**outcome,'status':'not_applicable' if status=='keep' else status}
            problem=patches.scene_outcome_problem(body,edits,candidate,goal,local_outcome)
        elif status=='resolved' and not touched[key]:problem='原位置尚无依据表明本轮改动已解决问题。'
        if problem:
            still_open[key]=problem
            if required:hard.append(key+' 原有必改问题仍未解决：'+problem)
    if signoff:
        # Final review is all-or-nothing. Never reconstruct an unreviewed
        # partial manuscript after a signoff or suppress a reported contradiction.
        hard.extend(facts)
    return {'facts':facts,'blocked':blocked,'additions':additions,'hard':hard,'open':still_open,
            'touched':touched,'problems':problems+hard}


def review_decision(report,context):
    if context.get('review_protocol')==SCOPED_REVIEW:
        return scoped_assessment(report,context)['problems']
    reading=book.reading()
    reading_contract=context['book_contract'].get('reading_contract',{})
    report=wire.expand(reading.without_unrequested_checks(report,reading_contract),context)
    for key in ('candidate_sha256','book_contract_sha256','review_input_sha256'):
        if report.get(key)!=context[key]:raise ValueError('独立复查与当前候选或本书规则不匹配：'+key)
    report=evidence.resolve_report(report,context['candidate'])
    if type(report.get('compatible')) is not bool or not isinstance(report.get('issues'),list):raise ValueError('独立复查缺少事实结论')
    reasons=[];source=context['source_body']+'\n'+context['confirmed_context']+'\n'+context['author_feedback']+'\n'+book.prompt(context['book_contract'])
    reading.validate_checks(report,context['candidate'],reading_contract)
    for issue in report['issues']:
        if (not isinstance(issue,dict) or any(not isinstance(issue.get(k),str) or not issue[k].strip() for k in ('id','candidate_quote','source_quote','reason'))
                or issue['candidate_quote'] not in context['candidate'] or issue['source_quote'] not in source):raise ValueError('事实复查缺少候选与冻结来源的逐字依据')
        reasons.append(issue['reason'])
    if report['compatible']!= (not report['issues']):raise ValueError('事实结论与问题列表不一致')
    additions = growth_findings(context,report)
    temp={'verdict':'pass','issues':[],'fact_review':{'verdict':'pass','summary':'独立事实复查'},'expression_review':copy.deepcopy(report.get('expression_review'))}
    quality.expression_gate(temp,context['candidate'],verified_addition_issues=bool(additions))
    expression.validate_checks(report,context['candidate'],required=True)
    reasons += [r['impact']+'；'+r['goal'] for r in temp['issues'] if r['priority'] in ('medium','high')]
    for row in patches.review_changes(context['edits'],report.get('change_reviews'),
                                      source=context['source_body'],candidate=context['candidate'],
                                      accept_equivalent=context.get('local_rephrased_indices', ())):
        reasons.append('改动未改善或损害原表达：'+row['reason'])
    reasons += [row['id']+' '+row['reason'] for row in additions]
    outcomes=report.get('issue_outcomes');goals_by_id={r['id']:r for r in context['goals']};expected=set(goals_by_id)
    if not isinstance(outcomes,list) or {r.get('id') for r in outcomes}!=expected or len(outcomes)!=len(expected):raise ValueError('原有实质问题未逐项复核')
    addition_goals = context.get('addition_goals', [])
    addition_ids = {row['id'] for row in addition_goals}
    remaining_additions = patches.review_addition_outcomes(
        context['source_body'], context['edits'], addition_goals,
        [row for row in outcomes if row['id'] in addition_ids], candidate=context['candidate'])
    reasons += [row['id']+' 增写返修仍有复述或损失有效增写：'+row['recheck_reason']
                for row in remaining_additions]
    for row in outcomes:
        if row['id'] in addition_ids:
            continue
        if (row.get('status') not in ('resolved','remaining','not_applicable') or not isinstance(row.get('reason'),str) or not row['reason'].strip()
                or not isinstance(row.get('excerpts'),list) or not row['excerpts']
                or any(not isinstance(q,str) or not q.strip() or q not in context['candidate'] for q in row['excerpts'])):raise ValueError('问题解决情况缺少当前候选原文依据')
        goal = goals_by_id[row['id']]
        if 'scene_anchor' in goal:
            reason = patches.scene_outcome_problem(context['source_body'],context['edits'],context['candidate'],goal,row)
            if reason:reasons.append(reason)
            continue
        if row['id'].startswith(('dialogue-', 'scene-')):
            reason = scoped_outcome_problem(context,goal,row)
            if reason:reasons.append(reason)
            continue
        if row['status']=='remaining':reasons.append('原有问题仍未解决：'+row['reason'])
        if goal.get('source') == 'reader_review' and row['status']=='not_applicable':
            reasons.append('已定位的返修目标须用候选原文说明解决效果：'+row['reason'])
        if (goal.get('source') == 'reader_review' and row['status']=='resolved'
                and context['candidate'] == context['source_body']):
            reasons.append('读者已核实的返修目标尚无实际修改：'+row['id'])
    return reasons


def equivalent_indices(report,context,reasons):
    rows=report['change_reviews']
    equivalent=[r for r in rows if r['effect']=='equivalent' and r['edit_index'] not in context.get('local_rephrased_indices', ())]
    # Other defects or a grouped/moved/dependent edit require writer attention.
    if not equivalent or len(reasons)!=len(equivalent):return []
    if any(r['effect']=='regressed' or r.get('preservation',{}).get('status')=='lost' for r in rows):return []
    if any(context['edits'][r['edit_index']].get('independent') is not True
           or context['edits'][r['edit_index']].get('group_id') for r in equivalent):return []
    if any(context['edits'][r['edit_index']] in scope_edits(context['edits'], goal)
           for goal in context['goals'] if goal['id'].startswith('dialogue-') and 'scene_anchor' not in goal
           for r in equivalent):return []
    return sorted(r['edit_index'] for r in equivalent)


def scene_trial_prunes(report,context):
    """Only withdraw proposals. The resulting text must receive a fresh full review."""
    if 'untried_scene_windows' not in context or context.get('whole_review_phase')=='signoff':
        return []
    expanded=expand_review(report,context)
    edits=context['edits']
    changes=expanded['change_reviews']
    if sorted(r['edit_index'] for r in changes)!=list(range(len(edits))):
        return []
    required = context.get('local_rephrased_indices', ())
    remove={r['edit_index'] for r in changes if r['effect']=='regressed' or
            (r['effect']=='equivalent' and r['edit_index'] not in required)}
    if context.get('whole_review_phase')=='selection':
        remove.update(r['edit_index'] for r in changes if r.get('preservation',{}).get('status')=='lost')
        remove.update(i for i,e in enumerate(edits) if e['old']==e['replacement'])
        for row in expanded.get('added_text_reviews',[]):
            i=row.get('edit_index')
            if type(i) is int and 0<=i<len(edits) and row.get('repetitions'):
                remove.add(i)
    for issue in expanded['issues']:
        quote=issue.get('candidate_quote')
        if not isinstance(quote,str) or not quote.strip() or quote not in context['candidate']:
            continue
        matches=[i for i,e in enumerate(edits) if quote in e['replacement'] and quote not in e['old']]
        if len(matches)==1:
            remove.add(matches[0])
    groups={edits[i]['group_id'] for i in remove if edits[i].get('group_id')}
    remove.update(i for i,e in enumerate(edits) if e.get('group_id') in groups)
    if context.get('whole_review_phase')!='selection' and not any(i not in remove and e['replacement']!=e['old'] for i,e in enumerate(edits)):
        return []
    return sorted(remove)


def scoped_publication(context, assessment, binding):
    if assessment['hard']:
        return None,assessment['hard']
    edits=context['edits']
    # Omitting a byte-identical replacement preserves the reviewed candidate,
    # including any grouped edits. It must not trigger partial publication.
    all_indices={i for i,edit in enumerate(edits) if edit['old']!=edit['replacement']}
    blocked=assessment['blocked'] & all_indices
    if assessment['facts']:
        selected=set()
    elif blocked:
        selected={i for i in all_indices-blocked
                  if edits[i].get('independent') is True and not edits[i].get('group_id')}
    else:
        selected=all_indices

    def checked(indices):
        selected_edits=[edit for i,edit in enumerate(edits) if i in indices]
        body=patches.apply_patches(context['source_body'],{'source_sha256':binding['body_sha256'],'edits':selected_edits},
                                  protected_phrases=context['book_contract']['protected_phrases'])
        length=quality.measurement(body.encode(),binding['chapter_number'],binding.get('target_policy',binding['bounds']))
        return {'candidate':body,'candidate_sha256':sha(body.encode()),'edits':selected_edits,'length':length}

    publication=checked(selected)
    if quality.is_blocking(publication['length']) and selected!=all_indices:
        selected=set()
        publication=checked(selected)
    if quality.is_blocking(publication['length']):
        return None,['最终正文仍须满足明确篇幅：'+json.dumps(publication['length'],ensure_ascii=False)]
    open_issues=[]
    blockers=[]
    for goal in context['goals']:
        key=goal['id']
        reason=assessment['open'].get(key)
        if not reason and assessment['touched'][key]-selected:
            reason='对应改动未验收采用，保留原问题供后续核对。'
        if not reason:continue
        if goal.get('level') in ('hard','mandatory'):
            blockers.append(key+' 原有必改问题仍未解决：'+reason)
        open_issues.append({**{name:goal[name] for name in ('id','source','goal','excerpts','preserve','level') if name in goal},
                            'reason':reason})
    if blockers:return None,blockers
    return {**publication,'open_issues':open_issues},[]


def stage_whole_text(root, folder, b, source, publication):
    path = folder + '/zhuque-round-input.json'
    data = {**b['zhuque_options'], 'body': publication['candidate'], 'source_sha256': publication['candidate_sha256'],
            'original_body': source['source_body'], 'book_contract': source['book_contract'],
            'length_bounds': b.get('target_policy', b['bounds']), 'chapter_number': b['chapter_number']}
    save(safe(root,path),data)
    return {'zhuque_round_input':path, 'continuity_stage_path':path}


def accept_whole_text(root, folder, b, publication, proof):
    path = folder + '/zhuque-round-result.json'
    raw = safe(root,path).read_bytes()
    if json.loads(proof or '{}') != {'sha256':sha(raw)}:
        raise ValueError('朱雀整篇结果和本次节点回执不一致。')
    result = json.loads(raw)
    body = result['candidate']
    after = sha(body.encode('utf-8'))
    report = result['report']
    ratio = report['labels_ratio']['2']
    if (result['source_sha256'] != publication['candidate_sha256'] or result['candidate_sha256'] != after
            or report.get('status') != 'success' or report.get('text_sha256') != zhuque.text_digest(body)
            or type(ratio) not in (int,float) or not 0 <= ratio <= .30):
        raise ValueError('朱雀报告未绑定本次完整正文，或疑似比例仍超过 30%。')
    length = quality.measurement(body.encode('utf-8'),b['chapter_number'],b.get('target_policy',b['bounds']))
    if quality.is_blocking(length):
        raise ValueError('整篇复测候选超出本书既定篇幅。')
    metadata = {'path':path,'sha256':sha(raw),'source_sha256':result['source_sha256'],
                'rounds':result['rounds'],'suspected':ratio}
    return {**publication,'candidate':body,'candidate_sha256':after,'length':length}, metadata


def continuity_publication(root, b, publication, receipt):
    if not receipt or not receipt.strip():
        return publication
    body = continuity.adopt_staged(root, receipt, b['task_id'], publication['candidate_sha256'])
    length = quality.measurement(body.encode('utf-8'), b['chapter_number'], b.get('target_policy', b['bounds']))
    if quality.is_blocking(length):
        raise ValueError('连贯性返修超出本书既定篇幅。')
    return {**publication, 'candidate': body, 'candidate_sha256': sha(body.encode('utf-8')), 'length': length}


def commit(root,folder,expected_review,*,stage_only=False,round_proof=None,continuity_receipt=None):
    execution_fence=guard.assert_current(root)
    b=read(safe(root,folder+'/source-binding.json'));saved=read(safe(root,b['outputs']['revision_review_input']))
    accepted_sha=saved['candidate_sha256']
    if saved.get('review_protocol')==SCOPED_REVIEW:
        for name in ('receipt.json','commit-intent.json'):
            path=safe(root,folder+'/'+name)
            if path.is_file():
                prior=read(path)
                if prior.get('task_id')==b['task_id'] and prior.get('before_sha256')==b['body_sha256']:
                    accepted_sha=prior['after_sha256']
                    break
    b,source=bound(root,folder,accepted_sha=accepted_sha)
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except CompositionConflict:raise
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',str(exc))
        raise Retry('agent_pl',str(exc)) from exc
    if 'blind_seed' in b and not context.get('blind_vote_digest'):
        candidate(root,folder)
        raise Retry('agent_blind_scene','当前两个版本尚待匿名对读，请提交本张票面。')
    if context!=saved:
        # The host retries the writer without resetting intermediate completed
        # nodes. Rebuild here and force a fresh reviewer before publication.
        if saved.get('review_input_sha256')!=digest({k:v for k,v in saved.items() if k!='review_input_sha256'}):
            raise ValueError('冻结复查输入已有变化，未发布')
        save(safe(root,b['outputs']['revision_review_input']),context)
        if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),context,'reviewer')
        if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),repair_record(root,b,context) or {})
        refresh_retry_budget(root,'agent_local_review')
        raise Retry('agent_local_review','候选补丁已有变化，已重建复查输入；请独立复查新候选，旧报告不能发布')
    if b['outputs'].get('revision_review_model'):
        verify_model(read(safe(root,b['outputs']['revision_review_model'])),context,'reviewer')
    report=read(safe(root,b['outputs']['revision_review_path']))
    actual_matches=False
    try:actual_matches=isinstance(expected_review,str) and json.loads(expected_review)==report
    except (ValueError,TypeError):pass
    try:
        if not actual_matches:raise ValueError('复查文件与本任务实际模型输出不一致')
        scoped=context.get('review_protocol')==SCOPED_REVIEW
        if scoped:
            remove=scene_trial_prunes(report,context)
            selection=context.get('whole_review_phase')=='selection'
            if selection:
                votes=expand_review(report,context)['change_reviews']
                if sorted(v['edit_index'] for v in votes)!=list(range(len(context['edits']))):
                    raise ValueError('初选须完整且不重复地审读所有补丁。')
                if not any((v['effect']=='improved' or (v['effect']=='equivalent' and v['edit_index'] in context.get('local_rephrased_indices', ()))) and v['edit_index'] not in remove
                           and v.get('preservation',{}).get('status')!='lost'
                           and context['edits'][v['edit_index']]['old']!=context['edits'][v['edit_index']]['replacement'] for v in votes):
                    message='初选没有可签发的有效改动。请根据实质问题重新逐场修订。'
                    guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',message)
                    raise Retry('agent_pl',message)
            if remove or selection:
                guard.store().event(root,'scene_trial_selection' if selection else 'scene_trial_prune',{'task_id':b['task_id'],'binding_digest':digest(b),
                    'merged_digest':digest(context['edits']),'indices':remove,'review_context':context,'review_report':report})
                fresh=compose(root,b,source)
                save(safe(root,b['outputs']['revision_review_input']),fresh)
                save_model(safe(root,b['outputs']['revision_review_model']),fresh,'reviewer')
                refresh_retry_budget(root,'agent_local_review')
                if selection:
                    raise Retry('agent_local_review','进入整稿签发。按照 review-model 的 signoff_instructions 阅读完整候选。change_reviews、added_text_reviews 填 []，逐项完成当前 goals 的签发和原目标结论。')
                raise Retry('agent_local_review','已撤回上一份报告中倒退、等价或引入所报矛盾的改动；请独立复查当前重组候选，按新索引填写。')
            assessment=scoped_assessment(report,context)
            publication,reasons=scoped_publication(context,assessment,b)
        else:
            active=repair_record(root,b,context)
            if b['outputs'].get('revision_review_repair') and read(safe(root,b['outputs']['revision_review_repair']))!=(active or {}):
                raise ValueError('局部补审资料与可信运行凭据不一致')
            if active:report_repair.verify(report,active,context)
            reasons=review_decision(report,context)
            publication=context
        expanded=expand_review(report,context)
    except Retry:
        raise
    except (ValueError,KeyError,TypeError) as exc:
        if actual_matches and context.get('review_protocol')!=SCOPED_REVIEW:
            targeted=report_repair.request(report,context,str(exc))
            if targeted:save_repair(root,b,context,targeted)
            elif '需要完整独立复审' in str(exc):save_repair(root,b,context,None)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_local_review',str(exc))
        raise Retry('agent_local_review',str(exc)) from exc
    if b['outputs'].get('revision_review_expanded'):save(safe(root,b['outputs']['revision_review_expanded']),expanded)
    if scoped and reasons:
        pending.retain(root,b,source,context,report,expanded,digest,patches,blocked_indices=assessment['blocked'])
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl','；'.join(reasons))
        raise Retry('agent_pl','；'.join(reasons))
    removable=[] if scoped else equivalent_indices(expanded,context,reasons)
    if removable:
        guard.store().event(root,'equivalent_prune',{'task_id':b['task_id'],'binding_digest':digest(b),
            'merged_digest':digest(context['edits']),'indices':removable,'review_context':context,'review_report':report})
        fresh=compose(root,b,source)
        save(safe(root,b['outputs']['revision_review_input']),fresh)
        if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),fresh,'reviewer')
        if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),{})
        refresh_retry_budget(root,'agent_local_review')
        raise Retry('agent_local_review','已撤回无依赖的等价改动，重新组装并检查篇幅；须独立复查新候选，原结论未改写')
    if reasons:
        new_findings = growth_findings(context,expanded)
        scene_findings = line_findings(context,evidence.resolve_report(expanded,context['candidate']))
        previous_goals = [row for row in context['goals'] if row.get('source') in ('added_text_review','local_scene_review')]
        new_findings += scene_findings
        goals = patches.merge_addition_issues(previous_goals,new_findings)
        if goals != previous_goals:
            guard.store().event(root,'local_added_text_goals',{'task_id':b['task_id'],'binding_digest':digest(b),
                'review_input_sha256':context['review_input_sha256'],'goals':goals})
        scene_paragraphs = {row['paragraph_id'] for row in scene_findings}
        blocked_indices = {row['edit_index'] for row in new_findings if 'edit_index' in row}
        blocked_indices.update(i for i,edit in enumerate(context['edits']) if edit['paragraph_id'] in scene_paragraphs)
        blocked_indices.update(row['edit_index'] for row in expanded['change_reviews']
                               if row.get('preservation',{}).get('status')=='lost')
        pending.retain(root,b,source,context,report,expanded,digest,patches,blocked_indices=blocked_indices)
        path=safe(root,folder+'/content-rejections.json');history=read(path) if path.is_file() else []
        payload=read(safe(root,b['outputs']['revision_patch_path']))
        key=sha((context['candidate_sha256']+digest(report)+str(safe(root,b['outputs']['revision_review_path']).stat().st_mtime_ns)).encode())
        if key not in history:history.append(key)
        save(path,history)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl','；'.join(reasons))
        raise Retry('agent_pl','；'.join(reasons))
    if quality.is_blocking(publication['length']):
        pending.retain(root,b,source,context,report,expanded,digest,patches)
        message='本轮表达已通过复核，最终正文仍须满足明确篇幅。保留已有表达，只补可见的反应或后果。'+json.dumps(context['length'],ensure_ascii=False)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',message)
        raise Retry('agent_pl',message)
    if source.get('zhuque_review',{}).get('required'):
        try:
            zhuque.check_coverage(source['zhuque_review'], publication['edits'])
        except ValueError as exc:
            raise Retry('agent_pl',str(exc)) from exc
    try:
        check_local_tone(source, publication['edits'], context['edits'])
    except ValueError as exc:
        raise Retry('agent_pl', str(exc)) from exc
    round_metadata = None
    if stage_only:
        return stage_whole_text(root,folder,b,source,publication)
    if continuity_receipt is not None and not continuity_receipt.strip():
        raise ValueError('正式润色发布前须取得全文连贯性验收凭据。')
    publication = continuity_publication(root, b, publication, continuity_receipt)
    if b.get('zhuque_options',{}).get('enabled'):
        publication, round_metadata = accept_whole_text(root,folder,b,publication,round_proof)
    receipt={'schema':1,'task_id':b['task_id'],'before_sha256':b['body_sha256'],'after_sha256':publication['candidate_sha256'],
             'book_contract_sha256':b['book_contract_sha256'],'review_digest':digest(report),'patch_digest':context['patch_digest'],
             'changed_spans':len(publication['edits']),'length':publication['length'],'accepted':True,
             'expanded_review_digest':digest(expanded)}
    if round_metadata:
        receipt['zhuque_whole_text'] = round_metadata
    if scoped:receipt.update(review_protocol=SCOPED_REVIEW,open_issues=publication['open_issues'],published_edits_digest=digest(publication['edits']))
    if 'blind_seed' in b:receipt['blind_vote_digest']=context['blind_vote_digest']
    if 'tone_review' in source:
        before_tone = read(safe(root,folder+'/tone-before.json'))
        if digest(before_tone) != source['tone_review']['snapshot_digest'] or before_tone['sha256'] != b['body_sha256']:
            raise ValueError('文体检测原稿与本次冻结凭据不一致')
        after_tone = tone.scan(publication['candidate'])
        if after_tone['sha256'] != receipt['after_sha256'] or after_tone['revision'] != before_tone['revision']:
            raise ValueError('文体复测版本与采用稿或原检测器不一致')
        tone_report = tone.comparison(before_tone, after_tone, report.get('issue_outcomes', []))
        receipt['tone_report'] = folder + '/tone-report.md'
    if 'zhuque_review' in source:
        before = source['zhuque_review']
        report_path = safe(root, folder+'/zhuque-report.json')
        comparison = read(report_path) if report_path.is_file() else {}
        if comparison.get('after_sha256') != receipt['after_sha256'] or comparison.get('before_sha256') != b['body_sha256']:
            after = before if receipt['after_sha256'] == b['body_sha256'] else zhuque.analyze(
                publication['candidate'], patches.paragraphs, os.environ.get('XS2_ZHUQUE_KEY_FILE', ''))
            comparison = {'before_sha256': b['body_sha256'], 'after_sha256': receipt['after_sha256'],
                          'before': before, 'after': after}
        receipt['zhuque_report'] = folder+'/zhuque-report.json'
    # Prepare bytes outside the database lock, then keep epoch verification,
    # final source validation, canonical replacement and receipt in one lock.
    p=safe(root,b['body_path'])
    import tempfile
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
            temporary=Path(f.name);f.write(publication['candidate'].encode());f.flush();os.fsync(f.fileno())
        with guard.publication(root,proof=execution_fence) as proof:
            bound(root,folder,accepted_sha=publication['candidate_sha256'])
            editor_bound(root,b)
            if proof:receipt['execution_fence']=proof
            save(safe(root,folder+'/commit-intent.json'),receipt)
            if sha(p.read_bytes())!=publication['candidate_sha256']:os.replace(temporary,p)
            if 'tone_report' in receipt:
                save(safe(root,folder+'/tone-after.json'), after_tone)
                quality.atomic_text(safe(root,receipt['tone_report']), tone_report)
            if 'zhuque_report' in receipt:
                save(report_path, comparison)
            save(safe(root,folder+'/receipt.json'),receipt)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
    return receipt


def verify_attempt(root,task):
    values=task.get('parameter_values') or {};folder=values.get('revision_dir','')
    if not folder:raise ValueError('局部修订完成记录缺少本任务凭据')
    receipt=read(safe(root,folder+'/receipt.json'));b=read(safe(root,folder+'/source-binding.json'))
    if receipt.get('task_id')!=task.get('task_id') or b['task_id']!=task.get('task_id'):
        raise ValueError('局部修订完成记录不属于本任务')
    if sha(safe(root,b['body_path']).read_bytes())!=receipt.get('after_sha256'):
        raise ValueError('局部修订发布后正文已有变化，不能沿用旧完成记录')
    b,source=bound(root,folder,accepted_sha=receipt['after_sha256']);context=compose(root,b,source)
    if 'blind_seed' in b:
        raw=compose(root,b,source,before_blind=True)
        public,_=blind.packet(source['source_body'],raw['edits'],editor_bound(root,b).get('scene_trial_windows',[]),b['blind_seed'],patches, required=source.get('zhuque_review',{}).get('required',False))
        vote=read(safe(root,b['outputs']['revision_blind_path']))
        if (read(safe(root,b['outputs']['revision_blind_packet']))!=public
                or json.loads(values.get('revision_blind_result') or 'null')!=vote
                or digest(vote)!=receipt.get('blind_vote_digest') or digest(vote)!=context.get('blind_vote_digest')):
            raise ValueError('匿名对读凭据与本次票面和实际选择不符。')
    if b['outputs'].get('revision_review_model'):
        verify_model(read(safe(root,b['outputs']['revision_review_model'])),context,'reviewer')
    report=read(safe(root,b['outputs']['revision_review_path']))
    if receipt.get('expanded_review_digest'):
        expanded=expand_review(report,context)
        if (digest(expanded)!=receipt['expanded_review_digest'] or
                read(safe(root,b['outputs']['revision_review_expanded']))!=expanded):raise ValueError('展开审查凭据与实际回复不符')
    if context.get('review_protocol')==SCOPED_REVIEW:
        publication,reasons=scoped_publication(context,scoped_assessment(report,context),b)
        if publication is not None:
            publication = continuity_publication(root, b, publication, values.get('continuity_receipt', ''))
        if b.get('zhuque_options',{}).get('enabled'):
            publication, metadata = accept_whole_text(root,folder,b,publication,values.get('zhuque_round_checksum'))
            if receipt.get('zhuque_whole_text') != metadata:
                raise ValueError('朱雀全文验收记录与本次任务不一致。')
        if (reasons or receipt.get('review_protocol')!=SCOPED_REVIEW
                or receipt.get('open_issues')!=publication['open_issues']
                or receipt.get('published_edits_digest')!=digest(publication['edits'])
                or receipt.get('after_sha256')!=publication['candidate_sha256']
                or receipt.get('length')!=publication['length'] or receipt.get('changed_spans')!=len(publication['edits'])):
            raise ValueError('局部复查结果与实际发布的改动或保留问题不符')
    else:reasons=review_decision(report,context)
    if (context!=read(safe(root,b['outputs']['revision_review_input'])) or digest(report)!=receipt['review_digest']
            or context['patch_digest']!=receipt['patch_digest'] or not isinstance(values.get('revision_review_result'),str)
            or json.loads(values['revision_review_result'])!=report or reasons):
        raise ValueError('局部修订完成凭据或复查与当前候选不符')
    return receipt


def writer_retry_had_review(task):
    writer=(task.get('node_states') or {}).get('agent_pl') or {}
    attempt=writer.get('attempt_count',0)
    interrupted=(writer.get('status') in {'failed','stopped','retry_waiting'}
                 or (task.get('status')=='stopped' and writer.get('status')=='running'))
    return (interrupted and type(attempt) is int
            and any(row.get('status')=='failed' and type(row.get('attempt_number')) is int
                    and row['attempt_number']<attempt
                    and '来自节点 script_local_commit' in str(row.get('error') or '')
                    for row in writer.get('attempt_history',[])))


def recover_rejected_review(root, task, *, interrupted_writer=False):
    """Carry genuine feedback into one fresh polish run without adopting the edits."""
    values=task.get('parameter_values') or {};nodes=task.get('node_states') or {}
    identity=task['task_id'];folder=f'cache/local-revision/{identity}'
    writer_verified=(writer_retry_had_review(task) if interrupted_writer
                     else nodes.get('agent_pl',{}).get('status')=='completed')
    allowed_status={'failed','stopped'} if interrupted_writer else {'failed'}
    if (task.get('status') not in allowed_status or not task.get('workspace_override')
            or Path(task['workspace_override']).resolve()!=Path(root).resolve()
            or values.get('revision_dir')!=folder or not writer_verified
            or nodes.get('agent_local_review',{}).get('status')!='completed' or safe(root,folder+'/receipt.json').exists()):
        raise ValueError('润色恢复缺少同一作品的独立复核记录')
    b,source=bound(root,folder);editor_bound(root,b)
    out=b['outputs']
    context=read(safe(root,out['revision_review_input']));report=read(safe(root,out['revision_review_path']))
    if interrupted_writer:
        historical=pending.recorded(root,b,digest)
        if not historical or historical['review_input']!=context or historical['raw_review']!=report:
            raise ValueError('润色恢复缺少已签名的待验收工作稿及复核')
    else:
        payload=read(safe(root,out['revision_patch_path']))
        if context['patch_digest']!=digest(payload) or json.loads(values.get('revision_patch_result','null'))!=payload:
            raise ValueError('润色补丁和原任务不一致')
    body=patches.apply_patches(source['source_body'],{'source_sha256':b['body_sha256'],'edits':context['edits']},
                               protected_phrases=source['book_contract']['protected_phrases'])
    if (b['task_id']!=identity or context.get('task_id')!=identity or context['source_body']!=source['source_body']
            or context['source_sha256']!=b['body_sha256'] or context['book_contract_sha256']!=b['book_contract_sha256']
            or context['candidate']!=body or context['candidate_sha256']!=sha(body.encode())
            or context['review_input_sha256']!=digest({k:v for k,v in context.items() if k!='review_input_sha256'})
            or json.loads(values.get('revision_review_result','null'))!=report):
        raise ValueError('润色补丁、候选或独立复核和原任务不一致')
    if out.get('revision_review_model'):
        verify_model(read(safe(root,out['revision_review_model'])),context,'reviewer')
    if context.get('review_protocol')==SCOPED_REVIEW:
        _,reasons=scoped_publication(context,scoped_assessment(report,context),b)
    else:reasons=review_decision(report,context)
    if not reasons:
        raise ValueError('没有需要继续处理的独立润色意见')
    retained=retained_feedback_sources(root,b['state']['author_feedback_file'])
    text=('# 上一次润色的独立复核意见\n\n'+'\n'.join('- '+item for item in dict.fromkeys(reasons))+
          '\n\n以当前已发布正文为底稿，集中解决有原文依据的问题。保留作者的篇幅、人物声线、叙述权限和情节范围，'
          '提交必要的局部补丁并重新接受独立复核。\n')
    relative=f"quality/repairs/{b['chapter_number']}/polish-{identity}/instructions.md"
    origin=relative.rsplit('/',1)[0]+'/automatic-origin.json'
    record={'origin':'automatic','feedback_sha256':sha(text.encode()),'retained_feedback_sources':retained,
            'source_task_id':identity,'source_body_sha256':b['body_sha256'],'review_digest':digest(report)}
    if safe(root,relative).is_file() or safe(root,origin).is_file():
        if safe(root,relative).read_text(encoding='utf-8')!=text or read(safe(root,origin))!=record:
            raise ValueError('润色续跑意见已有变化')
    else:
        def save_feedback(write):
            write(root,relative,text)
            write(root,origin,record)
        guards={path:value or '' for path,value in b['files'].items()}
        guards.update({row['source_id']:row['sha256'] for row in retained})
        guard.store().publish_views(root,save_feedback,lambda:guards)
    return relative


def verify_conflict(root,task,*,recover_evidence=False):
    values=task.get('parameter_values',{});folder=values.get('revision_dir','')
    if (not folder or task.get('status')!='failed' or task.get('node_states',{}).get('agent_pl',{}).get('status')!='completed'
            or not any(task.get('node_states',{}).get(k,{}).get('status')=='failed' for k in ('script_local_candidate','script_local_commit'))):
        raise ValueError('缺少原生重规划失败节点凭据')
    b,source=bound(root,folder);editor_bound(root,b)
    payload=read(safe(root,b['outputs']['revision_patch_path']))
    if b['task_id']!=task.get('task_id') or json.loads(values.get('revision_patch_result','null'))!=payload:
        raise ValueError('冲突补丁与本任务真实模型输出不一致')
    path=safe(root,folder+'/composition-conflict.json')
    if recover_evidence and not path.is_file():
        failed=(task.get('node_states') or {}).get('script_local_candidate') or {}
        if (failed.get('status')!='failed' or 'RETRY_STOP: evidence：重规划冲突缺少冻结原文和逐字证据' not in str(failed.get('error') or '')
                or set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['status']!='needs_replan' or payload['edits']!=[]):
            raise ValueError('未找到可恢复的原生重规划意见')
        save(path,conflict_packet(b,source,payload,payload['reason'],payload['evidence']))
    packet=read(path)
    measured=None;extras={}
    if 'review_digest' in packet:
        context=compose(root,b,source);report=read(safe(root,b['outputs']['revision_review_path']))
        if (task.get('node_states',{}).get('agent_local_review',{}).get('status')!='completed'
                or json.loads(values.get('revision_review_result','null'))!=report
                or len(read(safe(root,folder+'/content-rejections.json')))<2 or not review_decision(report,context)):
            raise ValueError('缺少连续实质返修的真实独立复查')
        measured=context['length'];reason='连续有原文依据的实质修订仍未解决问题，须回到阅读作用与篇幅规划。';quotes=[source['paragraphs'][0]['text']]
        extras={'review_digest':digest(report),'review_report':expand_review(report,context),'rejected_candidate':context['candidate']}
    elif payload.get('status')=='needs_replan':
        if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:raise ValueError('冲突响应不合规')
        reason,quotes=payload.get('reason'),payload.get('evidence')
    else:
        working=pending.current(root,b,digest)
        edits=pending.merge(source['source_body'],(working or {}).get('edits',[]),payload['edits'],patches)
        body=patches.apply_patches(source['source_body'],{'source_sha256':payload['source_sha256'],'edits':edits},protected_phrases=source['book_contract']['protected_phrases'])
        measured=quality.measurement(body.encode(),b['chapter_number'],b['bounds'])
        if measured['status'] not in ('short','long') or len(read(safe(root,folder+'/length-candidates.json')))<2:
            raise ValueError('没有连续篇幅冲突的实测来源')
        reason='内容修订连续出现篇幅冲突，应重新规划，不能用重复解释或动作填充。';quotes=[source['paragraphs'][0]['text']]
    if packet!={**conflict_packet(b,source,payload,reason,quotes,measured),**extras}:raise ValueError('冲突凭据已变化')
    return packet


def retry_feedback(root,folder,error):
    text=str(error)+'\n保持冻结原文和本书文风，仅纠正本轮问题。\n'
    if error.target=='agent_sc' and 'dialogue_review_format' in str(error):
        path = safe(root, folder+'/critic-exchange-repair.json')
        if path.is_file():
            repair = read(path)
            return text+'只补审下列对白组，在 exchange_review 中提交这些组的判断；其他组和其他字段由程序从旧报告保留。\n'+json.dumps({
                'recheck': repair['recheck'], 'previous_unverified_rows': repair['misfiled'],
            }, ensure_ascii=False, indent=2)+'\n'
    if error.target!='agent_pl':return text
    binding,source=bound(root,folder)
    target_policy=binding.get('target_policy',binding['bounds'])
    if source.get('added_text_review'):
        tracked = tracked_addition_goals(guard.store().events(root),binding)
        if tracked:
            current = safe(root,binding['outputs']['revision_review_input'])
            targets = {row['paragraph_id'] for row in tracked}
            edits = [edit for edit in read(current)['edits'] if edit['paragraph_id'] in targets] if current.is_file() else []
            text += ('\n【表达句子返修】按原编号处理针对的句子及其上下文。保留明确要求留住的接话、指令和有效增写；'
                     '这里列出的旧候选仅供定位，old 仍逐字取冻结原文。\n'
                     +json.dumps({'goals':tracked,'affected_edits':edits},ensure_ascii=False,indent=2)+'\n')
    working=pending.current(root,binding,digest)
    if working:
        body=patches.apply_patches(source['source_body'],{'source_sha256':binding['body_sha256'],'edits':working['edits']})
        if sha(body.encode())!=working['candidate_sha256']:raise ValueError('待验收工作稿与保留补丁不一致')
        return text+'\n【待验收工作稿；有效改动由程序保留，未发布】\n'+json.dumps({
            'source_sha256':binding['body_sha256'],'retained_edits':working['edits'],
            'working_candidate_sha256':working['candidate_sha256'],
            'length_edit_budget':patches.length_edit_budget(quality.count_prose(body),quality.required_bounds(target_policy))},ensure_ascii=False,indent=2)+(
            '\n完整冻结原文见主输入；待验收工作稿等于该原文应用上述保留补丁。只提交剩余问题的新增或更新edits，仍以冻结原文的段落id、old、source_sha256为锚点。未重交的保留改动继续存在；'
            '更新保留改动须使用其完整old范围，不能部分重叠。不得把工作稿新句当old。原始事实与全部目标不变，最终仍完整复核所有累计改动。\n')
    text+=('本轮整组edits仍应用于冻结原文，不累计上一版候选的改动；整组净增删按以下源预算计算，'
           '不能只补候选剩余缺口。不把候选新增句当作old；若问题来自replacement，只修该replacement并完整重交补丁。\n'+
           json.dumps(patches.length_edit_budget(quality.count_prose(source['source_body']),quality.required_bounds(target_policy)),ensure_ascii=False,indent=2)+'\n')
    patch_path=safe(root,binding['outputs']['revision_patch_path'])
    if patch_path.is_file():
        try:
            payload=read(patch_path)
            candidate=patches.apply_patches(source['source_body'],payload,protected_phrases=source['book_contract']['protected_phrases'])
        except (ValueError,KeyError,TypeError):pass
        else:
            diagnostic={'task_id':binding['task_id'],'source_sha256':binding['body_sha256'],
                'rejected_edits':payload['edits'],'candidate_length':quality.measurement(candidate.encode(),binding['chapter_number'],target_policy)}
            save(safe(root,folder+'/last-rejected-patch.json'),diagnostic)
            return text+'\n【最新未通过补丁；未发布，仅用于修订其replacement】\n'+json.dumps(diagnostic,ensure_ascii=False,indent=2)
    path=safe(root,folder+'/review-input.json')
    if not path.is_file():return text
    context=read(path);binding=read(safe(root,folder+'/source-binding.json'))
    if context.get('task_id')!=binding['task_id'] or context.get('source_sha256')!=binding['body_sha256']:return text
    # A fresh writer session has no previous assistant turn. Hand back the
    # actual rejected edits, while keeping its source/input immutable.
    diagnostic={'source_sha256':binding['body_sha256'],'rejected_edits':context['edits']}
    return text+('\n【上一轮未通过补丁；仅供诊断，未发布、未采用为事实或写法】\n'+
        json.dumps(diagnostic,ensure_ascii=False,indent=2)+
        '\n继续对冻结原文提交新补丁，不能把这份候选当作新底稿；核对上一轮具体替换，避免再次写回同义说明。\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','writer-input','candidate','accept-blind','specific-review','stage-whole-text','skip-whole-text','commit'])
    parser.add_argument('--chapter',default='0001');parser.add_argument('--target',default='');parser.add_argument('--dir',default='')
    parser.add_argument('--context',default='cache/story-support/context.md')
    parser.add_argument('--learning-context',default='learning/context/polish.md')
    parser.add_argument('--feedback',default=None)
    parser.add_argument('--dialogue-check',action='store_true')
    parser.add_argument('--dialogue-check-version',type=int,choices=range(1,packet.COMPACT_EXCHANGE_REVIEW_VERSION+1),default=1)
    parser.add_argument('--scoped-review',action='store_true')
    parser.add_argument('--blind-scenes',action='store_true')
    parser.add_argument('--whole-text-detection',action='store_true')
    parser.add_argument('--round-proof',default='')
    parser.add_argument('--continuity-receipt')
    parser.add_argument('--advisory-length',action='store_true')
    parser.add_argument('--review-scope',choices=('current_issues','whole_chapter'),default='current_issues')
    parser.add_argument('--critique',default='cache/sc/critique.json');parser.add_argument('--review-stdin',action='store_true')
    args=parser.parse_args();root=Path.cwd()
    try:
        if args.action=='prepare':out=prepare(root,args.chapter,os.environ.get('TASK_ID',''),args.target,args.context,args.learning_context,args.feedback,
                                             dialogue_check=args.dialogue_check,dialogue_check_version=args.dialogue_check_version,
                                             scoped_review=args.scoped_review,whole_chapter_review=args.review_scope=='whole_chapter',
                                             advisory=args.advisory_length,blind_scenes=args.blind_scenes,whole_text_detection=args.whole_text_detection)
        elif args.action=='writer-input':out=writer_input(root,args.dir,args.critique)
        elif args.action=='candidate':out=candidate(root,args.dir)
        elif args.action=='accept-blind':accept_blind(root,args.dir,sys.stdin.read());out={}
        elif args.action=='specific-review':
            binding,_=bound(root,args.dir)
            if 'blind_seed' in binding:raise ValueError('本轮普通润色需要完成匿名对读。')
            out={}
        elif args.action=='skip-whole-text':
            binding,_=bound(root,args.dir)
            if binding.get('zhuque_options',{}).get('enabled'):
                raise ValueError('本书已启用朱雀全文检测，须完成检测后签发。')
            out={}
        elif args.action=='stage-whole-text':out=commit(root,args.dir,sys.stdin.read(),stage_only=True)
        else:commit(root,args.dir,sys.stdin.read() if args.review_stdin else None,round_proof=args.round_proof,continuity_receipt=args.continuity_receipt);out={}
    except Retry as exc:
        out=locations(args.dir);quality.atomic_text(safe(root,out['revision_feedback_file']),retry_feedback(root,args.dir,exc))
        print('<WF_REJECT_UPSTREAM target="'+exc.target+'">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>');return
    for key,value in out.items():print('<WF_VAR>'+key+':'+value+'</WF_VAR>')
    print(json.dumps({'status':'completed','action':args.action},ensure_ascii=False))


if __name__=='__main__':main()
