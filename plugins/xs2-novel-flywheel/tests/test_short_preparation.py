import importlib.util
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / 'resources/script-library/xs2/short_preparation/short_preparation.py'


def helper():
    assert SCRIPT.is_file(), '轻量准备入口尚未实现'
    spec = importlib.util.spec_from_file_location('short_preparation_tests', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def world():
    return {'core_laws': {'rules': ['现实都市，无超自然']}, 'space_time': {'places': ['旧照相馆']},
            'society': {'pressure': '合作资金与续租相关'}, 'history_culture': {},
            'existence': {}, 'information': {'limits': ['录屏只能证明实际覆盖的操作']}}


def cast():
    return {'characters': [
        {'name': '程见夏', 'role': '修复师', 'want': '取回署名', 'fear': '失去生计', 'boundary': '不否认自己的劳动',
         'contradiction': '仍期待丈夫认可', 'relationships': [{'with': '周予安', 'dynamic': '婚姻与经营绑定'}],
         'voice': {'baseline': '先追问经手细节，受伤时可能转问金额',
                   'by_relationship': [{'with': '周予安', 'guidance': '追问具体兑现期限'}], 'avoid': ['不代断他人内心']}},
        {'name': '周予安', 'role': '经营者', 'want': '先完成签约', 'fear': '无法续租', 'boundary': '不否认经营贡献',
         'contradiction': '想维持共同生活，却让妻子改口', 'relationships': [{'with': '程见夏', 'dynamic': '劝说与依赖并存'}],
         'voice': {'baseline': '谈共同生活，再把话题转到眼前成本',
                   'by_relationship': [{'with': '程见夏', 'guidance': '用延期承诺争取配合'}], 'avoid': ['不作反派式自白']}}
    ]}


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def ready(root):
    for relative, text in {
        'meta/world_foundation.md': '现实照相馆；材料只覆盖部分操作。',
        'meta/character_profiles.md': '## 程见夏\n想留名却怕失去生计。\n## 周予安\n想先完成签约。',
        'meta/character_voice.md': '程见夏追问兑现，周予安谈成本。',
        'meta/style_profile.md': '第一人称有限视角，动作和选择承载情绪。',
        'meta/story_plan.md': '取回名字，真实承担退款和失店代价。',
        'outline/volume_outline.md': '一章内完整收尾。',
        'outline/near_term_outline.md': '海报缺名→交涉受阻→更正→搬离，私人饭桌收束。',
        'learning/context/mvp.md': '已批准写法：各人为了当前目标选择话语。',
        'learning/candidates.json': '{"unapproved":"不得进入写手的候选原句"}',
        'meta/character_voice_adaptations.md': '已检查的关系适配：对父亲先问生计安排。',
    }.items():
        write(root, relative, text)


def test_compact_world_and_cast_feed_the_existing_local_archive(tmp_path, monkeypatch):
    module = helper()
    module.render_world(tmp_path, world())
    module.render_characters(tmp_path, cast())
    monkeypatch.chdir(tmp_path)
    archive_path = PLUGIN / 'resources/script-library/nvl/local_archive/local_archive.py'
    spec = importlib.util.spec_from_file_location('compact_archive_test', archive_path)
    archive = importlib.util.module_from_spec(spec); spec.loader.exec_module(archive)
    archive._prepare(SimpleNamespace(require='meta/world_foundation.md,meta/character_profiles.md,meta/character_voice.md', context=True))
    assert json.loads((tmp_path / 'cache/sync/world.json').read_text(encoding='utf-8'))['core_laws']['rules'] == ['现实都市，无超自然']
    cached = json.loads((tmp_path / 'cache/sync/characters.json').read_text(encoding='utf-8'))['characters']
    assert [item['name'] for item in cached] == ['程见夏', '周予安']
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    voice = (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert '## 程见夏' in profile and '仍期待丈夫认可' in profile
    assert '追问具体兑现期限' in voice and '用延期承诺争取配合' in voice
    assert '寿命' not in (tmp_path / 'meta/world_foundation.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('invalid', ['duplicate', 'missing_voice', 'unsafe_name'])
def test_invalid_cast_cannot_publish_partial_profiles(tmp_path, invalid):
    data = cast()
    if invalid == 'duplicate': data['characters'][1]['name'] = '程见夏'
    elif invalid == 'missing_voice': data['characters'][1].pop('voice')
    else: data['characters'][1]['name'] = '../另一本书'
    with pytest.raises(ValueError): helper().render_characters(tmp_path, data)
    assert not (tmp_path / 'meta/character_profiles.md').exists()
    assert not (tmp_path / 'cache/character/skeleton.json').exists()


def test_compact_preparation_never_replaces_existing_foundations(tmp_path):
    write(tmp_path, 'meta/world_foundation.md', '作者已有世界规则')
    with pytest.raises(ValueError, match='已有'):
        helper().render_world(tmp_path, world())
    assert (tmp_path / 'meta/world_foundation.md').read_text(encoding='utf-8') == '作者已有世界规则'
    assert not (tmp_path / 'world/core_laws.json').exists()


def test_compact_writer_context_keeps_complete_facts_voices_and_approved_writing(tmp_path):
    ready(tmp_path)
    helper().prepare_context(tmp_path, '0001')
    context = (tmp_path / 'cache/short/production_context.md').read_text(encoding='utf-8')
    for expected in ['想留名却怕失去生计', '已批准写法', '已检查的关系适配', '私人饭桌收束', '退款和失店代价']:
        assert expected in context
    assert '不得进入写手的候选原句' not in context
    assert '尚未发生' in (tmp_path / 'story/0001/world_events.md').read_text(encoding='utf-8')
    assert (tmp_path / 'cache/se/se_output.json').is_file()
    assert (tmp_path / 'story/0001/single_chapter_guide.md').is_file()
    assert not (tmp_path / 'story/0001/chapter.md').exists()


def test_context_limit_stops_before_any_derived_files_are_written(tmp_path):
    ready(tmp_path)
    write(tmp_path, 'meta/character_profiles.md', '完整人物资料' * 5000)
    with pytest.raises(ValueError, match='完整'):
        helper().prepare_context(tmp_path, '0001')
    assert not (tmp_path / 'cache/short/production_context.md').exists()
    assert not (tmp_path / 'story/0001/world_events.md').exists()


def test_existing_body_and_nonfirst_chapter_cannot_enter_first_draft_shortcut(tmp_path):
    ready(tmp_path)
    write(tmp_path, 'story/0001/chapter.md', '作者已有正文')
    with pytest.raises(ValueError): helper().prepare_context(tmp_path, '0001')
    with pytest.raises(ValueError): helper().prepare_context(tmp_path, '0002')
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == '作者已有正文'


def test_missing_canonical_file_does_not_get_fabricated_from_candidates(tmp_path):
    ready(tmp_path)
    (tmp_path / 'meta/character_voice.md').unlink()
    with pytest.raises(ValueError, match='缺少'): helper().prepare_context(tmp_path, '0001')
    assert not (tmp_path / 'cache/short/production_context.md').exists()


def test_context_cli_binds_only_this_execution_and_writer_resolves_the_complete_file(tmp_path):
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    import asyncio
    ready(tmp_path)
    result = subprocess.run([sys.executable, str(SCRIPT), 'context'], cwd=tmp_path,
                            capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    outputs = _parse_wf_vars(result.stdout)
    assert outputs == {'short_context_file': 'cache/short/production_context.md'}
    expanded = asyncio.run(resolve_placeholders('{{short_context_file}}', outputs,
        [{'key': 'short_context_file', 'type': 'file', 'required': False}], str(tmp_path)))
    assert '已批准写法' in expanded and '已检查的关系适配' in expanded
    # A standard run has an empty output variable; stale files are not consumed.
    standard = asyncio.run(resolve_placeholders('{{short_context_file}}', {'short_context_file': ''},
        [{'key': 'short_context_file', 'type': 'file', 'required': False}], str(tmp_path)))
    assert standard == ''


def test_preparation_variable_contract_has_no_ambiguous_duplicate_defaults():
    for stage in ['build', 'character', 'mvp']:
        definition = json.loads((PLUGIN / f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8-sig'))
        keys = [item['key'] for item in definition['variables']]
        assert len(keys) == len(set(keys)), f'{stage} has duplicate variables'


def test_compact_character_model_receives_actual_world_and_confirmed_author_facts(tmp_path):
    from src.workflow.variable_resolution import resolve_placeholders
    import asyncio
    definition = json.loads((PLUGIN / 'resources/workflows/character/definition.json').read_text(encoding='utf-8-sig'))
    write(tmp_path, 'meta/world_foundation.md', '现实照相馆；原始记录不等于全部权属。')
    values = {item['key']: item.get('default', '') for item in definition['variables']}
    values.update(premise='程见夏31岁，唐小满22岁，保留师徒关系。', narrative_pov='first_person')
    node = next(item for item in definition['nodes'] if item['id'] == 'agent_short_character')
    expanded = asyncio.run(resolve_placeholders(node['first_message'], values, definition['variables'], str(tmp_path)))
    assert '现实照相馆；原始记录不等于全部权属。' in expanded
    assert '程见夏31岁，唐小满22岁，保留师徒关系。' in expanded
