"""Advisory evidence for purposeful precision; never a prose acceptance gate."""
from collections import Counter
import re


DEFAULT_PROSE = '''正文和导语默认少用确数。先试相对时间、可理解的规模、人物眼下的动作或实际后果；读者仍明白就省去数值。设定、场景卡、事实台账和已采用范文里的确数是内部依据，正文只写此刻有叙事作用的部分。对白和旁白连着读，确数只在需要的位置出现，接话、心理和动作不用重新报一遍。保留决定后续行动的数值、重要证据、作者明确保护的表达和确实体现人物声音的计数。'''

COUNTERFACTUAL = '''先实际用相对说法朗读整段，再判断是否需要确数。日常商量把「几点」换成正在做的事完成以后，确认时可答应或说到了联系。只要明白谁先忙完、为何改约、最后是否答应，日常约时间本身不构成保留确数的理由。若已知道只有一个道具，后续写道具名或动作即可，情节重要也不用每次重数。点单、找零、备料、交接等手续只写眼下有用的部分，普通生活真实感即可由物件和动作承载。若决定保留某值，说明遮住这一处后哪项实际判断会不成立；「是关键道具」「这是具体约定」「这是经营细节」本身不算理由。'''

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
_DETAIL_NUMBER = r'(?:[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+)'
_DETAIL = re.compile(
    rf'(?P<clock>(?<![0-9])[0-9]{{1,2}}[:：][0-5][0-9](?![0-9]))|(?P<hour>{_DETAIL_NUMBER})点(?P<half>半|{_DETAIL_NUMBER}分)?'
    rf'|(?P<value>{_DETAIL_NUMBER})[ \t]*(?P<unit>毫克|千克|公斤|公里|厘米|毫米|毫升|分钟|小时|个月|秒|米|升|克|斤|元|块钱|块|份|单|枚|套|箱|包|袋|颗|张|件|碗|杯|盘|个|次|遍|天|年|月|周|根|勺|步|圈)')
_PARAGRAPHS = re.compile(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)', re.S)
_PRECISE_UNIT = {'clock', '秒', '分钟', '小时', '厘米', '毫米', '毫升', '毫克', '千克', '公斤', '公里', '元'}
_ONE_OCLOCK_BEFORE = re.compile(r'(?:凌晨|下午|午后|中午|夜里|半夜|明天|今天|约在|定在|到了|到|约|改)$')


def _details(text):
    for match in _DETAIL.finditer(text):
        if match['clock']:
            hour,minute=re.split('[:：]',match['clock']);hour=int(hour);minute=int(minute)
            if hour>23:continue
            yield match[0],('clock',hour*60+minute)
        elif match['hour']:
            hour=_integer(match['hour'])
            if hour is None or not 0<=hour<=23:continue
            # Bare 一点 usually means a little; require a clock cue.
            if hour==1 and not match['half'] and (
                not _ONE_OCLOCK_BEFORE.search(text[max(0,match.start()-4):match.start()])
                and not re.match(r'前|后|整|钟',text[match.end():])
            ):continue
            minute = 30 if match['half']=='半' else _integer(match['half'][:-1]) if match['half'] else 0
            if minute is not None and 0<=minute<60:
                yield match[0],('clock',hour*60+minute)
        else:
            if match.start() and text[match.start()-1]=='第' and match['unit'] in {'个','天','次','年','月','周'}:
                continue
            unit='元' if match['unit'] in ('块','块钱') else match['unit']
            value=_integer(match['value'])
            if value is None:value=match['value']
            yield match[0],(unit,value)


def detail_keys(text):
    return {key for _,key in _details(text)}


def detail_counts(text):
    return Counter(key for _, key in _details(text))


def check_removed(before, after, targets):
    """Refuse to move a rejected value or change only its notation."""
    removed = Counter()
    for original_paragraph, details in targets:
        counts = detail_counts(original_paragraph)
        for key in detail_keys(' '.join(details)):
            removed[key] += counts[key]
    original, revised = detail_counts(before), detail_counts(after)
    if any(revised[key]>original[key]-count for key,count in removed.items()):
        raise ValueError('返修目标的确数仍在，不能换写成同值或移到其他段落。')


def review_candidates(text, paragraphs=None):
    """Locate exact values in dialogue and narration for a semantic decision."""
    if paragraphs is None:
        paragraphs = [{'id': f'p{index:04d}', 'text': match[0]}
                      for index, match in enumerate(_PARAGRAPHS.finditer(text), 1)]
    matches = [list(_details(row['text'])) for row in paragraphs]
    keys = [{key for _, key in row} for row in matches]
    result = []
    for index, (paragraph, details) in enumerate(zip(paragraphs, matches)):
        # Short interruptions may separate lines about the same quantity.
        nearby = set().union(*keys[max(0,index-4):index], *keys[index+1:index+5])
        bundled = set()
        for quote in _QUOTE.finditer(paragraph['text']):
            quoted = detail_keys(quote[0])
            if len(quoted)>=2:bundled.update(quoted)
        selected = [value for value, key in details if (
            key in bundled or key[0] in _PRECISE_UNIT or type(key[1]) is int and key[1]>=2
            or key in nearby and key[0] not in {'个','次','遍','步','圈','单','勺','块','根','张','天','年','月','周','个月'}
        )]
        if selected:
            result.append({'paragraph_id': paragraph['id'], 'details': list(dict.fromkeys(selected))})
    return result


def dialogue_details(text):
    """Suggest anchored review targets, leaving the use of precision to the critic."""
    rows=[]
    for index,paragraph in enumerate(re.finditer(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)',text,re.S),1):
        details=[]
        for quote in _QUOTE.finditer(paragraph[0]):
            matches=list(_details(quote[0]))
            if len({key for _,key in matches})>=2:
                details.extend(value for value,_ in matches)
        if details:
            rows.append({'paragraph_id':f'p{index:04d}','details':list(dict.fromkeys(details))})
    return rows


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
