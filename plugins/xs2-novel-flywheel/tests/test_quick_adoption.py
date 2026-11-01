"""Quick adoption exercises the real CLI against isolated book workspaces."""
import asyncio
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from types import SimpleNamespace

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SERVICE = PLUGIN / 'resources/script-library/xs2/console_service/console_service.py'
REFERENCE = PLUGIN / 'resources/script-library/xs2/reference_distill/reference_distill.py'
REF_DIR = REFERENCE.parent
sys.path.insert(0, str(REF_DIR))
from reference_choices import with_reference_choices, fingerprint


def service():
    spec = importlib.util.spec_from_file_location('quick_adoption_tests', SERVICE, submodule_search_locations=[str(SERVICE.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert hasattr(module, 'ReferenceAdoptionJobs'), 'plugin must own quick adoption business policy'
    return module


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def catalog(library='correct', name='代价推动', pov=None, scope=None, layer='narrative_lens'):
    items = [{'candidate_id': 'mechanism-' + library, 'mechanism': name, 'transfer_guidance': '旧规则',
              'constraints': [], 'scopes': ['mvp', 'polish'], 'layer': layer, 'target_pov': pov or [],
              'application_scope': scope or ['general'], 'evidence': [{'excerpt': '原作证据'}]}]
    data = with_reference_choices({'source': {'text_sha256': library}, 'candidates': items,
                                  'candidates_sha256': fingerprint(items), 'style_observations': [], 'conflict_patterns': []})
    return {'library_id': library, 'name': library, 'candidates': data, 'profile': {'markdown': '原作风格与篇幅'}}


def merge(base, incoming):
    from src.web.novel_library import enrich_candidates
    return enrich_candidates(base, incoming, exact_ids=True)


def runner(root, selection):
    result = subprocess.run([sys.executable, str(REFERENCE), 'adopt', '--selection-json', json.dumps(selection, ensure_ascii=False)],
                            cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise ValueError(result.stderr)


class Model:
    def __init__(self, response, before=None):
        self.response = response
        self.before = before
        self.closed = False
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.before:
            self.before()
        if isinstance(self.response, Exception):
            raise self.response
        return SimpleNamespace(content=json.dumps(self.response, ensure_ascii=False))

    async def aclose(self):
        self.closed = True


def setup_book(root, recommendation=None, manifest=True, characters=False):
    project = {'mode': 'short', 'values': {'premise': '许青为救被困的妹妹追查矿井事故，选择公开真相并承担失业代价。',
               'genre': '现实悬疑', 'narrative_pov': 'third_person', 'target_word_count': '8000', 'conflict_plan_mode': 'short_full'}}
    if manifest:
        write_json(root / '.novel-project.json', project)
    entry = {'id': 'adviser-1', 'purpose': 'advisor', 'status': 'completed', 'reply': '已分析方向', 'question': '我要写现实悬疑中的亲情与职业代价。',
             'configuration_base': {**project, 'advisor_brief': '现实悬疑中的亲情与职业代价'},
             'advisor_sections': {'direction': '许青追查矿难', 'hook': '救亲人与揭露真相之间的代价', 'writing': '第三人称短篇', 'risks': '避免巧合',
              'mechanism_recommendations': {'adopted_from_library': [recommendation or {'library_id': 'correct', 'candidate_id': 'mechanism-correct', 'mechanism': '代价推动'}]}}}
    write_json(root / 'learning/assistant-history.json', {'version': 1, 'entries': [entry]})
    (root / 'meta').mkdir(exist_ok=True)
    (root / 'meta/character_voice.md').write_text('原有声音不可覆盖', encoding='utf-8')
    if characters:
        (root / 'meta/character_profiles.md').write_text('# 人物\n\n## 许青\n矿工之女，谨慎、重情；对妹妹温和，对矿长克制质疑。\n\n## 许宁\n妹妹，敏锐，常以反问掩饰恐惧。', encoding='utf-8')
    (root / 'story/0001').mkdir(parents=True)
    (root / 'story/0001/chapter.md').write_text('用户已有正文', encoding='utf-8')
    return project


def decision(identifier='mechanism-correct', library='correct', **extra):
    return {'library_id': library, 'candidate_id': identifier, 'decision': 'adapt', 'reason': '适合许青揭露矿难的目标与代价链',
            'adaptation': '许青发现矿难线索后选择公开证据，失去矿上工作；以妹妹提供的旧照片回收短篇主线。', **extra}


def run_job(root, response=None, libraries=None, before=None, manifest=True, recommendation=None, characters=False, guard=None):
    setup_book(root, recommendation=recommendation, manifest=manifest, characters=characters)
    model = Model(response if response is not None else {'decisions': [decision()], 'voice_adaptations': []}, before)
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: model, lambda: libraries or [catalog()], merge, runner, threading.RLock(), guard=guard)
    request_id = str(uuid.uuid4())
    async def run():
        initial = jobs.start(root, request_id, {'advisor_entry_id': 'adviser-1', '_model_override': 'selected-model'})
        tasks = list(jobs.tasks.values())
        if tasks:
            await asyncio.gather(*tasks)
        return initial, jobs.get(root, request_id)
    initial, result = asyncio.run(run())
    return jobs, model, initial, result


def test_adopts_exact_library_into_versioned_context_and_preserves_novel(tmp_path):
    _, model, initial, result = run_job(tmp_path, libraries=[catalog('wrong'), catalog()])
    assert initial['status'] == 'checking'
    assert result['status'] == 'applied'
    assert [item['library_id'] for item in result['selected_references']] == ['correct']
    assert (tmp_path / 'learning/active.json').is_file()
    assert '许青发现矿难' in (tmp_path / 'learning/active_context.md').read_text(encoding='utf-8')
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == '用户已有正文'
    assert (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8') == '原有声音不可覆盖'
    assert json.loads((tmp_path / 'learning/library_refs.json').read_text(encoding='utf-8'))['items'] == ['correct']
    assert model.closed


@pytest.mark.parametrize('recommendation,libraries', [
    ({'mechanism': '代价'}, [catalog()]),
    ({'mechanism': '代价推动'}, [catalog(), catalog('duplicate')]),
    ({'library_id': 'missing', 'candidate_id': 'mechanism-correct'}, [catalog()]),
])
def test_missing_or_ambiguous_source_never_attaches_first_library(tmp_path, recommendation, libraries):
    _, model, _, result = run_job(tmp_path, libraries=libraries, recommendation=recommendation)
    assert result['status'] == 'no_match'
    assert not (tmp_path / 'learning/active.json').exists()
    assert not (tmp_path / 'learning/library_refs.json').exists()
    assert model.messages is None


def test_unique_exact_legacy_name_and_saved_adviser_base_support_new_book(tmp_path):
    _, _, _, result = run_job(tmp_path, recommendation={'mechanism': ' 代价推动 '}, manifest=False)
    assert result['status'] == 'applied'
    assert not (tmp_path / '.novel-project.json').exists()


@pytest.mark.parametrize('response', [
    {'decisions': [], 'voice_adaptations': []},
    {'decisions': [decision(), decision()], 'voice_adaptations': []},
    {'decisions': [decision(identifier='invented')], 'voice_adaptations': []},
    {'decisions': [decision(adaptation='')], 'voice_adaptations': []},
    ConnectionError('credentials must not leak'),
])
def test_invalid_or_failed_model_check_has_no_adoption_side_effects(tmp_path, response):
    _, model, _, result = run_job(tmp_path, response=response)
    assert result['status'] in {'review_required', 'failed'}
    assert not (tmp_path / 'learning/active.json').exists()
    assert not (tmp_path / 'learning/library_refs.json').exists()
    assert model.closed


@pytest.mark.parametrize('extra', [{'pov': ['first_person']}, {'scope': ['serial_arc']}])
def test_explicit_wrong_pov_or_scope_cannot_be_overruled_by_model(tmp_path, extra):
    _, _, _, result = run_job(tmp_path, libraries=[catalog(**extra)])
    assert result['status'] == 'review_required'
    assert not (tmp_path / 'learning/active.json').exists()
    assert result['skipped']


def test_edited_book_during_model_check_does_not_publish(tmp_path):
    def change():
        (tmp_path / 'meta/character_voice.md').write_text('用户在检查期间编辑', encoding='utf-8')
    _, _, _, result = run_job(tmp_path, before=change)
    assert result['status'] == 'review_required'
    assert result['error_code'] == 'stale'
    assert not (tmp_path / 'learning/active.json').exists()
    assert (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8') == '用户在检查期间编辑'


def test_voice_adapts_actual_characters_and_keeps_existing_voice(tmp_path):
    response = {'decisions': [decision()], 'voice_adaptations': [
        {'character_name': '许青', 'profile_evidence': '对妹妹温和，对矿长克制质疑', 'guidance': '面对妹妹时先问身体再谈证据；面对矿长时用短问句追究责任，压住愤怒。'},
        {'character_name': '许宁', 'profile_evidence': '常以反问掩饰恐惧', 'guidance': '对姐姐用反问掩饰害怕；独处时承认疼痛，避免说调查术语。'}]}
    _, _, _, result = run_job(tmp_path, response=response, libraries=[catalog(layer='character')], characters=True)
    assert result['status'] == 'applied'
    assert result['voice_status'] == 'adapted'
    text = (tmp_path / 'meta/character_voice_adaptations.md').read_text(encoding='utf-8')
    assert '许青' in text and '面对矿长' in text and '许宁' in text
    assert (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8') == '原有声音不可覆盖'


@pytest.mark.parametrize('voices', [[], [{'character_name': '原作主角', 'guidance': '沿用原作身世与口头禅'}]])
def test_dialogue_adoption_requires_book_character_voice_guidance(tmp_path, voices):
    _, _, _, result = run_job(tmp_path, response={'decisions': [decision()], 'voice_adaptations': voices}, libraries=[catalog(layer='dialogue')], characters=True)
    assert result['status'] == 'review_required'
    assert not (tmp_path / 'learning/active.json').exists()


def test_idempotent_request_and_restart_do_not_duplicate_blueprints(tmp_path):
    jobs, model, initial, result = run_job(tmp_path)
    async def again():
        return jobs.start(tmp_path, initial['id'], {'advisor_entry_id': 'adviser-1'})
    assert asyncio.run(again())['status'] == 'applied'
    assert len(list((tmp_path / 'learning/blueprints').glob('*.json'))) == 1
    assert jobs.latest(tmp_path)['id'] == result['id']
    pending = str(uuid.uuid4())
    write_json(tmp_path / f'learning/adoption-jobs/{pending}/job.json', {'id': pending, 'status': 'checking', 'created_at': '9999'})
    assert jobs.get(tmp_path, pending)['status'] == 'failed'


def test_client_recommendations_cannot_replace_saved_adviser(tmp_path):
    setup_book(tmp_path, recommendation={'mechanism': '不存在的写法'})
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: Model({'decisions': [decision()]}), lambda: [catalog()], merge, runner, threading.RLock())
    async def run():
        initial = jobs.start(tmp_path, str(uuid.uuid4()), {'advisor_entry_id': 'adviser-1', 'advisor_sections': {'mechanism_recommendations': {'adopted_from_library': [decision()]}}})
        if jobs.tasks:
            await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, initial['id'])
    assert asyncio.run(run())['status'] == 'no_match'


def test_adviser_catalog_injection_returns_exact_structured_source_ids(tmp_path):
    module = service()
    saved = setup_book(tmp_path)
    answer = {'reply': '推荐以职业代价推进矿难调查。', 'suggestions': [],
              'advisor_sections': {'direction': '许青调查', 'hook': '亲情代价', 'writing': '第三人称短篇', 'risks': '避免巧合',
               'mechanism_recommendations': {'adopted_from_library': [{'library_id': 'correct', 'candidate_id': 'mechanism-correct', 'mechanism': '代价推动'}]}}}
    model = Model(answer)
    jobs = module.create_assistant(lambda **kwargs: model, lambda **kwargs: None, catalog_loader=lambda: [catalog()])
    async def run():
        job = jobs.start(tmp_path, 'new-adviser', {'purpose': 'advisor', 'question': '怎么适配许青的矿难调查？', 'project': saved})
        await asyncio.gather(*list(jobs.tasks.values()))
        return next(item for item in jobs.history(tmp_path) if item['id'] == job['id'])
    result = asyncio.run(run())
    assert result['status'] == 'completed'
    context = json.loads(model.messages[1][1].split('参考上下文：\n', 1)[1])
    assert context['写法来源目录'][0]['library_id'] == 'correct'
    assert context['写法来源目录'][0]['candidates']['candidates'][0]['candidate_id'] == 'mechanism-correct'
    assert '原作证据' not in json.dumps(context['写法来源目录'], ensure_ascii=False)
    assert result['advisor_sections']['mechanism_recommendations']['adopted_from_library'][0]['candidate_id'] == 'mechanism-correct'


def test_adviser_rejects_model_invented_catalog_source_ids(tmp_path):
    module = service()
    sections = {'direction': '方向', 'hook': '看点', 'writing': '写法', 'risks': '风险',
                'mechanism_recommendations': {'adopted_from_library': [{'library_id': 'made-up', 'candidate_id': 'mechanism-correct', 'mechanism': '代价推动'}]}}
    with pytest.raises(ValueError):
        module.configuration.parse_advisor(json.dumps({'reply': '建议', 'suggestions': [], 'advisor_sections': sections}), 'short', catalog=[catalog()])


def test_voice_only_targets_suitable_roles_with_their_own_profile_evidence(tmp_path):
    voice = {'character_name': '许青', 'profile_evidence': '对妹妹温和，对矿长克制质疑',
             'guidance': '面对妹妹时先问身体再谈证据；面对矿长时用短问句追究责任，压住愤怒。'}
    _, _, _, result = run_job(tmp_path, response={'decisions': [decision()], 'voice_adaptations': [voice]}, libraries=[catalog(layer='dialogue')], characters=True)
    assert result['status'] == 'applied'
    assert [item['character_name'] for item in result['voice_adaptations']] == ['许青']


@pytest.mark.parametrize('evidence', ['', '常以反问掩饰恐惧', '原作主角生平'])
def test_voice_rejects_evidence_missing_or_belonging_to_another_role(tmp_path, evidence):
    voice = {'character_name': '许青', 'profile_evidence': evidence,
             'guidance': '面对妹妹时先问身体再谈证据；面对矿长时用短问句追究责任，压住愤怒。'}
    _, _, _, result = run_job(tmp_path, response={'decisions': [decision()], 'voice_adaptations': [voice]}, libraries=[catalog(layer='dialogue')], characters=True)
    assert result['status'] == 'review_required'
    assert not (tmp_path / 'learning/active.json').exists()


def test_source_profile_changed_during_review_invalidates_plan(tmp_path):
    libraries = [catalog()]
    def change():
        libraries[0]['profile'] = {'markdown': '第三人称已改成第一人称独白'}
    _, _, _, result = run_job(tmp_path, libraries=libraries, before=change)
    assert result['status'] == 'review_required'
    assert result['error_code'] == 'stale'
    assert not (tmp_path / 'learning/active.json').exists()


def test_pending_voice_can_be_adapted_after_characters_exist_without_new_blueprint(tmp_path):
    jobs, model, _, first = run_job(tmp_path, libraries=[catalog(layer='dialogue')])
    assert first['voice_status'] == 'pending_characters'
    (tmp_path / 'meta/character_profiles.md').write_text('## 许青\n矿工之女，对妹妹温和，对矿长克制质疑。', encoding='utf-8')
    model.response = {'decisions': [decision()], 'voice_adaptations': [{'character_name': '许青',
        'profile_evidence': '对妹妹温和，对矿长克制质疑', 'guidance': '面对妹妹先安抚后问证据；面对矿长用克制短句追问责任。'}]}
    async def again():
        initial = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, initial['id'])
    result = asyncio.run(again())
    assert result['status'] == 'applied'
    assert result['voice_status'] == 'adapted'
    assert (tmp_path / 'meta/character_voice_adaptations.md').is_file()
    assert len(list((tmp_path / 'learning/blueprints').glob('*.json'))) == 1


def test_existing_candidate_id_from_another_source_is_not_rebound(tmp_path):
    setup_book(tmp_path)
    old = catalog('original')['candidates']
    old['candidates'][0]['candidate_id'] = 'mechanism-correct'
    old['candidates_sha256'] = fingerprint(old['candidates'])
    write_json(tmp_path / 'learning/candidates.json', old)
    model = Model({'decisions': [decision()], 'voice_adaptations': []})
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: model, lambda: [catalog()], merge, runner, threading.RLock())
    async def run():
        job = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, job['id'])
    result = asyncio.run(run())
    assert result['status'] == 'review_required'
    assert not (tmp_path / 'learning/active.json').exists()
    assert json.loads((tmp_path / 'learning/candidates.json').read_text(encoding='utf-8'))['source']['text_sha256'] == 'original'


def test_edit_during_reference_cli_is_rechecked_before_publication(tmp_path):
    setup_book(tmp_path)
    def delayed_runner(stage, selection):
        runner(stage, selection)
        (tmp_path / 'meta/character_voice.md').write_text('用户在CLI执行期间编辑', encoding='utf-8')
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: Model({'decisions': [decision()], 'voice_adaptations': []}), lambda: [catalog()], merge, delayed_runner, threading.RLock())
    async def run():
        job = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, job['id'])
    result = asyncio.run(run())
    assert result['status'] == 'review_required'
    assert result['error_code'] == 'stale'
    assert not (tmp_path / 'learning/active.json').exists()


@pytest.mark.parametrize('external_change', [False, True])
def test_restart_rolls_back_partial_publication_without_losing_external_edits(tmp_path, external_change):
    setup_book(tmp_path)
    identifier = str(uuid.uuid4())
    folder = tmp_path / f'learning/adoption-jobs/{identifier}'
    write_json(folder / 'job.json', {'id': identifier, 'status': 'checking', 'created_at': '2026', 'selected_references': []})
    old_context, new_context = b'old adopted context', b'new uncommitted context'
    old_active, new_active = b'old active receipt', b'new intended receipt'
    (tmp_path / 'learning/active_context.md').write_bytes(new_context)
    (tmp_path / 'learning/active.json').write_bytes(old_active)
    (folder / 'backups/learning').mkdir(parents=True)
    (folder / 'backups/learning/active_context.md').write_bytes(old_context)
    (folder / 'backups/learning/active.json').write_bytes(old_active)
    new_voice = b'new uncommitted voice'
    (tmp_path / 'meta/character_voice_adaptations.md').write_bytes(b'author new edit' if external_change else new_voice)
    sha = lambda value: hashlib.sha256(value).hexdigest()
    write_json(folder / 'publication.json', {'state': 'publishing', 'changes': {
        'learning/active_context.md': {'before_sha256': sha(old_context), 'intended_sha256': sha(new_context)},
        'learning/active.json': {'before_sha256': sha(old_active), 'intended_sha256': sha(new_active)},
        'meta/character_voice_adaptations.md': {'before_sha256': None, 'intended_sha256': sha(new_voice)}}})
    jobs = service().ReferenceAdoptionJobs(None, None, None, None, threading.RLock())
    recovered = jobs.get(tmp_path, identifier)
    assert recovered['status'] == 'review_required'
    assert (tmp_path / 'learning/active_context.md').read_bytes() == old_context
    assert (tmp_path / 'learning/active.json').read_bytes() == old_active
    voice = tmp_path / 'meta/character_voice_adaptations.md'
    assert voice.read_bytes() == b'author new edit' if external_change else not voice.exists()


def test_restart_finalizes_completed_publication_without_reapplying(tmp_path):
    jobs, _, initial, result = run_job(tmp_path)
    path = tmp_path / f'learning/adoption-jobs/{initial["id"]}/job.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved.update(status='checking', selected_references=[])
    write_json(path, saved)
    restarted = service().ReferenceAdoptionJobs(None, None, None, None, threading.RLock())
    restored = restarted.get(tmp_path, initial['id'])
    assert restored['status'] == 'applied'
    assert restored['selected_references'][0]['library_id'] == 'correct'
    assert len(list((tmp_path / 'learning/blueprints').glob('*.json'))) == 1


def test_restart_preserves_author_edits_after_durable_commit(tmp_path):
    _, _, initial, _ = run_job(tmp_path)
    path = tmp_path / f'learning/adoption-jobs/{initial["id"]}/job.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['status'] = 'checking'
    write_json(path, saved)
    (tmp_path / 'learning/active_context.md').write_text('作者在提交后调整的创作指导', encoding='utf-8')
    restarted = service().ReferenceAdoptionJobs(None, None, None, None, threading.RLock())
    restored = restarted.get(tmp_path, initial['id'])
    assert restored['status'] == 'applied'
    assert (tmp_path / 'learning/active_context.md').read_text(encoding='utf-8') == '作者在提交后调整的创作指导'
    assert (tmp_path / 'learning/active.json').exists()


def test_stop_cancels_review_without_publishing(tmp_path):
    setup_book(tmp_path)
    class Blocked(Model):
        async def ainvoke(self, messages):
            await asyncio.Event().wait()
    model = Blocked(None)
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: model, lambda: [catalog()], merge, runner, threading.RLock())
    async def run():
        initial = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.sleep(0)
        assert jobs.has_active(tmp_path)
        await jobs.stop()
        return jobs.get(tmp_path, initial['id'])
    result = asyncio.run(run())
    assert result['status'] == 'failed'
    assert result['error_code'] == 'interrupted'
    assert not (tmp_path / 'learning/active.json').exists()
    assert model.closed


def test_only_safe_reviewed_items_apply_and_caution_stays_unattached(tmp_path):
    setup_book(tmp_path)
    path = tmp_path / 'learning/assistant-history.json'
    history = json.loads(path.read_text(encoding='utf-8'))
    recs = history['entries'][0]['advisor_sections']['mechanism_recommendations']['adopted_from_library']
    recs.append({'library_id': 'caution', 'candidate_id': 'mechanism-caution', 'mechanism': '结尾悬念'})
    write_json(path, history)
    model = Model({'decisions': [decision(), decision(identifier='mechanism-caution', library='caution', decision='caution', reason='不适合短篇收束')], 'voice_adaptations': []})
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: model, lambda: [catalog(), catalog('caution', name='结尾悬念')], merge, runner, threading.RLock())
    async def run():
        initial = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, initial['id'])
    result = asyncio.run(run())
    assert result['status'] == 'applied'
    assert [item['library_id'] for item in result['selected_references']] == ['correct']
    assert result['skipped'][0]['decision'] == 'caution'
    assert json.loads((tmp_path / 'learning/library_refs.json').read_text(encoding='utf-8'))['items'] == ['correct']


def test_new_source_retains_prior_adoption_with_flat_journal_backups(tmp_path):
    jobs, model, _, first = run_job(tmp_path)
    path = tmp_path / 'learning/assistant-history.json'
    history = json.loads(path.read_text(encoding='utf-8'))
    history['entries'][0]['advisor_sections']['mechanism_recommendations']['adopted_from_library'] = [
        {'library_id': 'second', 'candidate_id': 'mechanism-second', 'mechanism': '反问透露证据'}]
    write_json(path, history)
    jobs.catalog_loader = lambda: [catalog('second', name='反问透露证据')]
    model.response = {'decisions': [decision(identifier='mechanism-second', library='second')], 'voice_adaptations': []}
    async def run():
        initial = jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
        return jobs.get(tmp_path, initial['id'])
    result = asyncio.run(run())
    assert result['status'] == 'applied'
    active = json.loads((tmp_path / 'learning/active.json').read_text(encoding='utf-8'))
    blueprint = json.loads((tmp_path / active['blueprint_path']).read_text(encoding='utf-8'))
    assert blueprint['selected_candidate_ids'] == ['mechanism-correct', 'mechanism-second']
    backups = tmp_path / f'learning/adoption-jobs/{result["id"]}/backups'
    assert all(path.is_file() for path in backups.iterdir())


def test_review_closes_owned_sdk_transport_when_model_has_no_close(tmp_path):
    setup_book(tmp_path)
    class Client:
        closed = False
        async def close(self):
            self.closed = True
    model = Model({'decisions': [decision()], 'voice_adaptations': []})
    model.aclose = None
    model.root_async_client = Client()
    jobs = service().ReferenceAdoptionJobs(lambda **kwargs: model, lambda: [catalog()], merge, runner, threading.RLock())
    async def run():
        jobs.start(tmp_path, str(uuid.uuid4()), {'entry_id': 'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
    asyncio.run(run())
    assert model.root_async_client.closed
