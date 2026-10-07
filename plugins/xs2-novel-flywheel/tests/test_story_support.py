import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'resources/script-library/xs2/story_support/story_support.py'
spec = importlib.util.spec_from_file_location('test_story_support', MODULE)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def proposal(root, chapter='0001', quote='隔离站通风故障', mode='serial'):
    support.write(root, 'meta/world_foundation.md', '# 世界\n隔离站通风故障，人群不能聚集。')
    source = support.context(root, chapter, '通风与合作')
    raw = {'reply': '优先让主角通过合作恢复通风。', 'options': [{'id': 'A', 'title': '证据与合作',
           'reason': '沿用前文压力', 'chapters': [{'chapter': chapter, 'goal': '恢复通风', 'conflict': '记录保管者怕担责',
           'choice': '交换责任而非强夺记录', 'payoff': '救人并获得合作', 'setup': [{'source_id': 'meta/world_foundation.md', 'quote': quote, 'use': '触发行动'}]}]}]}
    reply, options = support.parse_proposal(json.dumps(raw, ensure_ascii=False), source, '创意', mode)
    return {'id': 'request-one', 'status': 'completed', 'plot_options': options, 'plot_source': source['source_hashes']}


def test_actual_upstream_files_and_runtime_functions():
    manifest = json.loads((MODULE.parent / 'UPSTREAM.json').read_text())
    assert len(manifest['projects']) == 3
    for project in manifest['projects']:
        for file in project['files']:
            original = MODULE.parent / 'vendor' / project['project'] / file['path']
            assert hashlib.sha256(original.read_bytes()).hexdigest() == file['sha256']
    assert support.methods()['indexed_sections'] > 0
    assert any(m['id'] == 'D15' for m in support.methods()['directions'])
    text = support.upstream.story_state_text({'characters': [{'name': '赵磊', 'motivation': '救人但怕担责', 'current_status': '缺氧'}]})
    assert '救人但怕担责' in text and '缺氧' in text


def test_adoption_is_explicit_idempotent_and_consumed_by_real_context(tmp_path):
    entry = proposal(tmp_path)
    assert not (tmp_path/'outline/near_term_outline.md').exists()
    support.write(tmp_path, 'outline/near_term_outline.md', '原有手动规划')
    # Changing the outline after analysis is a genuine stale-plan condition.
    with pytest.raises(ValueError, match='已过期'): support.apply_plan(tmp_path, entry, 'A')
    entry['plot_source'] = support.source_hashes(tmp_path)
    receipt = support.apply_plan(tmp_path, entry, 'A')
    assert receipt['chapters'] == ['0001']
    assert support.apply_plan(tmp_path, entry, 'A')['already_applied']
    support.prepare_context(tmp_path, '0001', check=True)
    text = support.read(tmp_path, 'cache/story-support/context.md')
    assert '交换责任而非强夺记录' in text and '救人并获得合作' in text
    assert '原有手动规划' in support.read(tmp_path, 'outline/near_term_outline.md')
    audit = support.load(tmp_path, 'story/0001/planning_context.json')
    assert audit['adopted_request'] == 'request-one' and len(audit['projects']) == 3


def test_fabricated_anchor_and_written_chapter_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='无法核实'): proposal(tmp_path, quote='不存在的回风阀')
    entry = proposal(tmp_path)
    support.write(tmp_path, 'story/0001/chapter.md', '已有正文')
    entry['plot_source'] = support.source_hashes(tmp_path)
    with pytest.raises(ValueError, match='已经写出'): support.apply_plan(tmp_path, entry, 'A')


def test_changed_foundation_keeps_author_selection_for_reconciliation(tmp_path):
    entry = proposal(tmp_path)
    support.apply_plan(tmp_path, entry, 'A')
    support.write(tmp_path, 'meta/character_profiles.md', '新确定的人物背景，需核对既有选择。')
    check = support.preflight(tmp_path, '0001')
    assert not check['ready'] and '创作助手' in check['message']
    ctx = support.prepare_context(tmp_path, '0001')
    assert ctx['adopted_plan']['compatible'] is False
    assert '交换责任而非强夺记录' in ctx['adopted_plan']['content']
    assert '待重新协调' in support.read(tmp_path, 'cache/story-support/context.md')
    with pytest.raises(ValueError): support.prepare_context(tmp_path, '0001', check=True)


def commit_chapter(root, chapter='0001', content='赵磊关上通风阀，决定留下救人。'):
    support.write(root, f'story/{chapter}/chapter.md', content)
    support.begin_review(root, chapter)
    support.write(root, 'cache/observer/obs_output.json', {'confirmed_state': {'characters': [{'name': '赵磊',
          'snapshot': {'location': '隔离站', 'knowledge': '通风异常', 'goal': '救人'}, 'evidence': '决定留下救人'}]}, 'character_diff': {'state_changes': []}})
    support.write(root, 'cache/arbiter/arb_output.json', {'story_confirmed': {'landed': [{'planned': '留下救人', 'evidence': '章末'}]}, 'world_rulings': {'entries': []}})
    return support.commit(root, chapter)


def test_confirmed_archive_updates_and_historical_repair_invalidates_dependents(tmp_path):
    commit_chapter(tmp_path)
    support.write(tmp_path, 'outline/near_term_outline.md', '### 第2章 · 继续')
    assert support.preflight(tmp_path, '0002')['ready']
    commit_chapter(tmp_path, '0002')
    assert support.archive_status(tmp_path)['updated_chapter'] == '0002'
    support.write(tmp_path, 'story/0001/chapter.md', '第一章被返修，决定不同。')
    status = support.archive_status(tmp_path)
    assert status['updated_chapter'] == '' and status['stale_chapters'] == ['0001', '0002']
    assert support.preflight(tmp_path, '0003')['action'] == 'post-hoc'


def test_review_cannot_commit_changed_body_or_false_evidence(tmp_path):
    support.write(tmp_path, 'story/0001/chapter.md', '真实原句')
    support.begin_review(tmp_path, '0001')
    support.write(tmp_path, 'story/0001/chapter.md', '原稿改变')
    with pytest.raises(ValueError, match='审核过程中'): support.commit(tmp_path, '0001')
    support.begin_review(tmp_path, '0001')
    support.write(tmp_path, 'cache/observer/obs_output.json', {'confirmed_state': {'characters': [{'name':'赵磊','evidence':'模型编造的原句'}]}})
    support.write(tmp_path, 'cache/arbiter/arb_output.json', {'story_confirmed': {}})
    with pytest.raises(ValueError, match='无法核实'): support.commit(tmp_path, '0001')
    assert not (tmp_path/'story/0001/confirmed_state.json').exists()


def test_no_distillation_and_short_story_remain_supported(tmp_path):
    entry = proposal(tmp_path, mode='short')
    support.apply_plan(tmp_path, entry, 'A')
    assert support.preflight(tmp_path, '0001')['ready']
    with pytest.raises(ValueError, match='同一篇'): proposal(tmp_path, chapter='0002', mode='short')


def test_missing_outline_requests_planning_instead_of_restarting_advisor(tmp_path):
    commit_chapter(tmp_path)
    check = support.preflight(tmp_path, '0002')
    assert not check['ready'] and check['action'] == 'outline'


def test_workflow_graphs_connect_real_context_and_archive_commit():
    for stage in ('mvp','outline','story-plan','polish','reader-sim','post-hoc'):
        data = json.loads((ROOT/f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8'))
        assert any(n['id']=='script_story_context' for n in data['nodes'])
        assert any(e['source']=='__start__' and e['target']=='script_story_context' for e in data['edges'])
        assert all('{{story_support_context}}' in n['first_message'] for n in data['nodes'] if n['node_type']=='agent')
    post = json.loads((ROOT/'resources/workflows/post-hoc/definition.json').read_text(encoding='utf-8'))
    assert any(e['source']=='script_confirm_archive' and e['target']=='__end__' for e in post['edges'])


def test_planned_hooks_do_not_become_facts_until_exact_body_confirmation(tmp_path):
    support.write(tmp_path, 'story/0001/planned_hooks.json', [{'id':'h001','description':'门外密码','status':'resolved'}])
    commit_chapter(tmp_path)
    assert support.load(tmp_path, 'archive/hooks.json') == []
    support.begin_review(tmp_path, '0001')
    observer = support.load(tmp_path, 'cache/observer/obs_output.json')
    observer['confirmed_state']['hooks'] = [{'id':'h001','operation':'plant','description':'留下的线索','evidence':'决定留下救人'}]
    support.write(tmp_path, 'cache/observer/obs_output.json', observer)
    support.commit(tmp_path, '0001')
    assert support.load(tmp_path, 'archive/hooks.json')[0]['status'] == 'open'
    support.write(tmp_path, 'story/0002/chapter.md', '他向她承认那句话。')
    support.begin_review(tmp_path,'0002')
    support.write(tmp_path,'cache/observer/obs_output.json',{'confirmed_state':{'characters':[],'hooks':[{'id':'h001','operation':'resolve','evidence':'承认那句话'}]}})
    support.commit(tmp_path,'0002')
    assert support.load(tmp_path,'archive/hooks.json')[0]['status'] == 'resolved'
    assert support.load(tmp_path,'story/0002/confirmed_state.json')['characters'][0]['snapshot']['knowledge'] == '通风异常'


def test_wrong_chapter_world_cache_cannot_enter_confirmed_archive(tmp_path):
    support.write(tmp_path,'cache/we/world_state.json',{'world_time':'错误的未来时间'})
    state = commit_chapter(tmp_path)
    assert '错误的未来时间' not in json.dumps(state, ensure_ascii=False)


def test_nonfinite_scores_and_malformed_reading_lists_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='有效数字'):
        support.rank([{'scores':{'surprise':float('nan')}}])
    source=support.context(tmp_path)
    with pytest.raises(ValueError, match='文字列表'):
        support.parse_proposal(json.dumps({'reply':'建议','options':[{'chapters':[], 'risks':{'risk':'坏格式'}}]}),source,'创意')
