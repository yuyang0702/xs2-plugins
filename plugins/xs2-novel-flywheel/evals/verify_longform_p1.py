"""Offline P1 verification: real manuscripts + clearly labelled distance fixtures.

Never regenerates prose or sends a book to an external model.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def hashes(root):return {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plugin-root',type=Path,required=True)
    parser.add_argument('--source-cases',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    source_before=hashes(args.source_cases)
    module=args.plugin_root/'resources/script-library/xs2/story_support/story_support.py'
    spec=importlib.util.spec_from_file_location('p1_eval_support',module)
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    actor_names={'ancient':'钟绫','romance':'程晏','apocalypse':'罗岑','scifi':'姜未','fantasy':'祝烬'}
    results=[]
    for name,actor in actor_names.items():
        book=args.output/name
        shutil.copytree(args.source_cases/name/'book',book)
        manuscript=book/'story/0001/chapter.md';before=sha(manuscript)
        contract=support.archive_store().contract(book)
        text=support.read(book,'story/0001/chapter.md')
        paragraphs=[line.strip() for line in text.splitlines() if len(line.strip())>=25]
        excerpt=paragraphs[len(paragraphs)//2][:20]
        alias='远距校验称呼'
        support.write(book,'meta/entity_registry.json',{'entities':[{'id':'fixture-actor','name':actor,'aliases':[alias]}]})
        os.environ['TASK_ID']='p1-copy-'+name
        support.begin_review(book,'0001')
        support.write(book,support.review_file('0001','observer.json'),{'confirmed_state':{'characters':[]}})
        support.write(book,support.review_file('0001','arbiter.json'),{'story_confirmed':{}})
        support.commit(book,'0001')
        # Valid legacy-shaped fixtures keep this a retrieval/propagation test,
        # rather than an expensive 200-chapter generation or P0 load benchmark.
        for number in range(2,201):
            chapter=f'{number:04d}';previous=f'story/{number-1:04d}/confirmed_state.json'
            body=f'离线检索距离测试填充资料 {number}；不属于新生成的小说。'
            support.write(book,f'story/{chapter}/chapter.md',body)
            state={'version':1,'chapter':chapter,'body_sha256':support.digest(book,f'story/{chapter}/chapter.md'),
                'source_hashes':{previous:support.digest(book,previous)},'characters':[],'world':{},
                'memory_dependencies':[]}
            if number==100:
                state['memory_dependencies']=[{'id':'fixture-use-of-original','source_id':'story/0001/chapter.md',
                    'source_sha256':before,'kind':'prose'}]
            support.write(book,f'story/{chapter}/confirmed_state.json',state)
        support.write(book,'planning/chapters/0201.json',{'chapter':'0201','goal':alias+'核对：'+excerpt,
            'source_hashes':{'story/0200/confirmed_state.json':support.digest(book,'story/0200/confirmed_state.json')}})
        started=time.monotonic()
        ctx=support.context(book,'0201')
        first_elapsed=time.monotonic()-started
        hit=next(h for h in ctx['memory']['hits'] if h['source_id']=='story/0001/chapter.md' and excerpt in h['text'])
        assert text[hit['start']:hit['end']]==hit['text'] and hit['source_sha256']==before
        assert ctx['memory']['entities'][0]['id']=='fixture-actor'
        assert ctx['memory']['entities'][0]['alias_boundary']=='author_only'
        assert ctx['memory']['cognition']['fixture-actor']['knowledge']==[]
        started=time.monotonic();second=support.context(book,'0201')
        repeated_elapsed=time.monotonic()-started
        assert second['memory']['index']['updated_documents']==0
        env=dict(os.environ,PYTHONIOENCODING='utf-8')
        actual=subprocess.run([sys.executable,str(module),'recall','--chapter','0201','--query',alias+' '+excerpt],
            cwd=book,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
        assert actual.returncode==0,actual.stderr
        recalled=json.loads(actual.stdout)
        assert any(h['source_id']=='story/0001/chapter.md' and excerpt in h['text'] for h in recalled['hits'])
        (book/'recall-result.json').write_text(actual.stdout,encoding='utf-8')
        revision=args.output/(name+'-revision')
        shutil.copytree(book,revision)
        support.write(revision,'story/0001/chapter.md',text+'\n\n[离线旧章变更故障注入，仅在修订测试副本中]\n')
        stale=support.memory().retrieve(revision,'0201',alias+' '+excerpt)
        assert not any(h['source_id']=='story/0001/chapter.md' for h in stale['hits'])
        report=support.memory().impact(revision)
        assert {f'{n:04d}' for n in range(1,201)} <= {c['chapter'] for c in report['chapters']}
        assert next(c for c in report['chapters'] if c['chapter']=='0100')['priority']=='retrieved_evidence_changed'
        assert '0201' in [p['chapter'] for p in report['plans']]
        gate=support.preflight(revision,'0201')
        assert not gate['ready'] and gate['reason_code']=='archive_stale'
        support.write(revision,'impact-verification.json',report)
        assert sha(manuscript)==before and support.archive_store().contract(book)==contract
        results.append({'book':name,'distance_chapters':200,'source_manuscript_unchanged':True,
            'book_contract_unchanged':True,'exact_excerpt_verified':True,'alias_resolved':True,
            'no_automatic_character_knowledge':True,'stale_hits_removed':True,
            'affected_chapters':len(report['chapters']),'affected_plan':'0201',
            'first_context_seconds':round(first_elapsed,3),'repeat_context_seconds':round(repeated_elapsed,3),
            'index_reused':True,'query':excerpt})
        print(json.dumps({'verified_book':name,'first_context_seconds':round(first_elapsed,3),
                          'repeat_context_seconds':round(repeated_elapsed,3)},ensure_ascii=False),flush=True)
    assert source_before==hashes(args.source_cases)
    result={'kind':'offline retrieval and impact fixtures, not generated novels or a quality evaluation',
        'source_files_checked':len(source_before),'source_files_unchanged':True,'books':results}
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
