"""Read authoritative cards and edit only a previewed range."""
import hashlib
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def service():
    entry = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/character_center/character_center.py'
    if not entry.is_file():
        pytest.fail('Character center service has not been implemented')
    spec = importlib.util.spec_from_file_location('test_character_center', entry,
                                                   submodule_search_locations=[str(entry.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def book(tmp_path):
    (tmp_path / 'meta').mkdir()
    (tmp_path / 'meta/character_profiles.md').write_text(
        '## 阿杏\n- 身份：修伞人\n- 当前欲望：留住作坊\n- 与掌柜：旧识\n'
        '### 人际与弧线\n#### 弧线潜能\n- 成长方向：独立作主\n'
        '## 掌柜\n- 身份：店主\n## 同名\n- 身份：甲\n## 同名\n- 身份：乙\n',
        encoding='utf-8')
    (tmp_path / 'meta/character_voice.md').write_bytes(
        b'\xef\xbb\xbf' + (
            '## 阿杏\r\n表达倾向（非固定台词）：说手艺时会解释。\r\n'
            '- 关系情境参考（可随情境调整），面对掌柜：会问清顾虑。\r\n'
            '```md\r\n## 例子\r\n```\r\n'
            '## 掌柜\r\n**长短句偏好**：说得慢。\r\n'
        ).encode())
    return tmp_path


def select(view):
    person = next(item for item in view['characters'] if item['name'] == '阿杏')
    section = next(item for item in person['sections'] if item['ai_editable'] and item['group'] == 'voice')
    return dict(character_id=person['id'], section_id=section['id'], source_id=section['source_id'])


def test_rendered_fields_directed_relationships_legacy_and_fences(service, book):
    view = service.read(book)
    assert [row['name'] for row in view['characters']] == ['阿杏', '掌柜', '同名', '同名']
    assert all(row['status'] == 'legacy' for row in view['characters'][2:])
    a, b = view['characters'][:2]
    assert a['planned_arcs'][0]['text'] == '独立作主'
    assert a['relationships'][0]['target_id'] == b['id']
    assert a['relationships'][0]['nature'] == '旧识'
    assert b['relationships'] == []
    assert not (book / 'learning').exists()


def test_exact_preview_rejects_tamper_staleness_and_restores_selected_range(service, book):
    view = service.read(book)
    original = (book / 'meta/character_voice.md').read_bytes()
    args = select(view)
    preview = service.preview(book, args | {'replacement': '只解释必要的细节。'}, view['revision'])
    assert preview['before'] == '说手艺时会解释。'
    assert not (book / 'learning').exists()
    with pytest.raises(ValueError):
        service.apply(book, preview | {'before': '改过的凭证'}, view['revision'])
    applied = service.apply(book, preview, view['revision'])
    target = book / 'meta/character_voice.md'
    assert target.read_bytes() == original.replace('说手艺时会解释。'.encode(), '只解释必要的细节。'.encode())
    with pytest.raises(ValueError):
        service.apply(book, preview, view['revision'])
    target.write_bytes(target.read_bytes().replace('说得慢。'.encode(), '很简短。'.encode()))
    restore = service.preview(book, {'character_id': args['character_id'],
                              'history_id': applied['entry']['id']}, service.read(book)['revision'])
    service.apply(book, restore, restore['revision'])
    assert target.read_bytes() == original.replace('说得慢。'.encode(), '很简短。'.encode())
    assert len(service.history(book, args['character_id'])['entries']) == 2


def test_state_evidence_uses_original_chapter_and_excludes_future_stale_and_bad_rows(service, book):
    for chapter in ('0001', '0002', '0003'):
        folder = book / 'story' / chapter
        folder.mkdir(parents=True)
        body = f'第{chapter}章原文。'.encode()
        (folder / 'chapter.md').write_bytes(body)
        (folder / 'confirmed_state.json').write_text(json.dumps({
            'chapter': chapter, 'body_sha256': hashlib.sha256(body).hexdigest(),
            'source_hashes': {}, 'characters': [False, {
                'name': '阿杏', 'source_chapter': '0001', 'evidence': '第0001章原文。',
                'snapshot': {'goal': '留住作坊', 'knowledge': ['真相'], 'misbelief': ['误会']},
            }], 'world': {'facts': [{'description': '假事实', 'source_chapter': chapter,
                                      'evidence': '不在正文里'}]},
        }), encoding='utf-8')
    view = service.read(book, '0002')
    assert [state['chapter'] for state in view['characters'][0]['states']] == ['0001', '0002']
    assert view['characters'][0]['states'][-1]['source_id'] == 'story/0001/chapter.md'
    assert view['world_facts'] == []
    (book / 'story/0001/chapter.md').write_bytes(b'edited')
    view = service.read(book, '0002')
    assert view['stale_chapters'] == ['0001']
    assert view['characters'][0]['states'] == []


def test_alias_and_failed_publication_keep_history_clean(service, book, monkeypatch):
    view = service.read(book)
    with pytest.raises(ValueError):
        service.preview(book, select(view) | {'source_id': 'meta/../meta/character_voice.md',
                                              'replacement': '新声音'}, view['revision'])
    preview = service.preview(book, select(view) | {'replacement': '新声音'}, view['revision'])
    original_replace = Path.replace

    def fail_card_write(self, target):
        if Path(target).name == 'character_voice.md':
            raise OSError('locked')
        return original_replace(self, target)

    monkeypatch.setattr(Path, 'replace', fail_card_write)
    with pytest.raises(OSError, match='locked'):
        service.apply(book, preview, view['revision'])
    assert service.history(book)['entries'] == []
    assert service.read(book)['revision'] == view['revision']


def _console():
    entry = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/console_service/console_service.py'
    spec = importlib.util.spec_from_file_location('test_cc_console', entry, submodule_search_locations=[str(entry.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_character_jobs_keep_reasoning_private_and_require_author_adoption(service, book):
    async def scenario():
        view = service.read(book)
        selected = select(view)
        calls = []
        closed = []

        class Model:
            model_name = 'actual-provider:real'

            async def ainvoke(self, messages):
                calls.append(messages)
                return SimpleNamespace(content=[{'type': 'reasoning', 'text': 'private'},
                                                {'type': 'text', 'text': '{"replacement":"看对方是否想听细节。"}'}])

            async def aclose(self):
                closed.append(True)

        jobs = _console().create_assistant(lambda **_: Model(), lambda **_: None, character_loader=lambda: service)
        options = dict(selected, purpose='character_edit', chapter='0001', question='措辞建议',
                       expected_revision=view['revision'], _model_override='chosen:writer')
        original = (book / 'meta/character_voice.md').read_bytes()
        started = jobs.start(book, 'edit', options)
        assert jobs.start(book, 'edit', options)['id'] == started['id']
        await jobs.tasks['edit']
        entry = jobs.history(book)[0]
        assert entry['status'] == 'completed'
        assert entry['model'] == 'actual-provider:real'
        assert entry['suggestion']['after'] == '看对方是否想听细节。'
        assert 'private' not in json.dumps(entry, ensure_ascii=False)
        assert len(calls) == len(closed) == 1
        assert (book / 'meta/character_voice.md').read_bytes() == original
        (book / 'meta/world_foundation.md').write_text('作者刚更新世界规则。', encoding='utf-8')
        assert jobs.history(book, check_freshness=True)[0]['stale']
        with pytest.raises(ValueError):
            service.apply(book, entry['suggestion'], entry['suggestion']['revision'])
        identity = next(row for row in view['characters'][0]['sections'] if row['label'] == '身份')
        with pytest.raises(ValueError):
            jobs.start(book, 'protected', options | {'section_id': identity['id']})
    asyncio.run(scenario())


def test_trial_binds_context_and_persists_preference_only_on_fresh_result(service, book):
    async def scenario():
        first_call = asyncio.Event()
        release = asyncio.Event()
        view = service.read(book)
        character_id = select(view)['character_id']
        chapter = book / 'story/0001'
        chapter.mkdir(parents=True)
        body = chapter / 'chapter.md'
        body.write_text('现存正文', encoding='utf-8')

        class Model:
            async def ainvoke(self, messages):
                first_call.set()
                await release.wait()
                return SimpleNamespace(content='{"candidate":"她把伞合拢。","checks":["人物仍握着伞"]}')

        jobs = _console().create_assistant(lambda **_: Model(), lambda **_: None, character_loader=lambda: service)
        options = dict(purpose='dialogue_trial', chapter='0001', question='写法试读',
                       character_ids=[character_id], baseline='她低头说完。', scene='收伞',
                       expected_revision=view['revision'], _model_override='chosen:writer')
        jobs.start(book, 'stale', options)
        await first_call.wait()
        body.write_text('正文被作者改动', encoding='utf-8')
        release.set()
        await jobs.tasks['stale']
        assert jobs.history(book)[0]['error_code'] == 'character_stale'
        jobs.start(book, 'fresh', options)
        await jobs.tasks['fresh']
        entry = jobs.history(book)[-1]
        assert entry['trial']['baseline'] == '她低头说完。'
        preference = service.accept_trial(book, entry, 'candidate', '动作符合场景', '用动作代替赘述')
        assert preference['preferred'] == 'candidate'
        assert body.read_text(encoding='utf-8') == '正文被作者改动'
        assert '她把伞合拢' not in (book / 'learning/character_center/preferences.json').read_text(encoding='utf-8')
        assert service.trial_preferences(book, '0001', [character_id], '收伞') == [
            {'reason': '动作符合场景', 'carry_forward': '用动作代替赘述'}]
        assert service.trial_preferences(book, '0001', [character_id], '其他场景') == []
        body.write_text('再次改动', encoding='utf-8')
        with pytest.raises(ValueError):
            service.accept_trial(book, entry, 'baseline', '理由', '取舍')
    asyncio.run(scenario())


def test_duplicate_model_json_keys_are_rejected(service, book):
    view = service.read(book)
    task = service.freeze(book, select(view) | dict(purpose='character_edit', chapter='0001',
                          question='换种说法', expected_revision=view['revision']))
    result = service.finish(book, task['target'], 'character_edit',
                            '{"replacement":"新写法","replacement":"另一写法"}')
    assert result['error_code'] == 'character_format'
    assert not (book / 'learning').exists()


def test_same_request_id_can_run_in_two_books(service, book, tmp_path):
    import shutil
    second = tmp_path / 'second'
    shutil.copytree(book / 'meta', second / 'meta')

    async def scenario():
        release = asyncio.Event()

        class Model:
            async def ainvoke(self, _):
                await release.wait()
                return SimpleNamespace(content='{"replacement":"试着说少一些。"}')

        jobs = _console().create_assistant(lambda **_: Model(), lambda **_: None, character_loader=lambda: service)
        view = service.read(book)
        options = select(view) | dict(purpose='character_edit', chapter='0001', question='调整措辞',
                                      expected_revision=view['revision'], _model_override='chosen:writer')
        jobs.start(book, 'shared-id', options)
        first_task = jobs.tasks['shared-id']
        jobs.start(second, 'shared-id', options)
        second_task = jobs.tasks['shared-id']
        assert first_task is not second_task
        release.set()
        await asyncio.gather(first_task, second_task)
        assert jobs.history(book)[0]['status'] == 'completed'
        assert jobs.history(second)[0]['status'] == 'completed'
    asyncio.run(scenario())
