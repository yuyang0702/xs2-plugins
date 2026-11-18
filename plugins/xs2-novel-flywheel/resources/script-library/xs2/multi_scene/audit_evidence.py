"""Deterministic references into the current candidate; never repair invented proof."""
import re

ZERO_PATTERN=r'(?<![^\s，。：:“「『（(])(?:零|0)(?=$|[，。！？；\s]|[.!?;](?:\s|$))'


def unit_names(contract):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('catalog_scoped_units',Path(__file__).with_name('continuity_contract.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.evidence_unit_names(contract)


def _occurrence(body,text,start):
    count=0;position=-1
    while position<start:
        position=body.find(text,position+1)
        if position<0:raise ValueError('凭据无法定位')
        count+=1
    return count


def position(body,quote):
    if not isinstance(quote,dict) or set(quote)!={'text','occurrence'}:
        raise ValueError('凭据需要逐字引文和出现序号')
    text,occ=quote['text'],quote['occurrence']
    if not isinstance(text,str) or not text.strip() or type(occ) is not int or not 1<=occ<=1000:
        raise ValueError('引文或出现序号无效')
    start=-1
    for _ in range(occ):
        start=body.find(text,start+1)
        if start<0:
            raise ValueError('核验引文不在当前正文中：'+text[:100])
    return start,start+len(text)


def catalog(body,units=None):
    rows=[]
    def add(kind,prefix,matches):
        for match in matches:
            text=match[0].strip()
            if not text:continue
            start=match.start()+len(match[0])-len(match[0].lstrip());end=start+len(text)
            rows.append({'id':f'{prefix}{sum(r["kind"]==kind for r in rows)+1:04d}','kind':kind,
                         'text':text,'occurrence':_occurrence(body,text,start),'start':start,'end':end})
    add('paragraph','p',re.finditer(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)',body,re.S))
    add('clause','c',re.finditer(r'[^，。！？；\n]+[，。！？；]?',body))
    if units:
        pattern=r'(?:第)?[0-9零〇一二两三四五六七八九十百千万半.]+?\s*(?:'+'|'.join(re.escape(u) for u in sorted(units,key=len,reverse=True))+r')(?:半(?!'+ '|'.join(re.escape(u) for u in units)+r'))?'
        add('amount','a',re.finditer('(?:'+pattern+')|(?:'+ZERO_PATTERN+')',body))
    return rows


def resolve_report(report,body,units=None,*,reader_excerpts=False):
    rows={r['id']:r for r in catalog(body,units)}
    def fail(path,reason):raise ValueError(path+'：'+reason)
    def reader_excerpt(quote,path):
        if not isinstance(quote,str) or not quote.strip() or quote in body:
            return quote
        # A model may collapse paragraph breaks. Restore only an unambiguous
        # contiguous span with every non-newline character intact.
        lines=re.split(r'(?:\r?\n)+',quote)
        if len(lines)>1 and all(lines):
            pattern=r'(?:\r?\n)+'.join(map(re.escape,lines))
            matches=re.finditer(pattern,body)
            first=next(matches,None)
            if first and next(matches,None) is None:
                return first[0]
        fail(path,'使用实际 ref_id 或完整范围引用当前原文中的连续片段')
    def span(value,path):
        if set(value)=={'ref_id'}:
            row=rows.get(value['ref_id'])
            if row is None:fail(path,'不是当前候选的有效凭据ID '+str(value['ref_id']))
            return {'text':row['text'],'occurrence':row['occurrence']}
        if set(value)=={'start_ref','end_ref'}:
            start,end=rows.get(value['start_ref']),rows.get(value['end_ref'])
            if start is None or end is None or start['start']>end['start'] or start['end']>end['end']:
                fail(path,'凭据范围ID无效或反序')
            text=body[start['start']:end['end']]
            return {'text':text,'occurrence':_occurrence(body,text,start['start'])}
        if set(value)=={'text','occurrence'}:
            try:position(body,value)
            except ValueError as exc:fail(path,str(exc))
            return dict(value)
        fail(path,'凭据结构无效')
    def walk(value,path):
        if isinstance(value,dict):
            if any(k in value for k in ('ref_id','start_ref','end_ref')) or set(value)=={'text','occurrence'}:
                return span(value,path)
            result={k:walk(v,path+'.'+k) for k,v in value.items()}
            if 'excerpts' in result and isinstance(result['excerpts'],list):
                result['excerpts']=[v['text'] if isinstance(v,dict) and set(v)=={'text','occurrence'} else v for v in result['excerpts']]
                if reader_excerpts:
                    result['excerpts']=[reader_excerpt(quote,f'{path}.excerpts[{index}]')
                                        for index,quote in enumerate(result['excerpts'])]
            return result
        if isinstance(value,list):return [walk(v,path+f'[{i}]') for i,v in enumerate(value)]
        return value
    return walk(report,'report')
