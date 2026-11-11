from runtime_graph import literary_graph
import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]


def module():
    path = PLUGIN / 'resources/script-library/xs2/multi_scene/multi_scene.py'
    spec = importlib.util.spec_from_file_location('test_scene_writer', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_scene_budgets_sum_to_book_target_without_rounding_loss():
    lo, hi = module().budgets('5000-5300')
    assert sum(lo) == 5000 and sum(hi) == 5300
    assert len(lo) == len(hi) == 6 and all(0 < a <= b for a, b in zip(lo, hi))


def test_assembly_refuses_short_duplicate_and_shifted_pov():
    m = module()
    lo, hi = m.budgets('300-330')
    bodies = [c * ((a + b) // 2) for c, a, b in zip('春夏秋冬梅竹', lo, hi)]
    assert m.validate(bodies, '300-330', 'third_person') is None
    assert m.validate(['春'] + bodies[1:], '300-330', 'third_person')[0] == 0
    assert m.validate(bodies[:1] + bodies[:1] + bodies[2:], '300-330', 'third_person')[0] == 1
    assert m.validate(['我' + bodies[0][1:]] + bodies[1:], '300-330', 'third_person')[0] == 0
    assert m.validate(['“我”' + bodies[0][1:]] + bodies[1:], '300-330', 'third_person') is None


def test_normal_mvp_routes_all_scene_writers_through_gate_before_body():
    definition = literary_graph(json.loads((PLUGIN / 'resources/workflows/mvp/definition.json').read_text(encoding='utf8')))
    nodes = {n['id']: n for n in definition['nodes']}
    assert '2000' not in str(nodes['agent_nw'].get('node_params'))
    edges = {(e['source'], e['target']) for e in definition['edges']}
    assert ('script_multi_join_5', 'agent_si') in edges
    assert ('script_multi_scene_6', 'script_multi_assemble') in edges
    assert ('script_multi_assemble', 'script_guard_prepare') in edges
    assert ('script_guard_expression_commit', 'script_guard_finish') in edges
    assert ('script_guard_finish', 'script_si_post') in edges
    assert ('script_multi_plan', 'gw-mqdqscyd-0') in edges
    assert ('gw-mqdqscyd-0', 'gw-multi-active-1') in edges
    assert ('agent_sw', 'script_guard_prepare') in edges
    for i, writer in enumerate(('agent_aw', 'agent_dw', 'agent_iw', 'agent_dsw', 'agent_tw', 'agent_si'), 1):
        gate = f'script_multi_scene_{i}'
        assert (writer, gate) in edges
        next_node = 'script_multi_assemble' if i == 6 else f'script_multi_join_{i}'
        assert (gate, next_node) in edges
        if i < 6:
            active = f'gw-multi-active-{i}'
            skip = f'script_multi_skip_{i}'
            assert (active, writer) in edges and (active, skip) in edges and (skip, next_node) in edges
            assert next(e for e in definition['edges'] if e['source']==active and e['target']==writer)['condition']['expression']==f'{{{{multi_active_{i}}}}}==yes'
        assert nodes[writer]['output_file_path'].endswith('.txt')
        assert 'json_required_fields' not in nodes[writer]['node_params']
def test_gate_retry_preserves_body_until_all_scenes_are_valid(tmp_path, monkeypatch, capsys):
    m = module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TASK_ID', 'task-a')
    monkeypatch.setattr('sys.argv', ['multi_scene', 'prepare', '--target', '300-330', '--pov', 'third_person'])
    m.main()
    assert 'multi_dir:cache/multi/task-a' in capsys.readouterr().out
    directory = tmp_path / 'cache/multi/task-a'
    lo, _ = m.budgets('300-330')
    bodies = [c * n for c, n in zip('春夏秋冬梅竹', lo)]
    for i, body in enumerate(bodies, 1):
        m.save_json(directory / f'validated-{i}.json', {'body': body})
        m.save_json(directory / f'brief-{i}.json', {'entry': '已成立的起点', 'turn': '本场行动', 'exit': '交棒'})
    m.save_json(directory / 'validated-4.json', {'body': '冬'})
    monkeypatch.setattr('sys.argv', ['multi_scene', 'assemble', '--target', '300-330', '--pov', 'third_person'])
    m.main()
    assert 'target="agent_dsw"' in capsys.readouterr().out
    assembly = tmp_path / 'cache/si/chapter.json'
    assert not assembly.exists()
    m.save_json(directory / 'validated-4.json', {'body': bodies[3]})
    m.main()
    draft = m.read_json(assembly)['body']
    assert draft.split('\n\n') == bodies
    assert m.length.count_prose(draft) == 300

def test_scene_gate_reports_its_own_budget_before_other_writers_finish():
    m = module()
    error = m.scene_problem('余青棠回到河边。', 700, 742, 'third_person')
    assert '[scene_length]' in error and '700' in error
    assert m.scene_problem('春' * 710, 700, 742, 'third_person') is None

def test_short_scene_retry_inserts_new_prose_without_rewriting_seed(tmp_path):
    m = module()
    seed = '春' * 30 + '\n\n' + '夏' * 30
    issue = m.accept_scene_attempt(tmp_path, 1, seed, 100, 120, 'third_person')
    assert '[scene_length]' in issue
    retry = (tmp_path / 'retry-1.md').read_text(encoding='utf-8')
    assert '至少 40' in retry and '只返回新增正文' in retry
    assert m.accept_scene_attempt(tmp_path, 1, '秋' * 45, 100, 120, 'third_person') is None
    expected = '春' * 30 + '\n\n' + '秋' * 45 + '\n\n' + '夏' * 30
    assert m.read_json(tmp_path / 'validated-1.json')['body'] == expected


def test_single_line_provider_draft_can_be_expanded_without_splitting_dialogue(tmp_path):
    m = module()
    seed = '春' * 25 + '。她问：“天黑了吗？要不要走？”' + '夏' * 35 + '。'
    issue = m.accept_scene_attempt(tmp_path, 1, seed, 100, 130, 'third_person')
    assert '新增片段' in issue
    guard = m.read_json(tmp_path / 'expansion-1.json')
    assert '“天黑了吗？要不要走？”' in guard['before'] or '“天黑了吗？要不要走？”' in guard['after']
    assert guard['before'] + guard['after'] == seed
    assert m.accept_scene_attempt(tmp_path, 1, '秋' * 40, 100, 130, 'third_person') is None


def test_fallback_accepts_plain_prose_and_exact_legacy_envelope():
    m = module()
    body = '她问：“今天走吗？”\n他的手还按着船桨。'
    assert m.scene_text(body) == body
    assert m.scene_text(json.dumps({'body': body}, ensure_ascii=False)) == body
    assert m.scene_text('{"body":') == ''
    assert m.scene_text('{"body":"句子","notes":"说明"}') == ''


def test_rejected_expansion_refreshes_feedback_without_publishing_or_mutating_seed(tmp_path):
    m = module()
    seed = '春' * 30 + '\n\n' + '夏' * 30
    m.accept_scene_attempt(tmp_path, 1, seed, 100, 120, 'third_person')
    before = (tmp_path / 'expansion-1.json').read_bytes()
    issue = m.accept_scene_attempt(tmp_path, 1, '春' * 30, 100, 120, 'third_person')
    assert '[scene_duplicate]' in issue
    assert '[scene_duplicate]' in (tmp_path / 'retry-1.md').read_text(encoding='utf8')
    assert (tmp_path / 'expansion-1.json').read_bytes() == before
    assert not (tmp_path / 'validated-1.json').exists()
    assert m.accept_scene_attempt(tmp_path, 1, '秋' * 45, 100, 120, 'third_person') is None


def test_reset_scene_preserves_other_scenes_and_archives_failed_seed(tmp_path):
    m = module()
    seed = {'before': '已经验过灯。', 'after': '她离开了。'}
    brief = {'entry': '验灯已经完成', 'turn': '协商结算', 'exit': '收款', 'knowledge': '只知道现场事实'}
    m.save_json(tmp_path / 'expansion-5.json', seed)
    m.save_json(tmp_path / 'brief-5.json', brief)
    m.save_json(tmp_path / 'validated-4.json', {'body': '第四场已通过'})
    keep = (tmp_path / 'validated-4.json').read_bytes()
    m.reset_scene(tmp_path, 5, 950, 1007, 'scene_duplicate')
    assert not (tmp_path / 'expansion-5.json').exists()
    assert (tmp_path / 'validated-4.json').read_bytes() == keep
    assert list((tmp_path / 'rejected').glob('scene-5-*.json'))
    retry = (tmp_path / 'retry-5.md').read_text(encoding='utf8')
    assert '【本场重写】' in retry and '验灯已经完成' in retry and '协商结算' in retry
    assert '已经验过灯。' not in retry


def test_scene_specific_contract_follows_background_and_target_is_inside_budget(tmp_path, monkeypatch, capsys):
    m = module()
    definition = literary_graph(json.loads((PLUGIN / 'resources/workflows/mvp/definition.json').read_bytes()))
    for node in definition['nodes']:
        if node.get('agent_type') == 'novel-multi-scene-writer':
            prompt = node['first_message']
            assert prompt.rfind('{{multi_brief_') > prompt.rfind('{{short_context_file}}')
            assert '至少六个' not in prompt
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TASK_ID', 'budget-test')
    directory = tmp_path / 'cache/multi/budget-test'
    m.save_json(directory / 'plan.json', {'focus': '主角', 'scenes': [
        {'id': i, 'entry': '起点', 'turn': '推进', 'exit': '终点', 'knowledge': '已知'} for i in range(1, 7)]})
    monkeypatch.setattr('sys.argv', ['multi_scene', 'plan', '--target', '5000-5300', '--pov', 'third_person'])
    m.main()
    for i in range(1, 7):
        row = m.read_json(directory / f'brief-{i}.json')
        assert row['minimum'] <= row['draft_target'] <= row['maximum']


def test_scene_workflow_retries_a_complete_scene_without_inserting_the_old_seed(tmp_path):
    m = module()
    m.save_json(tmp_path / 'brief-1.json', {'entry': '进门', 'turn': '取物', 'exit': '离开', 'draft_target': 110})
    issue = m.accept_full_scene_attempt(tmp_path, 1, '春' * 50, 100, 150, 'third_person')
    assert '[scene_length]' in issue
    assert not (tmp_path / 'expansion-1.json').exists()
    assert '完整场景' in (tmp_path / 'retry-1.md').read_text(encoding='utf8')
    assert m.accept_full_scene_attempt(tmp_path, 1, '夏' * 115, 100, 150, 'third_person') is None
    assert m.read_json(tmp_path / 'validated-1.json')['body'] == '夏' * 115


def test_draft_allocation_has_room_while_final_word_count_still_needs_polish():
    m = module()
    bodies = [c * n for c, n in zip('春夏秋冬梅竹', [710, 680, 1100, 1331, 1050, 750])]
    assert sum(map(m.length.count_prose, bodies)) > 5300
    assert m.validate(bodies, '5000-5300', 'third_person') is None
    assert m.validate([c * 300 for c in '春夏秋冬梅竹'], '5000-5300', 'third_person') is not None
