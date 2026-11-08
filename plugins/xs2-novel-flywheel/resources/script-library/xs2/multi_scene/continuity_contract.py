"""Source-grounded chapter facts, exact money arithmetic and observed event order."""
import hashlib
import json
import re
import importlib.util
from pathlib import Path
from decimal import Decimal
from fractions import Fraction

HARD=('money','facts','pov','handoff','resources')
_DIGITS=dict(zip('零〇一二两三四五六七八九', [0,0,1,2,2,3,4,5,6,7,8,9]))
_spec=importlib.util.spec_from_file_location('continuity_audit_evidence',Path(__file__).with_name('audit_evidence.py'))
audit_evidence=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(audit_evidence)


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


def _rows(rows,label):
    _require(isinstance(rows,list),label+'须为数组')
    result={}
    for row in rows:
        _require(isinstance(row,dict) and isinstance(row.get('id'),str) and row['id'].strip() and row['id'] not in result,label+'标识缺失或重复')
        result[row['id']]=row
    return result


def resource_contract(parent,row):
    return {'schema':1,'focus':parent['focus'],'facts':[],'events':parent['events'],
            **{k:row[k] for k in ('units','unit_equations','accounts','transfers')}}


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
        expected=amount(row['parts'],units)-(amount(row['change'],units) if row['change'] else 0)
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


def audit_issues(report,body,contract,phase):
    _require(phase in ('facts','expression') and isinstance(report,dict) and report.get('schema')==1,'核验报告格式无效')
    _require(report.get('candidate_sha256')==hashlib.sha256(body.encode()).hexdigest()
             and report.get('contract_sha256')==contract_digest(contract),'核验报告与当前候选或事实契约不匹配')
    report=audit_evidence.resolve_report(report,body,audit_evidence.unit_names(contract))
    categories=HARD+(('repetition',) if phase=='expression' else ())
    required=[k for k in categories if k!='resources' or contract.get('resource_ledgers')]
    _require(isinstance(report.get('checks'),dict) and all(report['checks'].get(k) is True for k in required),'核验报告未检查全部必需维度')
    issues=[]
    def issue(category,reason,quotes):
        issues.append({'category':category,'reason':reason,'excerpts':quotes,'goal':'按冻结契约修正实际正文，保持已成立的其他事实与情节边界'})
    def observed_amount(text,label):
        try:return amount(text,contract['units'])
        except ValueError as exc:raise ValueError(label+'：'+str(exc)+'；仅使用明确的数字数量，持有或状态描写另作语义核查。引文：'+text[:100]) from exc
    def observations(name,expected):
        actual=_rows(report.get(name),name);_require(set(actual)==set(expected),name+'遗漏或新增了约定核验项')
        return actual
    events=_rows(contract['events'],'事件');event_obs=observations('event_observations',events);positions={}
    for key,obs in event_obs.items():
        if obs.get('quote') is None:issue('handoff','缺少约定履行事件 '+key,[])
        else:positions[key]=located(obs['quote'],body)
    for key,row in events.items():
        for dep in row['after']:
            if key in positions and dep in positions:
                _require(max(positions[dep][0],positions[key][0])>=min(positions[dep][1],positions[key][1]),
                         '前后事件凭据重叠，请分别引用独立动作的最小分句，不能据宽引文断言正文反序')
            if key in positions and dep in positions and positions[dep][1]>positions[key][0]:
                issue('handoff',dep+' 必须先于 '+key,[event_obs[dep]['quote']['text'],event_obs[key]['quote']['text']])
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
        for obs in occurrences:
            located(obs.get('quote'),body);value=obs.get('value');_require(isinstance(value,str) and value.strip() and value in obs['quote']['text'],'标准值不能冒充实际引文中的名称')
            _require(type(obs.get('is_name',True)) is bool,'须区分专名使用与普通描述')
            if row.get('match_mode','name')=='referent' or not obs.get('is_name',True):
                _require(type(obs.get('same_referent')) is bool,'同物指代须经独立语义核对，不能把缺失视为通过')
                if not obs['same_referent']:issue('facts','共享物件或身份指向发生变化 '+key,[obs['quote']['text']])
            elif value not in [row['value'],*row['aliases']]:issue('facts','共享事实 '+key+' 发生变化：'+value,[obs['quote']['text']])
    ledgers=_rows(contract.get('resource_ledgers',[]),'分项资源账')
    resource_obs=observations('resource_observations',ledgers) if ledgers or 'resource_observations' in report else {}
    for key,ledger in ledgers.items():
        child=resource_contract(contract,ledger)
        child_report={**report,'contract_sha256':contract_digest(child),'fact_observations':[],'issues':[],
                      'money_observations':resource_obs[key].get('money_observations'),
                      'balance_observations':resource_obs[key].get('balance_observations')}
        child_report.pop('resource_observations',None)
        for found in audit_issues(child_report,body,child,phase):
            if found['category']=='money':
                issues.append({**found,'category':'resources','reason':key+'：'+found['reason']})
    semantic=report.get('issues');_require(isinstance(semantic,list),'语义问题须明确提供数组')
    for row in semantic:
        _require(isinstance(row,dict) and row.get('category') in categories
                 and all(isinstance(row.get(k),str) and row[k].strip() for k in ('reason','goal'))
                 and isinstance(row.get('excerpts'),list) and row['excerpts']
                 and all(isinstance(q,str) and q.strip() and q in body for q in row['excerpts']),'核验问题缺少当前正文原文与修订目标')
        issues.append(row)
    return sorted(issues,key=lambda i:i['category']=='repetition')
