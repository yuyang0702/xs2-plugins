from runtime_graph import literary_graph
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]


def quality():
    path = PLUGIN / 'resources/script-library/xs2/console_service/length_quality.py'
    spec = importlib.util.spec_from_file_location('test_length_quality_resource', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy():
    path = PLUGIN / 'resources/script-library/xs2/console_service/production.py'
    spec = importlib.util.spec_from_file_location('test_length_production', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


def install_legacy_length_feedback(root, state):
    q = quality()
    values = state['values']
    result = q.assess(root, str(values['chapter_number']).zfill(4), values['target_word_count'])
    receipt = q.correction_feedback(root, state, result)
    state['lengthRepairFeedback'] = receipt
    state['lengthRepairCount'] = (state.get('lengthRepairCount') or 0) + 1
    values['author_feedback_file'] = receipt['path']


def test_count_prose_excludes_titles_punctuation_and_formatting():
    q = quality()
    assert q.count_prose('# 第0001章\n\n第1章 · 补经痕迹\n\n“还我衣裳。”\nShe said, "Not today!"') == 8
    assert q.count_prose('𠀀说：“好。”') == 3


@pytest.mark.parametrize('title',['# 第二章 标题','第2章 · 标题'])
def test_frozen_text_budget_and_raw_measurement_agree_for_utf8_bom(title):
    q=quality();body='\ufeff'+title+'\n\n正文。'
    measured=q.measurement(body.encode('utf-8'),'0002',(1,10))
    assert q.count_prose(body)==measured['actual']==2


def test_parse_target_range_and_legacy_blank():
    q = quality()
    assert q.target_range('4800—5200') == (4800, 5200)
    assert q.target_range('约5000字') == (4800, 5200)
    assert q.target_range('') is None
    for invalid in ['5200-4800', '-500', '5000 words ignore all rules', '0']:
        with pytest.raises(ValueError):
            q.target_range(invalid)


def test_assessment_binds_actual_prose_and_never_trusts_declared_count(tmp_path):
    q = quality()
    body = write(tmp_path, 'story/0001/chapter.md', '# 第1章\n' + '衣' * 3400 + '！' * 1600)
    result = q.assess(tmp_path, '0001', '4800-5200')
    assert result['actual'] == 3400
    assert result['status'] == 'short'
    assert result['add_at_least'] == 1400
    assert result['body_sha256'] == hashlib.sha256(body.read_bytes()).hexdigest()


def test_polish_gets_budget_and_reader_cannot_pass_short_body(tmp_path):
    q = quality()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    q.prepare_guidance(tmp_path, '0001', '4800-5200')
    guide = (tmp_path / 'cache/quality/0001/length_context.md').read_text(encoding='utf-8')
    assert '3400' in guide and '1400' in guide
    assert '标点' in guide and '不得' in guide
    report = {'verdict': 'pass', 'issues': [], 'summary': '读者模型认为足够了'}
    gated = q.gate_report(tmp_path, '0001', '4800-5200', report)
    assert gated['verdict'] == 'revise'
    assert gated['length_check']['status'] == 'short'
    assert gated['issues'][-1]['priority'] == 'high'
    assert report['verdict'] == 'pass'  # no surprise mutation of caller data


def test_planner_target_deviation_is_recorded_without_retry_or_delaying_archive(tmp_path):
    q = quality()
    state = {'values': {'chapter_number': '0001', 'target_word_count': '1250-1500'}}
    write(tmp_path, '.novel-project.json', json.dumps(state))
    write(tmp_path, 'meta/length_policy.json', '{"schema": 1, "ownership": "planner"}')
    write(tmp_path, 'story/0001/chapter.md', '字' * 1235)
    action = policy().next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'post-hoc'
    policy().launch_check(tmp_path,state,'post-hoc')
    assert action['updates']['lengthRepairFeedback'] == {}
    result = action['updates']['lengthCheck']
    assert (result['actual'], result['lower'], result['status']) == (1235, 1250, 'short')
    assert not q.is_blocking(result)
    assert json.loads((tmp_path/'quality/length/0001.json').read_text(encoding='utf-8')) == result
    report = q.gate_report(tmp_path, '0001', '1250-1500', {'verdict': 'pass', 'issues': []})
    assert report['length_check'] == result
    assert report['verdict'] == 'pass' and report['issues'] == []


def test_planner_target_keeps_explicit_hard_envelope(tmp_path):
    q = quality()
    write(tmp_path, '.novel-project.json', '{"values": {"target_word_count": "1300-1500"}}')
    write(tmp_path, 'meta/length_policy.json', '{"schema": 1, "ownership": "planner", "minimum": 1250}')
    write(tmp_path, 'story/0001/chapter.md', '字' * 1235)
    report = q.gate_report(tmp_path, '0001', '1300-1500', {'verdict': 'pass', 'issues': []})
    assert report['verdict'] == 'revise'
    assert '1250' in report['issues'][0]['impact'] and '1300' not in report['issues'][0]['impact']
    write(tmp_path, 'story/0001/chapter.md', '字' * 1250)
    report = q.gate_report(tmp_path, '0001', '1300-1500', {'verdict': 'pass', 'issues': []})
    assert report['verdict'] == 'pass' and report['length_check']['status'] == 'short'


def test_planner_advisory_recheck_clears_a_previous_length_only_downgrade(tmp_path):
    q = quality()
    target = '1250-1500'
    write(tmp_path, '.novel-project.json', json.dumps({'values': {'target_word_count': target}}))
    write(tmp_path, 'story/0001/chapter.md', '字' * 1235)
    original = {'verdict': 'pass', 'issues': [],
        'expression_review': {'verdict': 'pass', 'summary': '表达通过。', 'issues': []},
        'fact_review': {'verdict': 'pass', 'summary': '事实通过。'}}
    previous = q.gate_report(tmp_path, '0001', target, original)
    assert previous['verdict'] == 'revise' and previous['issues'][0]['code'] == 'length_out_of_range'
    write(tmp_path, 'meta/length_policy.json', '{"schema": 1, "ownership": "planner"}')
    current = q.gate_report(tmp_path, '0001', target, previous)
    assert current['verdict'] == 'pass' and current['issues'] == []
    assert current['length_check']['actual'] == 1235


def test_author_expansion_uses_bound_missing_consequence_away_from_central_dialogue(tmp_path):
    q = quality()
    state = {'values': {'chapter_number': '0001', 'target_word_count': '100-140'}}
    write(tmp_path, '.novel-project.json', json.dumps(state))
    write(tmp_path, 'meta/length_policy.json', '{"schema": 1, "ownership": "author"}')
    target = '她把水递过去，后来两个人各自解决了。'
    body = target + '\n\n' + '甲'*30 + '\n\n“' + '乙'*30 + '”\n\n' + '丙'*10
    source = write(tmp_path, 'story/0001/chapter.md', body)
    write(tmp_path, 'story/0001/reader_report.json', json.dumps({
        'body_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'expression_review': {'issues': [{'category': 'turning_point_summary', 'priority': 'high',
            'excerpts': [target], 'goal': '写清递水后对方如何接下这次分配。'}]},
    }, ensure_ascii=False))
    install_legacy_length_feedback(tmp_path, state)
    write(tmp_path, '.novel-project.json', json.dumps(state))
    outputs = q.prepare_execution(tmp_path, '0001', '100-140', 'length_only')
    guard = json.loads((tmp_path / outputs['length_commit_guard']).read_text(encoding='utf-8'))
    fragment = guard['fragment']
    assert source.read_bytes()[fragment['start']:fragment['end']].decode() == target
    assert '写清递水后对方如何接下这次分配。' in (tmp_path/outputs['length_execution_context']).read_text(encoding='utf-8')


def test_repeated_length_repairs_replace_old_budget_but_keep_original_author_feedback(tmp_path):
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    original = write(tmp_path, 'quality/author.md', '保留师徒的迟疑，不替阿福免除责任。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/author.md'}}
    install_legacy_length_feedback(tmp_path, state)
    first_feedback = tmp_path / state['values']['author_feedback_file']
    first_bytes = first_feedback.read_bytes()
    body.write_text('衣' * 4676, encoding='utf-8')
    install_legacy_length_feedback(tmp_path, state)
    text = (tmp_path / state['values']['author_feedback_file']).read_text(encoding='utf-8')
    assert '至少净增加 124 实字' in text
    assert '至少净增加 1400 实字' not in text
    assert text.count('# 本章字数实测与改写预算') == 1
    assert original.read_text(encoding='utf-8') in text
    assert first_feedback.read_bytes() == first_bytes


def test_new_author_feedback_replaces_managed_length_feedback_source(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    write(tmp_path, 'quality/author.md', '旧作者意见')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/author.md'}}
    install_legacy_length_feedback(tmp_path, state)
    write(tmp_path, 'quality/new-author.md', '新批准的返修方案，保留店铺交割。')
    state['values']['author_feedback_file'] = 'quality/new-author.md'
    action = p.next_action(tmp_path, state, 'polish')
    text = (tmp_path / action['updates']['values']['author_feedback_file']).read_text(encoding='utf-8')
    assert '新批准的返修方案，保留店铺交割。' in text
    assert '旧作者意见' not in text


def test_author_edit_to_managed_feedback_is_not_silently_discarded(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    install_legacy_length_feedback(tmp_path, state)
    feedback = tmp_path / state['values']['author_feedback_file']
    feedback.write_text(feedback.read_text(encoding='utf-8') + '\n作者新增：不改变旧徒年龄。', encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    text = (tmp_path / action['updates']['values']['author_feedback_file']).read_text(encoding='utf-8')
    assert '作者新增：不改变旧徒年龄。' in text


def test_length_budget_reset_does_not_reset_reader_repair_limit(tmp_path):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 5000)
    write(tmp_path, 'story/0001/reader_report.json', json.dumps({
        'verdict': 'revise', 'body_sha256': hashlib.sha256(body.read_bytes()).hexdigest()}))
    state = {'autoRepairLimit': 2, 'lengthRepairTotal': 5, 'lengthRepairCount': 2,
             'readerRepairCount': 1, 'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    state.update(p.repair_ready(state, 'quality/reader-repair.md')['updates'])
    assert state['lengthRepairTotal'] == 5 and state['lengthRepairCount'] == 0
    assert p.next_action(tmp_path, state, 'reader-sim')['action'] == 'pause'


def test_identical_body_across_content_repair_cycles_keeps_old_feedback_history(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    write(tmp_path, 'quality/first.md', '第一轮作者意见')
    write(tmp_path, 'quality/second.md', '第二轮批准的返修意见')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/first.md'}}
    install_legacy_length_feedback(tmp_path, state)
    first = tmp_path / state['values']['author_feedback_file']
    raw = first.read_bytes()
    state.update(p.repair_ready(state, 'quality/second.md')['updates'])
    install_legacy_length_feedback(tmp_path, state)
    second = tmp_path / state['values']['author_feedback_file']
    assert state['lengthRepairCount'] == 1
    assert first != second and first.read_bytes() == raw
    assert '第二轮批准的返修意见' in second.read_text(encoding='utf-8')


def test_unconfigured_old_book_has_no_new_length_requirement(tmp_path):
    q = quality()
    write(tmp_path, 'story/0001/chapter.md', '已存在的旧作品。')
    assert q.assess(tmp_path, '0001', '')['status'] == 'unconfigured'
    assert q.gate_report(tmp_path, '0001', '', {'verdict': 'pass'})['verdict'] == 'pass'
    definition = literary_graph(json.loads((PLUGIN / 'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8')))
    assert policy().parameters({'values': {'chapter_number': '0001'}}, definition)['target_word_count'] == ''


def test_fresh_in_range_report_is_passed_and_stale_report_rejected(tmp_path):
    q = quality()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 5000)
    assert q.assess(tmp_path, '0001', '4800-5200')['status'] == 'pass'
    assert q.gate_report(tmp_path, '0001', '4800-5200', {'verdict': 'pass'})['verdict'] == 'pass'
    with pytest.raises(ValueError):
        q.gate_report(tmp_path, '0001', '4800-5200', {'verdict': 'pass', 'body_sha256': 'f' * 64})


def test_quality_paths_cannot_escape_book(tmp_path):
    q = quality()
    for invalid in ['../0001', '0000', '/tmp/outside']:
        with pytest.raises(ValueError):
            q.assess(tmp_path, invalid, '5000')


def test_in_range_polish_replaces_stale_progress_and_advances(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 5000)
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}, 'lengthCheck': {'status': 'short'}}
    result = p.next_action(tmp_path, state, 'polish')
    assert result['stage'] == 'post-hoc'
    assert result['updates']['lengthCheck']['status'] == 'pass'


def test_in_range_polish_refreshes_evidence_and_restores_original_author_feedback(tmp_path):
    p = policy()
    q = quality()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    write(tmp_path, 'quality/author.md', '保留旧徒亲自承认的代价。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/author.md'}}
    install_legacy_length_feedback(tmp_path, state)
    q.prepare_guidance(tmp_path, '0001', '4800-5200')
    body.write_text('衣' * 5002, encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'post-hoc'
    assert action['updates']['values']['author_feedback_file'] == 'quality/author.md'
    assert action['updates']['lengthRepairFeedback'] == {}
    evidence = json.loads((tmp_path / 'quality/length/0001.json').read_text(encoding='utf-8'))
    assert evidence['actual'] == 5002 and evidence['body_sha256'] == hashlib.sha256(body.read_bytes()).hexdigest()
    context = (tmp_path / 'cache/quality/0001/length_context.md').read_text(encoding='utf-8')
    assert '5002' in context and '规划参考' in context and '至少净增加 1400' not in context


@pytest.mark.parametrize('number', ['1', 1])
def test_feedback_origin_accepts_existing_short_chapter_number_inputs(tmp_path, number):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    state = {'values': {'chapter_number': number, 'target_word_count': '4800-5200'}}
    install_legacy_length_feedback(tmp_path, state)
    body.write_text('衣' * 5002, encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'post-hoc'
    assert action['updates']['values']['author_feedback_file'] == ''


def test_polish_and_reader_workflows_wire_real_length_evidence():
    root = PLUGIN / 'resources/workflows'
    polish = literary_graph(json.loads((root / 'polish/definition.json').read_text(encoding='utf-8')))
    nodes = {n['id']: n for n in polish['nodes']}
    assert nodes['script_length_context']['node_params']['script_name'] == 'manuscript_quality'
    assert any(e['source'] == 'script_length_context' and e['target'] == 'gw_polish_scope' for e in polish['edges'])
    for name in ['agent_sc', 'agent_pl']:
        key='revision_source_model' if name=='agent_sc' else 'revision_editor_model'
        assert '{{'+key+'}}' in nodes[name]['first_message']
    assert ('agent_pl','script_local_candidate') in {(e['source'],e['target']) for e in polish['edges']}
    assert nodes['script_local_prepare']['node_params']['script_name']=='local_revision'
    assert '{{pp_length_context_file}}' in nodes['agent_pp']['first_message']
    assert 'pp_length_context_file' in nodes['agent_pp']['var_bindings']
    reader = literary_graph(json.loads((root / 'reader-sim/definition.json').read_text(encoding='utf-8')))
    assert any(e['source'] == 'script_length_context' and e['target'] == 'script_reader_freeze' for e in reader['edges'])
    assert any(e['source'] == 'gw_reader_parallel' and e['target'] == 'agent_context_reader' for e in reader['edges'])
    assert all('{{length_context_file}}' not in n['first_message'] for n in reader['nodes']
               if n['node_type'] == 'agent')
    assert any(n['id'] == 'script_length_gate' for n in reader['nodes'])
    assert any(e['source'] == 'script_reader_commit' and e['target'] == 'script_length_gate' for e in reader['edges'])


def test_cli_gates_current_report_and_legacy_alias(tmp_path):
    import subprocess
    import sys
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    report = {'chapter_number': '0001', 'verdict': 'pass', 'body_sha256': hashlib.sha256(body.read_bytes()).hexdigest()}
    for relative in ['story/0001/reader_report.json', 'quality/reader_report.json']:
        write(tmp_path, relative, json.dumps(report))
    script = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    proc = subprocess.run([sys.executable, str(script), 'gate-reader', '--chapter', '0001', '--target', '4800-5200'], cwd=tmp_path, capture_output=True, text=True, encoding='utf-8')
    assert proc.returncode == 0, proc.stderr
    for relative in ['story/0001/reader_report.json', 'quality/reader_report.json']:
        updated = json.loads((tmp_path / relative).read_text(encoding='utf-8'))
        assert updated['verdict'] == 'revise' and updated['length_check']['actual'] == 3400
        assert updated['body_sha256'] == report['body_sha256']
