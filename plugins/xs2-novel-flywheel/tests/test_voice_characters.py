"""Character views and edits must preserve the existing voice/profile documents."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def voices(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/voice_support/voice_support.py'
    spec = importlib.util.spec_from_file_location('voice_character_tests', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'meta').mkdir()
    return module, tmp_path


def write(root, filename, content):
    path = root / 'meta' / filename
    path.write_bytes(content.encode('utf-8'))
    return path


def test_read_separates_characters_and_matches_profiles_without_writing(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '# 声音\n\n共同规则。\n\n## 林芷\n\n说话克制。\n\n```md\n## 示例标题\n```\n\n## 林启\n\n先谈具体安排。\n')
    profile = write(root, 'character_profiles.md', '# 档案\n\n## 1. 林芷（主角）\n\n- 性格：执拗但有分寸\n- 当前欲望：保留工具\n\n## 林启\n\n- 性格：务实\n')
    before = voice.read_bytes(), profile.read_bytes()
    document = service.read(root)
    assert [item['name'] for item in document['characters']] == ['林芷', '林启']
    assert document['characters'][0]['profile_status'] == 'matched'
    assert '执拗但有分寸' in document['characters'][0]['profile']
    assert '先谈具体安排' not in document['characters'][0]['voice']
    assert '## 示例标题' in document['characters'][0]['voice']
    assert '共同规则' in document['preamble']
    assert (voice.read_bytes(), profile.read_bytes()) == before


def test_edit_one_character_preserves_every_other_byte_and_profile(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '\ufeff# 声音\r\n\r\n通用规则不改。\r\n\r\n## 林芷\r\n\r\n原声音。\r\n\r\n## 林启\r\n\r\n保留这一整段。\r\n')
    profile = write(root, 'character_profiles.md', '## 林芷\n执拗\n## 林启\n务实\n')
    original = voice.read_bytes()
    original_profile = profile.read_bytes()
    document = service.read(root)
    result = service.save_character(root, document['characters'][0]['id'], '新的声音。\n面对哥哥时先提出具体请求。', document['revision'])
    assert result['status'] == 'success'
    expected = original.replace('原声音。'.encode(), '新的声音。\r\n面对哥哥时先提出具体请求。'.encode())
    assert voice.read_bytes() == expected
    assert profile.read_bytes() == original_profile
    assert len(service.read(root)['characters']) == 2


@pytest.mark.parametrize('changed_file', ['character_voice.md', 'character_profiles.md'])
def test_stale_reference_or_voice_rejects_save_without_losing_external_edits(voices, changed_file):
    service, root = voices
    write(root, 'character_voice.md', '## 林芷\n原声音\n')
    write(root, 'character_profiles.md', '## 林芷\n原性格\n')
    document = service.read(root)
    write(root, changed_file, '## 林芷\n外部更新\n')
    before = {path.name: path.read_bytes() for path in (root / 'meta').iterdir()}
    with pytest.raises(ValueError, match='更新|刷新'):
        service.save_character(root, document['characters'][0]['id'], '旧页面编辑', document['revision'])
    assert {path.name: path.read_bytes() for path in (root / 'meta').iterdir()} == before


def test_duplicate_names_are_separate_and_ambiguous_profiles_are_not_guessed(voices):
    service, root = voices
    write(root, 'character_voice.md', '## 林芷\n第一段\n## 林芷\n第二段\n')
    write(root, 'character_profiles.md', '## 林芷（成年）\n成年性格\n## 林芷（童年）\n童年性格\n')
    characters = service.read(root)['characters']
    assert len(characters) == 4
    assert len({item['id'] for item in characters}) == 4
    assert characters[0]['profile_status'] == 'ambiguous'
    assert characters[0]['profile'] == ''
    assert characters[1]['voice'].strip() == '第二段'


def test_profile_only_character_can_explicitly_add_voice_without_replacing_existing_roles(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '# 声音\n\n## 林芷\n\n旧声音。\n')
    write(root, 'character_profiles.md', '## 林芷\n执拗\n## 林启\n务实\n')
    document = service.read(root)
    missing = next(item for item in document['characters'] if item['name'] == '林启')
    assert missing['voice_status'] == 'missing'
    original = voice.read_bytes()
    service.save_character(root, missing['id'], '只答应自己能做到的事。', document['revision'])
    assert voice.read_bytes().startswith(original)
    assert '## 林启\n\n只答应自己能做到的事。' in voice.read_text(encoding='utf-8')


def test_unstructured_legacy_voice_remains_available_without_inventing_roles(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '# 声音\n这是旧格式，人物关系写在行文里。\n')
    before = voice.read_bytes()
    document = service.read(root)
    assert document['characters'] == []
    assert document['unsectioned_voice'] == document['content']
    assert voice.read_bytes() == before


def test_character_edit_cannot_inject_another_role_or_edit_unknown_id(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '## 林芷\n原声音\n')
    document = service.read(root)
    before = voice.read_bytes()
    for character, content in [(document['characters'][0]['id'], '变化\n## 林启\n插入'), ('unknown', '内容')]:
        with pytest.raises(ValueError):
            service.save_character(root, character, content, document['revision'])
    assert voice.read_bytes() == before


def test_empty_last_heading_without_newline_can_receive_voice(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '# 声音\n\n## 林芷')
    document = service.read(root)
    service.save_character(root, document['characters'][0]['id'], '新声音', document['revision'])
    assert '## 林芷\n' in voice.read_text(encoding='utf-8')
    assert service.read(root)['characters'][0]['voice'].strip() == '新声音'


@pytest.mark.parametrize('fence', ['```text', '~~~~'])
def test_unclosed_code_block_cannot_hide_or_delete_later_characters(voices, fence):
    service, root = voices
    voice = write(root, 'character_voice.md', '## 林芷\n原声音\n\n## 林启\n必须保留\n')
    document = service.read(root)
    before = voice.read_bytes()
    with pytest.raises(ValueError, match='代码块|分段'):
        service.save_character(root, document['characters'][0]['id'], '新声音\n'+fence+'\n示例', document['revision'])
    assert voice.read_bytes() == before
    assert [item['name'] for item in service.read(root)['characters']] == ['林芷', '林启']


def test_profile_voice_append_cannot_disappear_inside_an_old_unclosed_fence(voices):
    service, root = voices
    voice = write(root, 'character_voice.md', '# 共享规则\n\n```text\n示例未闭合\n')
    write(root, 'character_profiles.md', '## 林芷\n谨慎\n')
    document = service.read(root)
    before = voice.read_bytes()
    with pytest.raises(ValueError, match='代码块|分段'):
        service.save_character(root, document['characters'][0]['id'], '新声音', document['revision'])
    assert voice.read_bytes() == before


def test_document_revision_refers_to_the_bytes_that_were_actually_displayed(voices, monkeypatch):
    service, root = voices
    voice = write(root, 'character_voice.md', '## 林芷\n旧声音\n')
    original_revision = service.read(root)['revision']
    real_read = Path.read_bytes
    changed = False
    def read_then_update(path):
        nonlocal changed
        data = real_read(path)
        if path == voice and not changed:
            changed = True
            voice.write_text('## 林芷\n外部新声音\n', encoding='utf-8')
        return data
    monkeypatch.setattr(Path, 'read_bytes', read_then_update)
    document = service.read(root)
    assert '旧声音' in document['characters'][0]['voice']
    assert document['revision'] == original_revision
    with pytest.raises(ValueError, match='更新|刷新'):
        service.save_character(root, document['characters'][0]['id'], '旧页面修改', document['revision'])
