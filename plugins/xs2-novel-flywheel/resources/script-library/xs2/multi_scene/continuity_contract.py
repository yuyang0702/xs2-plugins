"""Source-grounded chapter facts, exact money arithmetic and observed event order."""
import hashlib
import json
import re
import importlib.util
import copy
from pathlib import Path
from decimal import Decimal
from fractions import Fraction

HARD=('money','facts','pov','handoff','resources')
_DIGITS=dict(zip('零〇一二两三四五六七八九', [0,0,1,2,2,3,4,5,6,7,8,9]))
_spec=importlib.util.spec_from_file_location('continuity_audit_evidence',Path(__file__).with_name('audit_evidence.py'))
audit_evidence=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(audit_evidence)
_expression_spec=importlib.util.spec_from_file_location('continuity_expression_rules',Path(__file__).resolve().parents[1]/'prose_policy/expression_review.py')
expression_rules=importlib.util.module_from_spec(_expression_spec);_expression_spec.loader.exec_module(expression_rules)


def _require(ok, message):
    if not ok:raise ValueError(message)


def number(text):
    if re.fullmatch(r'\d+(?:\.\d+)?',text):return Decimal(text)
    if text=='半':return Decimal('.5')
    total=section=digit=Decimal(0)
    for c in re.findall(r'\d+(?:\.\d+)?|.',text):
        if c[0].isdigit():digit=Decimal(c)
        elif c in _DIGITS:digit=digit*10+_DIGITS[c]
        elif c in '十百千':section+=(digit or 1)*{'十':10,'百':100,'千':1000}[c];digit=0
        elif c=='万':total+=(section+digit)*10000;section=digit=0
        else:raise ValueError('金额数字不可识别')
    return Decimal(total+section+digit)


def _terms(text,units):
    _require(isinstance(text,str) and units,'金额与本书单位不能为空')
    _require(not re.search(r'[-负]\s*[0-9零〇一二两三四五六七八九十百千万半]',text),'实际交付金额不能用负数冒充正数')
    pattern=re.compile(r'(?P<ordinal>第)?(?P<number>[0-9零〇一二两三四五六七八九十百千万半.]+?)\s*(?P<unit>'+ '|'.join(re.escape(u) for u in sorted(units,key=len,reverse=True))+')')
    matches=list(pattern.finditer(text))
    if not matches and re.search(audit_evidence.ZERO_PATTERN,text):return [(Decimal(0),next(iter(units)))]
    _require(matches,'引文没有可复算金额或数量')
    result=[]
    for m in matches:
        value=Decimal(1) if m['ordinal'] else number(m['number']);tail=text[m.end():]
        if tail.startswith('半') and not any(tail[1:].startswith(u) for u in units):value+=Decimal('.5')
        result.append((value,m['unit']))
    return result


def amount(text,units):
    value=sum((n*units[u] for n,u in _terms(text,units)),Decimal(0))
    _require(value==value.to_integral_value(),'金额不能精确表示为本书最小单位')
    return int(value)


class Arithmetic:
    """Reuse a calculation, while the caller checks the quote in the current prose."""

    def __init__(self, calculate, verified=None):
        self.calculate = calculate
        self.values = dict(verified or {})
        self.hits = self.misses = 0

    def __call__(self, text, units):
        evidence = json.dumps([text, units], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        key = hashlib.sha256(evidence.encode()).hexdigest()
        if key in self.values:
            self.hits += 1
        else:
            self.values[key] = self.calculate(text, units)
            self.misses += 1
        return self.values[key]


def _constrained_units(units,equations):
    if not units:return
    keys=list(units);matrix=[]
    base=[Fraction(0) for _ in keys];base[next(i for i,k in enumerate(keys) if units[k]==1)]=Fraction(1);matrix.append(base)
    for eq in equations:
        row=[Fraction(0) for _ in keys]
        for side,sign in [('left',1),('right',-1)]:
            for n,u in _terms(eq[side],units):row[keys.index(u)]+=sign*Fraction(n)
        matrix.append(row)
    rank=0
    for column in range(len(keys)):
        pivot=next((i for i in range(rank,len(matrix)) if matrix[i][column]),None)
        if pivot is None:continue
        matrix[rank],matrix[pivot]=matrix[pivot],matrix[rank];value=matrix[rank][column]
        matrix[rank]=[n/value for n in matrix[rank]]
        for i,row in enumerate(matrix):
            if i!=rank:
                value=row[column];matrix[i]=[a-value*b for a,b in zip(row,matrix[rank])]
        rank+=1
    _require(rank==len(keys),'资料换算不足以确定所有单位相对最小单位的倍率')


def contract_digest(contract):
    return hashlib.sha256(json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _modern_cny_evidence(quote, units):
    # Scope evidence must identify both the currency and this ledger's unit.
    if not isinstance(quote,str):return False
    # Every clause must fit the affirmative grammar. Selecting only a positive
    # substring would discard retractions or an unknown competing currency.
    clauses=[part.strip() for part in re.split(r'[，,。；;\n]',quote) if part.strip()]
    quantity=r'[一二三四五六七八九十百千万零〇两0-9]+\s*(?P<unit>元|块)(?:钱|整)?'
    scoped=False;unit_seen=False
    for part in clauses:
        if re.fullmatch(r'本账(?:使用|采用|以|用)(?:现代)?人民币(?:计价|结算)?',part):
            scoped=True;continue
        direct=re.fullmatch(r'人民币\s*'+quantity,part)
        amount_clause=direct or re.fullmatch(r'(?:收款|付款|支付|收入|支出|余额|期初|余款|现钱)?\s*'+quantity,part)
        if amount_clause is None:return False
        if direct:scoped=True
        if amount_clause['unit'] in units:unit_seen=True
    return scoped and unit_seen


def enrich_unit_aliases(ledger, source_quote):
    """Return a copy scoped to source-backed modern CNY; caller supplies ledger evidence only.

    Validate the resulting contract against the full approved sources before freezing its digest.
    Never pass a whole-book blob mixing independent currencies/resource ledgers here.
    """
    _require(_modern_cny_evidence(source_quote,ledger.get('units',{})), '缺少本账人民币单位的明确资料依据')
    result=copy.deepcopy(ledger)
    result['currency_scope']={'code':'CNY','source_quote':source_quote}
    effective_units(result)
    return result


def effective_units(ledger):
    """Expand only this ledger's proven synonyms, retaining its canonical rate matrix."""
    canonical=ledger.get('units',{});result=dict(canonical)
    aliases=ledger.get('unit_aliases',[])
    _require(isinstance(aliases,list),'本账单位别名须为数组')
    seen=set()
    for row in aliases:
        _require(isinstance(row,dict),'单位别名格式无效')
        alias,unit,quote=(row.get(k) for k in ('alias','unit','source_quote'))
        _require(isinstance(alias,str) and alias.strip() and alias not in canonical and alias not in seen
                 and unit in canonical and isinstance(quote,str),'单位别名重复、冲突或没有标准单位')
        # An explicit one-to-one statement is required, not mere co-occurrence.
        pair=lambda a,b: r'\s*(?:一|1)\s*'+re.escape(a)+r'\s*(?:等于|就是|=|＝)\s*(?:一|1)\s*'+re.escape(b)+r'\s*[。.;；]?\s*'
        _require(re.fullmatch(pair(unit,alias),quote) or re.fullmatch(pair(alias,unit),quote),'单位别名须有完整肯定的一比一等值依据')
        result[alias]=canonical[unit];seen.add(alias)
    scope=ledger.get('currency_scope')
    if scope is not None:
        _require(isinstance(scope,dict) and scope.get('code')=='CNY'
                 and _modern_cny_evidence(scope.get('source_quote'),canonical),'人民币作用域缺少本账单位依据')
        known=[u for u in ('元','块') if u in canonical]
        _require(known and len({canonical[u] for u in known})==1,'本账元与块倍率冲突')
        for alias in ('元','块'):
            _require(alias not in result or result[alias]==canonical[known[0]],'人民币别名倍率冲突')
            result[alias]=canonical[known[0]]
    return result


def evidence_unit_names(contract):
    """Catalog vocabulary only; arithmetic always uses each ledger independently."""
    return dict.fromkeys([*effective_units(contract),*(u for row in contract.get('resource_ledgers',[]) for u in effective_units(row))],1)


def _rows(rows,label):
    _require(isinstance(rows,list),label+'须为数组')
    result={}
    for row in rows:
        _require(isinstance(row,dict) and isinstance(row.get('id'),str) and row['id'].strip() and row['id'] not in result,label+'标识缺失或重复')
        result[row['id']]=row
    return result


def resource_contract(parent,row):
    return {'schema':1,'focus':parent['focus'],'facts':[],'events':parent['events'],
            **{k:row[k] for k in ('unit_aliases','currency_scope') if k in row},
            **{k:row[k] for k in ('units','unit_equations','accounts','transfers')}}


def _planning_quote_rows(sources):
    return {f'@Q{index:04d}': line for index, line in enumerate(sources.splitlines(), 1) if line.strip()}


def planning_quote_view(sources):
    instructions = (
        '【分场证据】source_quote 可直接填本页左侧的原文编号（如 @Q0001），程序会核对并换成对应原文。'
        '也可复制实际连续原句。description 可概括；source_quote 不能拼接、概括或改标点。'
        'opening_quote、parts 和 change 仍要填写可直接复算的原文。'
        '只登记确需跟踪且有原文支持的数量变化；预约标签或道具出现本身不构成库存进出，'
        '不能用已有容量反推一次无数量原文的交付。\n\n'
    )
    return instructions + '\n'.join(f'[{key}] {line}' for key, line in _planning_quote_rows(sources).items()) + '\n'


def bind_planning_quotes(contract, sources):
    """Resolve only citations from the exact task source; collect all bad rows."""
    rows = _planning_quote_rows(sources)
    problems = []

    def bind(value, path):
        if isinstance(value, list):
            return [bind(item, f'{path}[{item.get("id", index) if isinstance(item, dict) else index}]')
                    for index, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        result = {key: bind(item, f'{path}.{key}') for key, item in value.items()}
        if 'source_quote' in value:
            quote = value['source_quote']
            if isinstance(quote, str) and quote in rows:
                result['source_quote'] = rows[quote]
            elif not isinstance(quote, str) or not quote.strip() or quote not in sources:
                problems.append(f'{path}.source_quote')
        return result

    bound = bind(contract, 'continuity')
    if problems:
        raise ValueError('以下逐字证据不在冻结资料中，请改用该项对应的原文编号或连续原句：' + '、'.join(problems))
    return bound


def validate_contract(data,sources,scene_count):
    _require(isinstance(data,dict) and data.get('schema')==1 and isinstance(data.get('focus'),str) and data['focus'].strip(),'连续性契约格式无效')
    def supported(row):
        quote=row.get('source_quote');_require(isinstance(quote,str) and quote.strip() and quote in sources,'事实缺少有效资料原文依据')
        return quote
    facts=_rows(data.get('facts'),'共享事实')
    for row in facts.values():
        quote=supported(row);aliases=row.get('aliases')
        _require(isinstance(row.get('value'),str) and row['value'].strip() and row['value'] in quote
                 and isinstance(aliases,list) and all(isinstance(a,str) and a.strip() and a in quote for a in aliases)
                 and type(row.get('required')) is bool,'标准名称或别名没有来源依据')
        _require(row.get('match_mode','name') in ('name','referent'),'共享事实须声明称名或同物指代核验方式')
    units=data.get('units');_require(isinstance(units,dict) and all(isinstance(k,str) and k.strip() and type(v) is int and v>0 for k,v in units.items()),'单位比例须为正整数')
    equations=data.get('unit_equations');_require(isinstance(equations,list),'缺少换算依据')
    _require(not units or 1 in units.values(),'须声明本书最小金额单位')
    _require(len(units)<=1 or equations,'多单位换算不能凭空假设')
    for row in equations:
        quote=supported(row)
        _require(all(isinstance(row.get(k),str) and row[k].strip() and row[k] in quote for k in ('left','right')),'换算两侧须逐字出自依据')
        _require(amount(row['left'],units)==amount(row['right'],units),'本书单位与所引换算依据不一致')
    _constrained_units(units,equations)
    for alias in data.get('unit_aliases',[]):supported(alias)
    if data.get('currency_scope') is not None:supported(data['currency_scope'])
    units=effective_units(data)
    accounts=_rows(data.get('accounts'),'账户');balances={}
    for key,row in accounts.items():
        _require(type(row.get('opening')) is int and row['opening']>=0,'期初现钱须明确为非负整数')
        if row['opening']:
            quote=row.get('opening_quote');_require(isinstance(quote,str) and quote.strip() and quote in sources,'非零期初现钱须有资料原文依据')
            _require(amount(quote,units)==row['opening'],'期初现钱与所引资料不一致')
        balances[key]=row['opening']
    events=_rows(data.get('events'),'履行事件')
    for key,row in events.items():
        supported(row)
        _require(type(row.get('scene')) is int and 1<=row['scene']<=scene_count and isinstance(row.get('description'),str) and row['description'].strip(),'事件场次或说明无效')
        deps=row.get('after');_require(isinstance(deps,list) and len(deps)==len(set(deps)) and all(d in events and d!=key and events[d]['scene']<=row['scene'] for d in deps),'事件依赖或场次先后无效')
    visited=set()
    def visit(key,stack):
        _require(key not in stack,'履行事件不能循环依赖')
        if key not in visited:
            for d in events[key]['after']:visit(d,stack|{key})
            visited.add(key)
    for key in events:visit(key,set())
    transfers=_rows(data.get('transfers'),'钱款')
    previous=0
    for row in transfers.values():
        quote=supported(row);scene=row.get('scene')
        _require(type(scene) is int and previous<=scene<=scene_count and scene>=1,'钱款须按实际场次顺序记录');previous=scene
        _require(row.get('account') in balances and row.get('direction') in ('in','out')
                 and type(row.get('amount')) is int and row['amount']>=0 and type(row.get('balance')) is int,'钱款账户、方向或整数金额无效')
        _require(isinstance(row.get('parts'),str) and row['parts'].strip() and row['parts'] in quote
                 and isinstance(row.get('change'),str) and (not row['change'] or row['change'] in quote),'钱款分项与找零须出自资料原文')
        try:
            expected=amount(row['parts'],units)-(amount(row['change'],units) if row['change'] else 0)
        except ValueError as error:
            raise ValueError(f"记录 {row['id']} 的 parts 或 change 没有可复算金额或数量：{error}") from error
        _require(expected==row['amount'],'钱款分项、找零与净额不一致')
        balances[row['account']]+=row['amount']*(1 if row['direction']=='in' else -1)
        _require(balances[row['account']]>=0 and balances[row['account']]==row['balance'],'钱款余款不闭合或发生无来源支出')
        event=events.get(row.get('event_id'))
        _require(event is not None and event['scene']==scene,'钱款须绑定本场实际履行事件')
    for row in _rows(data.get('resource_ledgers',[]),'分项资源账').values():
        validate_contract(resource_contract(data,row),sources,scene_count)
    return data


def located(span,body):
    _require(isinstance(span,dict) and isinstance(span.get('text'),str) and span['text'].strip()
             and type(span.get('occurrence')) is int and 1<=span['occurrence']<=1000,'核验引文及出现序号无效')
    start=-1
    for _ in range(span['occurrence']):
        start=body.find(span['text'],start+1);_require(start>=0,'核验引文不在当前正文中')
    return start,start+len(span['text'])


def _overlapping(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def _report_of_completed_event(body, previous, later):
    """An explicit report of a completed action has two times in one sentence."""
    if previous[0] <= later[0]:
        return False
    lead = body[later[0]:previous[0]]
    report = re.search(r'(告诉我|跟我说|对我说|向我说明)[\t ：:，,“「]*$', lead)
    if not report or later[0] + report.end(1) > later[1] or re.search(r'[。！？；\r\n]', lead):
        return False
    sentence_prefix = re.split(r'[。！？；\r\n]', body[:previous[0]])[-1]
    if re.search(r'如果|要是|假如|假设|倘若|盼着|希望|没(?:有|能)?(?:告诉我|跟我说|对我说)', sentence_prefix):
        return False
    first_clause = re.split(r'[，,。！？；\r\n]', body[previous[0]:previous[1]], maxsplit=1)[0]
    completed = re.search(r'(?:已经|早已)(?P<action>.+?)(?:了|完|成|齐|好|清|妥|掉|解决)$', first_clause)
    return bool(completed and not re.search(r'打算|决定|准备|计划|预计|答应|尚未|没有|没能|要去|等.+再',
                                          completed.group('action')))


def _narrow_verified_events(event_obs, positions, edges, body, contract, facts_audit):
    """Reuse only exact, previously verified subspans of the current citations."""
    overlapping = [(before, after) for before, after in edges
                   if _overlapping(positions[before], positions[after])]
    if not overlapping or not facts_audit or facts_audit.get('candidate_sha256') != hashlib.sha256(body.encode()).hexdigest():
        return
    if audit_issues(facts_audit, body, contract, 'facts'):
        return
    prior = audit_evidence.resolve_report(facts_audit, body, evidence_unit_names(contract))
    quotes = {row['id']: row['quote'] for row in prior['event_observations'] if row.get('quote') is not None}
    verified = {key: located(quote, body) for key, quote in quotes.items()}
    for before, after in overlapping:
        if before not in verified or after not in verified or verified[before][1] > verified[after][0]:
            continue
        if all(positions[key][0] <= verified[key][0] and verified[key][1] <= positions[key][1]
               for key in (before, after)):
            for key in (before, after):
                event_obs[key]['quote'] = quotes[key]
                positions[key] = verified[key]


def audit_issues(report,body,contract,phase,*,arithmetic=None,facts_audit=None):
    _require(phase in ('facts','expression') and isinstance(report,dict) and report.get('schema')==1,'核验报告格式无效')
    _require(report.get('candidate_sha256')==hashlib.sha256(body.encode()).hexdigest()
             and report.get('contract_sha256')==contract_digest(contract),'核验报告与当前候选或事实契约不匹配')
    report=audit_evidence.resolve_report(report,body,evidence_unit_names(contract))
    categories=HARD+(('repetition',) if phase=='expression' else ())
    required=[k for k in categories if k!='resources' or contract.get('resource_ledgers')]
    if phase=='expression':categories+=('convenient_dialogue',)
    _require(isinstance(report.get('checks'),dict) and all(report['checks'].get(k) is True for k in required),'核验报告未检查全部必需维度')
    semantic=report.get('issues');_require(isinstance(semantic,list),'语义问题须明确提供数组')
    for row in semantic:
        _require(isinstance(row,dict) and row.get('category') in categories
                 and all(isinstance(row.get(k),str) and row[k].strip() for k in ('reason','goal'))
                 and isinstance(row.get('excerpts'),list) and row['excerpts']
                 and all(isinstance(q,str) and q.strip() and q in body for q in row['excerpts']),'核验问题缺少当前正文原文与修订目标')
        expression_rules.validate_narrative_issue(row)
    issues=[]
    calculate = amount if arithmetic is None else arithmetic
    units = None
    def issue(category,reason,quotes):
        issues.append({'category':category,'reason':reason,'excerpts':quotes,'goal':'按冻结契约修正实际正文，保持已成立的其他事实与情节边界'})
    def observed_amount(text,label):
        nonlocal units
        try:
            if units is None:
                units = effective_units(contract)
            return calculate(text,units)
        except ValueError as exc:raise ValueError(label+'：'+str(exc)+'；仅使用明确的数字数量，持有或状态描写另作语义核查。引文：'+text[:100]) from exc
    def observations(name,expected):
        actual=_rows(report.get(name),name);_require(set(actual)==set(expected),name+'遗漏或新增了约定核验项')
        return actual
    events=_rows(contract['events'],'事件');event_obs=observations('event_observations',events);positions={}
    for key,obs in event_obs.items():
        if obs.get('quote') is None:issue('handoff','缺少约定履行事件 '+key,[])
        else:positions[key]=located(obs['quote'],body)
    edges = [(dep, key) for key, row in events.items() for dep in row['after'] if key in positions and dep in positions]
    if phase == 'expression':
        _narrow_verified_events(event_obs, positions, edges, body, contract, facts_audit)
    for dep, key in edges:
        if _report_of_completed_event(body, positions[dep], positions[key]):
            continue
        _require(not _overlapping(positions[dep], positions[key]),
                 '前后事件凭据重叠：'+dep+' / '+key+'。请分别引用独立动作的最小分句，不能据宽引文断言正文反序')
        if positions[dep][1]>positions[key][0]:
            explicit=any(isinstance(item,dict) and item.get('category')=='handoff'
                and dep in str(item.get('reason','')) and key in str(item.get('reason',''))
                for item in semantic)
            _require(explicit,'事件凭据位置反向：'+dep+' / '+key+
                '。先核对实际完成时点并重取最小引文，不能用后文复述、追认或回忆的位置冒充发生时点。'
                '若实际履行确实违背依赖，请在issues的handoff中点名两个事件id，提供当前原文及因果说明；'
                '倒叙与复述本身不是正文因果错误，不据此要求作者改写正确顺序。')
    transfers=_rows(contract['transfers'],'钱款');money=observations('money_observations',transfers)
    for key,expected in transfers.items():
        obs=money[key];paid=obs.get('paid');change=obs.get('change')
        if paid is None:issue('money','未显示实际钱款履行 '+key,[]);continue
        paid_pos=located(paid,body);actual=observed_amount(paid['text'],'money_observations['+key+'].paid')
        change_pos=located(change,body) if change is not None else None
        if change is not None:actual-=observed_amount(change['text'],'money_observations['+key+'].change')
        if actual!=expected['amount']:issue('money',f'{key} 正文实际净额 {actual}，约定净额 {expected["amount"]}',[paid['text']]+([change['text']] if change else []))
        event_pos=positions.get(expected['event_id'])
        if event_pos and not (event_pos[0]<=paid_pos[0] and paid_pos[1]<=event_pos[1]):
            issue('money','金额引文不属于约定履行事件 '+key,[paid['text'],event_obs[expected['event_id']]['quote']['text']])
        if change_pos and (not event_pos or not (event_pos[0]<=change_pos[0] and change_pos[1]<=event_pos[1])):
            issue('money','找零引文不属于同一次实际支付 '+key,[change['text']])
        if change_pos and max(paid_pos[0],change_pos[0])<min(paid_pos[1],change_pos[1]):
            issue('money','交付金额与找零引文重叠，不能重复计数',[paid['text'],change['text']])
    balances=report.get('balance_observations');_require(isinstance(balances,list),'须核对正文出现的余额')
    def settled_position(transfer):
        obs=money[transfer['id']]
        spans=[located(obs[k],body) for k in ('paid','change') if obs.get(k) is not None]
        return max((p[1] for p in spans),default=None)
    for obs in balances:
        _require(isinstance(obs,dict) and obs.get('after') in transfers,'余额对应钱款不明');balance_pos=located(obs.get('quote'),body)
        transfer=transfers[obs['after']];settled=settled_position(transfer)
        for kind in ('paid','change'):
            evidence=money[transfer['id']].get(kind)
            if evidence is not None:
                payment_pos=located(evidence,body)
                _require(max(balance_pos[0],payment_pos[0])>=min(balance_pos[1],payment_pos[1]),
                         '余额凭据包含实际付款或找零，请分别引用最小分句，不能据宽引文断言余额提前')
        if settled is None or balance_pos[0]<settled:issue('money','余额早于所指的实际履行事件',[obs['quote']['text']])
        account_rows=[r for r in transfers.values() if r['account']==transfer['account']]
        index=account_rows.index(transfer)
        if index+1<len(account_rows):
            next_paid=money[account_rows[index+1]['id']].get('paid')
            next_start=located(next_paid,body)[0] if next_paid is not None else None
            if next_start is not None and balance_pos[0]>=next_start:issue('money','余额越过了该账户后续实际钱款，不能沿用旧余额',[obs['quote']['text']])
        components=obs.get('components',[obs['quote']])
        _require(isinstance(components,list) and components,'余额分项须有逐字金额凭据')
        component_spans=[];observed=anchored=0
        change=money[transfer['id']].get('change')
        retained=located(change,body) if change is not None else None
        for component in components:
            position=located(component,body)
            _require(all(max(position[0],other[0])>=min(position[1],other[1]) for other in component_spans),
                     '余额分项不能重复或重叠计数')
            inside=balance_pos[0]<=position[0] and position[1]<=balance_pos[1]
            _require(inside or (transfer['direction']=='out' and position==retained and position[1]<=balance_pos[0]),
                     '余额分项须出自该余额陈述，或本笔实际保留的找零，不能借用其他钱款')
            value=observed_amount(component['text'],'balance_observations['+obs['after']+'].components');observed+=value
            if inside:anchored+=value
            component_spans.append(position)
        _require(anchored==observed_amount(obs['quote']['text'],'balance_observations['+obs['after']+'].quote'),
                 '余额分项没有完整覆盖本次余额陈述')
        if observed!=transfers[obs['after']]['balance']:
            issue('money','正文余额与已履行的钱款不闭合',[obs['quote']['text']])
    facts=_rows(contract['facts'],'事实');facts_obs=observations('fact_observations',facts)
    for key,row in facts.items():
        occurrences=facts_obs[key].get('occurrences');_require(isinstance(occurrences,list),'事实观察须为数组')
        if row['required'] and not occurrences:issue('facts','缺少约定共享事实 '+key,[])
        observed_same = any(isinstance(obs, dict) and obs.get('same_referent') is True for obs in occurrences)
        for obs in occurrences:
            located(obs.get('quote'),body);value=obs.get('value');_require(isinstance(value,str) and value.strip() and value in obs['quote']['text'],'标准值不能冒充实际引文中的名称')
            _require(type(obs.get('is_name',True)) is bool,'须区分专名使用与普通描述')
            if row.get('match_mode','name')=='referent' or not obs.get('is_name',True):
                _require(type(obs.get('same_referent')) is bool,'同物指代须经独立语义核对，不能把缺失视为通过')
                if not obs['same_referent']:
                    quote = obs['quote']['text']
                    if phase == 'expression' and observed_same:
                        _require(any(item['category'] == 'facts' and key in item['reason']
                                     and any(quote in evidence or evidence in quote for evidence in item['excerpts'])
                                     for item in semantic),
                                 '同一事实同时出现同物指代和异物。请复核 '+key+
                                 '：容器、部件、同场另一物件只作上下文，不列为该事实的指代。'
                                 '如正文确实用异物替换原物，须在 issues 的 facts 中列出事实 ID、引文及替换关系。')
                    else:
                        issue('facts','共享物件或身份指向发生变化 '+key,[quote])
            elif value not in [row['value'],*row['aliases']]:issue('facts','共享事实 '+key+' 发生变化：'+value,[obs['quote']['text']])
    ledgers=_rows(contract.get('resource_ledgers',[]),'分项资源账')
    resource_obs=observations('resource_observations',ledgers) if ledgers or 'resource_observations' in report else {}
    for key,ledger in ledgers.items():
        child=resource_contract(contract,ledger)
        child_report={**report,'contract_sha256':contract_digest(child),'fact_observations':[],'issues':[],
                      'money_observations':resource_obs[key].get('money_observations'),
                      'balance_observations':resource_obs[key].get('balance_observations')}
        child_report.pop('resource_observations',None)
        for found in audit_issues(child_report,body,child,phase,arithmetic=arithmetic):
            if found['category']=='money':
                issues.append({**found,'category':'resources','reason':key+'：'+found['reason']})
    issues.extend(semantic)
    return sorted(issues,key=lambda i:i['category'] not in HARD)
