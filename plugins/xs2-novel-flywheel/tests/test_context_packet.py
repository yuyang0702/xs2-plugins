import importlib.util
import json
import shutil
import subprocess
import sys
import pytest
from test_book_contract import PLUGIN


@pytest.mark.parametrize('node_id',['agent_blind_reader','agent_context_reader','agent_reader'])
def test_all_reader_roles_use_verified_full_prose_view_instead_of_duplicate_catalog(node_id):
    from src.workflow.definition import WorkflowDef
    definition=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8-sig'))
    assert not WorkflowDef.from_dict(definition).validate()
    node=next(n for n in definition['nodes'] if n['id']==node_id)
    assert '{{reader_blind_model}}' in node['first_message']
    assert '{{reader_blind_input}}' not in node['first_message']
    assert '【无损输入视图】' in node['first_message']
    if node_id!='agent_blind_reader':
        assert '{{book_contract_file}}' in node['first_message']
        assert '{{reader_revision_context}}' in node['first_message']
        assert '{{story_support_context}}' in node['first_message']


@pytest.mark.parametrize('tool_name',['wire_performance_p0.py','wire_performance_p1.py'])
def test_resource_wiring_is_idempotent(tmp_path,tool_name):
    target=tmp_path/'plugin'
    shutil.copytree(PLUGIN,target,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','vendor','data'))
    tool=target/'tools'/tool_name
    subprocess.run([sys.executable,str(tool)],check=True,capture_output=True)
    paths=[target/'resources/prompts.json',*[target/f'resources/workflows/{s}/definition.json' for s in ('mvp','polish','reader-sim')]]
    first={str(p):p.read_bytes() for p in paths}
    subprocess.run([sys.executable,str(tool)],check=True,capture_output=True)
    assert {str(p):p.read_bytes() for p in paths}==first


def module():
    path=PLUGIN/'resources/script-library/xs2/prose_policy/context_packet.py'
    assert path.is_file(),'Missing lossless model context projection'
    spec=importlib.util.spec_from_file_location('context_packet_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.mark.parametrize('body',['','  ','\ufeff第一段。\r\n\r\n第二段。\r\n',
    '  雨\n    落\n\n   没有固定句式。\n\n','{"第一层": "第二层"}\n\nABC 123 🐦\n'])
def test_lossless_projection_preserves_all_prose_and_whitespace(body):
    p=module();view=p.prose(body)
    assert p.restore(view)==body
    assert [r['id'] for r in view['paragraphs']]==[f'p{i+1:04d}' for i in range(len(view['paragraphs']))]


def test_projection_removes_duplicates_but_keeps_full_contract_and_sources():
    p=module();text='长段内容。'*100
    data={'source_body':text,'paragraphs':[{'id':'p0001','text':text}], 'candidate':text+'改。',
        'evidence_catalog':[{'id':'p0001','text':text+'改。'},{'id':'c0001','text':text+'改。'}],
        'book_contract':{'genre':'任意','style_intent':'允许复沓、全知、技术与抒情'},'confirmed_context':'远距离事实。',
        'author_feedback':'作者只改此处。','goals':[{'id':'g','goal':'保留语言探索。'}]}
    before=json.dumps(data,ensure_ascii=False);view=p.local(data,'reviewer')
    assert p.restore(view['source_body'])==text and p.restore(view['candidate'])==data['candidate']
    assert view['book_contract']==data['book_contract'] and view['confirmed_context']==data['confirmed_context']
    assert view['author_feedback']==data['author_feedback'] and view['goals']==data['goals']
    assert 'paragraphs' not in view and 'evidence_catalog' not in view
    assert len(json.dumps(view,ensure_ascii=False))<len(before)
    assert data['source_body']==text and 'evidence_catalog' in data


def test_writer_gets_one_manuscript_and_only_current_goals_linked_to_exact_paragraphs():
    p=module();body='雨停了。\r\n\r\n她把门推开。\r\n\r\n雨停了。'; book={'narrator_scope':'limited'}
    data={'writer_view_version':2,'source_body':body,'source_sha256':'bound', 'book_contract':book,
          'author_feedback':'只合并重复交代。','writer_references':{'meta/character_voice_adaptations.md':'保留短句。'},
          'confirmed_context':body,'reader_report':{'summary':'旧报告全文'},'critique':{'issues':[]},
          'prior_revision':{'candidate':body},'composition_plan':{'review':{'reason':'旧规划复查'}},
          'goals':[{'id':'g','goal':'合并重复。','excerpts':['雨停了。','雨停了。\n\n她把门推开。','过期稿引文。']}]}
    view=p.local(data,'writer')
    assert p.restore(view['source_body'])==body and view['book_contract']==book
    assert view['author_feedback']==data['author_feedback'] and view['writer_references']==data['writer_references']
    assert view['goals']==[{'id':'g','goal':'合并重复。','paragraph_ids':['p0001','p0002','p0003']}]
    assert not {'confirmed_context','reader_report','critique','prior_revision','composition_plan'}&view.keys()
    assert '过期稿引文。' not in json.dumps(view,ensure_ascii=False)
    p.verify(view,data,'writer')


def test_reviewer_shares_unchanged_paragraphs_and_context_with_full_reports():
    p=module()
    opening='【只传一次的开场】'*60
    world='【世界规则】'*60
    source=f'\ufeff{opening}\r\n\r\n删掉这段。\r\n\r\n尾声。\r\n\r\n重复。\r\n\r\n重复。\r\n'
    candidate=f'\ufeff{opening}\r\n\r\n尾声。\r\n\r\n重复。\r\n\r\n重复。\r\n'
    context='正文存档\n'+source.replace('\r\n','\n')+'\n故事规则\n'+world+'\n独有事实。'
    data={'writer_view_version':2,'reviewer_view_version':1,'source_body':source,'candidate':candidate,
          'confirmed_context':context,'book_contract':{'world_sources':[{'text':world}]},
          'reader_report':{'blind_review':{'summary':'完整报告','evidence':['保留所有报告字段。']}},
          'critique':{'issues':[{'description':'自审全文。'}]}}
    view=p.local(data,'reviewer')
    assert view['candidate']==p.prose(candidate)
    assert p.restore(view['source_body'],view['candidate'])==source
    assert p.restore_review_context(view)==context
    assert view['reader_report']==data['reader_report'] and view['critique']==data['critique']
    serialized=json.dumps(view,ensure_ascii=False)
    assert serialized.count(opening)==serialized.count(world)==1
    p.verify(view,data,'reviewer')


def test_critic_shares_exact_context_text_without_losing_the_reader_report():
    p=module();source=('一段原文。'*40)+'\r\n\r\n最后一句。'
    context='冻结上下文\n'+source.replace('\r\n','\n')+'\n剩余上下文'
    data={'critic_view_version':1,'source_body':source,'confirmed_context':context,'reader_report':{'summary':'完整报告'}}
    view=p.local(data,'critic')
    assert p.restore(view['source_body'])==source
    assert p.restore_review_context(view)==context and view['reader_report']==data['reader_report']
    assert json.dumps(view,ensure_ascii=False).count('一段原文。'*40)==1
    p.verify(view,data,'critic')


def test_reviewer_compacts_paragraph_labels_and_whitespace_without_changing_evidence_ids():
    p=module()
    source='\ufeff开场。\r\n\r\n下一段。\n\n \r\n原句。'+('\r\n\r\n保留。'*10)+'\r\n'
    candidate=source.replace('原句。','新句。')
    data={'reviewer_view_version':2,'source_body':source,'candidate':candidate,
          'confirmed_context':'正文：'+source,'reader_report':{'summary':'完整原报告'}}
    view=p.local(data,'reviewer')
    assert view['candidate']['paragraphs']['p0003']=='新句。'
    assert view['candidate']['before_overrides']['p0003']=='\n\n \r\n'
    assert p.restore(view['candidate'])==candidate
    assert p.restore(view['source_body'],view['candidate'])==source
    assert p.restore_review_context(view)==data['confirmed_context']
    assert view['reader_report']==data['reader_report']
    assert len(json.dumps(view['candidate'],ensure_ascii=False,separators=(',',':')))<len(
        json.dumps(p.prose(candidate),ensure_ascii=False,separators=(',',':')))
    p.verify(view,data,'reviewer')


def test_blind_projection_preserves_allowlist_and_cannot_inject_hidden_author_data():
    p=module();data={'manuscript':'雪\n\n停了。','style_contract':{'narrator_scope':'unreliable'},'genre':'幻想',
        'evidence_catalog':[{'id':'p0001','text':'雪'}]}
    view=p.blind(data)
    assert p.restore(view['manuscript'])==data['manuscript'] and view['style_contract']==data['style_contract']
    assert 'author_feedback' not in view and 'evidence_catalog' not in view


@pytest.mark.parametrize('role',['source','editor','review'])
def test_actual_local_pipeline_binds_model_view_to_full_inputs_and_rejects_tamper(tmp_path,role):
    from test_local_revision import setup,patch,approved,BODY
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    paths={'source':'revision_source_model','editor':'revision_editor_model','review':'revision_review_model'}
    view_path=tmp_path/out[paths[role]]
    data=json.loads(view_path.read_text(encoding='utf-8'))
    target='candidate' if role=='review' else 'source_body'
    assert module().restore(data[target])
    if role=='review':data[target]['paragraphs']['p0001']='模型不可见的替换。'
    else:data[target]['paragraphs'][0]['text']='模型不可见的替换。'
    view_path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(ValueError):
        if role=='review':m.commit(tmp_path,out['revision_dir'],approved(m,out,tmp_path))
        else:m.candidate(tmp_path,out['revision_dir'])
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_blind_pipeline_verifies_the_actual_model_view(tmp_path):
    from test_reader_review_p0 import review,book
    m=review();book(tmp_path);out=m.prepare(tmp_path,'0001','model-view-test')
    path=tmp_path/out['reader_blind_model'];data=json.loads(path.read_text(encoding='utf-8'))
    data['manuscript']['paragraphs'][0]['text']='伪造正文。';path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError):m._bound(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])
