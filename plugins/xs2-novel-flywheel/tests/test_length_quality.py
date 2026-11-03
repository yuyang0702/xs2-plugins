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


def test_count_prose_excludes_titles_punctuation_and_formatting():
    q = quality()
    assert q.count_prose('# 第0001章\n\n第1章 · 补经痕迹\n\n“还我衣裳。”\nShe said, "Not today!"') == 8
    assert q.count_prose('𠀀说：“好。”') == 3


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


def test_length_retry_is_bounded_and_keeps_body_and_feedback(tmp_path):
    q = quality()
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    original = write(tmp_path, 'quality/author.md', '保留阿福救人的事实，勿替他免除伪证责任。')
    state = {'mode': 'short', 'values': {'chapter_number': '0001', 'target_word_count': '4800-5200', 'author_feedback_file': 'quality/author.md'}}
    action = p.next_action(tmp_path, state, 'polish')
    assert action['action'] == 'advance' and action['stage'] == 'polish'
    assert action['updates']['lengthRepairCount'] == 1
    feedback = tmp_path / action['updates']['values']['author_feedback_file']
    assert original.read_text(encoding='utf-8') in feedback.read_text(encoding='utf-8')
    assert body.read_text(encoding='utf-8') == '衣' * 3400
    state.update(action['updates']);state['lengthRepairCount'] = 2
    stopped = p.next_action(tmp_path, state, 'polish')
    assert stopped['action'] == 'pause' and '字数' in stopped['reason']
    assert list((tmp_path / 'quality/length-repairs/0001').rglob('before.md'))


def test_length_gate_runs_before_posthoc_and_export_even_for_legacy_pass(tmp_path):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    write(tmp_path, 'story/0001/reader_report.json', json.dumps({'verdict': 'pass', 'body_sha256': hashlib.sha256(body.read_bytes()).hexdigest()}))
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    for stage in ['post-hoc', 'export']:
        with pytest.raises(ValueError):
            p.launch_check(tmp_path, state, stage)


def test_repeated_length_repairs_replace_old_budget_but_keep_original_author_feedback(tmp_path):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    original = write(tmp_path, 'quality/author.md', '保留师徒的迟疑，不替阿福免除责任。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/author.md'}}
    first = p.next_action(tmp_path, state, 'polish')
    state.update(first['updates'])
    first_feedback = tmp_path / state['values']['author_feedback_file']
    first_bytes = first_feedback.read_bytes()
    body.write_text('衣' * 4676, encoding='utf-8')
    second = p.next_action(tmp_path, state, 'polish')
    text = (tmp_path / second['updates']['values']['author_feedback_file']).read_text(encoding='utf-8')
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
    state.update(p.next_action(tmp_path, state, 'polish')['updates'])
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
    state.update(p.next_action(tmp_path, state, 'polish')['updates'])
    feedback = tmp_path / state['values']['author_feedback_file']
    feedback.write_text(feedback.read_text(encoding='utf-8') + '\n作者新增：不改变旧徒年龄。', encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    text = (tmp_path / action['updates']['values']['author_feedback_file']).read_text(encoding='utf-8')
    assert '作者新增：不改变旧徒年龄。' in text


def test_reader_repair_has_fresh_bounded_length_budget_without_erasing_history(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    write(tmp_path, 'quality/reader-repair.md', '落实前夫当场同意交易的动作。')
    state = {'autoLengthRepairLimit': 3, 'lengthRepairCount': 3, 'readerRepairCount': 1,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    state.update(p.repair_ready(state, 'quality/reader-repair.md')['updates'])
    assert state['lengthRepairCount'] == 0
    assert state['lengthRepairTotal'] == 3
    assert state['readerRepairCount'] == 2
    action = p.next_action(tmp_path, state, 'polish')
    assert action['action'] == 'advance' and action['stage'] == 'polish'
    assert action['updates']['lengthRepairCount'] == 1
    assert action['updates']['lengthRepairTotal'] == 4
    state.update(action['updates'])
    for _ in range(2):
        state.update(p.next_action(tmp_path, state, 'polish')['updates'])
    assert p.next_action(tmp_path, state, 'polish')['action'] == 'pause'


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


def test_legacy_in_progress_content_repair_gets_one_tracked_cycle_not_unbounded_resets(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    state = {'autoLengthRepairLimit': 3, 'lengthRepairCount': 3, 'readerRepairCount': 2,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    first = p.next_action(tmp_path, state, 'polish')
    assert first['action'] == 'advance'
    assert first['updates']['lengthRepairCycle'] == 2
    assert first['updates']['lengthRepairCount'] == 1
    assert first['updates']['lengthRepairTotal'] == 4
    state.update(first['updates'])
    for _ in range(2):
        action = p.next_action(tmp_path, state, 'polish')
        assert action['action'] == 'advance'
        state.update(action['updates'])
    assert state['lengthRepairTotal'] == 6
    assert p.next_action(tmp_path, state, 'polish')['action'] == 'pause'


def test_legacy_first_draft_limit_is_not_reset_by_new_cycle_tracking(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    state = {'autoLengthRepairLimit': 3, 'lengthRepairCount': 3,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    assert policy().next_action(tmp_path, state, 'polish')['action'] == 'pause'


def test_identical_body_across_content_repair_cycles_keeps_old_feedback_history(tmp_path):
    p = policy()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    write(tmp_path, 'quality/first.md', '第一轮作者意见')
    write(tmp_path, 'quality/second.md', '第二轮批准的返修意见')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/first.md'}}
    state.update(p.next_action(tmp_path, state, 'polish')['updates'])
    first = tmp_path / state['values']['author_feedback_file']
    raw = first.read_bytes()
    state.update(p.repair_ready(state, 'quality/second.md')['updates'])
    action = p.next_action(tmp_path, state, 'polish')
    second = tmp_path / action['updates']['values']['author_feedback_file']
    assert action['updates']['lengthRepairCount'] == 1
    assert first != second and first.read_bytes() == raw
    assert '第二轮批准的返修意见' in second.read_text(encoding='utf-8')


def test_unconfigured_old_book_has_no_new_length_requirement(tmp_path):
    q = quality()
    write(tmp_path, 'story/0001/chapter.md', '已存在的旧作品。')
    assert q.assess(tmp_path, '0001', '')['status'] == 'unconfigured'
    assert q.gate_report(tmp_path, '0001', '', {'verdict': 'pass'})['verdict'] == 'pass'
    definition = json.loads((PLUGIN / 'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8'))
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
    assert result['stage'] == 'reader-sim'
    assert result['updates']['lengthCheck']['status'] == 'pass'


def test_in_range_polish_refreshes_evidence_and_restores_original_author_feedback(tmp_path):
    p = policy()
    q = quality()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    write(tmp_path, 'quality/author.md', '保留旧徒亲自承认的代价。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200',
                        'author_feedback_file': 'quality/author.md'}}
    state.update(p.next_action(tmp_path, state, 'polish')['updates'])
    q.prepare_guidance(tmp_path, '0001', '4800-5200')
    body.write_text('衣' * 5002, encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'reader-sim'
    assert action['updates']['values']['author_feedback_file'] == 'quality/author.md'
    assert action['updates']['lengthRepairFeedback'] == {}
    evidence = json.loads((tmp_path / 'quality/length/0001.json').read_text(encoding='utf-8'))
    assert evidence['actual'] == 5002 and evidence['body_sha256'] == hashlib.sha256(body.read_bytes()).hexdigest()
    context = (tmp_path / 'cache/quality/0001/length_context.md').read_text(encoding='utf-8')
    assert '5002' in context and '至少净增加 1400' not in context


@pytest.mark.parametrize('number', ['1', 1])
def test_feedback_origin_accepts_existing_short_chapter_number_inputs(tmp_path, number):
    p = policy()
    body = write(tmp_path, 'story/0001/chapter.md', '衣' * 3400)
    state = {'values': {'chapter_number': number, 'target_word_count': '4800-5200'}}
    state.update(p.next_action(tmp_path, state, 'polish')['updates'])
    body.write_text('衣' * 5002, encoding='utf-8')
    action = p.next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'reader-sim'
    assert action['updates']['values']['author_feedback_file'] == ''


def test_polish_and_reader_workflows_wire_real_length_evidence():
    root = PLUGIN / 'resources/workflows'
    polish = json.loads((root / 'polish/definition.json').read_text(encoding='utf-8'))
    nodes = {n['id']: n for n in polish['nodes']}
    assert nodes['script_length_context']['node_params']['script_name'] == 'manuscript_quality'
    assert any(e['source'] == 'script_length_context' and e['target'] == 'gw_polish_scope' for e in polish['edges'])
    for name in ['agent_sc', 'agent_pl', 'agent_pp']:
        assert '{{length_context_file}}' in nodes[name]['first_message']
        assert 'length_context_file' in nodes[name]['var_bindings']
    reader = json.loads((root / 'reader-sim/definition.json').read_text(encoding='utf-8'))
    assert any(e['source'] == 'script_length_context' and e['target'] == 'agent_reader' for e in reader['edges'])
    assert '{{length_context_file}}' in next(n for n in reader['nodes'] if n['id'] == 'agent_reader')['first_message']
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
