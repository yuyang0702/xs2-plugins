"""Rebuildable, book-local retrieval and dependency diagnostics.

Only confirmed snapshots supply factual records. Prose excerpts remain prose,
author identity mappings remain backstage, and absence of a knowledge record
does not prove a character ignorant. No genre-specific rules or model calls.
"""
from contextlib import closing
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3


@lru_cache(maxsize=1)
def support():
    spec = importlib.util.spec_from_file_location('p1_story_support', Path(__file__).with_name('story_support.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_id(name):
    return 'character-' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:20]


def entities(root, characters=(), known_entities=()):
    s = support()
    registry = s.load(root, 'meta/entity_registry.json', {'entities':[]})
    if not isinstance(registry, dict) or not isinstance(registry.get('entities'), list):
        raise ValueError('人物身份登记必须包含 entities 列表')
    result = {item['id']:dict(item,aliases=list(item.get('aliases',[]))) for item in known_entities}
    registry_ids=set()
    for item in registry['entities']:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in ('id','name')):
            raise ValueError('人物身份登记缺少稳定编号或姓名')
        if item['id'] in registry_ids:
            raise ValueError('人物身份编号重复')
        registry_ids.add(item['id'])
        aliases = item.get('aliases', [])
        if not isinstance(aliases, list) or any(not isinstance(a,str) or not a.strip() for a in aliases):
            raise ValueError('人物别名必须是文字列表')
        result[item['id']] = {'id':item['id'], 'name':item['name'], 'aliases':list(dict.fromkeys([*result.get(item['id'],{}).get('aliases',[]),*aliases])), 'alias_boundary':'author_only'}
    for character in characters:
        key = character.get('entity_id') or stable_id(character['name'])
        # Registry canonical names can upgrade old name-keyed archives.
        matches = [e for e in result.values() if character['name'] in [e['name'],*e['aliases']]]
        if not character.get('entity_id') and len(matches) == 1:
            key = matches[0]['id']
        if key not in result:
            result[key] = {'id':key,'name':character['name'], 'aliases':[], 'alias_boundary':'author_only'}
        result[key]['aliases'] = list(dict.fromkeys([*result[key]['aliases'], *character.get('confirmed_aliases', [])]))
    return result


def alias_map(records):
    result = {}
    for key, item in records.items():
        for name in [item['name'], *item['aliases']]:
            result.setdefault(name, []).append(key)
    return {name:sorted(set(keys)) for name,keys in result.items()}


def canonicalize(root, previous, observed, rulings, body, known_entities=()):
    s = support()
    records = entities(root, previous, known_entities)
    if not isinstance(rulings, list):
        raise ValueError('身份仲裁必须是列表')
    for ruling in rulings:
        if not isinstance(ruling,dict) or ruling.get('verdict') not in ('adopt','pending'):
            raise ValueError('身份仲裁格式无效')
        if ruling['verdict'] != 'adopt':
            continue
        key = ruling.get('entity_id')
        if key not in records or not isinstance(ruling.get('aliases'),list):
            raise ValueError('别名归并必须指向已确认人物编号')
        quote = s.validated_evidence(ruling.get('evidence'),body,'人物别名缺少真实正文依据')
        text = ' '.join(quote) if isinstance(quote,list) else quote
        aliases = ruling['aliases']
        if any(not isinstance(a,str) or not a or a not in text for a in aliases) or records[key]['name'] not in text:
            raise ValueError('别名归并依据须保留姓名与别名，不能仅凭称呼相似归并')
        records[key]['aliases'] = list(dict.fromkeys([*records[key]['aliases'],*aliases]))
    mapping = alias_map(records)

    def resolve(item):
        name = item['name']
        candidates = mapping.get(name, [])
        key = item.get('entity_id')
        if not isinstance(name,str) or not name.strip():
            raise ValueError('人物姓名或别名无效')
        if key and key in records and key not in candidates:
            raise ValueError('人物编号与姓名/别名的已确认身份冲突')
        if not key:
            if len(candidates)>1:
                raise ValueError('人物别名指向多个身份，请明确 entity_id，不自动合并')
            key = candidates[0] if candidates else stable_id(name)
        if not isinstance(key,str) or not key.strip():
            raise ValueError('人物编号无效')
        if key not in records:
            records[key] = {'id':key,'name':name,'aliases':[],'alias_boundary':'author_only'}
        return {**item, 'entity_id':key, 'name':records[key]['name'], 'confirmed_aliases':records[key]['aliases']}

    return [resolve(item) for item in previous], [resolve(item) for item in observed], records


def validate_events(root, chapter, proposed, prior, records, body):
    if not isinstance(proposed,list):
        raise ValueError('认知与事实事件必须是列表')
    existing = {e['id']:e for state in prior for e in state.get('memory_events',[])}
    result = []
    for item in proposed:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'].strip() or item['id'] in existing:
            raise ValueError('记忆事件需要独立且不重复的编号')
        kind = item.get('kind')
        if kind not in ('fact','knowledge','belief','rumor') or not isinstance(item.get('text'),str) or not item['text'].strip():
            raise ValueError('记忆事件类型或内容无效；计划不能确认为已发生事实')
        item=dict(item)
        if kind in ('knowledge','belief','rumor') and item.get('holder') not in records:
            holders=alias_map(records).get(item.get('holder'),[])
            if len(holders)==1:item['holder']=holders[0]
        if kind in ('knowledge','belief','rumor') and (item.get('holder') not in records or not isinstance(item.get('acquisition'),str) or not item['acquisition'].strip()):
            raise ValueError('人物认知须指定已确认身份和获知/信念来源')
        old = item.get('supersedes')
        if old and (old not in existing or (existing[old]['kind']=='fact') != (kind=='fact') or existing[old].get('holder') != item.get('holder')):
            raise ValueError('记忆替代须指向同类型、同主体的已有事件')
        quote = support().validated_evidence(item.get('evidence'),body,'记忆事件缺少真实正文依据')
        if 'world_time_key' in item and type(item['world_time_key']) is not int:
            raise ValueError('可选世界时间序号须为整数；未指定时保留时间未知')
        value = {**item,'chapter':chapter,'evidence':quote}
        existing[value['id']] = value
        result.append(value)
    return result


def tokens(text):
    result = []
    for word in re.findall(r'[\u3400-\u9fff]+|[A-Za-z0-9_]+',text.lower()):
        result.extend(word[i:i+2] for i in range(len(word)-1)) if re.match(r'[\u3400-\u9fff]',word) else result.append(word)
    return list(dict.fromkeys(result))


def state_source(root,state):
    relative=f"story/{state['chapter']}/confirmed_state.json"
    raw=support().safe(root,relative).read_bytes()
    if json.loads(raw.decode('utf-8-sig'))!=state:
        raise ValueError('检索期间确认档案已有变化，与核验版本不一致')
    return {'source_id':relative,'source_sha256':hashlib.sha256(raw).hexdigest()}


def _initialize(db):
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, source TEXT, chapter TEXT, sha TEXT, payload TEXT, tokens TEXT)')
    if {row[1] for row in db.execute('PRAGMA table_info(documents)')} != {'id','source','chapter','sha','payload','tokens'}:
        db.close();raise sqlite3.DatabaseError('derived index schema mismatch')
    try:
        new = not db.execute("SELECT name FROM sqlite_master WHERE name='search'").fetchone()
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,tokens)')
        if new:db.execute('INSERT INTO search SELECT id,tokens FROM documents')
        fts = True
    except sqlite3.OperationalError:
        fts = False
    db.commit()
    return db, fts


def _open(target):
    db=sqlite3.connect(target,timeout=30)
    try:return _initialize(db)
    except Exception:
        db.close()
        raise


def connect(root):
    target = support().safe(root,'archive/memory-index.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        return _open(target)
    except sqlite3.DatabaseError:
        # This is a disposable cache, never the P0 canonical archive database.
        # Preserve a damaged file; read-only/locked workspaces can use RAM.
        try:
            stamp=hashlib.sha256(target.read_bytes()).hexdigest()[:16]
            backup=support().safe(root,f'archive/memory-index.corrupt-{stamp}.sqlite3')
            os.replace(target,backup)
            return _open(target)
        except (OSError,sqlite3.DatabaseError):
            return _open(':memory:')


def documents(root, states, before):
    s = support()
    for relative in ('meta/world_foundation.md','meta/character_profiles.md','meta/character_voice.md','meta/style_profile.md'):
        file=s.safe(root,relative)
        raw=file.read_bytes() if file.is_file() else b''
        text=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
        if s._prose_policy().effective_text(root,relative,text) != text:
            continue  # Superseded canonical drafts cannot bypass adopted prose rules.
        for start in range(0,len(text),880):
            yield {'id':relative+':'+str(start), 'source_id':relative, 'chapter':'', 'kind':'author_reference',
                   'source_sha256':hashlib.sha256(raw).hexdigest(), 'text':text[start:start+1000], 'start':start, 'end':min(start+1000,len(text))}
    for state in states:
        number = state['chapter']
        if int(number)>=int(before):
            continue
        relative = f'story/{number}/chapter.md'
        text = s.read(root,relative)
        for start in range(0,len(text),880):
            yield {'id':relative+':'+str(start), 'source_id':relative, 'chapter':number, 'kind':'prose',
                   'source_sha256':state['body_sha256'], 'text':text[start:start+1000], 'start':start, 'end':min(start+1000,len(text))}
        relative = f'story/{number}/confirmed_state.json'
        sha = state_source(root,state)['source_sha256']
        for event in state.get('memory_events',[]):
            yield {'id':relative+':event:'+event['id'], 'source_id':relative, 'source_sha256':sha, 'chapter':number,
                   'kind':event['kind'],'text':event['text'],'event':event}
        for i,fact in enumerate(state.get('world',{}).get('facts',[])):
            if fact.get('source_chapter') == number:
                yield {'id':relative+':fact:'+str(i), 'source_id':relative, 'source_sha256':sha, 'chapter':number,
                       'kind':'confirmed_world_fact','text':fact['description'], 'evidence':fact.get('evidence')}


def _index(db, fts, items):
    seen = set()
    updated = 0
    for item in items:
        key = item['id']; seen.add(key)
        payload = json.dumps(item,ensure_ascii=False,sort_keys=True)
        row = db.execute('SELECT payload FROM documents WHERE id=?',(key,)).fetchone()
        if row and row['payload'] == payload:
            continue
        words = ' '.join(tokens(item['text']))
        db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)',
                   (key,item['source_id'],item['chapter'],item['source_sha256'],payload,words))
        if fts:
            db.execute('DELETE FROM search WHERE id=?',(key,))
            db.execute('INSERT INTO search VALUES(?,?)',(key,words))
        updated += 1
    for row in db.execute('SELECT id FROM documents').fetchall():
        if row['id'] not in seen:
            db.execute('DELETE FROM documents WHERE id=?',(row['id'],))
            if fts:db.execute('DELETE FROM search WHERE id=?',(row['id'],))
            updated += 1
    return updated


def retrieve(root, chapter, question='', *, states=None, budget=12000, outline_text=None):
    s = support(); chapter = s.chapter_id(chapter)
    if type(budget) is not int or budget<1:raise ValueError('检索预算须为正整数')
    if states is None:
        s.archive_store().recover(root)
        states,_ = s.confirmed(root,before=int(chapter))
    states = [state for state in states if int(state['chapter'])<int(chapter)]
    latest = states[-1] if states else {}
    registry_sha=s.digest(root,'meta/entity_registry.json')
    records = entities(root,latest.get('characters',[]),latest.get('entities',[]))
    if outline_text is None:
        outline_text=s.chapter_outline(root,chapter,s._prose_policy().effective_text(root,'outline/near_term_outline.md',s.read(root,'outline/near_term_outline.md')))
    query = question + '\n' + outline_text
    mapping = alias_map(records)
    matched = {name:ids for name,ids in mapping.items() if name in query}
    active = {ids[0] for ids in matched.values() if len(ids)==1}
    aliases = [name for key in active for name in [records[key]['name'],*records[key]['aliases']]]
    time_source=f'@memory/scene-time/{chapter}'
    time_sha=s.digest(root,time_source)
    scene_time = s.load(root,f'story/{chapter}/planned_world_state.json',{}).get('world_time_key')
    if scene_time is not None and type(scene_time) is not int:
        raise ValueError('场景世界时间序号须为整数，或省略使用叙事顺序')
    query_terms=tokens(' '.join(aliases)+' '+query)
    terms = query_terms[:128]
    db,fts = connect(root)
    with closing(db), db:
        db.execute('BEGIN IMMEDIATE')
        updated = _index(db,fts,documents(root,states,chapter))
        if terms and fts:
            expression = ' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
            rows = db.execute('SELECT d.payload FROM search JOIN documents d ON d.id=search.id WHERE search MATCH ? ORDER BY bm25(search), d.chapter, d.id LIMIT 96',(expression,)).fetchall()
        elif terms:
            expression = '+'.join('CASE WHEN instr(tokens,?)>0 THEN 1 ELSE 0 END' for _ in terms)
            rows = db.execute(f'SELECT payload,({expression}) AS score FROM documents WHERE ({expression})>0 ORDER BY score DESC,chapter,id LIMIT 96',terms+terms).fetchall()
        else:rows=[]
    all_events=[event for state in states for event in state.get('memory_events',[])]
    event_sources={event['id']:{'event':event, **state_source(root,state)}
        for state in states for event in state.get('memory_events',[])}
    def status(event):
        if scene_time is None:return 'active'
        if 'world_time_key' not in event:return 'time_unverified'
        return 'active' if event['world_time_key']<=scene_time else 'outside_scene_time'
    eligible=[e for e in all_events if status(e)=='active']
    replaced={e['supersedes'] for e in eligible if e.get('supersedes')}
    replacements={}
    for event in eligible:
        if event.get('supersedes'):replacements.setdefault(event['supersedes'],[]).append(event_sources[event['id']])
    hits=[];used=0;rejected=[]; dependencies={}
    def depend(source,kind,identity):
        relative=source['source_id']; sha=source['source_sha256']
        if s.digest(root,relative)!=sha:
            raise ValueError('检索期间认知或身份来源已有变化，请重新准备上下文')
        dependencies[(relative,sha)]={'id':identity,'source_id':relative,'source_sha256':sha,'kind':kind}
    for row in rows:
        item=json.loads(row['payload'])
        if s.digest(root,item['source_id']) != item['source_sha256']:
            rejected.append(item['id']);continue
        if item.get('event'):
            event=item['event']
            item['event_status']='superseded' if event['id'] in replaced else status(event)
            chain=[];todo=[event['id']];seen=set()
            while todo:
                old=todo.pop()
                for replacement in replacements.get(old,[]):
                    key=replacement['event']['id']
                    if key in seen:continue
                    seen.add(key);chain.append(replacement);todo.append(key)
            item['replacements']=chain
            for replacement in chain:depend(replacement,'replacement_event',replacement['event']['id'])
        elif scene_time is not None and item['kind']=='confirmed_world_fact':
            item['event_status']='time_unverified'
        size=len(json.dumps(item,ensure_ascii=False))
        if used+size>budget:continue
        used+=size;hits.append(item);depend(item,item['kind'],item['id'])
    cognition={key:{'knowledge':[], 'beliefs':[], 'rumors':[], 'time_unverified':[], 'provenance':'未记录不代表确定不知；不得将作者资料直接当作人物所知'} for key in sorted(active)}
    for event in all_events:
        if event.get('holder') in cognition:
            depend(event_sources[event['id']],'cognition_state',event['id'])
        if event['id'] in replaced or event.get('holder') not in cognition:continue
        if status(event)=='outside_scene_time':continue
        if status(event)=='time_unverified':
            cognition[event['holder']]['time_unverified'].append(event);continue
        field={'knowledge':'knowledge','belief':'beliefs','rumor':'rumors'}.get(event['kind'])
        if field:cognition[event['holder']][field].append(event)
    if latest:
        source=state_source(root,latest)
        depend(source,'character_world_state',source['source_id'])
    if s.digest(root,'meta/entity_registry.json')!=registry_sha:
        raise ValueError('检索期间身份目录已有变化，请重新准备上下文')
    if registry_sha:
        depend({'source_id':'meta/entity_registry.json','source_sha256':registry_sha},'author_identity_registry','entity_registry')
    depend({'source_id':time_source,'source_sha256':time_sha},'scene_time_input',time_source)
    dependencies[(time_source,time_sha)].update(physical_source=f'story/{chapter}/planned_world_state.json',
        selector='world_time_key',hash_mode='selected-json-value')
    return {'schema':1, 'query':query, 'hits':hits, 'entities':[records[k] for k in sorted(active)],
            'scene_time_key':scene_time, 'temporal_boundary':'按明确世界时间核对；时间未知的获知记录不能直接确认为本场景已知' if scene_time is not None else '仅有叙事先后；跨时序场景需另核对世界时间，不能自动沿用上一叙事位置的全部状态',
            'ambiguities':{name:ids for name,ids in matched.items() if len(ids)>1}, 'cognition':cognition,
            'read_set':list(dependencies.values()),
            'index':{'backend':'fts5-bigrams' if fts else 'lexical-fallback','updated_documents':updated},
            'omitted_hits':len(rows)-len(hits), 'rejected_stale_hits':rejected, 'budget':budget,
            'omitted_query_terms':max(0,len(query_terms)-len(terms)),
            'boundary':'原文摘录不自动成为客观事实；作者别名映射不是人物已知。事实、获知、误信和传言分别使用，遵守本书叙述权限。'}


def impact(root, *, states=None, stale=None, replacements=None):
    s=support(); root=Path(root); replacements=replacements or {}
    if states is None:states,stale=s.confirmed(root)
    stale=set(stale or [])
    overrides={f'story/{n}/confirmed_state.json':hashlib.sha256((json.dumps(v,ensure_ascii=False,indent=2).rstrip()+'\n').encode()).hexdigest() for n,v in replacements.items()}
    def changed(hashes):
        return sorted(p for p,h in hashes.items() if not p.startswith('cache/') and overrides.get(p,s.digest(root,p))!=h)
    chapters=[];plans=[]; records={}; invalid={}
    for p in sorted((root/'story').glob('[0-9][0-9][0-9][0-9]/confirmed_state.json')):
        number=p.parent.name
        try:
            value=replacements.get(number) or s.load(root,p.relative_to(root).as_posix(),{})
            if not isinstance(value,dict) or not isinstance(value.get('source_hashes',{}),dict):
                raise ValueError('格式无效')
        except (ValueError,OSError):
            invalid[number]=['确认档案格式无效'];records[number]={};continue
        records[number]=value
        reasons=changed(value.get('source_hashes',{}))
        body=f'story/{number}/chapter.md'
        if s.digest(root,body)!=value.get('body_sha256'):reasons.insert(0,body)
        if number not in replacements and (number in stale or reasons):invalid[number]=reasons
    # A dependency can be semantically stale even before its bytes are rebuilt.
    again=True
    while again:
        again=False
        for number,value in records.items():
            if number in replacements:continue
            reads=[r for r in value.get('memory_dependencies',[]) if isinstance(r,dict)]
            dependencies=list(value.get('source_hashes',{}))+[r.get('source_id','') for r in reads]
            inherited=[p for p in dependencies if (m:=re.match(r'story/([0-9]{4})/',p)) and m[1] in invalid and m[1]!=number]
            if inherited:
                reasons=sorted(set(invalid.get(number,[])+inherited))
                if number not in invalid:again=True
                invalid[number]=reasons
    for number,reasons in sorted(invalid.items()):
        reads=[r for r in records[number].get('memory_dependencies',[]) if isinstance(r,dict)]
        direct=[r for r in reads if r.get('source_id') in reasons]
        chapters.append({'chapter':number,'status':'needs_archive_review','changed_sources':reasons,
            'priority':'retrieved_evidence_changed' if direct else 'conservative_dependency_review',
            'retrieval_dependencies':direct, 'next_action':'复核原文因果与认知，再重新归档；不自动改写后文'})
    for p in sorted((root/'planning/chapters').glob('*.json')):
        try:
            value=s.load(root,p.relative_to(root).as_posix(),{})
            dependencies=value.get('source_hashes',{})
            reasons=changed(dependencies)
            reasons+= [p for p in dependencies if (m:=re.match(r'story/([0-9]{4})/',p)) and m[1] in invalid]
        except (ValueError,OSError,AttributeError):reasons=['计划格式无效']
        if reasons:plans.append({'chapter':p.stem,'changed_sources':reasons,'next_action':'重新核对并采用计划'})
    return {'schema':1,'chapters':chapters,'plans':plans,'automatic_prose_edits':False,
            'boundary':'优先复核排序不是其他章节无影响的证明；未知隐含依赖继续使用保守失效检查。'}
