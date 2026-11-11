"""Advisory evidence for purposeful precision; never a prose acceptance gate."""
import re


GUIDANCE = '''按阅读目的判断精确计数是否有用：数字应帮助读者理解选择、约束、变化或人物声音。
金额、期限、科学数量、资源账、类型表达、刻意夸张和强迫计数都可以保留；本书契约与风格要求优先。
怀疑无用的精确秒数、步数或字数时，引用当前原文及位置，说明它如何打断阅读，再交由作者复核。
不设数字配额，不禁数字，不强制短句；未知用途不等于错误，不自动拒绝或改写。
字数事实候选仅核对紧邻、唯一、纯汉字的逐字引语，每个汉字计一字，不计引号；有标点、外文、嵌套或远距指代则标未知。
若“下午聊一下”后紧接“这四个字”，五个汉字与声称的四个不符，也先判断计数是否必要。
不机械四→五，不为过审编造事实或通过记录；可根据阅读目的删去无用计数，必要时才核对并修正。'''

_NUM = r'[0-9零〇一二两三四五六七八九十百千万]+'
_CLAIM = re.compile(r'(?:这|那)(?P<count>'+_NUM+r')个字')
_QUOTE = re.compile(r'“(?P<curly>[^“”「」『』"\n]*)”|「(?P<corner>[^“”「」『』"\n]*)」|"(?P<ascii>[^“”「」『』"\n]*)"')
_PRECISE = re.compile(r'(?:(?:恰好|整整|精确到|准确地?)\s*(?:'+_NUM+r'|\d+\.\d+)\s*(?:秒|分钟|步|次)|\d+\.\d+\s*(?:秒|分钟|步|次))')
_PURPOSE = re.compile(r'实验|测量|科学|倒计时|截止|期限|限时|计时器|比赛|强迫|数数|计数习惯|夸张')


def _integer(value):
    if re.fullmatch(r'[0-9]+',value):
        try:return int(value)
        except ValueError:return None
    if not re.fullmatch(r'[零〇一二两三四五六七八九十百千]+',value):return None
    digits=dict(zip('零〇一二两三四五六七八九',(0,0,1,2,2,3,4,5,6,7,8,9)))
    total=section=digit=0
    for char in value:
        if char in digits:digit=digit*10+digits[char]
        elif char in '十百千':section+=(digit or 1)*{'十':10,'百':100,'千':1000}[char];digit=0
        elif char=='万':total+=(section+digit)*10000;section=digit=0
        else:return None
    result=total+section+digit
    # A Chinese count must have a canonical positional form. Consecutive digits
    # such as 四五 may mean "four or five", never silently turn them into 45.
    if not 0<=result<10000:return None
    chars='零一二三四五六七八九';rendered='';pending_zero=False
    for divisor,unit in ((1000,'千'),(100,'百'),(10,'十'),(1,'')):
        n=(result//divisor)%10
        if n:
            if pending_zero:rendered+='零'
            rendered+=chars[n]+unit;pending_zero=False
        elif rendered:pending_zero=True
    rendered=rendered or '零'
    if rendered.startswith('一十'):rendered=rendered[1:]
    return result if value.replace('〇','零').replace('两','二')==rendered else None


def _span(text,start,end):
    return {'quote':text[start:end],'start':start,'end':end}


def _enclosing_quote(text, position):
    """Conservatively detect any still-open outer quotation before an antecedent."""
    stack=[];pairs={'“':'”','「':'」','『':'』'}
    for char in text[:position]:
        if char=='"':
            if stack and stack[-1]=='"':stack.pop()
            else:stack.append('"')
        elif char in pairs:stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1]!=char:return True
            stack.pop()
    return bool(stack)


def analyze(text, contract=None):
    """Return JSON-safe advisory findings with zero-based, end-exclusive text offsets.

    contract.precision_policy.preserve_counting=True suppresses style advice only.
    It cannot certify or hide explicit factual mismatches. Other book/style information
    remains available to callers for semantic adjudication; no automatic pass is emitted.
    """
    if not isinstance(text,str):raise TypeError('正文须为字符串')
    findings=[];quotes=list(_QUOTE.finditer(text))
    for claim in _CLAIM.finditer(text):
        row={**_span(text,claim.start(),claim.end()),'kind':'quoted_character_count',
             'status':'unknown','claimed_count':_integer(claim['count']), 'actual_count':None,
             'reason':'紧邻唯一的纯汉字引语依据不足，字数与计数用途须人工复核。'}
        preceding=[q for q in quotes if q.end()<=claim.start()]
        quote=preceding[-1] if preceding else None
        if quote and re.fullmatch(r'[\s，,：:]*',text[quote.end():claim.start()]):
            group=next(name for name in ('curly','corner','ascii') if quote[name] is not None)
            literal=quote[group]
            # Consecutive/nested quotes and punctuation admit different referents/rules.
            previous=preceding[-2] if len(preceding)>1 else None
            multiple=bool(previous and re.fullmatch(r'[\s，,、和与及]*',text[previous.end():quote.start()]))
            nested=_enclosing_quote(text,quote.start())
            if (row['claimed_count'] is not None and not multiple and not nested
                    and re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+',literal)):
                row.update(antecedent=_span(text,quote.start(group),quote.end(group)),
                           actual_count=len(literal), counting_rule='纯汉字逐字计数，每个汉字计一字；不计外围引号')
                if row['actual_count']==row['claimed_count']:continue
                row.update(status='fact_candidate',reason='紧邻纯汉字引语的逐字数与声称字数不符；先复核阅读目的，不机械改数。')
        findings.append(row)
    policy=contract.get('precision_policy',{}) if isinstance(contract,dict) else {}
    preserve=isinstance(policy,dict) and policy.get('preserve_counting') is True
    if not preserve:
        for match in _PRECISE.finditer(text):
            # Only local purpose hints suppress advice; distant quantities cannot excuse it.
            start=max(text.rfind('。',0,match.start()),text.rfind('\n',0,match.start()))+1
            stops=[p for p in (text.find('。',match.end()),text.find('\n',match.end())) if p>=0]
            end=min(stops) if stops else len(text)
            if _PURPOSE.search(text[start:end]):continue
            findings.append({**_span(text,match.start(),match.end()), 'kind':'possibly_unnecessary_precision',
                             'status':'advisory','reason':'此处强调精确计数；请结合本书契约和人物声音，复核数字是否帮助阅读目的。'})
    return {'schema':1,'advisory_only':True,'findings':sorted(findings,key=lambda r:r['start'])}
