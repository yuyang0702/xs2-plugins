"""Lossless model views; canonical audit inputs and validators remain unchanged."""
import copy
import hashlib
import json
import re
import importlib.util
from bisect import bisect_left, bisect_right
from collections import Counter
from functools import lru_cache
from pathlib import Path

PROTOCOL='lossless-context-v1'
FOCUSED_WRITER_VERSION=2
SHARED_REVIEW_VERSION=1
COMPACT_REVIEW_VERSION=2
COMPACT_CRITIC_VERSION=1
SHARED_PROSE='candidate-shared-v1'
COMPACT_PARAGRAPHS='paragraph-map-v1'
GUIDANCE=('正文按paragraphs顺序完整提供，before与suffix保留原始空白；不是摘要或节选。'
    '段落id可作证据ref_id；精确局部证据也可逐字引用。源稿与候选分开，不混用依据。')


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def precision():
    spec=importlib.util.spec_from_file_location('packet_precision_policy',Path(__file__).with_name('precision_policy.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


@lru_cache(maxsize=1)
def book_guidance():
    spec=importlib.util.spec_from_file_location('packet_book_guidance',Path(__file__).with_name('book_contract.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.prompt({}).split('\n',2)[-1]


def prose(body):
    if not isinstance(body,str):raise ValueError('Model prose view requires text')
    rows=[];end=0
    for match in re.finditer(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)',body,re.S):
        rows.append({'id':f'p{len(rows)+1:04d}','before':body[end:match.start()],'text':match[0]});end=match.end()
    return {'format':PROTOCOL,'paragraphs':rows,'suffix':body[end:]}


def compact_paragraphs(view):
    rows=view['paragraphs']
    default=Counter(row['before'] for row in rows).most_common(1)[0][0] if rows else ''
    return {'format':COMPACT_PARAGRAPHS,'default_before':default,
            'before_overrides':{row['id']:row['before'] for row in rows if row['before']!=default},
            'paragraphs':{row['id']:row['text'] for row in rows},'suffix':view['suffix']}


def unpack_paragraphs(view):
    if view.get('format')!=COMPACT_PARAGRAPHS:return view
    paragraphs=view['paragraphs'];overrides=view['before_overrides'];default=view['default_before']
    if not isinstance(default,str) or not set(overrides)<=paragraphs.keys():
        raise ValueError('Invalid compact paragraph whitespace')
    rows=[]
    for index in range(1,len(paragraphs)+1):
        reference=f'p{index:04d}'
        if reference not in paragraphs:raise ValueError('Invalid compact paragraph ID')
        rows.append({'id':reference,'before':overrides.get(reference,default),'text':paragraphs[reference]})
    return {'format':PROTOCOL,'paragraphs':rows,'suffix':view['suffix']}


def restore(view,candidate=None):
    view=unpack_paragraphs(view)
    if view.get('format')==SHARED_PROSE:
        if candidate is not None:candidate=unpack_paragraphs(candidate)
        if candidate is None or candidate.get('format')!=PROTOCOL:
            raise ValueError('Shared prose requires the full candidate view')
        base=candidate['paragraphs']
        positions={row['id']:i for i,row in enumerate(base)}
        rows=[]
        for row in view['paragraphs']:
            if 'same_as_candidate' in row:
                first,last=(positions[key] for key in row['same_as_candidate'])
                start=len(rows)+1
                rows.extend({**entry,'id':f'p{i:04d}'} for i,entry in enumerate(base[first:last+1],start))
            else:
                rows.append(row)
        view={'format':PROTOCOL,'paragraphs':rows,'suffix':view['suffix']}
    if view.get('format')!=PROTOCOL or not isinstance(view.get('suffix'),str):raise ValueError('Invalid prose view')
    result=''
    for i,row in enumerate(view['paragraphs']):
        if row.get('id')!=f'p{i+1:04d}' or any(not isinstance(row.get(k),str) for k in ('before','text')):
            raise ValueError('Invalid paragraph in prose view')
        result+=row['before']+row['text']
    return result+view['suffix']


def shared_prose(source,candidate):
    def text_and_space(row):
        return row['before'],row['text']

    base=candidate['paragraphs']
    keys=[text_and_space(row) for row in base]
    first_match={}
    for index,key in enumerate(keys):
        first_match.setdefault(key,index)
    rows=[]
    previous=None
    for row in source['paragraphs']:
        key=text_and_space(row)
        next_index=previous+1 if previous is not None else len(base)
        if next_index<len(base) and keys[next_index]==key:
            rows[-1]['same_as_candidate'][1]=base[next_index]['id']
            previous=next_index
        else:
            previous=first_match.get(key)
            if previous is None:
                rows.append(row)
            else:
                reference=base[previous]['id']
                rows.append({'same_as_candidate':[reference,reference]})
    if not any('same_as_candidate' in row for row in rows):
        return source
    return {'format':SHARED_PROSE,'paragraphs':rows,'suffix':source['suffix']}


def review_context_refs(data):
    parts=[data['confirmed_context']]
    sources=[(['source_body'],data['source_body'])]
    for name in ('world_sources','style_sources'):
        for index,source in enumerate(data.get('book_contract',{}).get(name,[])):
            sources.append((['book_contract',name,index,'text'],source['text']))
    for path,raw in sources:
        normalized=raw.replace('\r\n','\n')
        variants=[(raw,{'ref':path})]
        if normalized!=raw:
            variants.append((normalized,{'ref':path,'line_endings':'lf'}))
        for text,reference in variants:
            if len(text)<=len(json.dumps(reference,ensure_ascii=False,separators=(',',':'))):
                continue
            replaced=[]
            for part in parts:
                if isinstance(part,str):
                    first,*rest=part.split(text)
                    replaced.append(first)
                    for following in rest:
                        replaced.extend((reference,following))
                else:
                    replaced.append(part)
            parts=replaced
    return parts[0] if len(parts)==1 else {'parts':parts}


def restore_review_context(view):
    context=view['confirmed_context']
    if isinstance(context,str):
        return context
    parts=[]
    for part in context['parts']:
        if isinstance(part,str):
            parts.append(part)
            continue
        value=view
        for key in part['ref']:
            value=value[key]
        if part['ref']==['source_body']:
            value=restore(value,view.get('candidate'))
        parts.append(value.replace('\r\n','\n') if part.get('line_endings')=='lf' else value)
    return ''.join(parts)


def focused_goals(goals,body,view):
    normalized=body.replace('\r\n','\n')
    starts,ends,ids=[],[],[]
    end=0
    for row in view['paragraphs']:
        start=end+len(row['before'].replace('\r\n','\n'))
        end=start+len(row['text'].replace('\r\n','\n'))
        starts.append(start);ends.append(end);ids.append(row['id'])
    result=[]
    for goal in goals:
        references=set()
        for quote in goal.get('excerpts') or []:
            if not isinstance(quote,str) or not quote.strip():continue
            for match in re.finditer(re.escape(quote.replace('\r\n','\n')),normalized):
                first=bisect_right(ends,match.start());last=bisect_left(starts,match.end())
                references.update(range(first,last))
        anchors=goal.get('paragraph_ids') or ([goal['paragraph_id']] if 'paragraph_id' in goal else [ids[i] for i in sorted(references)])
        row={'id':goal['id'],'goal':goal['goal'],'paragraph_ids':anchors}
        if 'turns' in goal:row['turns']=copy.deepcopy(goal['turns'])
        if 'target' in goal:row.update(focus=goal['focus'],target=copy.deepcopy(goal['target']))
        result.append(row)
    return result


def local(data,role):
    focused=data.get('writer_view_version')==FOCUSED_WRITER_VERSION
    if role=='writer' and focused:
        fields=('source_body','source_sha256','book_contract','book_contract_sha256',
                'author_feedback','automatic_revision_advice','writer_references','length_edit_budget','fixed_edit')
        result={key:copy.deepcopy(data[key]) for key in fields if key in data}
        goal_plans=((data.get('composition_plan') or {}).get('plan') or {}).get('goal_plans')
        if goal_plans:
            result['composition_plan']={'plan':{'goal_plans':copy.deepcopy(goal_plans)}}
    else:
        result=copy.deepcopy(data)
    result.pop('writer_view_version',None)
    result.pop('reviewer_view_version',None)
    result.pop('critic_view_version',None)
    for key in ('source_body','candidate','candidate_body'):
        if isinstance(result.get(key),str):result[key]=prose(result[key])
    review_version=data.get('reviewer_view_version') if role=='reviewer' else None
    compact_review=review_version in (SHARED_REVIEW_VERSION,COMPACT_REVIEW_VERSION)
    compact_critic=role=='critic' and data.get('critic_view_version')==COMPACT_CRITIC_VERSION
    if compact_review:
        result['source_body']=shared_prose(result['source_body'],result['candidate'])
        if review_version==COMPACT_REVIEW_VERSION:
            result['candidate']=compact_paragraphs(result['candidate'])
    if compact_review or compact_critic:
        result['confirmed_context']=review_context_refs(data)
    result.pop('paragraphs',None);result.pop('evidence_catalog',None)
    if 'book_contract' in result:
        result['_book_guidance']=book_guidance()
        if result['book_contract'].get('reading_contract'):
            spec=importlib.util.spec_from_file_location('packet_reading',Path(__file__).with_name('reading_contract.py'))
            reading=importlib.util.module_from_spec(spec);spec.loader.exec_module(reading)
            result['_book_guidance']+='\n'+reading.GUIDANCE
    result['_model_view']={'protocol':PROTOCOL,'role':role,'canonical_sha256':digest(data),'guidance':GUIDANCE}
    if focused and role=='writer':
        result['goals']=focused_goals(data['goals'],data['source_body'],result['source_body'])
        result['_model_view']['guidance']+=' 本轮问题见goals。paragraph_ids指向上方原文，空数组表示没有可逐字绑定的引文，请按问题和作者要求在全文中核对。'
        if 'fixed_edit' in result:
            result['_model_view']['guidance']+=' 作者指定单句删除，提交fixed_edit.patch；程序已核算该候选的篇幅，实际候选仍须独立复查。'
    elif focused and role=='reviewer':
        result['_model_view']['guidance']+=' reader_report和critique分别是修改前的完整读者报告和本轮自审。用它们复核本轮目标和原有判断，当前结论须依据实际候选。'
    if compact_review:
        result['_model_view']['guidance']+=' candidate是完整候选，候选证据只用candidate.paragraphs的编号或原句。source_body按序提供原稿。same_as_candidate的两个编号之间（含首尾）的候选段落在原稿中逐字相同，保留before；单独列出的原稿段落使用自己的文字。confirmed_context若含parts，按顺序阅读；ref是本输入中的字段路径，line_endings为lf时只转换原有换行。'
    if review_version==COMPACT_REVIEW_VERSION:
        result['_model_view']['guidance']+=' 候选paragraphs是段号到原文的映射；按段号顺序阅读。段前空白取before_overrides对应值，否则取default_before；篇末空白为suffix。'
    if compact_critic:
        result['_model_view']['guidance']+=' confirmed_context若含parts，按顺序阅读；ref是本输入中的字段路径，line_endings为lf时只转换原有换行。'
    result['_precision_guidance']=precision().GUIDANCE
    if data.get('precision_review_version')==2:
        result['_precision_guidance']=precision().DEFAULT_PROSE+'\n'+result['_precision_guidance']
    if role=='critic' and data.get('precision_review_version')==2:
        result['_precision_guidance']+=' precision_candidates 同时覆盖对白和旁白。每段逐项填 precision_checks。检查相邻轮次是否重报相同信息，确认必要值时具体说清放在这一段有什么作用。无作者指定范围时必须逐项判断，不能填 outside_scope。'
        result['_precision_guidance']+='\n'+precision().COUNTERFACTUAL
    result['_precision_advisory']=precision().analyze(data.get('candidate',data.get('candidate_body',data.get('source_body',''))),data.get('book_contract'))
    return result


def blind(data):
    result=copy.deepcopy(data);result['manuscript']=prose(result['manuscript']);result.pop('evidence_catalog',None)
    result['_model_view']={'protocol':PROTOCOL,'role':'blind-reader','canonical_sha256':digest(data),'guidance':GUIDANCE}
    result['_precision_guidance']=precision().GUIDANCE
    return result


def verify(actual,data,role):
    expected=blind(data) if role=='blind-reader' else local(data,role)
    if actual!=expected:raise ValueError('模型所见输入与冻结的完整资料不一致，核验未复用或发布')


def _composition_refs(data):
    return {key: '@' + prefix + data[key][:16] for key, prefix in (('request_digest', 'R'), ('plan_digest', 'P'))
            if isinstance(data.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', data[key])}


def bind_composition_response(response, canonical):
    result = dict(response)
    for key, reference in _composition_refs(canonical).items():
        if result.get(key) not in (reference, canonical[key]):
            raise ValueError(f'篇幅审核返回的 {key} 与当前输入编号不一致')
        result[key] = canonical[key]
    return result


def composition(data):
    """Full current prose/rules; stale versioned artifacts cannot guide planning.

    Keep all semantic review judgments. Only machine binding manifests remain
    local. A version mismatch is quarantined explicitly, never summarized into
    an apparently current quality judgment.
    """
    result=copy.deepcopy(data)
    if isinstance(data.get('request'),dict):
        result['request']=composition(data['request'])
    else:
        body=data.get('body','');result['body']=body
        current=(data.get('source_hashes') or {}).get(f"story/{data.get('chapter','0001')}/chapter.md") or hashlib.sha256(body.encode()).hexdigest()
        for key,binding in (('reader_report','body_sha256'),('conflict','source_sha256')):
            value=data.get(key)
            if not isinstance(value,dict):continue
            if value.get(binding)!=current:
                result[key]={'status':'stale_not_authoritative','source_sha256':value.get(binding),'current_source_sha256':current,
                    'canonical_sha256':digest(value),'note':'旧版本诊断仅留本地；本轮依据完整当前正文、本书规则与作者要求重新规划，不把旧稿问题当作当前事实。'}
            elif key=='reader_report':result[key].pop('review_binding',None)
        result.pop('source_hashes',None)
    result['_model_view']={'protocol':'composition-view-v1','canonical_sha256':digest(data),'guidance':'body字符串是完整当前原文，不是摘要或节选；规则、作者要求和有效审稿判断完整保留。'}
    refs = _composition_refs(data)
    if refs:
        result.update(refs)
        if 'request_digest' in refs and isinstance(result.get('plan'), dict) and 'request_digest' in result['plan']:
            result['plan']['request_digest'] = refs['request_digest']
        result['_model_view']['guidance'] += ' 输出时原样复制当前顶层 request_digest 和已提供的 plan_digest 短编号，程序会绑定完整指纹。'
    result['_book_guidance']=book_guidance()
    return result


def verify_composition(actual,data):
    if actual!=composition(data):raise ValueError('规划模型输入与冻结的完整当前资料不一致，未采用方案')
