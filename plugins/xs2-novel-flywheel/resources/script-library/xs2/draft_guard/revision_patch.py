"""Apply exact-source local revisions without regenerating untouched prose."""
import hashlib
import re


def digest(text):return hashlib.sha256(text.encode()).hexdigest()


def paragraphs(body):
    rows=[]
    for match in re.finditer(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)',body,re.S):
        rows.append({'id':f'p{len(rows)+1:04d}','text':match[0],'sha256':digest(match[0]),'start':match.start(),'end':match.end()})
    return rows


def apply_patches(source,payload,*,protected_phrases=()):
    if not isinstance(payload,dict) or set(payload)!={'source_sha256','edits'} or payload['source_sha256']!=digest(source):
        raise ValueError('局部修订来源哈希不匹配，只能修改当前冻结原文')
    edits=payload['edits']
    if not isinstance(edits,list):raise ValueError('局部修订edits须为数组；无须修改可为空')
    rows={r['id']:r for r in paragraphs(source)};spans=[]
    for index,edit in enumerate(edits):
        if (not isinstance(edit,dict) or set(edit)!={'paragraph_id','old','occurrence','replacement'}
            or edit['paragraph_id'] not in rows or not isinstance(edit['old'],str) or not edit['old'].strip()
            or not isinstance(edit['replacement'],str) or type(edit['occurrence']) is not int or not 1<=edit['occurrence']<=1000):
            raise ValueError(f'edits[{index}]的段落、原句、出现序号或替代文字无效')
        row=rows[edit['paragraph_id']];start=-1
        for _ in range(edit['occurrence']):
            start=row['text'].find(edit['old'],start+1)
            if start<0:raise ValueError(f'edits[{index}]原句不在{row["id"]}指定出现位置，不能猜测或修改别处')
        start+=row['start'];end=start+len(edit['old'])
        if any(max(start,a)<min(end,b) for a,b,_ in spans):raise ValueError('局部修订范围重叠，不能重复替换同一原文')
        spans.append((start,end,edit['replacement']))
    result=source
    for start,end,replacement in sorted(spans,reverse=True):result=result[:start]+replacement+result[end:]
    for phrase in protected_phrases:
        if result.count(phrase)<source.count(phrase):raise ValueError('修订删掉了本书要求保留的表达：'+phrase)
    if not result.strip():raise ValueError('局部修订不能清空正文')
    return result
