import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_focused_length import definition
from test_reader_output_contract import definition as reader_definition


def execute(root, node_id, content):
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    wf=WorkflowDef.from_dict(definition());node=next(n for n in wf.nodes if n.id==node_id)
    class Manager:
        sessions={}
        async def create_sub_session(self,**kwargs):
            self.sessions['body']=SimpleNamespace(record=[{'type':'user','content':'write'}, {'type':'assistant','content':content}])
            kwargs['on_auto_complete']('body','done','success','');return {'success':True,'session_id':'body'}
    return asyncio.run(AgentNode().execute(NodeContext(definition=wf,node_def=node,node_state=NodeExecutionState(node_id=node_id),session_manager=Manager(),shared_ws=root,parameter_values={'chapter_number':'0001','length_execution_context':''})))


def test_only_polish_pl_pp_opt_into_single_body_envelope():
    nodes=definition()['nodes']
    assert definition()['version']>=15
    assert {n['id'] for n in nodes if n.get('node_params',{}).get('json_single_string_field')}=={'agent_pl','agent_pp'}
    for n in nodes:
        if n['id'] in ('agent_pl','agent_pp'):assert n['node_params']['json_single_string_field']=='body'
    assert all('json_single_string_field' not in n.get('node_params',{}) for n in reader_definition()['nodes'])


def test_single_writer_uses_same_body_envelope_without_changing_planning_nodes(tmp_path, monkeypatch):
    resource=Path(__file__).resolve().parents[1]/'resources/workflows/mvp/definition.json'
    doc=json.loads(resource.read_text(encoding='utf-8'))
    assert doc['version']>=10
    assert {n['id'] for n in doc['nodes'] if n.get('node_params',{}).get('json_single_string_field')}=={'agent_sw'}
    monkeypatch.setitem(execute.__globals__,'definition',lambda:doc)
    body='她问:"这是谁的春幡？"\n"我的。"'
    result=execute(tmp_path,'agent_sw','{"body":"'+body+'"}')
    assert result.status=='completed',result.error
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']==body


@pytest.mark.parametrize('node_id',['agent_pl','agent_pp'])
def test_real_workflow_preserves_malformed_body_characters_exactly(tmp_path,node_id):
    # Exact observed failure shape: ordinary ASCII dialogue quotes inside body.
    body='她开口问:"这幅春幡多少钱?"\n沈照棠摸着"沈照棠制"的署名。'
    malformed='```json\n{"body":"'+body+'"}\n```'
    result=execute(tmp_path,node_id,malformed)
    assert result.status=='completed',result.error
    node=next(n for n in definition()['nodes'] if n['id']==node_id)
    target=node['output_file_path'].replace('{{chapter_number}}','0001')
    assert json.loads((tmp_path/target).read_text(encoding='utf-8'))['body']==body


@pytest.mark.parametrize('sid',['0b8aa649','b6ffc1c5'])
def test_actual_captured_response_replays_without_prose_rewrite(tmp_path,sid):
    source=Path('C:/xs2/DeterminFlow/data/sessions')/(sid+'.json')
    if not source.exists():pytest.skip('local acceptance capture unavailable')
    session=json.loads(source.read_text(encoding='utf-8'))
    text=next(m['content'] for m in session['record'] if m.get('type')=='assistant' and m.get('content'))
    result=execute(tmp_path,'agent_pp',text)
    assert result.status=='completed',result.error
    # Decoder removes the envelope, escaping changes no prose characters.
    bare=text.strip().removeprefix('```json').removesuffix('```').strip()
    raw_body=bare[len('{"body":"'):-2]
    expected=raw_body.replace('\\n','\n').replace('\\r','\r').replace('\\t','\t')
    assert json.loads((tmp_path/'cache/pp/body.json').read_text(encoding='utf-8'))['body']==expected


@pytest.mark.parametrize('content', ['{"body":"一段"}{"body":"另一段"}', '{"body":"他说:"你好"","status":"success"}', '{"body":"甲","body":"乙"}'])
def test_ambiguous_envelopes_never_publish_even_with_opt_in(tmp_path,content):
    target=tmp_path/'cache/pp/body.json'
    target.parent.mkdir(parents=True);target.write_text('existing candidate',encoding='utf-8')
    result=execute(tmp_path,'agent_pp',content)
    assert result.status=='failed'
    assert target.read_text(encoding='utf-8')=='existing candidate'
