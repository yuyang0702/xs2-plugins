from runtime_graph import literary_graph
import json
from pathlib import Path
import pytest
from test_book_contract import PLUGIN
from test_local_revision import setup,patch,approved


def test_content_polish_uses_patches_and_independent_review_length_only_stays_separate():
    import re
    from jsonschema import Draft202012Validator
    d=literary_graph(json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf-8')))
    nodes={n['id']:n for n in d['nodes']};edges={(e['source'],e['target']) for e in d['edges']}
    assert ('gw_polish_scope','script_local_prepare') in edges
    assert '--scoped-review' in nodes['script_local_prepare']['node_params']['script_argv']
    assert ('script_local_prepare','gw_local_critique') in edges
    assert ('gw_local_critique','script_local_confirmed_input') in edges
    assert ('script_local_confirmed_input','agent_pl') in edges
    assert ('gw_local_critique','agent_sc') in edges and ('agent_sc','script_normalize_critique') in edges
    assert nodes['script_local_writer_input']['enable_reject_upstream']
    assert nodes['agent_pl']['node_params']['json_output_schema']['required']==['source_sha256','edits']
    assert {('script_local_candidate','gw_blind_scene'),('gw_blind_scene','agent_blind_scene'),
            ('agent_blind_scene','script_blind_select'),('script_blind_select','agent_local_review'),
            ('gw_blind_scene','script_specific_review'),('script_specific_review','agent_local_review'),
            ('agent_local_review','gw_zhuque_whole_text'),('gw_zhuque_whole_text','script_zhuque_skip'),
            ('script_zhuque_skip','script_local_commit'),
            ('gw_zhuque_whole_text','script_zhuque_stage'),('script_zhuque_stage','agent_zhuque_rounds'),
            ('agent_zhuque_rounds','script_local_commit')} <= edges
    assert nodes['script_local_commit']['node_params']['script_stdin_variable']=='revision_review_result'
    assert ('script_focused_execution','agent_pp') in edges and ('agent_pp','script_fragment_review_context') in edges
    assert 'script_polish_post' not in nodes
    review_schema=nodes['agent_local_review']['node_params']['json_output_schema']
    schema=review_schema.get('anyOf',[review_schema])[0]['properties']['change_reviews']['items']['properties']
    assert review_schema['properties']['protocol']['const']=='local-review-v3'
    assert set(schema)=={'edit_index','effect','reason','preservation'}
    for node in ('agent_sc','agent_local_review'):
        message=nodes[node]['first_message']
        embedded,=re.findall(r'<OUTPUT_SCHEMA>\s*(.*?)\s*</OUTPUT_SCHEMA>',message,re.S)
        assert json.loads(embedded)==nodes[node]['node_params']['json_output_schema']
    Draft202012Validator(review_schema).validate({'protocol':'local-review-v3','compatible':True,
        'issues':[],'change_reviews':[],'issue_outcomes':[]})


def test_completion_check_rejects_a_post_publication_edit(tmp_path):
    from test_length_quality import policy
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=approved(m,out,tmp_path)
    m.commit(tmp_path,out['revision_dir'],report)
    task={'task_id':'local-test','parameter_values':{**out,'revision_review_result':report},'node_states':{'script_local_commit':{'status':'completed'}}}
    state={'values':{'chapter_number':'0001'}}
    path=tmp_path/'story/0001/chapter.md';path.write_bytes(path.read_bytes()+'作者新改。'.encode())
    current=path.read_bytes()
    with pytest.raises(ValueError):policy().verify_completion(tmp_path,state,'polish',task)
    assert path.read_bytes()==current


def test_frozen_v9_writer_accepts_compact_grounded_review_for_long_chapter(tmp_path):
    from test_book_contract import put
    from test_local_revision import module

    m = module()
    body = '\n\n———\n\n'.join(
        '“门开了吗？”\n\n他让开身子。\n\n“还没有。”\n\n“门的钥匙在我手里。”\n\n“先把它放下。”'
        for _ in range(45)
    )
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'dialogue-v9', '1-5000', dialogue_check=True, dialogue_check_version=9)
    view = m.read(tmp_path/out['revision_source_model'])
    assert view['dialogue_exchanges']['exchange-1'] == ['d0001', 'd0002', 'd0003', 'd0004']
    assert view['dialogue_turns']['d0002'] == ['p0003', 1]

    report = {
        'feels_human': True, 'scene_assessment': '检查了每一次开场与后续接话。', 'issues': [],
        'dialogue_checks': [
            {'focus': focus, 'status': 'not_applicable', 'reason': '没有适用的情境。', 'goal': '', 'turns': []}
            for focus in ('literal_echo', 'situational_speech', 'scripted_delivery', 'voice_contrast')
        ],
        'scene_checks': [{'status': 'not_applicable', 'focus': 'narration',
                          'reason': '只有短动作，无可独立判断的叙述过程。', 'goal': '', 'anchors': []}],
        'exchange_review': {
            'passed': [f'exchange-{i}' for i in range(3, 46)],
            'revisions': [
                {'exchange_id': 'exchange-1', 'phase': 'opening', 'target_turn': 1,
                 'reason': '只问答门开没开，没接住让步。', 'goal': '让他接住对方让开身子的犹豫。',
                 'preserve': ['门还没打开', '他让开身子']},
                {'exchange_id': 'exchange-2', 'phase': 'later', 'turns': [{'turn_id': 'd0006'}, {'turn_id': 'd0008'}],
                 'target_turn': 1, 'reason': '后面继续报告，没有回应对方的要求。',
                 'goal': '说出他为什么要求把钥匙放下。', 'preserve': ['钥匙还在原主手里']},
            ],
        },
    }
    causality_only = report | {'scene_checks': [report['scene_checks'][0] | {'focus': 'causality'}]}
    put(tmp_path, 'critique.json', causality_only)
    with pytest.raises(m.Retry, match='scene_review_format'):
        m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    invalid = [
        (report['exchange_review']['passed'][:-1], report['exchange_review']['revisions'], 'exchange-45'),
        (['exchange-1', *report['exchange_review']['passed']], report['exchange_review']['revisions'], 'exchange-1'),
        (report['exchange_review']['passed'], [report['exchange_review']['revisions'][0],
         report['exchange_review']['revisions'][1] | {'turns': [{'turn_id': 'd0003'}, {'turn_id': 'd0008'}]}], '指定连续对白段'),
    ]
    for passed, revisions, error in invalid:
        put(tmp_path, 'critique.json', report | {'exchange_review': {'passed': passed, 'revisions': revisions}})
        with pytest.raises(m.Retry, match=error):
            m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    put(tmp_path, 'critique.json', report)
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    editor = m.read(tmp_path/out['revision_editor_model'])
    opening, later = [goal for goal in editor['goals'] if 'exchange_id' in goal]
    assert opening['turns'] == [{'paragraph_id': 'p0001', 'quote': '门开了吗？'},
                                {'paragraph_id': 'p0003', 'quote': '还没有。'}]
    assert opening['target']['quote'] == '还没有。'
    assert opening['paragraph_ids'] == ['p0001', 'p0002', 'p0003', 'p0004', 'p0005']
    assert later['target']['quote'] == '先把它放下。'
    assert [turn['quote'] for turn in later['turns']] == ['还没有。', '门的钥匙在我手里。', '先把它放下。']


@pytest.mark.parametrize('classified', [False, True])
def test_exchange_retry_keeps_other_finding_and_exact_misfiled_evidence(tmp_path, classified):
    from test_book_contract import put
    from test_local_revision import module

    m = module()
    lead = '屏上写着“准备中”。\n\n' if classified else ''
    body = '\n\n———\n\n'.join(f'{lead}“先开{place}的门？”\n\n“还没准备好。”\n\n“钥匙在我手里。”\n\n“那就都放下。”'
                              for place in ('仓库', '楼梯', '码头'))
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'exchange-retry', '1-500', dialogue_check=True, dialogue_check_version=9)

    def revision(exchange_id, turn_ids, goal):
        return {'exchange_id': exchange_id, 'phase': 'later', 'target_turn': 1,
                'goal': goal, 'reason': '后一句没有回应当场要求。', 'preserve': ['钥匙在说话人手里'],
                'turns': [{'turn_id': key} for key in turn_ids]}

    first = ['d0004', 'd0005'] if classified else ['d0003', 'd0004']
    second = ['d0009', 'd0010'] if classified else ['d0007', 'd0008']
    report = {'feels_human': False, 'scene_assessment': '回看接话意图。', 'issues': [],
              'dialogue_checks': [{'focus': focus, 'status': 'not_applicable', 'reason': '没有相应场景。',
                                   'goal': '', 'turns': []}
                                  for focus in ('literal_echo', 'situational_speech', 'scripted_delivery', 'voice_contrast')],
              'scene_checks': [{'status': 'not_applicable', 'focus': 'narration',
                                'reason': '当前只有对白。', 'goal': '', 'anchors': []}],
              'exchange_review': {'passed': ['exchange-2'], 'revisions': [
                  revision('exchange-1', first, '接住仓库门的争议。'),
                  revision('exchange-3', second, '接住楼梯口这次拒绝。'),
              ]}}
    if classified:
        report['exchange_review']['non_turn_ids'] = ['d0001', 'd0006', 'd0011']
    put(tmp_path, 'critique.json', report)
    with pytest.raises(m.Retry):
        m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    # A subsequent model answer judges the outstanding group and forgets the old findings.
    put(tmp_path, 'critique.json', report | {'exchange_review': {'passed': ['exchange-3'], 'revisions': []}})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    accepted = m.read(tmp_path / out['revision_editor_model'])['goals']
    assert [(item['exchange_id'], item['goal']) for item in accepted] == [
        ('exchange-1', '接住仓库门的争议。'), ('exchange-2', '接住楼梯口这次拒绝。')]
    if classified:
        accepted_report = m.read(tmp_path / out['revision_input'])['critique']
        assert accepted_report['exchange_review']['non_turn_ids'] == ['d0001', 'd0006', 'd0011']


def fixture_zhuque_transport(root, raw, monkeypatch):
    """Use the real attested adapter in its isolated subprocess, replacing its HTTP transport."""
    import asyncio
    import shutil
    from src.workflow import script_library
    from src.workflow.runtime_guards import RUNTIME_GUARD_KEY
    library = shutil.copytree(PLUGIN/'resources/script-library', root/'fixture-library',
                              ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    catalog = script_library.ScriptLibraryCatalog(library)
    monkeypatch.setattr(script_library, 'get_script_library', lambda: catalog)
    prepare = next(n for n in raw['nodes'] if n['id'] == 'script_local_prepare')
    prepare['node_params'][RUNTIME_GUARD_KEY] = {
        'library_script_attestation': catalog.attest('xs2', 'local_revision', 'python'),
    }
    key = root/'offline-key'
    key.write_text('fixture-only', encoding='utf-8')
    entry = root/'offline-adapter.py'
    entry.write_text("""
import io, json, runpy, sys, urllib.request
from pathlib import Path

def respond(request, timeout):
    payload = json.loads(request.data)
    text = payload['text']
    with Path('full-text-checks.jsonl').open('a', encoding='utf-8') as stream:
        current = Path('story/0001/chapter.md').read_bytes().decode()
        print(json.dumps({'request': payload, 'published': current}), file=stream)
    first = '潮水会回来。' in text
    rows = []
    for index, paragraph in enumerate(text.split('\\n\\n')):
        start = text.index(paragraph)
        rows.append({'text': paragraph, 'position': [start, start + len(paragraph)],
                     'label': 2 if first and index in (0, 2) else 0})
    return io.BytesIO(json.dumps({'status': 'success', 'segment_labels': rows,
        'labels_ratio': {'0': .4 if first else .7, '1': 0, '2': .6 if first else .3}}).encode())

urllib.request.urlopen = respond
runpy.run_path(sys.argv[1], run_name='__main__')
""", encoding='utf-8')
    real_exec = asyncio.create_subprocess_exec
    async def exec_with_fixture(*argv, **kwargs):
        if Path(argv[-1]).name == 'zhuque_round_adapter.py':
            argv = (*argv[:-1], str(entry), argv[-1])
            kwargs['env'] = {**kwargs['env'], 'XS2_ZHUQUE_KEY_FILE': str(key)}
        return await real_exec(*argv, **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', exec_with_fixture)
    return library


@pytest.mark.parametrize('first_problem',['stale','quality','combined','catalog_refs','unknown_catalog_refs','planned_budget','native_conflict','cached_budget','compact_report','retained_progress','confirmed_reader','blind','zhuque'])
def test_real_scheduler_retries_only_responsible_role_and_passes_actual_report_on_stdin(tmp_path,monkeypatch,first_problem):
    monkeypatch.setenv('XS2_ZHUQUE_KEY_FILE', '')
    import asyncio,os,shlex,sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.failure_policy import activate_scheduled_retry
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.script import _parse_wf_vars,_parse_reject_upstream
    from src.workflow.variable_resolution import resolve_placeholders
    from test_length_quality import policy
    from test_local_revision import BODY,module,scoped_setup
    from test_book_contract import put
    state={'mode':'short','values':{'chapter_number':'0001','target_word_count':'1-5000'}}
    if first_problem=='retained_progress':
        state['values']['author_feedback_file']='author.md'
        put(tmp_path,'author.md','必须补写第一段有关保留的动作。')
    put(tmp_path,'.novel-project.json',state)
    if first_problem in ('planned_budget','native_conflict','cached_budget'):put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'planner'})
    (tmp_path/'story/0001').mkdir(parents=True);(tmp_path/'story/0001/chapter.md').write_bytes(BODY.encode())
    if first_problem=='confirmed_reader':scoped_setup(tmp_path,raw=BODY.encode())
    if first_problem=='cached_budget':
        from test_composition_plan import module as comp_module
        cm=comp_module();req=cm.prepare(tmp_path,'0001','cache-origin','1-5000')
        plan={'request_digest':req['request_digest'],'status':'ready','reason':'经批准的分配。','minimum':1,'maximum':4000,
            'segments':[{'id':'quiet','purpose':'保留回环','development':'情绪有发展','minimum':1,'maximum':4000}]}
        cm.accept(tmp_path,'cache-origin',plan,{'request_digest':req['request_digest'],'plan_digest':cm.identity(plan),
            'verdict':'approve','scope_preserved':True,'length_feasible':True,'reason':'依照本书。',
            'checks':[{'segment_id':'quiet','develops_function':True,'style_basis':'允许回环','reason':'有作用。'}]})
    raw=literary_graph(json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8')))
    library = PLUGIN/'resources/script-library'
    if first_problem == 'zhuque':
        put(tmp_path, 'zhuque-options.json', {'enabled': True, 'reference_text': '同文通过稿里的潮声。'})
        library = fixture_zhuque_transport(tmp_path, raw, monkeypatch)
    if first_problem not in ('blind','confirmed_reader','zhuque'):
        # Replay pre-ballot snapshots: their original reviewer contract and retry sequence must remain valid.
        next(n for n in raw['nodes'] if n['id']=='script_local_prepare')['node_params']['script_argv'].remove('--blind-scenes')
    wf=WorkflowDef.from_dict(raw);assert not wf.validate()
    calls=[];m=module();out=m.locations('cache/local-revision/scheduler-local')
    class Manager:
        sessions={};main_session_id=''
        async def create_sub_session(self,**kwargs):
            node=kwargs['node_id'];calls.append(node)
            assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
            if node=='agent_composition_plan':
                from test_composition_plan import module as comp_module
                cm=comp_module();req=json.loads((tmp_path/'cache/composition/scheduler-local/request.json').read_text())
                output={'request_digest':req['request_digest'],'status':'ready','reason':'保留回环并合并重复说明。',
                    'minimum':1,'maximum':4000,'segments':[{'id':'reflection','purpose':'心理与回环','development':'情绪有变化，承载本书声线','minimum':1,'maximum':4000}]}
            elif node=='agent_composition_review':
                req=json.loads((tmp_path/'cache/composition/scheduler-local/review-input.json').read_text())
                output={'request_digest':req['request_digest'],'plan_digest':req['plan_digest'],'verdict':'approve','scope_preserved':True,
                    'length_feasible':True,'reason':'不强制新增事件。','checks':[{'segment_id':'reflection','develops_function':True,'style_basis':'本书回环声线','reason':'情绪有发展。'}]}
            elif node=='agent_sc':
                output={'feels_human':True,'scene_assessment':'保留原声线，合并复述。','issues':[]}
                if first_problem=='retained_progress':
                    output['issues']=[{'dimension':'行动','severity':'high','description':'第一段动作须按作者意见补写。',
                        'evidence':['第一段保留。'],'impact':'缺少新动作。','suggestion':'补写动作。',
                        'required_source':'必须补写第一段有关保留的动作。'}]
                if first_problem in ('catalog_refs','unknown_catalog_refs'):
                    output['issues']=[{'dimension':'复述','severity':'medium','description':'重复说明。',
                        'evidence':['第二段重复说明。'],'impact':'正文重复。','suggestion':'合并为一句。'}]
            elif node=='agent_pl':
                if calls.count(node)>1:
                    assert '第二段简明。' in kwargs['task_description']
                    assert ('待验收工作稿' if first_problem=='retained_progress' else '未通过补丁') in kwargs['task_description']
                if first_problem=='native_conflict':
                    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
                    output={'source_sha256':source['source_sha256'],'edits':[],'status':'needs_replan','reason':'范围与篇幅无法同时满足。','evidence':['第二段重复说明。']}
                elif first_problem=='retained_progress' and calls.count(node)>1:
                    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
                    output={'source_sha256':source['source_sha256'],'edits':[{'paragraph_id':'p0001','old':'第一段保留。','occurrence':1,'replacement':'第一段仍旧保留。'}]}
                else:output=patch(m,out,tmp_path,'第二段简明。' if calls.count(node)==1 else '第二段只保留新信息。')
            elif node=='agent_blind_scene':
                ballot=m.read(tmp_path/out['revision_dir']/'blind-packet.json')
                scene,=ballot['scenes']
                side='A' if '第二段简明。' in scene['A'] else 'B'
                output={'ballot':ballot['ballot'],'scenes':[{'id':scene['id'],'prefer':side,'exceptions':[],
                         'voice_quote':'第二段简明。','redundant_quote':'','reason':'这一句收得干净。'}]}
            elif node=='agent_zhuque_rounds':
                prompt = kwargs['task_description']
                if '独立审校本轮改写' in prompt:
                    assert '潮水还会回来。' in prompt and '第一段照旧保留。' in prompt
                    output = {'meaning_preserved': True, 'facts_preserved': True, 'voice_preserved': True,
                              'rejected_ids': [], 'reason': '两处仍保留原意及叙述口吻。'}
                else:
                    assert '同文通过稿里的潮声。' in prompt and '第二段简明。' in prompt
                    if 'p0001-s1' in prompt:
                        output = {'id': 'p0001-s1', 'reference_id': 'p0002', 'replacement': '第一段照旧保留。'}
                    else:
                        assert 'p0003-s3' in prompt
                        output = {'id': 'p0003-s3', 'reference_id': 'p0002', 'replacement': '潮水还会回来。'}
            elif first_problem in ('blind','zhuque'):
                ctx=m.read(tmp_path/out['revision_review_input'])
                output={'protocol':'local-review-v3','compatible':True,'issues':[],'change_reviews':[],'added_text_reviews':[],
                        'issue_outcomes':[{'id':k,'excerpts':[v[0]],'status':'resolved','reason':'对读后衔接成立。'}
                                          for k,v in m.signoff_evidence(ctx).items()]}
            else:
                from test_review_wire import compact
                output=compact(json.loads(approved(m,out,tmp_path)))
                output['protocol']='local-review-v3'
                output.pop('expression_checks');output.pop('expression_review')
                if first_problem=='retained_progress':
                    first=calls.count(node)==1
                    output['issue_outcomes']=[{'id':'critic-0','status':'remaining' if first else 'resolved',
                        'reason':'第一段仍需行动。' if first else '动作已补。',
                        'excerpts':['第一段保留。' if first else '第一段仍旧保留。']}]
                elif first_problem=='compact_report':
                    if calls.count(node)==1:output['change_reviews']=[]
                elif first_problem in ('planned_budget','cached_budget'):pass
                elif first_problem in ('catalog_refs','unknown_catalog_refs'):
                    reference='c9999' if first_problem=='unknown_catalog_refs' and calls.count(node)==1 else 'p0002'
                    output['issue_outcomes']=[{'id':'critic-0','status':'resolved','reason':'重复解释已合并。',
                                               'excerpts':[{'ref_id':reference}]}]
                elif first_problem=='confirmed_reader':
                    output['issue_outcomes']=[{'id':'context-door','status':'resolved','reason':'已压缩同处重复说明。',
                                               'excerpts':[{'ref_id':'p0002'}]}]
                elif first_problem=='combined':
                    if calls.count(node)<=2:output['candidate_sha256']='stale'
                    elif calls.count(node)==3:output['change_reviews'][0]['effect']='regressed'
                elif calls.count(node)==1:
                    if first_problem=='stale':output['candidate_sha256']='stale'
                    else:output['change_reviews'][0]['effect']='regressed'
            sid=node+str(calls.count(node))
            self.sessions[sid]=SimpleNamespace(record=[{'type':'user','content':kwargs['task_description']},
                {'type':'assistant','content':json.dumps(output,ensure_ascii=False)}])
            kwargs['on_auto_complete'](sid,'fixture at model boundary','success','')
            return {'success':True,'session_id':sid}
    class CLI(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            params=ctx.node_def.node_params
            if 'script_argv' in params:argv=[await resolve_placeholders(x,ctx.parameter_values,wf.variables,str(tmp_path)) for x in params['script_argv']]
            else:argv=shlex.split(await resolve_placeholders(params['script_args'],ctx.parameter_values,wf.variables,str(tmp_path)))
            script=library/params['script_group']/params['script_name']/(params['script_name']+'.py')
            stdin=ctx.parameter_values.get(params.get('script_stdin_variable',''))
            proc=await asyncio.create_subprocess_exec(sys.executable,str(script),*argv,cwd=tmp_path,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},creationflags=0x08000000 if sys.platform=='win32' else 0)
            stdout,stderr=await proc.communicate(stdin.encode() if stdin is not None else None)
            reject=_parse_reject_upstream(stdout.decode())
            if reject:
                reason,target=reject;result=ctx.on_reject_upstream('script:'+ctx.node_def.id,reason,target)
                assert result['success'],result
                return NodeResult(status='failed',error=reason)
            return NodeResult(status='completed' if proc.returncode==0 else 'failed',outputs=_parse_wf_vars(stdout.decode()),error=stderr.decode())
    monkeypatch.setitem(registry._plugins,'agent',AgentNode);monkeypatch.setitem(registry._plugins,'script',CLI)
    engine=WorkflowEngine(Manager())
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    state=json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf8'))
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(policy().parameters(state,raw))
    task=WorkflowTask(task_id='scheduler-local',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run():
        for _ in range(8):
            for key,value in list(task.node_states.items()):
                if value.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(value)
            outcome=await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),
                disabled_ids=set(),shared_ws=tmp_path,parent_id='test',on_node_started=lambda *_:None,needs_approval=False,
                run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
            if outcome!='retry_waiting':return outcome
    outcome=asyncio.run(run())
    assert task.node_states['script_composition_ready'].status=='completed'
    if first_problem in ('planned_budget','cached_budget'):
        expected_range = '1-4000' if first_problem == 'cached_budget' else '1-5000'
        for sid,session in engine._session_manager.sessions.items():
            if sid.startswith(('agent_sc','agent_pl')):
                assert f'本章参考字数：{expected_range}' in session.record[0]['content']
        assert json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf-8'))['values']['target_word_count']=='1-5000'
    if first_problem=='native_conflict':
        assert outcome=='failed';task.status='failed'
        action=policy().recovery_action(state,'polish',task.to_dict(),root=tmp_path)
        assert action['action']=='advance' and action['stage']=='polish'
        assert calls==['agent_sc','agent_pl']
        assert action['updates']['compositionReplans']['0001'] == [task.task_id]
        conflict = json.loads((tmp_path/'planning/composition-conflicts/0001.json').read_text(encoding='utf-8'))
        assert conflict['evidence'] == ['第二段重复说明。']
        assert conflict['no_publication'] is True
        assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
        return
    assert outcome=='completed',(calls,{k:s.status for k,s in task.node_states.items() if k.startswith('agent_')},
                                 {k:s.error for k,s in task.node_states.items() if s.error})
    assert task.node_states['script_local_commit'].status == 'completed', {
        k: s.status for k, s in task.node_states.items() if 'zhuque' in k or k == 'script_local_commit'}
    expected={'stale':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'quality':['agent_sc','agent_pl','agent_local_review'],
              'combined':['agent_sc','agent_pl','agent_local_review','agent_local_review','agent_local_review'],
              'catalog_refs':['agent_sc','agent_pl','agent_local_review'],
              'unknown_catalog_refs':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'planned_budget':['agent_sc','agent_pl','agent_local_review'],
              'cached_budget':['agent_sc','agent_pl','agent_local_review'],
              'compact_report':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'confirmed_reader':['agent_pl','agent_local_review']}
    expected['retained_progress']=['agent_sc','agent_pl','agent_local_review','agent_pl','agent_local_review']
    expected['blind']=['agent_sc','agent_pl','agent_blind_scene','agent_local_review']
    expected['zhuque'] = expected['blind'] + ['agent_zhuque_rounds'] * 3
    assert calls==expected[first_problem]
    policy().verify_completion(tmp_path,state,'polish',task.to_dict())
    replacement='第二段简明。' if first_problem in ('blind','zhuque','stale','catalog_refs','unknown_catalog_refs','planned_budget','cached_budget','compact_report','confirmed_reader') else '第二段只保留新信息。'
    result=BODY.replace('第二段重复说明。',replacement)
    if first_problem in ('quality','combined'):result=BODY
    if first_problem=='retained_progress':result=BODY.replace('第二段重复说明。','第二段简明。').replace('第一段保留。','第一段仍旧保留。')
    if first_problem=='zhuque':
        signed = result
        result = signed.replace('第一段保留。', '第一段照旧保留。').replace('潮水会回来。', '潮水还会回来。')
        checks = [json.loads(row) for row in (tmp_path/'full-text-checks.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [row['request'] for row in checks] == [
            {'text': m.zhuque.detector_input(body)[2], 'is_merge': False} for body in (signed, result)]
        assert [row['published'] for row in checks] == [BODY, BODY]
        assert m.read(tmp_path/out['revision_dir']/'zhuque-round-result.json')['rounds'] == 1
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==result.encode()
