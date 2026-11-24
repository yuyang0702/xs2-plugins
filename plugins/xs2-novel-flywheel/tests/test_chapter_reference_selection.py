import json
import subprocess
import sys

import pytest

from test_book_contract import PLUGIN, put
from test_reader_review_p0 import review
from test_serial_p2 import contract, serial
from test_story_support import commit_chapter, support


REFERENCES = PLUGIN / 'resources/script-library/xs2/reference_distill/reference_distill.py'
NEAR_OUTLINE = PLUGIN / 'resources/script-library/nvl/no_post/no_post.py'
CONFRONT = '对峙时让双方围绕被扣下的车票追问，容许针锋相对。'
RECONCILE = '和解时让两个人并排收拾旧屋，用停顿给对方留下余地。'
AUTHOR_STYLE = '全书保留方言。'


def book(root, mode='serial_chapter'):
    blueprint = {'mechanisms': [], 'styles': [{'choice_id': 'c', 'guidance': CONFRONT}],
                 'conflicts': [{'choice_id': 'r', 'guidance': RECONCILE}]}
    refs = support.references()
    put(root, 'learning/blueprints/v1.json', blueprint)
    put(root, 'learning/active.json', {'version': 1, 'blueprint_path': 'learning/blueprints/v1.json',
                                      'blueprint_sha256': refs.fingerprint(blueprint)})
    put(root, 'learning/active_context.md', CONFRONT + RECONCILE + 'FULL_CATALOG')
    put(root, 'learning/advisor_report.json', {'private': 'RAW_ADVISOR'})
    put(root, '.novel-project.json', {'mode': 'short' if mode == 'short_full' else 'long',
                                     'values': {'conflict_plan_mode': mode, 'style_intent': AUTHOR_STYLE,
                                                'human_intent': '第三章写两人坐船，不复述争执。'}})
    return refs, blueprint


def render(root, chapter, stage):
    result = subprocess.run([sys.executable, str(REFERENCES), 'prepare-context', '--scope', stage,
                             '--chapter', chapter], cwd=root, capture_output=True, text=True, encoding='utf8')
    assert result.returncode == 0, result.stderr
    return (root / f'learning/context/{stage}.md').read_text(encoding='utf8')


def test_planned_confrontation_reconciliation_and_zero_reach_writing_and_review(tmp_path):
    refs, _ = book(tmp_path)
    options = refs.planner_options(tmp_path, '')
    assert options['author']['style_intent'] == AUTHOR_STYLE
    assert '第三章' in options['author']['human_intent']
    put(tmp_path, 'cache/story-support/reference-options.json', options)
    chapters = [{'number': i, 'title': title, 'summary': title, 'reference_ids': choices}
                for i, (title, choices) in enumerate([('姐妹在站台对峙', ['c']),
                                                       ('姐妹在父亲的旧屋和解', ['r']),
                                                       ('登船', [])], 1)]
    put(tmp_path, 'draft.json', {'volume_number': 1, 'is_new_volume': True, 'chapters': chapters})
    result = subprocess.run([sys.executable, str(NEAR_OUTLINE), '--input', 'draft.json'],
                            cwd=tmp_path, capture_output=True)
    assert result.returncode == 0, result.stderr
    outline = tmp_path / 'outline/near_term_outline.md'
    outline.write_text(outline.read_text(encoding='utf8').replace('登船', '姐妹在旧屋和解后登船'), encoding='utf8')
    for chapter, selected in [('0001', [CONFRONT]), ('0002', [RECONCILE]), ('0003', [])]:
        for stage in ('mvp', 'polish'):
            context = render(tmp_path, chapter, stage)
            assert [s for s in (CONFRONT, RECONCILE) if s in context] == selected
            assert 'RAW_ADVISOR' not in context
        contextual = review().revision_context(tmp_path, chapter)
        assert contextual.get('optional_scene_references', {}).get('guidance', []) == selected
        common = support.prepare_context(tmp_path, chapter)
        assert not any('FULL_CATALOG' in row['content'] for row in common['sources'])


def test_old_short_outline_uses_ending_and_long_ignores_previous_chapter(tmp_path):
    refs, blueprint = book(tmp_path, 'short_full')
    put(tmp_path, 'meta/story_plan.md', '结局落在父女和解，二人并排收拾旧屋。')
    assert refs.chapter_selection(tmp_path, '0001', blueprint) == (['r'], 'scene_match')
    book(tmp_path)
    put(tmp_path, 'outline/near_term_outline.md', '### 第1章 · 公开对峙\n\n### 第2章 · 海上日出\n')
    assert refs.chapter_selection(tmp_path, '0002', blueprint) == ([], 'scene_match')


def test_rolling_window_binds_each_choice_and_rejects_unknown_ids(tmp_path):
    refs, blueprint = book(tmp_path)
    contract(tmp_path)
    commit_chapter(tmp_path)
    module = serial()
    module.prepare(tmp_path, '0002', 'select')
    prompt = support.load(tmp_path, 'cache/serial/select/prompt.json')
    assert {row['id'] for row in prompt['reference_options']['options']} == {'c', 'r'}
    assert 'FULL_CATALOG' not in json.dumps(prompt)
    rows = [{'chapter': n, 'intent': intent, 'reference_ids': [identifier],
             'setup': [{'source_id': 'story/0001/chapter.md', 'quote': '决定留下救人'}]}
            for n, intent, identifier in [('0002', '对峙', 'c'), ('0003', '和解', 'r')]]
    path = 'cache/serial/select/candidate.json'
    support.write(tmp_path, path, {'chapters': [rows[0], {**rows[1], 'reference_ids': ['unknown']}]})
    with pytest.raises(ValueError, match='候选'):
        module.normalize(tmp_path, 'select')
    support.write(tmp_path, path, {'chapters': rows})
    checked = module.normalize(tmp_path, 'select')
    support.write(tmp_path, 'cache/serial/select/review.json', {'verdict': 'pass', 'scope_change': False,
                  'findings': [], 'candidate_sha256': checked['candidate_sha256'],
                  'request_sha256': checked['request_sha256']})
    module.commit(tmp_path, 'select')
    assert refs.chapter_selection(tmp_path, '0002', blueprint) == (['c'], 'chapter_plan')
    assert refs.chapter_selection(tmp_path, '0003', blueprint) == (['r'], 'chapter_plan')


def test_multi_scene_reuses_explicit_chapter_when_project_cursor_differs(tmp_path, monkeypatch):
    from test_multi_scene import module
    from test_reading_contract import adopt
    m = module()
    adopt(tmp_path)
    put(tmp_path, '.novel-project.json', {'values': {'chapter_number': '0001'}})
    put(tmp_path, 'planning/chapters/0001.json', {'reference_ids': ['mechanism-opening']})
    put(tmp_path, 'planning/chapters/0002.json', {'reference_ids': []})
    task = 'manual-second-chapter'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TASK_ID', task)
    frozen = m.book_policy.freeze(tmp_path, task, chapter='0002')
    before = (tmp_path / frozen['prompt_file']).read_bytes()
    args = ['multi_scene', 'prepare', '--target', '300-330', '--pov', 'third_person']
    monkeypatch.setattr('sys.argv', args + ['--chapter', '0002'])
    m.main()
    monkeypatch.setattr('sys.argv', args)
    m.main()
    assert (tmp_path / frozen['prompt_file']).read_bytes() == before
    assert 'mechanism-opening' not in before.decode()
    with pytest.raises(ValueError, match='绑定其他章节'):
        m.book_policy.freeze(tmp_path, task, chapter='0001')


def test_chapter_instruction_reaches_its_writer_and_plan_only(tmp_path):
    from test_book_contract import helper
    refs, _ = book(tmp_path)
    state = json.loads((tmp_path / '.novel-project.json').read_text(encoding='utf8'))
    state['values'].update(chapter_number='0002', author_feedback_file='instructions.md')
    put(tmp_path, '.novel-project.json', state)
    put(tmp_path, 'instructions.md', '本章准许姐妹唱山歌，保留整段方言。')
    for number, included in [('0001', False), ('0002', True)]:
        options = refs.planner_options(tmp_path, '和解', number)
        assert ('chapter_instruction' in options['author']) == included
        path = helper().freeze(tmp_path, 'writer-' + number, chapter=number)['prompt_file']
        prompt = (tmp_path / path).read_text(encoding='utf8')
        assert ('姐妹唱山歌' in prompt) == included
        assert AUTHOR_STYLE in prompt
