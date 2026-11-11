"""Lossless model views; canonical audit inputs and validators remain unchanged."""
import copy
import hashlib
import json
import re
import importlib.util
from functools import lru_cache
from pathlib import Path

PROTOCOL='lossless-context-v1'
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


def restore(view):
    if view.get('format')!=PROTOCOL or not isinstance(view.get('suffix'),str):raise ValueError('Invalid prose view')
    result=''
    for i,row in enumerate(view['paragraphs']):
        if row.get('id')!=f'p{i+1:04d}' or any(not isinstance(row.get(k),str) for k in ('before','text')):
            raise ValueError('Invalid paragraph in prose view')
        result+=row['before']+row['text']
    return result+view['suffix']


def local(data,role):
    result=copy.deepcopy(data)
    for key in ('source_body','candidate','candidate_body'):
        if isinstance(result.get(key),str):result[key]=prose(result[key])
    result.pop('paragraphs',None);result.pop('evidence_catalog',None)
    if 'book_contract' in result:
        result['_book_guidance']=book_guidance()
        if result['book_contract'].get('reading_contract'):
            spec=importlib.util.spec_from_file_location('packet_reading',Path(__file__).with_name('reading_contract.py'))
            reading=importlib.util.module_from_spec(spec);spec.loader.exec_module(reading)
            result['_book_guidance']+='\n'+reading.GUIDANCE
    result['_model_view']={'protocol':PROTOCOL,'role':role,'canonical_sha256':digest(data),'guidance':GUIDANCE}
    result['_precision_guidance']=precision().GUIDANCE
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
    result['_book_guidance']=book_guidance()
    return result


def verify_composition(actual,data):
    if actual!=composition(data):raise ValueError('规划模型输入与冻结的完整当前资料不一致，未采用方案')
