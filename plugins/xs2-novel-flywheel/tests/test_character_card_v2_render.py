"""Versioned cards survive real compact/full publication without changing old cards."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
COMPACT = PLUGIN / 'resources/script-library/xs2/short_preparation/short_preparation.py'
FULL = PLUGIN / 'resources/script-library/nvl/json_to_md/json_to_md.py'


def load(path):
    spec = importlib.util.spec_from_file_location(path.parent.name + '_v2_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def person(name='林叶'):
    return {'name': name, 'card_schema': 'xs2.character.v2', 'role': '修伞师',
            'want': '先修好屋顶', 'fear': '欠款失信', 'contradiction': '想独立也盼人帮忙',
            'facts': ['林叶借给顾石一把蓝伞；顾石是借用者'],
            'personality': '重视兑现；受压时可能先谈成本，也能承认害怕',
            'plot_constraints': ['本章结束前归还蓝伞'],
            'relationships': [{'with': '顾石', 'dynamic': '曾经合作，现在互相试探'}],
            'voice': {'baseline': '先问目前能做什么', 'avoid': ['不编造已发生的承诺']}}


def write_json(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def full_cli(root, characters, deep=None):
    write_json(root, 'cache/character/skeleton.json', {'characters': characters})
    for name, record in (deep or {}).items():
        write_json(root, f'cache/character/{name}_deep.json', record)
    return subprocess.run([sys.executable, str(FULL), '--mode', 'character',
                           '--book-dir', str(root), '--output', str(root / 'meta/character_profiles.md')],
                          capture_output=True, encoding='utf-8')


def assert_categories(text):
    assert '## 林叶\n' in text
    assert '### 已确认事实\n' in text
    assert '### 性格与关系\n' in text
    assert '### 作者情节边界\n' in text
    assert text.index('### 已确认事实') < text.index('林叶借给顾石') < text.index('### 性格与关系')
    assert text.index('### 性格与关系') < text.index('重视兑现') < text.index('### 作者情节边界')
    assert text.index('### 作者情节边界') < text.index('本章结束前归还蓝伞')
    assert '价值底线' not in text


def test_compact_v2_publishes_semantic_categories_and_lossless_cache(tmp_path, monkeypatch):
    data = {'characters': [person(), person('顾石')]}
    before = copy.deepcopy(data)
    load(COMPACT).render_characters(tmp_path, data)
    assert_categories((tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8'))
    cached = json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8'))
    for actual, original in zip(cached['characters'], data['characters']):
        for field in ('card_schema', 'facts', 'personality', 'plot_constraints', 'relationships'):
            assert actual[field] == original[field]
        assert 'boundary' not in actual
    assert '不编造已发生的承诺' in (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    archive = load(PLUGIN / 'resources/script-library/nvl/local_archive/local_archive.py')
    archive._build_character_cache()
    synced = json.loads((tmp_path / 'cache/sync/characters.json').read_text(encoding='utf-8'))
    assert synced['characters'][0]['card_schema'] == 'xs2.character.v2'
    assert synced['characters'][0]['facts'] == ['林叶借给顾石一把蓝伞；顾石是借用者']
    assert synced['characters'][0]['plot_constraints'] == ['本章结束前归还蓝伞']
    assert data == before


@pytest.mark.parametrize('boundary', [' 不替别人保证结果 ', [' 不替别人保证结果 ', ' 也能求助 ']])
def test_legacy_boundary_cache_preserves_exact_values_and_list_shape(tmp_path, boundary):
    record = person()
    record.pop('card_schema')
    record.pop('personality')
    record.pop('plot_constraints')
    record['boundary'] = boundary
    before = copy.deepcopy(record)
    load(COMPACT).render_characters(tmp_path, {'characters': [record]})
    cached = json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8'))
    assert cached['characters'][0]['boundary'] == boundary
    text = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    assert '价值底线' in text and '不替别人保证结果' in text
    assert '作者情节边界' not in text
    assert record == before


BAD = [('card_schema', 'xs2.character.v9'), ('card_schema', None),
       ('boundary', '不能猜测它属于哪类'), ('boundary', []),
       ('facts', '非数组'), ('facts', [42]), ('facts', ['']),
       ('personality', ''), ('personality', []),
       ('plot_constraints', '非数组'), ('plot_constraints', [False]), ('plot_constraints', [''])]


@pytest.mark.parametrize('field,value', BAD)
def test_compact_invalid_second_card_publishes_no_files(tmp_path, field, value):
    invalid = person('顾石')
    invalid[field] = value
    with pytest.raises(ValueError):
        load(COMPACT).render_characters(tmp_path, {'characters': [person(), invalid]})
    assert not list(tmp_path.rglob('*.*'))


@pytest.mark.parametrize('field', ['facts', 'personality', 'plot_constraints'])
def test_compact_v2_requires_explicit_semantics(tmp_path, field):
    record = person()
    record.pop(field)
    with pytest.raises(ValueError):
        load(COMPACT).render_characters(tmp_path, {'characters': [record]})
    assert not list(tmp_path.rglob('*.*'))


def test_empty_v2_constraints_are_valid_and_full_renderer_reads_compact_cache(tmp_path):
    record = person()
    record['plot_constraints'] = []
    load(COMPACT).render_characters(tmp_path, {'characters': [record]})
    cache = json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8'))
    text = load(FULL).render_character('林叶', '林叶', [], cache['characters'][0], [], {})
    assert '林叶借给顾石' in text and '重视兑现' in text
    assert '### 作者情节边界' in text
    assert cache['characters'][0]['plot_constraints'] == []


def test_full_cli_retains_new_categories_and_does_not_modify_source(tmp_path):
    record = person()
    before = copy.deepcopy(record)
    result = full_cli(tmp_path, [record])
    assert result.returncode == 0, result.stderr
    assert_categories((tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8'))
    assert json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8')) == {'characters': [before]}


@pytest.mark.parametrize('field,value', BAD)
def test_full_cli_invalid_later_card_preserves_existing_profile(tmp_path, field, value):
    invalid = person('顾石')
    invalid[field] = value
    path = tmp_path / 'meta/character_profiles.md'
    path.parent.mkdir()
    path.write_bytes(b'author profile remains byte-for-byte\r\n')
    result = full_cli(tmp_path, [person(), invalid])
    assert result.returncode != 0
    assert path.read_bytes() == b'author profile remains byte-for-byte\r\n'


@pytest.mark.parametrize('skeleton_v2', [False, True])
def test_unversioned_deep_bottom_line_retains_legacy_meaning(skeleton_v2):
    skeleton = person() if skeleton_v2 else {'name': '林叶'}
    deep = {'bottom_line': {'condition': '有人伤害无辜', 'source': '旧事', 'reaction_when_crossed': '拒绝合作'}}
    before = copy.deepcopy(deep)
    text = load(FULL).render_character('林叶', '林叶', [], skeleton, [], deep)
    assert '#### 不可触碰的底线' in text
    assert '- 触犯条件：有人伤害无辜' in text and '- 反应：拒绝合作' in text
    assert deep == before


def test_explicit_v2_deep_bottom_line_is_personal_tendency():
    deep = person()
    deep['bottom_line'] = {'condition': '欠别人帮助', 'source': '旧事', 'reaction_when_crossed': '通常想偿还，也能协商'}
    original = copy.deepcopy(deep)
    text = load(FULL).render_character('林叶', '林叶', [], {'name': '林叶'}, [], deep)
    assert '#### 个人价值倾向' in text
    assert '不可触碰的底线' not in text
    assert '通常想偿还，也能协商' in text and '本章结束前归还蓝伞' in text
    assert deep == original


def test_unknown_deep_version_fails_before_profile_publication(tmp_path):
    result = full_cli(tmp_path, [person()], {'林叶': {'card_schema': 'xs2.character.v8'}})
    assert result.returncode != 0
    assert not (tmp_path / 'meta/character_profiles.md').exists()


@pytest.mark.parametrize('field', ['facts', 'personality', 'plot_constraints'])
@pytest.mark.parametrize('location', ['skeleton', 'deep'])
def test_full_cli_requires_v2_fields_in_each_versioned_record(tmp_path, field, location):
    record = person()
    record.pop(field)
    result = full_cli(tmp_path, [record] if location == 'skeleton' else [person()],
                      {'林叶': record} if location == 'deep' else None)
    assert result.returncode != 0
    assert not (tmp_path / 'meta/character_profiles.md').exists()


def test_full_cli_cannot_skip_invalid_version_on_unnamed_record(tmp_path):
    result = full_cli(tmp_path, [person(), {'card_schema': 'xs2.character.v9'}])
    assert result.returncode != 0
    assert not (tmp_path / 'meta/character_profiles.md').exists()


def test_full_cli_retains_supplemental_deep_fields_and_original_source_bytes(tmp_path):
    skeleton, deep = person(), person()
    deep['facts'].append('顾石手中只有一把蓝伞')
    deep['personality'] = '在熟人面前更愿意说明窘境'
    deep['plot_constraints'].append('归还前不得出现第二把蓝伞')
    deep['bottom_line'] = {'condition': '欠帮助', 'reaction_when_crossed': '通常试着偿还'}
    source = write_json(tmp_path, 'cache/character/林叶_deep.json', deep)
    source_before = source.read_bytes()
    result = full_cli(tmp_path, [skeleton])
    assert result.returncode == 0, result.stderr
    text = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    for phrase in ['顾石手中只有一把蓝伞', '在熟人面前更愿意说明窘境', '归还前不得出现第二把蓝伞', '重视兑现']:
        assert phrase in text
    assert text.count('林叶借给顾石一把蓝伞') == 1
    assert text.count('本章结束前归还蓝伞') == 1
    assert source.read_bytes() == source_before


def test_unversioned_records_do_not_infer_v2_semantics():
    record = person()
    record.pop('card_schema')
    record['boundary'] = ['旧边界原义']
    text = load(FULL).render_character('林叶', '林叶', [], record, [], {})
    assert '价值底线：旧边界原义' in text
    assert '作者情节边界' not in text
    assert '本章结束前归还蓝伞' not in text
    assert '性格倾向：重视兑现' not in text


def test_full_voice_preserves_both_supported_legacy_prohibition_fields():
    record = {'name': '林叶', 'avoid': ['不代替顾石承诺'], 'forbidden_speech': ['不泄露住址']}
    before = copy.deepcopy(record)
    text = load(FULL).render_voice_char(record)
    assert '不代替顾石承诺' in text and '不泄露住址' in text
    assert '旧档表达约束（原文保留）' in text
    assert record == before


@pytest.mark.parametrize('empty_field', ['avoid', 'forbidden_speech'])
def test_full_voice_still_tolerates_empty_legacy_prohibition_fields(empty_field):
    record = {'name': '林叶', empty_field: None, 'preferences': ['通常先听完对方的话']}
    text = load(FULL).render_voice_char(record)
    assert '通常先听完对方的话' in text


def test_v2_internal_sections_do_not_create_extra_voice_ui_characters(tmp_path):
    load(COMPACT).render_characters(tmp_path, {'characters': [person(), person('顾石')]})
    service = load(PLUGIN / 'resources/script-library/xs2/voice_support/voice_support.py')
    characters = service.read(tmp_path)['characters']
    assert [entry['name'] for entry in characters] == ['林叶', '顾石']
    assert all(entry['profile_status'] == 'matched' for entry in characters)
    assert all('作者情节边界' in entry['profile'] for entry in characters)


IDENTITY_BAD = [('name', None), ('name', ''), ('name', '  '), ('name', '../../outside'),
                ('name', '..\\outside'), ('name', '林叶'), ('aliases', '别名字符串'),
                ('aliases', [42]), ('aliases', ['']), ('aliases', ['别名\n## 伪角色']),
                ('true_name', 42), ('true_name', '真名\n## 伪角色'),
                ('name', '顾\u2028石'), ('aliases', ['旧\u2028名']), ('true_name', '真\u2028名'),
                ('name', '顾石\u2028'), ('aliases', ['旧名\u2028']), ('true_name', '真名\u2028')]


@pytest.mark.parametrize('field,value', IDENTITY_BAD)
@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_later_v2_invalid_identity_preserves_existing_profile(tmp_path, field, value, mode):
    path = tmp_path / 'meta/character_profiles.md'
    path.parent.mkdir()
    path.write_bytes(b'original author profile\r\n')
    invalid = person('顾石')
    if value is None:
        invalid.pop(field)
    else:
        invalid[field] = value
    original = copy.deepcopy(invalid)
    if mode == 'compact':
        with pytest.raises(ValueError, match='v2|姓名'):
            load(COMPACT).render_characters(tmp_path, {'characters': [person(), invalid]})
    else:
        result = full_cli(tmp_path, [person(), invalid])
        assert result.returncode != 0
        assert 'v2' in result.stderr or '姓名' in result.stderr
    assert path.read_bytes() == b'original author profile\r\n'
    assert invalid == original


def test_full_prevalidates_all_v2_names_before_any_deep_path_lookup(tmp_path, monkeypatch):
    invalid = person('../../outside')
    write_json(tmp_path, 'cache/character/skeleton.json', {'characters': [person(), invalid]})
    renderer = load(FULL)
    checked = []
    real_exists = renderer.os.path.exists

    def record_exists(path):
        checked.append(str(path))
        return real_exists(path)

    monkeypatch.setattr(renderer.os.path, 'exists', record_exists)
    monkeypatch.setattr(sys, 'argv', ['json_to_md.py', '--mode', 'character', '--book-dir', str(tmp_path),
                                     '--output', str(tmp_path / 'meta/character_profiles.md')])
    with pytest.raises(ValueError, match='姓名|name'):
        renderer.main()
    assert not any(path.endswith('_deep.json') for path in checked)
    assert not (tmp_path / 'meta/character_profiles.md').exists()


@pytest.mark.parametrize('mode', ['compact', 'full', 'deep'])
@pytest.mark.parametrize('field', ['personality', 'facts', 'plot_constraints', 'relationship', 'voice'])
def test_v2_heading_text_is_rejected_without_creating_false_ui_characters(tmp_path, mode, field):
    load(COMPACT).render_characters(tmp_path, {'characters': [person()]})
    profile = tmp_path / 'meta/character_profiles.md'
    original_profile = profile.read_bytes()
    record = person()
    injected = '原来的一段\n\n## 伪角色\n\n另一段'
    if field in ('facts', 'plot_constraints'):
        record[field] = [injected]
    elif field == 'relationship':
        record['relationships'][0]['dynamic'] = injected
    elif field == 'voice':
        record['voice']['baseline'] = injected
    else:
        record[field] = injected
    before = copy.deepcopy(record)
    if mode == 'compact':
        with pytest.raises(ValueError, match='标题'):
            load(COMPACT).render_characters(tmp_path, {'characters': [record]})
    else:
        result = full_cli(tmp_path, [record] if mode == 'full' else [person()],
                          {'林叶': record} if mode == 'deep' else None)
        assert result.returncode != 0
        assert '标题' in result.stderr
    assert profile.read_bytes() == original_profile
    service = load(PLUGIN / 'resources/script-library/xs2/voice_support/voice_support.py')
    assert [entry['name'] for entry in service.read(tmp_path)['characters']] == ['林叶']
    assert record == before


@pytest.mark.parametrize('mode', ['compact', 'full', 'deep'])
def test_v2_plain_multiline_paragraphs_keep_source_and_one_ui_character(tmp_path, mode):
    record = person()
    record['facts'] = ['第一段事实\n\n第二段事实']
    record['personality'] = '通常愿意解释\n\n有压力时也会沉默'
    record['plot_constraints'] = ['本章先归还蓝伞\n\n随后离开修理铺']
    before = copy.deepcopy(record)
    if mode == 'compact':
        load(COMPACT).render_characters(tmp_path, {'characters': [record]})
        source = tmp_path / 'cache/character/skeleton.json'
        saved = json.loads(source.read_text(encoding='utf-8'))['characters'][0]
    else:
        result = full_cli(tmp_path, [record] if mode == 'full' else [person()],
                          {'林叶': record} if mode == 'deep' else None)
        assert result.returncode == 0, result.stderr
        source = tmp_path / 'cache/character/林叶_deep.json' if mode == 'deep' else tmp_path / 'cache/character/skeleton.json'
        saved = json.loads(source.read_text(encoding='utf-8'))
        if mode == 'full':
            saved = saved['characters'][0]
    for field in ('facts', 'personality', 'plot_constraints'):
        assert saved[field] == record[field]
    service = load(PLUGIN / 'resources/script-library/xs2/voice_support/voice_support.py')
    assert [entry['name'] for entry in service.read(tmp_path)['characters']] == ['林叶']
    assert record == before


@pytest.mark.parametrize('linebreak', ['\r', '\u2028'])
@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_v2_heading_guard_matches_ui_line_splitting(tmp_path, linebreak, mode):
    record = person()
    record['personality'] = '第一段' + linebreak + '## 伪角色' + linebreak + '第二段'
    if mode == 'compact':
        with pytest.raises(ValueError, match='标题'):
            load(COMPACT).render_characters(tmp_path, {'characters': [record]})
    else:
        result = full_cli(tmp_path, [record])
        assert result.returncode != 0 and '标题' in result.stderr
    assert not (tmp_path / 'meta/character_profiles.md').exists()


def test_legacy_full_missing_name_remains_tolerated(tmp_path):
    result = full_cli(tmp_path, [{'name': '林叶'}, {'essence': '没有姓名的旧记录'}])
    assert result.returncode == 0, result.stderr
    text = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    assert '## 林叶' in text and '没有姓名的旧记录' not in text


@pytest.mark.parametrize('mode', ['compact', 'full', 'deep'])
@pytest.mark.parametrize('field,fence', [('personality', '```'), ('facts', '~~~'),
    ('plot_constraints', '   ````python'), ('nested', '  ~~~~  '),
    ('personality', '``` text'), ('facts', ' ~~~')])
def test_v2_fence_rejection_preserves_two_ui_characters_and_profile_ownership(tmp_path, mode, field, fence):
    records = [person(), person('顾石')]
    service = load(PLUGIN / 'resources/script-library/xs2/voice_support/voice_support.py')
    if mode == 'compact':
        load(COMPACT).render_characters(tmp_path, {'characters': records})
    else:
        result = full_cli(tmp_path, records)
        assert result.returncode == 0, result.stderr
    profile = tmp_path / 'meta/character_profiles.md'
    original_profile = profile.read_bytes()
    original_cache = (tmp_path / 'cache/character/skeleton.json').read_bytes()
    injected = '通常愿意解释\n\n' + fence + '\n\n压力下会沉默'
    invalid = copy.deepcopy(records[0])
    if field in ('facts', 'plot_constraints'):
        invalid[field] = [injected]
    elif field == 'nested':
        invalid['relationships'][0]['dynamic'] = injected
    else:
        invalid[field] = injected
    before = copy.deepcopy(invalid)
    if mode == 'compact':
        with pytest.raises(ValueError, match='代码围栏'):
            load(COMPACT).render_characters(tmp_path, {'characters': [invalid, records[1]]})
        assert (tmp_path / 'cache/character/skeleton.json').read_bytes() == original_cache
    else:
        result = full_cli(tmp_path, [invalid, records[1]] if mode == 'full' else records,
                          {'林叶': invalid} if mode == 'deep' else None)
        assert result.returncode != 0 and '代码围栏' in result.stderr
        source = tmp_path / 'cache/character/林叶_deep.json' if mode == 'deep' else tmp_path / 'cache/character/skeleton.json'
        saved = json.loads(source.read_text(encoding='utf-8'))
        assert (saved if mode == 'deep' else saved['characters'][0]) == before
    assert profile.read_bytes() == original_profile
    characters = service.read(tmp_path)['characters']
    assert [entry['name'] for entry in characters] == ['林叶', '顾石']
    assert all(entry['profile_status'] == 'matched' for entry in characters)
    assert '## 顾石' not in characters[0]['profile']
    assert '## 林叶' not in characters[1]['profile']
    assert invalid == before


@pytest.mark.parametrize('mode', ['compact', 'full', 'deep'])
def test_plain_v2_multiline_with_inline_backticks_keeps_two_ui_profiles(tmp_path, mode):
    first, second = person(), person('顾石')
    first['personality'] = '通常愿意解释，谈到`修伞`时具体一些\n\n压力下会沉默，也能求助'
    before = copy.deepcopy(first)
    if mode == 'compact':
        load(COMPACT).render_characters(tmp_path, {'characters': [first, second]})
    else:
        result = full_cli(tmp_path, [first, second] if mode == 'full' else [person(), second],
                          {'林叶': first} if mode == 'deep' else None)
        assert result.returncode == 0, result.stderr
    source = tmp_path / 'cache/character/林叶_deep.json' if mode == 'deep' else tmp_path / 'cache/character/skeleton.json'
    saved = json.loads(source.read_text(encoding='utf-8'))
    assert (saved if mode == 'deep' else saved['characters'][0])['personality'] == before['personality']
    service = load(PLUGIN / 'resources/script-library/xs2/voice_support/voice_support.py')
    characters = service.read(tmp_path)['characters']
    assert [entry['name'] for entry in characters] == ['林叶', '顾石']
    assert all(entry['profile_status'] == 'matched' for entry in characters)
    assert '## 顾石' not in characters[0]['profile']
    assert first == before
