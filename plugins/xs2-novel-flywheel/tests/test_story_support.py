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


def test_deleted_chapter_blocks_later_production_even_when_outline_exists(tmp_path):
    support.write(tmp_path, "archive/chapter_resets/0002.json", {"operation": "delete"})
    support.write(tmp_path, "outline/near_term_outline.md", "### 第3章\n推进")
    check = support.preflight(tmp_path, "0003")
    assert not check["ready"] and check["reason_code"] == "chapter_missing"
    assert check["chapter"] == "0002"


def test_archive_refresh_clears_deleted_chapter_facts_when_no_valid_states_remain(tmp_path):
    support.write(tmp_path, "archive/hooks.json", [{"id": "old", "description": "已删除的事件"}])
    support.write(tmp_path, "archive/debts.json", [{"id": "old-debt"}])
    status = support.refresh_archive(tmp_path)
    assert status["updated_chapter"] == ""
    assert support.load(tmp_path, "archive/hooks.json") == []
    assert support.load(tmp_path, "archive/debts.json") == []
    assert "已删除的事件" not in support.read(tmp_path, "meta/hooks.md")
    assert any(m['id'] == 'D15' for m in support.methods()['directions'])
    text = support.upstream.story_state_text({'characters': [{'name': '赵磊', 'motivation': '救人但怕担责', 'current_status': '缺氧'}]})
    assert '救人但怕担责' in text and '缺氧' in text


def test_reader_reports_are_chapter_scoped_and_bound_to_reviewed_body(tmp_path):
    for chapter in ("0001", "0002"):
        support.write(tmp_path, f"story/{chapter}/chapter.md", f"第{chapter}章的正文")
        support.begin_reader(tmp_path, chapter)
        support.write(tmp_path, f"story/{chapter}/reader_report.json", {"verdict":"pass","summary":chapter})
        support.commit_reader(tmp_path, chapter)
    assert support.load(tmp_path, "story/0001/reader_report.json")["summary"] == "0001"
    assert support.load(tmp_path, "quality/reader_report.json")["chapter_number"] == "0002"
    support.begin_reader(tmp_path, "0001")
    support.write(tmp_path, "story/0001/chapter.md", "评估期间改了正文")
    with pytest.raises(ValueError, match="正文在评估过程中"):
        support.commit_reader(tmp_path, "0001")


def test_revision_context_uses_chapter_start_indexes_not_future_archive(tmp_path):
    commit_chapter(tmp_path)
    state = support.load(tmp_path, "story/0001/confirmed_state.json")
    state["indexes_before"] = {"hooks":[], "debts":[]}
    support.write(tmp_path, "story/0001/confirmed_state.json", state)
    support.write(tmp_path, "archive/hooks.json", [{"id":"h999","chapter_created":2,"description":"第二章才发生的秘密"}])
    support.prepare_context(tmp_path, "0001")
    assert "第二章才发生的秘密" not in support.read(tmp_path, "cache/story-support/0001/hooks-before.md")
    assert "不能把后续发生的事提前写成角色已知" in support.read(tmp_path, "cache/story-support/context.md")


def test_historical_context_excludes_full_book_current_state_and_ledgers(tmp_path):
    commit_chapter(tmp_path)
    support.write(tmp_path, "archive/hooks.json", [
        {"id":"h002", "chapter_created":2, "description":"第二章未来伏笔"}])
    support.write(tmp_path, "archive/debts.json", [
        {"id":"d002", "chapter_created":2, "description":"第二章未来债务"}])
    support.write(tmp_path, "meta/hooks.md", "第二章未来伏笔")
    support.write(tmp_path, "meta/debts.md", "第二章未来债务")
    support.write(tmp_path, "meta/conflict_ledger.md", "第二章未来冲突")
    support.write(tmp_path, "meta/current_world.md", "第二章未来世界状态")
    support.write(tmp_path, "meta/current_characters.md", "第二章未来人物状态")

    support.prepare_context(tmp_path, "0001")
    context = support.read(tmp_path, "cache/story-support/context.md")
    for future_fact in ("第二章未来伏笔", "第二章未来债务", "第二章未来冲突",
                        "第二章未来世界状态", "第二章未来人物状态"):
        assert future_fact not in context


def test_begin_review_never_uses_unfiltered_future_archive_as_chapter_start(tmp_path):
    commit_chapter(tmp_path)
    state = support.load(tmp_path, "story/0001/confirmed_state.json")
    state["indexes_before"] = {}
    support.write(tmp_path, "story/0001/confirmed_state.json", state)
    support.write(tmp_path, "archive/hooks.json", [
        {"id":"h002", "chapter_created":2, "description":"第二章未来伏笔"}])
    support.write(tmp_path, "archive/debts.json", [
        {"id":"d002", "chapter_created":2, "description":"第二章未来债务"}])

    support.begin_review(tmp_path, "0001")
    indexes = support.load(tmp_path, "cache/story-support/0001/indexes-before.json")
    assert indexes == {"hooks":[], "debts":[]}


def test_legacy_index_fallback_requires_creation_and_last_change_before_chapter(tmp_path):
    support.write(tmp_path, "story/0002/chapter.md", "本章正文")
    entries = [
        {"id":"h001", "chapter_created":1, "source_chapter":"0001", "description":"前文已埋"},
        {"id":"h002", "chapter_created":1, "source_chapter":"0003", "status":"resolved"},
        {"id":"h003", "chapter_created":1, "chapter_resolved":3},
        {"id":"h004", "chapter_created":1, "last_advanced":3},
        {"id":"h005", "chapter_created":3},
        {"id":"h006", "description":"来源不明"},
        {"id":"h007", "chapter_created":"未知"},
    ]
    support.write(tmp_path, "archive/hooks.json", entries)
    support.prepare_context(tmp_path, "0002")
    support.begin_review(tmp_path, "0002")
    indexes = support.load(tmp_path, "cache/story-support/0002/indexes-before.json")
    assert indexes["hooks"] == entries[:1]
    assert "前文已埋" in support.read(tmp_path, "cache/story-support/0002/hooks-before.md")


def test_context_without_adopted_plan_contains_target_outline_not_future_plans(tmp_path):
    support.write(tmp_path, "outline/near_term_outline.md",
                  "### 第1章\n" + "先前规划\n" * 1500 +
                  "\n### 第 2 章 · 借粮\n本章必须承担借粮的代价。\n"
                  "#### 场景选择\n承认自己的困境。\n"
                  "#### 第3章内的分场标题\n这仍属于第2章。\n"
                  "### 第3章\n未来才揭示的秘密。\n## 角色弧线\n未来的角色结局。\n")
    support.prepare_context(tmp_path, "0002")
    text = support.read(tmp_path, "cache/story-support/context.md")
    assert "本章必须承担借粮的代价" in text
    assert "承认自己的困境" in text
    assert "这仍属于第2章" in text
    assert "未来才揭示的秘密" not in text and "未来的角色结局" not in text


def test_chapter_plot_context_does_not_receive_future_outline_sections(tmp_path):
    support.write(tmp_path, "outline/near_term_outline.md",
                  "### 第1章\n第一章计划。\n### 第2章\n目标章节计划。\n"
                  "#### 场景拆分\n本章场景。\n### 第3章\n未来章节计划。")
    support.write(tmp_path, "outline/volume_outline.md",
                  "## 卷1（第1-10章）\n本卷后续转折与结局。\n"
                  "## 卷2（第11-20章）\n第二卷的未来规划。")

    context = support.context(tmp_path, "0002", scope="chapter")
    sources = {item["source_id"]: item["content"] for item in context["sources"]}
    assert sources["outline/near_term_outline.md"] == (
        "### 第2章\n目标章节计划。\n#### 场景拆分\n本章场景。")
    assert "outline/volume_outline.md" not in sources


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
    assert not check['ready'] and check['action'] == 'outline'
    assert check['reason_code'] == 'adopted_plan_stale'
    assert check['changed_sources'] == ['meta/character_profiles.md']
    assert '创作助手' in check['next_step'] and '仍保留' in check['message']
    ctx = support.prepare_context(tmp_path, '0001')
    assert ctx['adopted_plan']['compatible'] is False
    assert '交换责任而非强夺记录' in ctx['adopted_plan']['content']
    assert '待重新协调' in support.read(tmp_path, 'cache/story-support/context.md')
    with pytest.raises(ValueError): support.prepare_context(tmp_path, '0001', check=True)


def test_story_plan_changes_invalidate_adopted_chapter_plan(tmp_path):
    entry = proposal(tmp_path)
    support.apply_plan(tmp_path, entry, "A")
    support.write(tmp_path, "meta/story_plan.md", "本书核心目标已调整。")

    check = support.preflight(tmp_path, "0001")
    assert not check["ready"]
    assert check["reason_code"] == "adopted_plan_stale"
    assert check["changed_sources"] == ["meta/story_plan.md"]


def test_preflight_explains_the_next_action_before_chapter_generation(tmp_path):
    support.write(tmp_path, 'outline/near_term_outline.md', '### 第1章 · 先找食物')
    check = support.preflight(tmp_path, '0001')
    assert check['ready'] and check['action'] == 'mvp'
    assert check['reason_code'] == 'ready'
    assert check['next_step'] == '开始生成第 1 章正文。'

    check = support.preflight(tmp_path, '0002')
    assert not check['ready'] and check['action'] == 'outline'
    assert check['reason_code'] == 'outline_missing'
    assert '第 2 章' in check['next_step']


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


def test_evidence_accepts_independent_quotes_and_legacy_excerpt_formatting():
    body = '他把明天那份包好，压在空饭盒底下。吃完今天的几块，他捋出碎屑。\n\n柜门还开着，里面只有两个空袋。他关上柜门。'
    first = '他把明天那份包好，压在空饭盒底下。'
    last = '柜门还开着，里面只有两个空袋。'
    assert support.validated_evidence([first, last], body, 'bad') == [first, last]
    assert support.validated_evidence(first + last, body, 'bad') == [first, last]
    assert support.validated_evidence(first + '\n\n' + last, body, 'bad') == [first, last]
    quote = '他捋出碎屑。\n柜门还开着'
    assert support.validated_evidence(quote, body, 'bad') == quote


@pytest.mark.parametrize('evidence', [
    [], ['真实原句。', '编造原句。'], ['真实原句。', ''], [123], None, 123,
    {'quote': '真实原句。'}, '真实原句。编造原句。', '真实 原句。',
    '真实原句！', '原句。他安全。', '他安全。',
])
def test_evidence_never_drops_or_fuzzy_matches_invalid_passages(evidence):
    with pytest.raises(ValueError, match='bad'):
        support.validated_evidence(evidence, '真实原句。\n他不安全。', 'bad')


def test_evidence_preserves_english_spaces_and_word_boundaries():
    body = 'The room is not safe. The caretaker is unsafe.'
    assert support.validated_evidence('not  safe', body, 'bad') == 'not  safe'
    for quote in ['notsafe', 'caret', 'safe room', ['not safe.', 'not safe!']]:
        with pytest.raises(ValueError, match='bad'):
            support.validated_evidence(quote, body, 'bad')
    with pytest.raises(ValueError, match='bad'):
        support.validated_evidence('safe', 'unsafe', 'bad')


def test_commit_verifies_all_archive_evidence_before_writing(tmp_path):
    body = '赵磊关上通风阀。\n\n他决定留下救人。'
    support.write(tmp_path, 'story/0001/chapter.md', body)
    support.begin_review(tmp_path, '0001')
    evidence = ['赵磊关上通风阀。', '他决定留下救人。']
    observer = {'confirmed_state': {
        'characters': [{'name': '赵磊', 'evidence': evidence}],
        'hooks': [{'id': 'h001', 'description': '通风异常', 'evidence': evidence}],
        'debts': [{'id': 'd001', 'description': '救人的承诺', 'evidence': evidence}]}}
    arbiter = {'story_confirmed': {}, 'world_rulings': {'entries': [
        {'fact': '通风阀已关闭', 'verdict': 'adopt', 'evidence': evidence}]},
        'new_hooks': [{'id': 'h002', 'description': '尚未确认', 'evidence': evidence + ['凭空出现的枪声。']}]}
    support.write(tmp_path, 'cache/observer/obs_output.json', observer)
    support.write(tmp_path, 'cache/arbiter/arb_output.json', arbiter)
    with pytest.raises(ValueError, match='正文依据'):
        support.commit(tmp_path, '0001')
    for path in ['story/0001/confirmed_state.json', 'archive/hooks.json', 'archive/debts.json']:
        assert not (tmp_path / path).exists()
    arbiter['new_hooks'][0]['evidence'] = ''.join(evidence)
    support.write(tmp_path, 'cache/arbiter/arb_output.json', arbiter)
    state = support.commit(tmp_path, '0001')
    assert state['characters'][0]['evidence'] == evidence
    assert state['world']['facts'][0]['evidence'] == evidence
    assert state['indexes']['hooks'][-1]['evidence'] == evidence
    assert state['indexes']['debts'][0]['evidence'] == evidence
    assert support.archive_status(tmp_path)['pending_chapters'] == []


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
