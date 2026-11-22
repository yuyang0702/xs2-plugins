import json
from unittest.mock import Mock
import pytest
from test_local_revision import module, put


def test_new_polish_freezes_checkbox_and_never_detects_before_signoff(tmp_path, monkeypatch):
    m = module()
    put(tmp_path, 'story/0001/chapter.md', '门开了。')
    monkeypatch.setenv('XS2_ZHUQUE_KEY_FILE', 'configured')
    detect = Mock(side_effect=AssertionError('成稿签发前不得调用朱雀'))
    monkeypatch.setattr(m.zhuque, 'analyze', detect)
    def prepare(task):
        return m.prepare(tmp_path, '0001', task, scoped_review=True, whole_chapter_review=True,
                         blind_scenes=True, whole_text_detection=True)
    first = prepare('first')
    def mode(out):
        return m.read(tmp_path/out['revision_dir']/'source-binding.json')['zhuque_options']
    assert mode(first) == {'enabled': False}
    put(tmp_path,'zhuque-options.json', {'enabled': True, 'reference_text':'获准的同文稿。'})
    assert mode(prepare('first')) == {'enabled': False}
    assert mode(prepare('second')) == {'enabled': True, 'reference_text':'获准的同文稿。'}
    assert not detect.called


def test_signed_whole_text_result_binds_content_and_threshold(tmp_path):
    m = module()
    root=tmp_path
    folder='cache/local-revision/test'
    body='门开了。\n\n她没有动。'
    final='院门开了。\n\n她没有动。'
    binding={'chapter_number':'0001','bounds':None}
    publication={'candidate':body, 'candidate_sha256':m.sha(body.encode())}
    def result(suspected):
        data={'source_sha256':m.sha(body.encode()),'candidate':final,'candidate_sha256':m.sha(final.encode()),
              'rounds':1,'report':{'status':'success','text_sha256':m.sha(final.encode()),
                                  'labels_ratio':{'0':1-suspected,'1':0,'2':suspected}}}
        path=root/folder/'zhuque-round-result.json'
        put(root,folder+'/zhuque-round-result.json', data)
        return json.dumps({'sha256':m.sha(path.read_bytes())})
    with pytest.raises(ValueError):m.accept_whole_text(root,folder,binding,publication,result(.3001))
    proof=result(.30)
    accepted,metadata=m.accept_whole_text(root,folder,binding,publication,proof)
    assert accepted['candidate']==final and accepted['length']['body_sha256']==m.sha(final.encode())
    assert metadata['suspected']==.30
    with pytest.raises(ValueError):m.accept_whole_text(root,folder,binding,publication,'{}')
    with pytest.raises(ValueError):m.accept_whole_text(root,folder,binding,{**publication,'candidate_sha256':'x'},proof)

def test_installed_graph_has_one_full_text_gate_before_publication():
    from pathlib import Path
    from importlib.util import spec_from_file_location, module_from_spec
    base = Path(__file__).resolve().parents[1]/'resources'
    graph = json.loads((base/'workflows/polish/definition.json').read_bytes())
    nodes = {n['id']:n for n in graph['nodes']}
    edges = {(e['source'],e['target']):e for e in graph['edges']}
    assert '--whole-text-detection' in nodes['script_local_prepare']['node_params']['script_argv']
    gate = 'gw_zhuque_whole_text'
    assert ('agent_local_review','script_continuity_stage') in edges
    assert ('gw_continuity_publication',gate) in edges
    assert edges[gate,'script_zhuque_skip']['condition']['is_default']
    assert ('script_zhuque_skip','script_local_commit') in edges
    assert edges[gate,'script_budget_agent_zhuque_rounds']['condition']['expression'] == '{{zhuque_round_mode}} == yes'
    assert ('agent_zhuque_rounds','script_local_commit') in edges
    agent = nodes['agent_zhuque_rounds']
    assert agent['node_params']['zhuque_rounds_input'] == 'zhuque_round_input'
    assert 'zhuque_round_checksum' == agent['output_variable']
    spec = spec_from_file_location('round_model_route',base/'script-library/xs2/console_service/production.py')
    prod = module_from_spec(spec); spec.loader.exec_module(prod)
    choices = prod.model_overrides({'analysisModel':'other:critic','polishModel':'other:writer'},graph,'polish') or {}
    assert choices.get(agent['id'],agent['model_override']) == 'lingsuan-google:gemini-4-neon'

def test_an_opt_in_polish_cannot_complete_with_skipped_publication(tmp_path):
    from test_length_quality import policy
    p = tmp_path/'story/0001/chapter.md'
    p.parent.mkdir(parents=True)
    p.write_text('原文仍在。',encoding='utf8')
    task = {'task_id':'test','created_at':'2020-01-01T00:00:00+00:00',
            'parameter_values':{'revision_dir':'cache/local-revision/test','zhuque_round_mode':'yes'},
            'node_states':{'script_local_prepare':{'status':'completed'},'script_local_commit':{'status':'skipped'}}}
    with pytest.raises(ValueError,match='签发'):
        policy()._verify_completion(tmp_path,{'mode':'short','values':{'chapter_number':'0001'}},'polish',task)
