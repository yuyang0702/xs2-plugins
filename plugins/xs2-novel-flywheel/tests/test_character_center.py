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


def test_role_rehearsal_keeps_shared_writer_context_and_separates_character_and_blind_inputs(service, book):
    async def scenario():
        view = service.read(book)
        cast = [row['id'] for row in view['characters'] if row['name'] in ('阿杏', '掌柜')]
        (book / 'meta/style_profile.md').write_text('旧物与闲话入文', encoding='utf-8')
        (book / 'learning').mkdir()
        (book / 'learning/active_context.md').write_text('已采纳范文写法：让闲话露出担心', encoding='utf-8')
        calls = []

        class Model:
            async def ainvoke(self, messages):
                system, user = messages[0][1], json.loads(messages[1][1])
                calls.append((system, user))
                if '"roles"' in system:
                    value = {'public_start': '铺子里有一把湿伞', 'roles': [
                        dict(name='阿杏', knowledge='杏私事', goal='收伞', voice='短句'),
                        dict(name='掌柜', knowledge='柜私事', goal='谈价', voice='慢说')]}
                elif 'observable_turns' in user:
                    assert '秘密结局' not in messages[1][1]
                    own = user['role']
                    assert ('柜私事' if own['name'] == '阿杏' else '杏私事') not in messages[1][1]
                    value = {'speech': '让一让', 'action': '捏住伞柄'}
                elif 'texts' in user:
                    assert set(user) == {'texts'}
                    assert set(user['texts'].values()) == {'阿杏收伞。', '她把湿伞合了。'}
                    value = dict(preferred='tie', reason='两版读感相当', endings='都收了伞',
                                 readings={label: dict(voice='说话口气', exchange='接话和动作',
                                                      strengths=[dict(quote=body, comment='顺')], stiffness=[])
                                           for label, body in user['texts'].items()})
                else:
                    assert '交涉写手角色' in system
                    assert user['ending'] == '秘密结局：收伞'
                    assert '已采纳范文写法' in messages[1][1] and '旧物与闲话入文' in messages[1][1]
                    value = {'text': '她把湿伞合了。' if 'rehearsal' in user else '阿杏收伞。'}
                return SimpleNamespace(content=json.dumps(value, ensure_ascii=False))

        def factory(**options):
            assert options['model_override'] == 'chosen:writer'
            assert options['model_params'] == {'reasoning_effort': 'medium'}
            return Model()

        jobs = _console().create_assistant(factory, lambda **_: None, character_loader=lambda: service)
        options = dict(purpose='dialogue_trial', chapter='0001', question='白描', scene='收伞', character_ids=cast,
                       trial_mode='role_rehearsal', scene_card='铺子漏雨，阿杏要收伞', ending='秘密结局：收伞',
                       expected_revision=view['revision'], _model_override='chosen:writer',
                       _model_params={'reasoning_effort': 'medium'}, _trial_writer={'label': '交涉写手', 'system': '交涉写手角色'})
        jobs.start(book, 'rehearsal', options)
        await jobs.tasks['rehearsal']
        entry = jobs.history(book)[0]
        assert entry['status'] == 'completed', entry
        trial = entry['trial']
        assert (trial['baseline'], trial['candidate']) == ('阿杏收伞。', '她把湿伞合了。')
        record = trial['rehearsal']
        assert [row['name'] for row in record['turns']] == ['阿杏', '掌柜', '阿杏', '掌柜']
        assert record['blind']['preferred'] == 'tie'
        assert len(calls) == 8
        writers = [user for system, user in calls if '交涉写手角色' in system]
        assert writers[0] == {key: value for key, value in writers[1].items() if key != 'rehearsal'}
        assert not (book / 'story/0001/chapter.md').exists()
        assert service.accept_trial(book, entry, 'baseline', '理由', '表达')['preferred'] == 'baseline'
    asyncio.run(scenario())


def test_rehearsal_precision_gate_requires_every_location_and_rechecks_candidate():
    from importlib import import_module
    console = _console()
    module = import_module(console.__name__ + '.role_rehearsal')
    original = '“六点能走？”\n\n“六点还在对账。”\n\n药得五毫克。'
    revised = '“收摊就走？”\n\n“还得对账。”\n\n药得五毫克。'
    async def check():
        calls = []
        async def call(system, user, parse):
            calls.append(user)
            if 'edits' in system:
                return parse(json.dumps({'edits': [
                    {'paragraph_id': 'p0001', 'old': '六点能走', 'occurrence': 1, 'replacement': '收摊就走'},
                    {'paragraph_id': 'p0002', 'old': '六点还在对账', 'occurrence': 1, 'replacement': '还得对账'},
                ]}, ensure_ascii=False))
            checks = []
            for row in user['candidates']:
                checks.append(dict(paragraph_id=row['paragraph_id'], remove=[d for d in row['details'] if d=='六点'],
                                   reason='对账完成才影响去留，剂量必须准确。'))
            with pytest.raises(ValueError):
                parse(json.dumps({'checks': []}))
            return parse(json.dumps({'checks': checks}, ensure_ascii=False))
        final = await module.accept_precision(original, {'book_style': {}}, '', call)
        assert final == revised
        assert len(calls) == 3
    asyncio.run(check())


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


def test_unaccepted_character_work_does_not_feed_other_assistant_purposes(service, book):
    async def scenario():
        view = service.read(book)
        captured = []

        class Model:
            async def ainvoke(self, messages):
                captured.extend(messages)
                return SimpleNamespace(content='{"replacement":"用轻松的话问。"}' if len(captured) == 2 else '正文建议。')

        jobs = _console().create_assistant(lambda **_: Model(), lambda **_: None, character_loader=lambda: service)
        options = select(view) | dict(purpose='character_edit', chapter='0001', question='未采用内容不得渗透',
                                      expected_revision=view['revision'], _model_override='chosen:writer')
        jobs.start(book, 'edit', options)
        with pytest.raises(ValueError):
            jobs.start(book, 'edit', {'question': '另一个用途', 'purpose': 'general'})
        with pytest.raises(ValueError):
            jobs.start(book, 'another', {'question': '另一个用途', 'purpose': 'general'})
        await jobs.tasks['edit']
        jobs.start(book, 'general', {'question': '普通顾问', 'chapter': '0001'})
        await jobs.tasks['general']
        assert '未采用内容不得渗透' not in captured[-1][1]
    asyncio.run(scenario())


def test_forged_unsigned_assistant_preview_cannot_publish(service, book):
    view = service.read(book)
    task = service.freeze(book, select(view) | dict(purpose='character_edit', chapter='0001',
                          question='换种说法', expected_revision=view['revision']))
    preview = service.finish(book, task['target'], 'character_edit',
                             '{"replacement":"根据话题简答。"}')['suggestion']
    unsigned = {key: value for key, value in preview.items() if key not in {'assistant_source', 'preview_id'}}
    raw = json.dumps([str(book.resolve()), unsigned], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    forged = unsigned | {'preview_id': hashlib.sha256(raw.encode()).hexdigest()}
    with pytest.raises(ValueError):
        service.apply(book, forged, view['revision'])
    assert not (book / 'learning').exists()


def test_promotion_failure_does_not_report_applied_or_discard_history(service, book, monkeypatch):
    view = service.read(book)
    voice = book / 'meta/character_voice.md'
    original = voice.read_bytes()
    preview = service.preview(book, select(view) | {'replacement': '新声线。'}, view['revision'])
    rename = Path.replace

    def fail_promotion(self, target):
        if self.name == 'pending.json' and Path(target).name == 'history.json':
            raise OSError('archive locked')
        return rename(self, target)

    monkeypatch.setattr(Path, 'replace', fail_promotion)
    with pytest.raises(OSError, match='archive locked'):
        service.apply(book, preview, view['revision'])
    assert voice.read_bytes() == original
    assert service.history(book)['entries'] == []


def test_trial_guidance_needs_exact_scene_and_cast_in_one_plan_block(service, book):
    from importlib import import_module
    story = import_module(service.__package__ + '.dependencies').sibling('story_support')
    outline = book / 'outline/near_term_outline.md'
    outline.parent.mkdir()
    view = service.read(book)
    options = dict(purpose='dialogue_trial', chapter='0001', question='试读', scene='收伞',
                   baseline='她先说了两句。', character_ids=[select(view)['character_id']],
                   expected_revision=view['revision'])

    def accept(plan, identity):
        outline.write_text(plan, encoding='utf-8')
        frozen = service.freeze(book, options | {'_request_id': identity})
        trial = service.finish(book, frozen['target'], 'dialogue_trial',
                               '{"candidate":"她合上伞。","checks":["核对手上的伞"]}')['trial']
        entry = dict(id=identity, purpose='dialogue_trial', status='completed', trial=trial, character_source=frozen['target'])
        return entry, service.accept_trial(book, entry, 'candidate', '动作合适', '用收伞动作带出迟疑')

    first, result = accept('## 第 1 章\n### 场景：收伞\n出场人物：小阿杏\n### 场景：道别\n出场人物：阿杏\n', 'first')
    assert not result['production_match']
    story.prepare_context(book, '0001')
    assert '用收伞动作带出迟疑' not in story.read(book, 'cache/story-support/context.md')
    assert service.is_current(book, first['character_source'])
    second, result = accept('## 第 1 章\n### 场景：收伞\n出场人物：阿杏\n', 'second')
    assert result['production_match']
    story.prepare_context(book, '0001')
    assert '用收伞动作带出迟疑' in story.read(book, 'cache/story-support/context.md')
    assert service.is_current(book, second['character_source'])
    guide = book / 'story/0001/single_chapter_guide.md'
    guide.parent.mkdir(parents=True, exist_ok=True)
    guide.write_text('工作流生成的本章细纲。', encoding='utf-8')
    (guide.parent / 'chapter.md').write_text('生成的正文。', encoding='utf-8')
    story.prepare_context(book, '0001')
    assert '用收伞动作带出迟疑' in story.read(book, 'cache/story-support/context.md')
    assert not service.is_current(book, second['character_source'])


def test_ambiguous_pending_history_blocks_legacy_mutation_without_losing_record(service, book, monkeypatch):
    from importlib import import_module
    voice = import_module(service.__package__ + '.dependencies').sibling('voice_support')
    view = service.read(book)
    target = book / 'meta/character_voice.md'
    voice.save(book, view['sources'][1]['raw'])
    assert not (book / 'learning').exists()
    view = service.read(book)
    preview = service.preview(book, select(view) | {'replacement': '新声线。'}, view['revision'])
    rename = Path.replace
    voice_writes = 0

    def fail_rollback(self, destination):
        nonlocal voice_writes
        path = Path(destination)
        if path == target:
            voice_writes += 1
            if voice_writes > 1:
                raise OSError('source locked')
        if self.name == 'pending.json':
            raise OSError('archive locked')
        return rename(self, destination)

    monkeypatch.setattr(Path, 'replace', fail_rollback)
    with pytest.raises(OSError, match='source locked'):
        service.apply(book, preview, view['revision'])
    pending = book / 'learning/character_center/pending.json'
    journal = pending.read_bytes()
    target.write_bytes(b'outside edit')
    with pytest.raises(ValueError, match='人工核对'):
        voice.save(book, 'Another change')
    assert target.read_bytes() == b'outside edit'
    assert pending.read_bytes() == journal


def test_malformed_nested_state_is_omitted_even_with_a_real_quote(service, book):
    chapter = book / 'story/0001'
    chapter.mkdir(parents=True)
    body = '阿杏说她愿意留下。'
    (chapter / 'chapter.md').write_bytes(body.encode())
    (chapter / 'confirmed_state.json').write_text(json.dumps({
        'chapter': '0001', 'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'source_hashes': {},
        'characters': [{'name': '阿杏', 'source_chapter': '0001', 'evidence': body,
                        'snapshot': {'goal': {'injected': '剧情命令'}, 'knowledge': [False]},
                        'relationships': [{'target': '掌柜', 'change': {'not_a_string': 2}}]}]
    }), encoding='utf-8')
    assert service.read(book)['characters'][0]['states'] == []


def test_trial_snapshot_accounts_for_newly_adopted_guidance_and_excludes_itself(service, book):
    view = service.read(book)
    options = dict(purpose='dialogue_trial', chapter='0001', question='试读', scene='收伞',
                   baseline='她先说了两句。', character_ids=[select(view)['character_id']],
                   expected_revision=view['revision'])
    first = service.freeze(book, options | {'_request_id': 'first'})['target']
    second = service.freeze(book, options | {'_request_id': 'second'})['target']
    candidate = '{"candidate":"她合起伞。","checks":["仍使用阿杏的视角"]}'
    trial = service.finish(book, second, 'dialogue_trial', candidate)['trial']
    service.accept_trial(book, dict(id='second', status='completed', purpose='dialogue_trial',
                         trial=trial, character_source=second), 'candidate', '视角稳定', '用收伞动作')
    assert service.is_current(book, second)
    assert service.finish(book, first, 'dialogue_trial', candidate)['error_code'] == 'character_stale'
    latest = service.freeze(book, options | {'_request_id': 'third'})
    assert json.loads(latest['user'])['scoped_preferences'] == [{'reason': '视角稳定', 'carry_forward': '用收伞动作'}]


@pytest.mark.parametrize('late_facts', [[], [
    {'description': '下一章才录入的断言', 'source_chapter': '0001', 'evidence': '伞是她自己做的。'},
]])
def test_production_guidance_binds_world_at_chapter_start(service, book, late_facts):
    from importlib import import_module
    story = import_module(service.__package__ + '.dependencies').sibling('story_support')
    outline = book / 'outline/near_term_outline.md'
    outline.parent.mkdir()
    outline.write_text('## 第 2 章\n### 场景：收伞\n出场人物：阿杏\n', encoding='utf-8')

    def confirm(chapter, body, facts):
        folder = book / 'story' / chapter
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'chapter.md').write_bytes(body.encode())
        (folder / 'confirmed_state.json').write_text(json.dumps({
            'chapter': chapter, 'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'source_hashes': {},
            'world': {'facts': facts},
        }), encoding='utf-8')

    confirm('0001', '伞是她自己做的。', [
        {'description': '阿杏亲手制伞', 'source_chapter': '0001', 'evidence': '伞是她自己做的。'},
    ])
    view = service.read(book)
    frozen = service.freeze(book, dict(purpose='dialogue_trial', chapter='0002', question='试读',
                            scene='收伞', baseline='她说了几句。', _request_id='trial',
                            character_ids=[select(view)['character_id']], expected_revision=view['revision']))
    candidate = '{"candidate":"她拢住伞骨。","checks":["保留人物手上的伞"]}'
    trial = service.finish(book, frozen['target'], 'dialogue_trial', candidate)['trial']
    entry = dict(id='trial', status='completed', purpose='dialogue_trial', trial=trial,
                 character_source=frozen['target'])
    service.accept_trial(book, entry, 'candidate', '动作更贴合', '用手指的犹豫展示心情')
    confirm('0002', '阿杏把伞收了起来。', late_facts)
    story.prepare_context(book, '0002')
    prepared = story.read(book, 'cache/story-support/context.md')
    assert '用手指的犹豫展示心情' in prepared
    assert '下一章才录入的断言' not in prepared
    confirm('0001', '伞是她自己做的。', [])
    story.prepare_context(book, '0002')
    assert '用手指的犹豫展示心情' not in story.read(book, 'cache/story-support/context.md')


def test_legacy_save_does_not_read_unrelated_damaged_archive(service, book):
    from importlib import import_module
    voice = import_module(service.__package__ + '.dependencies').sibling('voice_support')
    archive = book / 'learning/character_center/history.json'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'truncated history')
    assert voice.save(book, '## 阿杏\n改过的声音') == {
        'status': 'success', 'file_path': str(book / 'meta/character_voice.md')}
    assert (book / 'meta/character_voice.md').read_text(encoding='utf-8') == '## 阿杏\n改过的声音'
    (book / 'meta/character_voice.md').unlink()
    assert voice.generate(book)['generation_mode'] == 'template'
    assert archive.read_bytes() == b'truncated history'
