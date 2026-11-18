import json

import pytest

from test_length_quality import PLUGIN, policy, quality, write


@pytest.mark.parametrize('settings', [None, {'schema': 1, 'ownership': 'author'},
    {'schema': 1, 'ownership': 'planner', 'minimum': 4500, 'maximum': 5200}])
@pytest.mark.parametrize('actual', [3200, 6100])
def test_legacy_ranges_still_show_counts_but_allow_polish_archive_and_export(tmp_path, settings, actual):
    body = write(tmp_path, 'story/0001/chapter.md', '字' * actual)
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4500-5200'}}
    write(tmp_path, '.novel-project.json', json.dumps(state))
    if settings:
        write(tmp_path, 'meta/length_policy.json', json.dumps(settings))
    service = policy()
    for stage in ('post-hoc', 'export'):
        service.launch_check(tmp_path, state, stage)
    action = service.next_action(tmp_path, state, 'polish')
    assert action['stage'] == 'post-hoc'
    result = action['updates']['lengthCheck']
    assert result['actual'] == actual and result['status'] in ('short', 'long')
    assert not quality().is_blocking(result)
    assert body.read_text(encoding='utf-8') == '字' * actual
    assert not (tmp_path/'quality/length-repairs').exists()


def test_formal_workflows_bind_advisory_length_through_manuscript_entrypoints():
    for stage, nodes in {
        'mvp': {'script_guard_prepare', 'script_multi_assemble', 'script_multi_scene_1', 'script_composition_prepare'},
        'polish': {'script_local_prepare', 'script_length_context', 'script_composition_prepare'},
    }.items():
        definition = json.loads((PLUGIN/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8-sig'))
        params = {node['id']: node['node_params'] for node in definition['nodes'] if node['id'] in nodes}
        assert set(params) == nodes
        assert all('--advisory-length' in row['script_argv'] for row in params.values())


def test_old_length_only_request_restores_author_notes_and_counts_as_content(tmp_path):
    body = write(tmp_path, 'story/0001/chapter.md', '甲把灯递了过去。\n\n「那留下的人呢？」')
    write(tmp_path, 'quality/author.md', '保留这句接话。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '3000-4000',
                        'author_feedback_file': 'quality/author.md'}}
    q = quality()
    receipt = q.correction_feedback(tmp_path, state, q.assess(tmp_path, '0001', '3000-4000'))
    state['values']['author_feedback_file'] = receipt['path']
    state['lengthRepairFeedback'] = receipt
    write(tmp_path, '.novel-project.json', json.dumps(state))
    original = body.read_bytes()
    out = q.prepare_execution(tmp_path, '0001', '3000-4000', 'length_only', feedback_path=receipt['path'], advisory=True)
    assert out['polish_pass'] == 'content' and not out['length_commit_guard']
    assert out['author_feedback_file'] == 'quality/author.md'
    guide = (tmp_path/out['length_context_file']).read_text(encoding='utf-8')
    assert '规划参考' in guide and '至少净增加' not in guide
    assert body.read_bytes() == original


def test_local_edit_freezes_the_reference_but_has_no_minimum(tmp_path):
    from test_local_revision import module
    write(tmp_path, 'story/0001/chapter.md', '「那留下的人呢？」\n\n她停了一下。')
    write(tmp_path, 'meta/length_policy.json', '{"schema":1,"ownership":"author"}')
    local = module()
    outputs = local.prepare(tmp_path, '0001', 'advisory', '3000-4000', advisory=True, scoped_review=True)
    source = json.loads((tmp_path/outputs['revision_source_input']).read_text(encoding='utf-8'))
    assert source['length']['status'] == 'short'
    assert source['length']['blocking'] is False


def test_multi_writer_accepts_a_short_scene_and_chapter_but_checks_structure():
    from test_multi_scene import module
    multi = module()
    bodies = ['后来还能闻见潮气。', '灯亮了。', '她握住绳头。', '门合上。', '有人走回去。', '船驶出雾里。']
    assert multi.validate(bodies, '3000-4000', 'third_person', advisory=True) is None
    bodies[2] = '# 这里还是场景标题'
    assert multi.validate(bodies, '3000-4000', 'third_person', advisory=True)[1].startswith('[scene_markup]')
