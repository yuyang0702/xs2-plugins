"""Plugin policy regression: personality and reference choices are not scripts."""
import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
RESOURCES = PLUGIN / 'resources'


def prompt(agent):
    data = json.loads((RESOURCES / 'prompts.json').read_text(encoding='utf-8'))
    return '\n'.join(s['content'] for s in data['agents'][agent]['sections'] if s.get('enabled'))


@pytest.mark.parametrize('agent', (
    'novel-short-character', 'novel-character-skeleton', 'novel-character-deep',
    'novel-character-belief', 'novel-character-voice', 'novel-character-semantic-review',
    'novel-director', 'novel-outliner', 'novel-story-planner', 'novel-single-writer',
    'novel-writer', 'novel-multi-scene-writer', 'novel-transition-writer', 'novel-polisher',
    'xs2-local-revision-critic', 'xs2-local-revision-writer', 'xs2-local-revision-reviewer',
    'xs2-draft-auditor', 'xs2-reader-sim', 'xs2-blind-reader',
))
def test_roles_distinguish_character_belief_from_world_facts(agent):
    text = prompt(agent)
    assert '人物相信的事不自动成为世界事实' in text
    assert '性格是倾向，不是固定应对流程' in text
    assert '作者明确要求' in text
    assert '未采用参考写法不构成缺陷' in text


def test_style_boundaries_are_optional_and_have_an_authority_source():
    text = prompt('novel-style-profiler')
    assert '3-6条' not in text
    assert 'commandments' in text and '允许为空数组' in text
    assert '模型推导的偏好' in text
    assert '题材特有的创作惯例和禁忌' not in text


@pytest.mark.parametrize('single_writer', (False, True))
def test_compact_context_preserves_material_with_authority_guidance(tmp_path, single_writer):
    from test_short_preparation import helper, ready, write
    ready(tmp_path)
    write(tmp_path, '.novel-project.json', json.dumps({'values': {
        'premise': '女孩相信母亲仍在屋里。', 'human_intent': '本篇结尾必须保留录音机。'
    }}, ensure_ascii=False))
    original = (tmp_path / 'meta/character_profiles.md').read_bytes()
    helper().prepare_context(tmp_path, '0001', single_writer=single_writer)
    text = (tmp_path / 'cache/short/production_context.md').read_text(encoding='utf-8')
    assert '性格是倾向，不是固定应对流程' in text
    assert '人物相信的事不自动成为世界事实' in text
    assert '未采用参考写法不构成缺陷' in text
    assert '本篇结尾必须保留录音机。' in text
    assert (tmp_path / 'meta/character_profiles.md').read_bytes() == original


def test_book_contract_preserves_explicit_instructions_and_optional_reference_policy():
    path = RESOURCES / 'script-library/xs2/prose_policy/book_contract.py'
    spec = importlib.util.spec_from_file_location('latitude_book', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    text = module.prompt({'author_intent': {'human_intent': '必须保留这句对白。'}})
    assert '必须保留这句对白。' in text
    assert '人物相信的事不自动成为世界事实' in text
    assert '未采用参考写法不构成缺陷' in text


def test_short_writer_keeps_advisor_guidance_separate_from_author_words(tmp_path):
    from test_short_preparation import helper, ready, write
    ready(tmp_path)
    write(tmp_path, '.novel-project.json', json.dumps({'values': {
        'premise': '小店最后一夜，来人的身份由故事决定。',
        'human_intent': '结尾保留一枚旧硬币。',
        'advisor_guidance': '来人可以是旧邻居。',
    }}, ensure_ascii=False))
    helper().prepare_context(tmp_path, '0001', single_writer=True)
    text = (tmp_path / 'cache/short/production_context.md').read_text(encoding='utf-8')
    assert '## 作者确认要求\n\n结尾保留一枚旧硬币。' in text
    assert '## 创作建议\n\n来人可以是旧邻居。' in text
    assert '## 作者确认要求\n\n来人可以是旧邻居。' not in text


def test_reference_only_feedback_still_cannot_fail_review():
    from test_reading_contract import module, checks
    reading = module()
    contract = {'objectives': [{'id': 'r1', 'dimension': 'voice', 'intent': '参考口语'}]}
    result = reading.apply({'verdict': 'revise', 'issues': [],
                            'reading_checks': checks(contract, 'revise')}, '风停了。', contract)
    assert result['verdict'] == 'pass'
    assert all(row['priority'] == 'low' for row in result['issues'])


def test_old_reference_questions_are_conditional_in_model_view_without_rewriting_blueprint(tmp_path):
    from test_reading_contract import adopt, module
    adopt(tmp_path)
    reading = module()
    contract = reading.for_book(tmp_path)
    before = (tmp_path / 'learning/blueprints/v0001.json').read_bytes()
    question = contract['objectives'][0]['acceptance_question']
    viewed = reading.model_view(contract)
    assert viewed['objectives'][0]['acceptance_question'].startswith('仅在实际采用时评估：')
    assert question in viewed['objectives'][0]['acceptance_question']
    assert viewed['objectives'][0]['id'] == contract['objectives'][0]['id']
    assert contract == reading.for_book(tmp_path)
    assert (tmp_path / 'learning/blueprints/v0001.json').read_bytes() == before


def test_reference_renderer_qualifies_old_questions_and_preserves_blueprint(tmp_path, monkeypatch):
    from test_reading_contract import adopt
    from test_reference_distill import _load_module
    adopt(tmp_path)
    original = (tmp_path / 'learning/blueprints/v0001.json').read_bytes()
    monkeypatch.chdir(tmp_path)
    _load_module().render('mvp')
    text = (tmp_path / 'learning/context/mvp.md').read_text(encoding='utf-8')
    assert '未采用参考写法不构成缺陷' in text
    assert '仅在实际采用时评估：' in text
    assert (tmp_path / 'learning/blueprints/v0001.json').read_bytes() == original


def test_prompt_wiring_is_idempotent_and_keeps_resource_shapes(tmp_path):
    import shutil
    root = tmp_path / 'plugin'
    (root / 'resources').mkdir(parents=True)
    shutil.copy2(RESOURCES / 'prompts.json', root / 'resources/prompts.json')
    target = root / 'resources/script-library/xs2/prose_policy'
    target.mkdir(parents=True)
    shutil.copy2(RESOURCES / 'script-library/xs2/prose_policy/creative_latitude.py', target)
    spec = importlib.util.spec_from_file_location('latitude_wire', PLUGIN / 'tools/wire_creative_latitude.py')
    wiring = importlib.util.module_from_spec(spec); spec.loader.exec_module(wiring)
    before = (root / 'resources/prompts.json').read_bytes()
    wiring.update(root)
    assert (root / 'resources/prompts.json').read_bytes() == before
