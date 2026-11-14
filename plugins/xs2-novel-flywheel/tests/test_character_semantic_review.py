"""The new-card gate must publish reviewed cards without touching author files."""
import copy
import importlib.util
import json
from pathlib import Path
import os
import subprocess
import sys
import shutil

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/character_review/character_review.py'


@pytest.fixture
def gate():
    assert MODULE.is_file(), 'standalone semantic gate is missing'
    spec = importlib.util.spec_from_file_location('semantic_gate_tests', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def person():
    return {'card_schema': 'xs2.character.v2', 'name': '林叶', 'true_name': '林叶',
            'aliases': [], 'role': '修伞师', 'want': '修好屋顶', 'fear': '失信',
            'contradiction': '想独立也希望人帮忙', 'facts': ['最终归还蓝伞'],
            'personality': '必须先问成本', 'plot_constraints': ['先问再答'],
            'relationships': [{'with': '顾石', 'dynamic': '曾经合作'}],
            'voice': {'baseline': '每次必须先问成本', 'by_relationship': [
                {'with': '顾石', 'guidance': '必须先问再答'}], 'avoid': [],
                'preferences': ['问成本'], 'when_adaptable': [], 'boundaries': []}}


def setup(gate, root, mode='compact'):
    world = root / 'meta/world_foundation.md'
    world.parent.mkdir(parents=True)
    world.write_text('林叶借给顾石一把蓝伞，尚未归还。', encoding='utf-8')
    variables = gate.preflight(root, '归还蓝伞', '允许犹豫，也能求助', '现实世界', world, 'task-1')
    batch, draft = Path(variables['card_batch_dir']), Path(variables['card_draft_dir'])
    record = person()
    if mode == 'compact':
        write(draft / 'cache/short/characters.json', {'characters': [record]})
        gate.render_compact(batch)
    else:
        voice = record.pop('voice')
        write(draft / 'cache/character/skeleton.json', {'characters': [record]})
        deep = copy.deepcopy(record)
        deep['personality'] = '深化里的不同倾向'
        deep['bottom_line'] = {'condition': '受人帮助', 'reaction_when_crossed': '希望偿还'}
        write(draft / 'cache/character/林叶_deep.json', deep)
        write(draft / 'cache/character/beliefs.json', {'beliefs': [{'character': '林叶', 'core_belief': '兑现承诺'}]})
        write(draft / 'cache/character/voice.json', {'characters': [{'name': '林叶', 'voice_positioning': voice['baseline'],
              'syntax_fingerprint': {'sentence_preference': '先问再答', 'catchphrases': []},
              'forbidden_speech': [], 'preferences': ['问成本']}]})
        gate.render_full(draft)
    prepared = gate.prepare(batch)
    request = json.loads(Path(prepared['card_review_input_file']).read_text(encoding='utf-8'))
    voice = copy.deepcopy(request['characters'][0]['voice'])
    if mode == 'compact':
        voice['baseline'] = '通常先问成本，也能求助'
    else:
        voice['voice_positioning'] = '通常先问成本，也能求助'
    review = {'schema': 'xs2.character.semantic-review.v2', 'task_id': 'task-1',
              'source_sha256': prepared['card_review_binding_sha'], 'status': 'accepted',
              'characters': [{'name': '林叶', 'facts': ['林叶借给顾石一把蓝伞，尚未归还。'],
                'personality': '珍惜独立，允许犹豫，也能求助', 'plot_constraints': ['归还蓝伞'], 'voice': voice,
                'persona_edits': [], 'changes': [{'field': field, 'reason': '遵循权威原文',
                  'source_id': 'author.human_intent' if field in ('personality', 'voice') else 'world' if field == 'facts' else 'author.premise',
                  'evidence_quote': '允许犹豫，也能求助' if field in ('personality', 'voice') else '尚未归还' if field == 'facts' else '归还蓝伞'}
                 for field in ('facts', 'personality', 'plot_constraints', 'voice')]}], 'blocking_issues': []}
    return variables, prepared, request, review


def apply(gate, variables, prepared, review):
    text = json.dumps(review, ensure_ascii=False)
    Path(variables['card_review_result_file']).write_text(text, encoding='utf-8')
    return gate.apply(variables['card_batch_dir'], prepared['card_review_binding_sha'], text)


@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_review_reaches_real_renderers_and_preserves_raw(gate, tmp_path, mode):
    variables, prepared, request, review = setup(gate, tmp_path, mode)
    assert request['task_id'] == 'task-1'
    assert request['source_sha256'] == prepared['card_review_binding_sha']
    raw = {p: p.read_bytes() for p in Path(variables['card_draft_dir']).rglob('*') if p.is_file()}
    receipt = apply(gate, variables, prepared, review)
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    assert '尚未归还' in profile and '最终归还蓝伞' not in profile
    assert profile.count('珍惜独立，允许犹豫，也能求助') == 1
    assert '通常先问成本，也能求助' in (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert all(p.read_bytes() == content for p, content in raw.items())
    assert gate.apply(variables['card_batch_dir'], prepared['card_review_binding_sha'], json.dumps(review, ensure_ascii=False)) == receipt
    if mode == 'full':
        deep = json.loads((tmp_path / 'cache/character/林叶_deep.json').read_text(encoding='utf-8'))
        skeleton = json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8'))['characters'][0]
        assert deep['personality'] == skeleton['personality']
        assert deep['bottom_line'] == {'condition': '受人帮助', 'reaction_when_crossed': '希望偿还'}


@pytest.mark.parametrize('existing', ['meta/character_profiles.md', 'meta/character_voice.md',
                                      'cache/character/legacy.json', 'cache/short/characters.json'])
def test_preflight_preserves_existing_card_bytes(gate, tmp_path, existing):
    path = tmp_path / existing
    path.parent.mkdir(parents=True)
    path.write_bytes(b'author\r\n')
    world = tmp_path / 'world.md'
    world.write_text('world', encoding='utf-8')
    with pytest.raises(ValueError):
        gate.preflight(tmp_path, 'a', 'b', 'c', world, 'task')
    assert path.read_bytes() == b'author\r\n'
    assert not (tmp_path / 'cache/character-review').exists()


def test_claim_retry_never_resets_author_world_baseline(gate, tmp_path):
    world = tmp_path / 'world.md'
    world.write_text('original', encoding='utf-8')
    args = (tmp_path, 'a', 'b', 'c', world, 'task')
    variables = gate.preflight(*args)
    assert gate.preflight(*args) == variables
    for changed in [(tmp_path, 'a', 'b', 'c', world, 'other'), (tmp_path, 'new', 'b', 'c', world, 'task')]:
        with pytest.raises(ValueError):
            gate.preflight(*changed)
    world.write_text('edited', encoding='utf-8')
    with pytest.raises(ValueError):
        gate.preflight(*args)


@pytest.mark.parametrize('prior_state', ['failed', 'running', 'foreign', 'draft_exists'])
def test_native_preflight_retires_only_empty_terminal_claim(gate, tmp_path, monkeypatch, prior_state):
    root = tmp_path / 'book'
    root.mkdir()
    world = root / 'world.md'
    world.write_text('原始设定', encoding='utf-8')
    args = (root, '题材', '人设', '现实世界', world)
    first = gate.preflight(*args, 'task-first')
    old_batch = Path(first['card_batch_dir'])
    claim = old_batch.parent / 'claim.json'
    old_bytes = claim.read_bytes()
    if prior_state == 'draft_exists':
        write(old_batch / 'draft/characters.json', {'characters': [person()]})

    host = tmp_path / 'host'
    (host / 'src').mkdir(parents=True)
    workflow = 'xs2-novel-flywheel-character'
    tasks = host / 'data/workflows' / workflow / 'tasks'
    snapshot = {'workflow_id': workflow, 'nodes': [], 'variables': []}
    old_task = {'workflow_id': workflow, 'task_id': 'task-first',
                'workspace_override': str(root if prior_state != 'foreign' else host),
                'status': 'running' if prior_state == 'running' else 'failed',
                'node_states': {'script_card_preflight': {'status': 'completed'}}}
    new_task = {'workflow_id': workflow, 'task_id': 'task-next', 'status': 'running',
                'workspace_override': str(root), 'created_at': '2026-11-12T00:00:00+00:00',
                'snapshot_definition': snapshot}
    write(tasks / 'task-first.json', old_task)
    write(tasks / 'task-next.json', new_task)
    monkeypatch.setenv('DETERMINFLOW_PROJECT_DIR', str(host))
    monkeypatch.setenv('WORKFLOW_ID', workflow)
    monkeypatch.setenv('TASK_ID', 'task-next')
    source = MODULE.parents[1] / 'production_guard/production_guard.py'
    spec = importlib.util.spec_from_file_location('semantic_preflight_guard', source)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    guard.run(root, 'character', '0001', 'task-next', workflow)

    archived = old_batch / 'retired-claim.json'
    if prior_state == 'failed':
        result = gate.preflight(*args)
        assert Path(result['card_batch_dir']).name == 'task-next'
        assert archived.read_bytes() == old_bytes
        assert gate.preflight(*args) == result
    else:
        with pytest.raises(ValueError):
            gate.preflight(*args)
        assert claim.read_bytes() == old_bytes
        assert not archived.exists()


def test_project_runtime_progress_tolerated_but_author_values_frozen(gate, tmp_path):
    project = tmp_path / '.novel-project.json'
    original = {'values': {'premise': '归还蓝伞', 'human_intent': '允许犹豫，也能求助', 'world_intent': '现实世界'},
                'runtime': {'status': 'queued', 'updated_at': 'earlier'}}
    write(project, original)
    variables, prepared, _, review = setup(gate, tmp_path)
    changed = copy.deepcopy(original)
    changed['runtime'] = {'status': 'running', 'updated_at': 'later'}
    write(project, changed)
    receipt = apply(gate, variables, prepared, review)
    assert receipt['completed']
    changed['values']['human_intent'] = '新作者要求'
    write(project, changed)
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert json.loads(project.read_text(encoding='utf-8')) == changed


def test_preflight_cli_raw_world_path_stdin(gate, tmp_path):
    world = tmp_path / '世界 input.md'
    world.write_text('输入世界', encoding='utf-8')
    environment = {**os.environ, 'TASK_ID': 'cli-task', 'PYTHONUTF8': '1'}
    result = subprocess.run([sys.executable, str(MODULE), 'preflight', '--premise', '中文"原文\n下一行',
        '--human-intent', '愿望', '--world-intent', '世界', '--world-file-stdin'], cwd=tmp_path,
        input=str(world), capture_output=True, encoding='utf-8', env=environment)
    assert result.returncode == 0, result.stderr
    assert '<WF_VAR>card_batch_dir:' in result.stdout
    claim = json.loads((tmp_path / 'cache/character-review/claim.json').read_text(encoding='utf-8'))
    assert claim['authority']['world'] == '输入世界'
    assert claim['authority']['author.premise'] == '中文"原文\n下一行'


def relocated_gate(root, group='xs2-novel-flywheel-xs2'):
    library = root / 'script-library'
    for source_group, target_group, script in [('xs2', group, 'character_review'),
            ('xs2', group, 'short_preparation'), ('nvl', 'xs2-novel-flywheel-nvl', 'json_to_md')]:
        source = MODULE.parents[2] / source_group / script / (script + '.py')
        target = library / target_group / script / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    spec = importlib.util.spec_from_file_location('relocated_review_gate', library / group / 'character_review/character_review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, library


def test_real_runtime_qualified_renderer_groups_resolve_without_main_imports(gate, tmp_path):
    runtime, library = relocated_gate(tmp_path / 'runtime')
    book = tmp_path / 'book'
    variables, prepared, _, review = setup(runtime, book)
    apply(runtime, variables, prepared, review)
    assert '尚未归还' in (book / 'meta/character_profiles.md').read_text(encoding='utf-8')


def test_renderer_drift_blocks_publication(gate, tmp_path):
    runtime, library = relocated_gate(tmp_path / 'runtime', 'xs2')
    variables, prepared, _, review = setup(runtime, tmp_path / 'book')
    renderer = library / 'xs2/short_preparation/short_preparation.py'
    renderer.write_bytes(renderer.read_bytes() + b'\n# drift\n')
    with pytest.raises(ValueError): apply(runtime, variables, prepared, review)
    assert not (tmp_path / 'book/meta/character_profiles.md').exists()


@pytest.mark.parametrize('bad', ['task', 'source', 'missing', 'duplicate', 'renamed', 'unknown',
                               'no-evidence', 'false-evidence', 'voice-target', 'voice-shape',
                               'blocked', 'heading', 'fence', 'voice-quota'])
def test_invalid_reviews_never_publish(gate, tmp_path, bad):
    variables, prepared, request, review = setup(gate, tmp_path)
    char = review['characters'][0]
    if bad == 'task': review['task_id'] = 'other'
    elif bad == 'source': review['source_sha256'] = '0' * 64
    elif bad == 'missing': review['characters'] = []
    elif bad == 'duplicate': review['characters'].append(copy.deepcopy(char))
    elif bad == 'renamed': char['name'] = '别人'
    elif bad == 'unknown': char['relationships'] = []
    elif bad == 'no-evidence': char['changes'] = []
    elif bad == 'false-evidence': char['changes'][0]['evidence_quote'] = '不存在的原文'
    elif bad == 'voice-target': char['voice']['by_relationship'][0]['with'] = '别人'
    elif bad == 'voice-shape': char['voice']['new'] = '新声音结构'
    elif bad == 'voice-quota': char['voice']['avoid'].append('禁止提问')
    elif bad == 'blocked': review['status'] = 'blocked'
    elif bad == 'heading': char['personality'] = '文本\n## 伪角色'
    elif bad == 'fence': char['personality'] = '文本\n```'
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert not (tmp_path / 'meta/character_profiles.md').exists()


@pytest.mark.parametrize('drift', ['world', 'draft', 'binding', 'stdin', 'duplicate-json', 'result'])
def test_source_and_transport_drift_rejected(gate, tmp_path, drift):
    variables, prepared, request, review = setup(gate, tmp_path)
    text = json.dumps(review, ensure_ascii=False)
    Path(variables['card_review_result_file']).write_text(text, encoding='utf-8')
    binding = prepared['card_review_binding_sha']
    if drift == 'world': (tmp_path / 'meta/world_foundation.md').write_text('edited', encoding='utf-8')
    elif drift == 'draft': Path(variables['card_draft_short_characters']).write_text('{}', encoding='utf-8')
    elif drift == 'binding': binding = '0' * 64
    elif drift == 'stdin': text = text.replace('accepted', 'blocked')
    elif drift == 'duplicate-json':
        text = text.replace('"status": "accepted"', '"status": "blocked", "status": "accepted"')
        Path(variables['card_review_result_file']).write_text(text, encoding='utf-8')
    elif drift == 'result': Path(variables['card_review_result_file']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError): gate.apply(variables['card_batch_dir'], binding, text)
    assert not (tmp_path / 'meta/character_profiles.md').exists()


def test_exclusive_publication_collision_preserves_user_bytes(gate, tmp_path, monkeypatch):
    variables, prepared, _, review = setup(gate, tmp_path)
    original = gate.os.link
    def race(source, target, *args, **kwargs):
        if str(target).endswith('character_profiles.md'):
            Path(target).write_bytes(b'user racing edit\r\n')
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(gate.os, 'link', race)
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert (tmp_path / 'meta/character_profiles.md').read_bytes() == b'user racing edit\r\n'


@pytest.mark.parametrize('edited', [False, True])
def test_partial_publication_can_resume_and_preserves_later_user_edit(gate, tmp_path, monkeypatch, edited):
    variables, prepared, _, review = setup(gate, tmp_path)
    original, count = gate.os.link, 0
    def failure(source, target, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2: raise OSError('injected publication failure')
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(gate.os, 'link', failure)
    with pytest.raises(OSError): apply(gate, variables, prepared, review)
    published = [tmp_path / name for name in ('cache/short/characters.json', 'cache/character/skeleton.json',
                  'cache/character/voice.json', 'meta/character_profiles.md', 'meta/character_voice.md') if (tmp_path / name).is_file()]
    assert published
    monkeypatch.setattr(gate.os, 'link', original)
    if edited:
        published[0].write_bytes(b'later author edit')
        with pytest.raises(ValueError): apply(gate, variables, prepared, review)
        assert published[0].read_bytes() == b'later author edit'
    else:
        apply(gate, variables, prepared, review)
        assert '尚未归还' in (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')


def test_completed_receipt_does_not_recreate_deleted_author_destination(gate, tmp_path):
    variables, prepared, _, review = setup(gate, tmp_path)
    apply(gate, variables, prepared, review)
    profile = tmp_path / 'meta/character_profiles.md'
    profile.unlink()
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert not profile.exists()


def test_unknown_publication_journal_destination_rejected(gate, tmp_path, monkeypatch):
    variables, prepared, _, review = setup(gate, tmp_path)
    original = gate.os.link
    def failure(*args, **kwargs): raise OSError('injected before publication')
    monkeypatch.setattr(gate.os, 'link', failure)
    with pytest.raises(OSError): apply(gate, variables, prepared, review)
    monkeypatch.setattr(gate.os, 'link', original)
    batch = Path(variables['card_batch_dir'])
    journal = json.loads((batch / 'publication.json').read_text(encoding='utf-8'))
    import hashlib
    payload = b'unsupported output'
    journal['output_sha256']['meta/other.md'] = hashlib.sha256(payload).hexdigest()
    path = batch / 'publication/meta/other.md'
    path.write_bytes(payload)
    write(batch / 'publication.json', journal)
    with pytest.raises(ValueError): apply(gate, variables, prepared, review)
    assert not (tmp_path / 'meta/other.md').exists()
