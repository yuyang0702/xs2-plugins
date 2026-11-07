import asyncio
import json
from types import SimpleNamespace
import pytest
from test_length_quality import PLUGIN, policy, quality, write
from test_fragment_length import setup
from test_focused_length import definition


def actual_message(root, state, outputs):
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    raw=definition();wf=WorkflowDef.from_dict(raw);node=next(n for n in wf.nodes if n.id=='agent_pp')
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(state['values']);values.update(outputs)
    captured=[]
    class Manager:
        sessions={}
        async def create_sub_session(self,**kwargs):
            captured.append(kwargs);self.sessions['p']=SimpleNamespace(record=[{'type':'assistant','content':'{"body":"片段"}'}])
            kwargs['on_auto_complete']('p','done','success','');return {'success':True,'session_id':'p'}
    result=asyncio.run(AgentNode().execute(NodeContext(definition=wf,node_def=node,node_state=NodeExecutionState(node_id='agent_pp'),session_manager=Manager(),shared_ws=root,parameter_values=values)))
    assert result.status=='completed'
    return captured[0],node,values,wf


def test_focused_actual_user_message_is_isolated_and_has_body_once(tmp_path):
    state,_,raw=setup(tmp_path)
    body=raw.decode('utf-8-sig')
    shared='### meta/world_foundation.md\n已确认规则：不得伪造署名。\n### meta/character_profiles.md\n角色只知道看见的事。\n### story/0001/chapter.md\n'+body+'\n## 用户已采用的本章计划\n未来计划不能当事实。'
    write(tmp_path,'cache/story-support/context.md',shared)
    feedback='保留已经交付的事实。\n执行要求：按上述意见修改完整正文，不以计划代替正文；维护既定事实、人物、视角与本书风格。只处理本章，短篇收束全文，长篇普通章不提前完结全书。读者复评要检查修改是否落实，独立判断，不因采用方案而默认通过。\n'
    write(tmp_path,'quality/author.md',feedback)
    state.update(policy().next_action(tmp_path,state,'polish')['updates']);write(tmp_path,'.novel-project.json',json.dumps(state,ensure_ascii=False))
    outputs=quality().prepare_execution(tmp_path,'0001','130-160','length_only')
    call,node,values,wf=actual_message(tmp_path,state,outputs)
    prompt=call['task_description'];source=raw.decode('utf-8-sig').replace('\r\n','\n')
    assert prompt.count(source)==1
    assert '再润色完整正文' not in prompt and '完整修订正文' not in prompt and '修改完整正文' not in prompt
    assert '片段' in prompt and '保留已经交付的事实' in prompt and '不得伪造署名' in prompt
    assert '未来计划不能当事实' not in prompt
    assert call['agent_type']==node.agent_type


def test_normal_actual_user_message_remains_original_renderer(tmp_path):
    state,_,raw=setup(tmp_path);outputs=quality().prepare_execution(tmp_path,'0001','130-160','content')
    call,node,values,wf=actual_message(tmp_path,state,outputs)
    from src.workflow.variable_resolution import resolve_placeholders
    expected=asyncio.run(resolve_placeholders(node.first_message,values,wf.variables,str(tmp_path)))
    assert call['task_description']==expected
    assert outputs['length_execution_context']==''


def test_v3_initial_draft_contract_migrates_once_but_markerless_limit_does_not(tmp_path):
    write(tmp_path,'story/0001/chapter.md','衣'*3206)
    state={'readerRepairCount':0,'lengthRepairCycle':0,'lengthRepairCount':3,'lengthRepairTotal':3,'lengthRepairStrategy':'fragment-v3',
           'autoLengthRepairLimit':3,'values':{'chapter_number':'0001','target_word_count':'4800-5200'}}
    action=policy().next_action(tmp_path,state,'polish');assert action['action']=='advance';state.update(action['updates'])
    assert state['lengthRepairStrategy']==quality().LENGTH_REPAIR_STRATEGY=='fragment-v6' and state['lengthRepairTotal']==4
    for _ in range(2):state.update(policy().next_action(tmp_path,state,'polish')['updates'])
    assert policy().next_action(tmp_path,state,'polish')['stage']=='reader-sim'
    assert state['lengthRepairTotal']==6 and state['readerRepairCount']==0
    state.pop('lengthRepairStrategy')
    assert policy().next_action(tmp_path,state,'polish')['stage']=='reader-sim'
