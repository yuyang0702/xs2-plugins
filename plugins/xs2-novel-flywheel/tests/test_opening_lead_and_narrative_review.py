import asyncio
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import pytest

from test_advisor_book_contract import service
from runtime_graph import literary_graph
from test_expression_evidence import PLUGIN, checks, module as expression_module
from test_reader_review_p0 import review, write


def exporter():
    path = PLUGIN / 'resources/script-library/xs2/manuscript_export/manuscript_export.py'
    spec = importlib.util.spec_from_file_location('test_opening_lead_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BODY = '1．桥头\n\n她把空信封藏进口袋。\n\n2．火光\n\n后来她把桥烧了。\n'
LEAD = '我原以为守着渡口，就能等到回信。'


def test_included_lead_precedes_body_without_changing_chapters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = write(tmp_path, 'story/0001/chapter.md', BODY)
    original = source.read_bytes()
    write(tmp_path, '.novel-project.json', {'mode': 'short', 'values': {'opening_lead': 'include'}})
    export = exporter()
    prepared = export.prepare_lead(tmp_path, 'book', 'export-a')
    write(tmp_path, prepared['draft'], {'lead': LEAD})
    result = export.build_manuscript('export/manuscript.md', 'export/manifest.json',
                                     binding=prepared['binding'], task_id='export-a')
    final = (tmp_path / 'export/manuscript.md').read_text(encoding='utf8')
    assert final == LEAD + '\n\n' + BODY
    assert result['chapter_count'] == 1
    assert result['chapters'][0]['characters'] == len(BODY.strip())
    assert source.read_bytes() == original


def test_legacy_book_skips_lead_and_rejects_late_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = write(tmp_path, 'story/0001/chapter.md', BODY)
    export = exporter()
    assert export.prepare_lead(tmp_path, 'book', 'legacy') == {}
    export.build_manuscript('export/manuscript.md', 'export/manifest.json')
    before = (tmp_path / 'export/manuscript.md').read_bytes()
    prepared = export.prepare_lead(tmp_path, 'include', 'new')
    write(tmp_path, prepared['draft'], {'lead': LEAD})
    source.write_text(BODY + '她在岸边等。', encoding='utf8')
    with pytest.raises(ValueError, match='变化'):
        export.build_manuscript('export/manuscript.md', 'export/manifest.json',
                                mode='include', binding=prepared['binding'], task_id='new')
    assert (tmp_path / 'export/manuscript.md').read_bytes() == before


def test_a_date_in_a_lead_is_not_a_numbered_section():
    export = exporter()
    lead = '2088.04.01，气闸还开着。'
    assert export._validated_lead({'lead': lead}, BODY) == lead
    with pytest.raises(ValueError, match='编号'):
        export._validated_lead({'lead': '1．桥头\n\n人来了。'}, BODY)


@pytest.mark.parametrize('verdict, stale', [('pass', False), ('revise', False), ('pass', True)])
def test_export_handoff_review_is_bound_to_current_opening_and_lead(tmp_path, monkeypatch, verdict, stale):
    monkeypatch.chdir(tmp_path)
    export = exporter()
    write(tmp_path, '.novel-project.json', {'mode': 'short', 'values': {'opening_lead': 'include'}})
    chapter = write(tmp_path, 'story/0001/chapter.md', BODY)
    before = chapter.read_bytes()
    paths = export.prepare_lead(tmp_path, 'book', 'handoff')
    draft = write(tmp_path, paths['draft'], {'lead': LEAD})
    review_input = export.prepare_lead_review(tmp_path, 'handoff')
    assert json.loads((tmp_path / review_input).read_text(encoding='utf8'))['lead'] == LEAD
    if stale:
        write(tmp_path, paths['draft'], {'lead': LEAD + '雾也没有散。'})
    assert draft.is_file()
    review_path = write(tmp_path, paths['review'], {'verdict': verdict, 'lead_quote': '守着渡口',
        'opening_quote': '她把空信封藏进口袋。', 'reason': '导语建立期待，首场给出已经收到空信的发现。'})
    if verdict == 'revise' or stale:
        with pytest.raises(ValueError, match='改写|变化'):
            export.build_manuscript('export/manuscript.md', 'export/manifest.json', binding=paths['binding'],
                                    task_id='handoff', lead_review=review_path.relative_to(tmp_path).as_posix())
        assert not (tmp_path / 'export/manuscript.md').exists()
    else:
        report = export.build_manuscript('export/manuscript.md', 'export/manifest.json', binding=paths['binding'],
                                         task_id='handoff', lead_review=paths['review'])
        assert report['opening_lead']['handoff_review']['verdict'] == 'pass'
        assert (tmp_path / 'export/manuscript.md').read_text(encoding='utf8') == LEAD + '\n\n' + BODY
    assert chapter.read_bytes() == before


def test_handoff_review_accepts_an_intentional_echo_but_checks_both_sources():
    export = exporter()
    quote = '她把空信封藏进口袋。'
    judgement = {'verdict': 'pass', 'lead_quote': quote, 'opening_quote': quote,
                 'reason': '导语是老年回忆，首场的同句落回童年视角并补上隐瞒的理由。'}
    assert export._validated_handoff(judgement, quote, BODY) == judgement
    judgement['opening_quote'] = '从未出现的开场'
    with pytest.raises(ValueError, match='原文'):
        export._validated_handoff(judgement, quote, BODY)


@pytest.mark.parametrize('category', [
    'premature_explanation', 'aftermath_checklist', 'dialogue_stall', 'post_action_restatement',
])
def test_staged_expression_finding_requires_two_sides_of_the_problem(category):
    policy = expression_module()
    issue = {'category': category, 'excerpts': ['后来她把桥烧了。']}
    with pytest.raises(ValueError, match='两处'):
        policy.validate_narrative_issue(issue)
    issue['excerpts'].append('她把空信封藏进口袋。')
    policy.validate_narrative_issue(issue)


def test_advisor_recommends_a_setting_without_changing_the_book(tmp_path):
    sys.path.insert(0, str(PLUGIN / 'resources/script-library/xs2'))
    try:
        from console_service.configuration import parse_configuration
    finally:
        sys.path.pop(0)
    state = write(tmp_path, '.novel-project.json', {'values': {'style_intent': '碎片化悬疑'}})
    jobs = service().create_assistant(lambda **_: None, lambda **_: None)
    system, user, *_ = jobs._general_messages(tmp_path, 'q', {'purpose': 'advisor',
        'question': '参照样文规划开头', 'project': {'values': {}}})
    assert '导语' in system and '碎片化悬疑' in user
    _, suggestions = parse_configuration(json.dumps({'reply': '保留悬念。', 'suggestions': [
        {'key': 'opening_lead', 'value': 'omit', 'reason': '保留身份谜面'},
    ]}), 'short')
    assert [item['value'] for item in suggestions] == ['omit']
    assert 'opening_lead' not in state.read_text(encoding='utf8')


@pytest.mark.parametrize('dimension', ['explanation_progression', 'turning_point_payoff'])
def test_narrative_review_finding_needs_two_distinct_excerpts_and_blocks_pass(dimension):
    m = expression_module()
    rows = checks(m)
    row = next(row for row in rows if row['dimension'] == dimension)
    first = '她把空信封藏进口袋。'
    later = '后来她把桥烧了。'
    for check in rows:
        check['excerpts'] = [first]
    row.update(status='issue', excerpts=[later, later], issue_ids=['n1'])
    report = {'verdict': 'pass', 'fact_review': {'verdict': 'pass', 'summary': '事实成立。'},
        'expression_review': {'verdict': 'pass', 'summary': '因果表现有缺口。', 'issues': [
            {'id': 'n1', 'location': '第二节', 'priority': 'medium', 'excerpts': [first, later],
             'impact': '关键选择只剩结果。', 'goal': '补出触发选择的有效细节。'}]},
        'expression_checks': rows}
    with pytest.raises(ValueError, match='两处'):
        m.validate_checks(report, BODY)
    row['excerpts'] = [first, later]
    m.validate_checks(report, BODY)
    review().quality().expression_gate(report, BODY)
    assert report['verdict'] == 'revise'


def run_export_workflow(root, monkeypatch, mode, lead):
    from src.workflow.definition import WorkflowDef, WorkflowRunRecord, WorkflowTask
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin, NodeResult, registry
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders

    definition = literary_graph(json.loads(
        (PLUGIN / 'resources/workflows/export/definition.json').read_text(encoding='utf8')))
    wf = WorkflowDef.from_dict(definition)
    assert not wf.validate()
    calls = []

    class Manager:
        sessions = {}
        main_session_id = ''

        async def create_sub_session(self, **kwargs):
            node_id = kwargs['node_id']
            calls.append(node_id)
            source = (root / 'story/0001/chapter.md').read_bytes().decode('utf8')
            message = kwargs['task_description']
            if node_id == 'agent_opening_lead':
                assert json.dumps(source[:32], ensure_ascii=False)[1:-1] in message
                response = {'lead': lead}
            else:
                assert lead in message and '她把空信封藏进口袋。' in message
                response = {'verdict': 'pass', 'lead_quote': lead,
                            'opening_quote': '她把空信封藏进口袋。',
                            'reason': '导语建立期待，首场给出空信封的意外。'}
            self.sessions[node_id] = SimpleNamespace(record=[
                {'type': 'user', 'content': kwargs['task_description']},
                {'type': 'assistant', 'content': json.dumps(response, ensure_ascii=False)},
            ])
            kwargs['on_auto_complete'](node_id, 'local fixture', 'success', '')
            return {'success': True, 'session_id': node_id}

    class CLI(BaseNodePlugin):
        node_type = 'script'

        async def execute(self, ctx):
            params = ctx.node_def.node_params
            argv = [await resolve_placeholders(arg, ctx.parameter_values, wf.variables, str(root))
                    for arg in params['script_argv']]
            name = params['script_name']
            script = PLUGIN / 'resources/script-library' / params['script_group'] / name / (name + '.py')
            proc = await asyncio.create_subprocess_exec(sys.executable, str(script), *argv, cwd=root,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, 'TASK_ID': ctx.task_id, 'PYTHONUTF8': '1'})
            out, err = await proc.communicate()
            return NodeResult(status='completed' if proc.returncode == 0 else 'failed',
                              outputs=_parse_wf_vars(out.decode()), error=err.decode())

    monkeypatch.setitem(registry._plugins, 'agent', AgentNode)
    monkeypatch.setitem(registry._plugins, 'script', CLI)
    engine = WorkflowEngine(Manager())

    async def no_save(*_):
        pass

    monkeypatch.setattr(engine, '_save_task_state', no_save)
    monkeypatch.setattr(engine, '_push_wf_task_update', lambda *_: None)
    values = {v['key']: v.get('default', '') for v in definition['variables']}
    values['opening_lead'] = mode
    task = WorkflowTask(task_id='export-' + (mode or 'default'), workflow_id=wf.workflow_id,
                        status='running', parameter_values=values)
    result = asyncio.run(engine._execute_plan_segment(definition=wf, task=task, execution_plan=wf.get_execution_plan(),
        disabled_ids=set(), shared_ws=root, parent_id='test', on_node_started=lambda *_: None,
        needs_approval=False, run_record=WorkflowRunRecord(workflow_id=wf.workflow_id)))
    assert result == 'completed', {key: state.error for key, state in task.node_states.items() if state.error}
    return calls


@pytest.mark.parametrize('mode', ['include', 'omit', ''])
def test_export_workflow_calls_writer_only_when_lead_is_enabled(tmp_path, monkeypatch, mode):
    source = write(tmp_path, 'story/0001/chapter.md', BODY)
    write(tmp_path, '.novel-project.json', {'mode': 'short', 'values': {}})
    original = source.read_bytes()
    calls = run_export_workflow(tmp_path, monkeypatch, mode, LEAD)
    manuscript = (tmp_path / 'export/manuscript.md').read_text(encoding='utf8')
    assert calls == (['agent_opening_lead', 'agent_opening_lead_review'] if mode == 'include' else [])
    assert manuscript.startswith(LEAD + '\n\n1．' if mode == 'include' else '# 第0001章\n\n1．')
    assert source.read_bytes() == original


def test_preserved_opening_lead_is_reviewed_without_calling_the_writer(tmp_path, monkeypatch):
    write(tmp_path, 'story/0001/chapter.md', BODY)
    write(tmp_path, '.novel-project.json', {'mode': 'short', 'values': {}})
    lead_file = write(tmp_path, 'planning/opening_lead.md', LEAD + '\n')
    assert run_export_workflow(tmp_path, monkeypatch, 'include', LEAD) == ['agent_opening_lead_review']
    assert (tmp_path / 'export/manuscript.md').read_text(encoding='utf8') == LEAD + '\n\n' + BODY
    assert lead_file.read_text(encoding='utf8') == LEAD + '\n'
    manifest = json.loads((tmp_path / 'export/manifest.json').read_text(encoding='utf8'))
    assert manifest['opening_lead']['preserved'] is True


def test_preserved_opening_lead_rejects_a_replacement_even_if_it_was_reviewed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    export = exporter()
    write(tmp_path, 'story/0001/chapter.md', BODY)
    write(tmp_path, 'planning/opening_lead.md', LEAD)
    paths = export.prepare_lead(tmp_path, 'include', 'preserve')
    draft = tmp_path / paths['draft']
    assert json.loads(draft.read_text(encoding='utf8')) == {'lead': LEAD}
    changed = LEAD + '后来却等到了桥被烧的消息。'
    write(tmp_path, paths['draft'], {'lead': changed})
    with pytest.raises(ValueError, match='保留|变动'):
        export.prepare_lead_review(tmp_path, 'preserve')
    assert not (tmp_path / 'export/manuscript.md').exists()
