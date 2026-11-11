"""Signed pending edits, always anchored to the immutable original manuscript."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path


def support():
    path=Path(__file__).resolve().parents[1]/'story_support/story_support.py'
    spec=importlib.util.spec_from_file_location('pending_support',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def profile():
    here=Path(__file__).resolve().parents[1];resources=here.parent.parent
    scripts=[*sorted((here/'local_revision').glob('*.py')),*sorted((here/'prose_policy').glob('*.py'))]
    paths={str(Path('script-library/xs2')/p.relative_to(here)):p for p in scripts}
    spec=importlib.util.spec_from_file_location('pending_resources',here/'production_guard/production_guard.py')
    locator=importlib.util.module_from_spec(spec);spec.loader.exec_module(locator)
    configs={str(Path(name)):locator.resource(here,name) for name in ('prompts.json','workflows/polish/definition.json')}
    return hashlib.sha256(json.dumps({name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in {**paths,**configs}.items()},sort_keys=True).encode()).hexdigest()


def current(root,b,digest):
    s=support();store=s.archive_store();store.recover(root)
    relative=b['outputs']['revision_dir']+'/working.json';path=s.safe(root,relative)
    if not path.is_file() and not s.safe(root,'archive/longform.sqlite3').is_file():return None
    actual=path.read_text(encoding='utf8') if path.is_file() else None
    with closing(store.connect(root)) as db:
        rows=db.execute("SELECT content FROM publications WHERE status='complete' AND chapter='' AND instr(content,?)>0 ORDER BY rowid DESC",(relative,))
        expected=next((json.loads(r['content'])['outputs'][relative] for r in rows if relative in json.loads(r['content'])['outputs']),None)
    if actual is None and expected is None:return None
    if actual!=expected:raise ValueError('待验收工作稿与可信运行凭据不符')
    value=json.loads(actual)
    if value['binding_digest']!=digest(b) or value['profile']!=profile():raise ValueError('待验收工作稿的来源或版本变化，须重新核验')
    return value


def span(source,edit,patches):
    rows={r['id']:r for r in patches.paragraphs(source)};row=rows[edit['paragraph_id']];start=-1
    for _ in range(edit['occurrence']):start=row['text'].find(edit['old'],start+1)
    if start<0:raise ValueError('保留补丁来源不匹配')
    return row['start']+start,row['start']+start+len(edit['old'])


def merge(source,retained,proposed,patches):
    # Validate new proposals independently before resolving retained spans.
    patches.apply_patches(source,{'source_sha256':patches.digest(source),'edits':proposed})
    groups={edit['group_id'] for edit in retained if edit.get('group_id')}
    touched={span(source,e,patches) for e in proposed}
    for group in groups:
        required={span(source,e,patches) for e in retained if e.get('group_id')==group}
        if touched&required and not required<=touched:raise ValueError('原子补丁组必须完整更新，不能单独替换移动的一半')
    result=list(retained)
    for edit in proposed:
        a,z=span(source,edit,patches);updated=[]
        for old in result:
            x,y=span(source,old,patches)
            if (a,z)==(x,y):continue # Explicit exact-span replacement.
            if max(a,x)<min(z,y):raise ValueError('新增补丁与保留改动部分重叠，请按保留的完整old范围更新')
            updated.append(old)
        result=updated+[edit]
    return sorted(result,key=lambda e:span(source,e,patches))


def retain(root,b,source,context,raw,expanded,digest,patches):
    if expanded['compatible'] is not True or expanded['issues']:return
    effects={r['edit_index']:r['effect'] for r in expanded['change_reviews']}
    groups={e['group_id'] for e in context['edits'] if e.get('group_id')}
    blocked={g for g in groups if any(e.get('group_id')==g and effects[i]!='improved' for i,e in enumerate(context['edits']))}
    improved=[e for i,e in enumerate(context['edits']) if effects[i]=='improved' and e.get('group_id') not in blocked]
    if not improved:return
    previous=current(root,b,digest)
    edits=merge(source['source_body'],(previous or {}).get('edits',[]),improved,patches)
    body=patches.apply_patches(source['source_body'],{'source_sha256':b['body_sha256'],'edits':edits},protected_phrases=source['book_contract']['protected_phrases'])
    value={'schema':1,'status':'pending_full_acceptance','task_id':b['task_id'],'binding_digest':digest(b),'profile':profile(),
        'edits':edits,'candidate_sha256':patches.digest(body),'raw_review':raw,'review_input':context,
        'note':'未发布工作稿；不是已确认事实或整章通过凭据。所有原始目标与累计改动须重新整章验收。'}
    relative=b['outputs']['revision_dir']+'/working.json';s=support()
    s.archive_store().publish_views(root,lambda write:write(root,relative,value),lambda:{p:h or '' for p,h in b['files'].items()})
