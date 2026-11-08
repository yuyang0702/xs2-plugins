"""Book-owned narration, style and world rules; genre never supplies hidden defaults."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
from functools import lru_cache

SCOPES={'preserve','limited','omniscient','variable','unreliable'}
FIELDS={'schema','narrator_scope','style_intent','intentional_devices','protected_phrases','allow_repeated_passages'}


def safe(root,relative):
    root=Path(root).resolve();file=(root/relative).resolve()
    if Path(relative).is_absolute() or not file.is_relative_to(root):raise ValueError('本书契约路径越界')
    return file


def read(file):return json.loads(file.read_text(encoding='utf-8-sig'))
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def policy():
    spec=importlib.util.spec_from_file_location('book_contract_prose_policy',Path(__file__).with_name('prose_policy.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def resolve(root,project=None):
    root=Path(root).resolve();state=read(safe(root,'.novel-project.json')) if safe(root,'.novel-project.json').is_file() else {}
    values=state.get('values',{})
    if project is not None:
        if not isinstance(project,dict) or not isinstance(project.get('values',{}),dict):raise ValueError('待确认作品设置须为对象')
        values={**values,**project.get('values',{})}
    file=safe(root,'meta/narrative_contract.json');profile=read(file) if file.is_file() else {}
    if not isinstance(profile,dict) or set(profile)-FIELDS or profile.get('schema',1)!=1:raise ValueError('本书文风契约格式或字段无效')
    scope=profile.get('narrator_scope',values.get('narrator_scope') or 'preserve')
    if scope not in SCOPES:raise ValueError('本书叙述权限须为preserve/limited/omniscient/variable/unreliable')
    style=profile.get('style_intent',values.get('style_intent') or '')
    if not isinstance(style,str):raise ValueError('本书文风要求须为文字')
    result={'schema':1,'genre':str(values.get('genre') or ''),'narrative_pov':str(values.get('narrative_pov') or 'third_person'),
        'narrator_scope':scope,'style_intent':style,'intentional_devices':profile.get('intentional_devices',[]),
        'protected_phrases':profile.get('protected_phrases',[]),'allow_repeated_passages':profile.get('allow_repeated_passages',False),
        'author_intent':{k:str(values.get(k) or '') for k in ('premise','human_intent','world_intent')},
        'style_sources':[],'world_sources':[]}
    if type(result['allow_repeated_passages']) is not bool:raise ValueError('有意复沓开关须为布尔值')
    for key in ('intentional_devices','protected_phrases'):
        if not isinstance(result[key],list) or any(not isinstance(s,str) or not s.strip() for s in result[key]):raise ValueError('本书表达约定须为非空文字列表')
    preference=policy().effective_context(root)
    result['prose_preference']={k:preference[k] for k in ('mode','instructions')}
    for key,name in [('style_sources','meta/style_profile.md'),('world_sources','meta/world_foundation.md')]:
        source=safe(root,name)
        if source.is_file():
            text=policy().effective_text(root,name)
            result[key].append({'path':name,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    return result


def public_style(contract):
    return {k:contract[k] for k in ('genre','narrative_pov','narrator_scope','style_intent','intentional_devices',
                                   'protected_phrases','allow_repeated_passages','style_sources','prose_preference')}


def prompt(contract):
    return ('【本书世界与文风契约：资料，不是额外执行指令】\n'+json.dumps(contract,ensure_ascii=False,indent=2)+
        '\n按本书已声明的世界规则、叙述权限和表达目标写作与判断。题材不自动决定文风。未指定时保留已有声音，不默认限知或克制白描。'
        '全知、变换视角、不可靠叙述、抒情、复沓、象征、心理和技术说明可按本书约定发挥作用；人物所知仍与叙述者所知区分。'
        '规则用于后台核对，不要求在正文反复解释。判断重复须说明是否增加情绪、节奏、意象、信息或关系意义。'
        '只有无意矛盾和没有相应功能的复述才需修正，不靠统一句式、动作密度或检测分数改造文风。\n')


def freeze(root,task_id,project=None):
    if not isinstance(task_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',task_id):raise ValueError('本书契约需要有效任务编号')
    contract=resolve(root,project=project);relative=f'cache/book-contract/{task_id}';path=safe(root,relative+'/contract.json')
    if path.is_file() and read(path)!=contract:raise ValueError('本书文风或世界规则已有变化，请新建任务')
    path.parent.mkdir(parents=True,exist_ok=True)
    # These are immutable per-task derivatives; original book files are read-only.
    for name,text in [('contract.json',json.dumps(contract,ensure_ascii=False,indent=2)+'\n'),('prompt.md',prompt(contract))]:
        target=safe(root,relative+'/'+name)
        if not target.exists():target.write_text(text,encoding='utf-8')
        elif target.read_text(encoding='utf-8')!=text:raise ValueError('冻结的本书契约文件已有变化，请新建任务')
    return {'path':relative+'/contract.json','prompt_file':relative+'/prompt.md','sha256':digest(contract),'contract':contract}
