import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_book_contract import helper,put,PLUGIN
from test_quick_adoption import service


def test_pending_advisor_settings_use_effective_contract_without_writing_archives(tmp_path):
    put(tmp_path,'.novel-project.json',{'values':{'genre':'旧题材','narrator_scope':'limited'}})
    pending={'mode':'short','values':{'genre':'科幻','narrator_scope':'omniscient','style_intent':'允许技术说明'}}
    original=copy.deepcopy(pending)
    contract=helper().resolve(tmp_path,project=pending)
    assert contract['genre']=='科幻' and contract['narrator_scope']=='omniscient'
    assert pending==original and not (tmp_path/'meta').exists()
    assert json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf-8'))['values']['genre']=='旧题材'


def test_advisor_receives_json_overrides_and_protected_devices(tmp_path):
    put(tmp_path,'meta/narrative_contract.json',{'schema':1,'narrator_scope':'variable',
        'style_intent':'独有的树木独白','protected_phrases':['潮水会回来。'],'intentional_devices':['有意回环']})
    jobs=service().create_assistant(lambda **_:None,lambda **_:None)
    system,user,*_=jobs._general_messages(tmp_path,'q',{'purpose':'advisor','question':'怎样规划？',
        'project':{'values':{'narrator_scope':'limited','style_intent':'旧值'}}})
    c=json.loads(user.split('参考上下文：\n',1)[1])['本书规则契约']
    assert c['narrator_scope']=='variable' and c['protected_phrases']==['潮水会回来。']
    assert '独有的树木独白' in c['style_intent'] and '本书规则契约' in system


def test_advisor_uses_author_brief_and_existing_planning_without_assuming_ending(tmp_path):
    put(tmp_path,'meta/character_profiles.md','舟子拒绝替兄长作证。')
    put(tmp_path,'meta/story_plan.md','主线从渡口失约开始。')
    jobs=service().create_assistant(lambda **_:None,lambda **_:None)
    system,user,*_=jobs._general_messages(tmp_path,'q',{'purpose':'advisor','question':'补一下规划',
        'project':{'advisor_brief':'终局保留开放结尾。','values':{'premise':'渡口失约'}}})
    basis=json.loads(user.split('参考上下文：\n',1)[1])['规划依据']
    assert basis['作者简报']=='终局保留开放结尾。'
    assert basis['已备资料']=={'人物':'meta/character_profiles.md','结构':'meta/story_plan.md'}
    assert '终局' not in basis['已备资料']
    assert '只补' in system


def test_advisor_cannot_publish_advice_after_world_changes_during_model_call(tmp_path):
    put(tmp_path,'meta/world_foundation.md','不能让记忆恢复。')
    class Model:
        async def ainvoke(self,messages):
            put(tmp_path,'meta/world_foundation.md','作者已经改成可恢复。')
            return SimpleNamespace(content=json.dumps({'reply':'建议献忆。','suggestions':[],
                'advisor_sections':{'direction':'方向','hook':'看点','writing':'写法','risks':'风险'}}))
        async def aclose(self):pass
    jobs=service().create_assistant(lambda **_:Model(),lambda **_:None)
    async def run():
        jobs.start(tmp_path,'rule-drift',{'purpose':'advisor','question':'怎样规划？','project':{'values':{}}})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.history(tmp_path)[0]
    result=asyncio.run(run())
    assert result['status']=='failed' and result['error_code']=='book_contract_changed'
    assert not result.get('suggestions')


def test_standalone_advisor_prepares_contract_without_a_chapter(tmp_path):
    d=json.loads((PLUGIN/'resources/workflows/novel-advisor/definition.json').read_text(encoding='utf-8'))
    assert any(n['id']=='script_advisor_contract' for n in d['nodes'])
    cli=PLUGIN/'resources/script-library/xs2/book_context/book_context.py'
    result=subprocess.run([sys.executable,str(cli),'prepare','--genre','玄幻','--narrator-scope','variable',
        '--style-intent','华丽独白'],cwd=tmp_path,env={**os.environ,'TASK_ID':'advisor-fresh'},capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    contract=json.loads((tmp_path/'cache/book-contract/advisor-fresh/contract.json').read_text(encoding='utf-8'))
    assert contract['narrator_scope']=='variable' and contract['style_intent']=='华丽独白'
    assert not (tmp_path/'.novel-project.json').exists() and not (tmp_path/'story').exists()


@pytest.mark.parametrize('changed',[False,True])
def test_standalone_advice_is_published_only_for_the_same_effective_rules(tmp_path,changed):
    cli=PLUGIN/'resources/script-library/xs2/book_context/book_context.py'
    env={**os.environ,'TASK_ID':'advisor-publication'}
    put(tmp_path,'meta/world_foundation.md','技术有不可逆代价。')
    result=subprocess.run([sys.executable,str(cli),'prepare'],cwd=tmp_path,env=env,capture_output=True)
    assert result.returncode==0
    draft='cache/book-contract/advisor-publication/advisor-report.json'
    report={'direction':'按不可逆代价规划。'};put(tmp_path,draft,report)
    put(tmp_path,'learning/advisor_report.json',{'direction':'旧建议'})
    if changed:put(tmp_path,'meta/world_foundation.md','代价可以恢复。')
    result=subprocess.run([sys.executable,str(cli),'commit'],cwd=tmp_path,env=env,
        input=json.dumps(report),capture_output=True,text=True,encoding='utf8')
    assert (result.returncode!=0)==changed
    current=json.loads((tmp_path/'learning/advisor_report.json').read_text(encoding='utf8'))
    assert current==({'direction':'旧建议'} if changed else report)


@pytest.mark.parametrize('target',['1-5000',''])
def test_standalone_adviser_freezes_requested_length_and_scope_without_genre_defaults(tmp_path,target):
    cli=PLUGIN/'resources/script-library/xs2/book_context/book_context.py'
    env={**os.environ,'TASK_ID':'advisor-budget'}
    put(tmp_path,'.novel-project.json',{'mode':'short','values':{'target_word_count':'1-5000'}})
    result=subprocess.run([sys.executable,str(cli),'prepare','--target',target,'--scope','short_full'],cwd=tmp_path,env=env,capture_output=True,text=True,encoding='utf8')
    assert result.returncode==0,result.stderr
    text=(tmp_path/'cache/book-contract/advisor-budget/constraints.md').read_text(encoding='utf8')
    assert '1-5000' in text and 'short_full' in text
    report={'pov':'按本书规则。'};put(tmp_path,'cache/book-contract/advisor-budget/advisor-report.json',report)
    put(tmp_path,'.novel-project.json',{'mode':'short','values':{'target_word_count':'1-3000'}})
    result=subprocess.run([sys.executable,str(cli),'commit'],cwd=tmp_path,env=env,input=json.dumps(report),capture_output=True,text=True,encoding='utf8')
    assert result.returncode!=0 and not (tmp_path/'learning/advisor_report.json').exists()
