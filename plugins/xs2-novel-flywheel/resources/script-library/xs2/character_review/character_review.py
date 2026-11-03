"""Standalone new-card review gate. All model work stays in a task-owned draft."""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CARD = 'xs2.character.v2'
SCHEMA = 'xs2.character.semantic-review.v2'
INPUT_SCHEMA = 'xs2.character.semantic-review-input.v2'
SEMANTICS = ('facts', 'personality', 'plot_constraints')
PERSONA_ROOT = ('want', 'fear', 'contradiction')
PERSONA_DEEP = {
    'core_desire': ('surface_goal', 'deep_desire'),
    'deep_fear': ('fear',),
    'bottom_line': ('reaction_when_crossed',),
    'key_trauma': ('stress_response', 'impact_on_behavior'),
    'internal_contradiction': ('conflicting_elements', 'possible_direction'),
    'arc_potential': ('growth_direction', 'corruption_direction', 'key_choice'),
    'secret': ('exposure_consequence',),
}
METADATA = ('meta/character_profiles.md', 'meta/character_voice.md')
TASK = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


class ReviewCorrectionNeeded(ValueError):
    """Only missing coverage or nonexact evidence quotes permit model correction."""

    def __init__(self, missing_fields, quote_mismatches=None):
        self.missing_fields = missing_fields
        self.quote_mismatches = quote_mismatches or []
        codes = []
        if missing_fields: codes.append('[character_review_missing_evidence]')
        if self.quote_mismatches: codes.append('[character_review_quote_mismatch]')
        diagnostic = json.dumps({'missing_fields': missing_fields, 'quote_mismatches': self.quote_mismatches},
                                ensure_ascii=False, sort_keys=True)
        instruction = (' Copy continuous real source text exactly, without reordering words or punctuation;'
                       ' resubmit the complete review JSON.') if self.quote_mismatches else ''
        super().__init__(' '.join(codes) + ' Review evidence correction required: ' + diagnostic + instruction)


class EvidenceQuoteMismatch(ValueError):
    """An eligible source exists but its quoted text does not match exactly."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(path):
    return _sha(Path(path).read_bytes())


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _loads(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('non-finite JSON')))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError('plain JSON document required') from error


def _load(path):
    return _loads(Path(path).read_text(encoding='utf-8-sig'))


def _safe(path):
    """Reject links, junctions and redirected ancestors, including nonexistent children."""
    path = Path(os.path.abspath(path))
    if path.resolve() != path:
        raise ValueError('linked or escaping path: ' + str(path))
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
            raise ValueError('linked path: ' + str(path))
        cursor = cursor.parent
    return path


def _under(root, relative):
    root = _safe(root)
    path = _safe(root / relative)
    if not path.is_relative_to(root):
        raise ValueError('path escapes owned root')
    return path


def _write_new(path, data):
    path = _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def _save_owned(path, value):
    """Replace only a task journal, never a book card or raw source."""
    path = _safe(path)
    fd, temporary = tempfile.mkstemp(prefix='.review-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(value).encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _variables(batch):
    draft = batch / 'draft'
    return {'card_batch_dir': str(batch), 'card_draft_dir': str(draft),
            'card_draft_relative': batch.relative_to(batch.parents[2]).as_posix() + '/draft',
            'card_draft_skeleton': str(draft / 'cache/character/skeleton.json'),
            'card_draft_beliefs': str(draft / 'cache/character/beliefs.json'),
            'card_draft_voice_json': str(draft / 'cache/character/voice.json'),
            'card_draft_profiles': str(draft / METADATA[0]),
            'card_draft_voice': str(draft / METADATA[1]),
            'card_draft_short_characters': str(draft / 'cache/short/characters.json'),
            'card_review_input_file': str(batch / 'review-input.json'),
            'card_review_result_file': str(batch / 'review-result.json')}


def _canonical(root):
    paths = []
    for relative in (*METADATA, 'cache/short/characters.json'):
        path = _under(root, relative)
        if path.exists():
            paths.append(path)
    character_dir = _under(root, 'cache/character')
    if character_dir.exists():
        if not character_dir.is_dir():
            paths.append(character_dir)
        else:
            paths.extend(_safe(p) for p in character_dir.rglob('*') if p.is_file() or p.is_symlink())
    return paths


def _project_author(root):
    path = _under(root, '.novel-project.json')
    if not path.exists():
        return None
    document = _load(path)
    values = document.get('values', {}) if isinstance(document, dict) else None
    if not isinstance(values, dict):
        raise ValueError('project author values must be an object')
    return {key: values[key] for key in ('premise', 'human_intent', 'world_intent') if key in values}


def preflight(book_dir, premise, human_intent, world_intent, world_file, task_id=None):
    """Claim a new book's character outputs; return absolute workflow path variables."""
    root = _safe(book_dir)
    task_id = task_id if task_id is not None else os.environ.get('TASK_ID', '')
    if not isinstance(task_id, str) or not TASK.fullmatch(task_id):
        raise ValueError('TASK_ID must be a safe single path component')
    if any(not isinstance(value, str) for value in (premise, human_intent, world_intent)):
        raise ValueError('author sources must be strings')
    world = _safe(root / world_file)
    if not world.is_file():
        raise ValueError('world source must be an existing regular file')
    authority = {'author.premise': premise, 'author.human_intent': human_intent,
                 'author.world_intent': world_intent, 'world': world.read_text(encoding='utf-8-sig')}
    sources = {str(world): _digest(world)}
    expected = {'task_id': task_id, 'book_dir': str(root), 'authority': authority,
                'source_files': sources, 'project_author': _project_author(root)}
    claim = _under(root, 'cache/character-review/claim.json')
    batch = _under(root, f'cache/character-review/{task_id}')
    if claim.exists():
        if _load(claim) != expected:
            raise ValueError('task claim or immutable author/world sources changed')
        if not batch.is_dir():
            raise ValueError('claimed task draft is missing')
        return _variables(batch)
    if _canonical(root):
        raise ValueError('existing canonical character files are preserved; new-card gate only')
    if batch.exists():
        raise ValueError('unclaimed task directory already exists')
    try:
        _write_new(claim, _json(expected).encode('utf-8'))
    except FileExistsError as error:
        raise ValueError('another character task already owns this book') from error
    batch.mkdir()
    (batch / 'draft').mkdir()
    return _variables(batch)


def _context(batch_dir):
    batch = _safe(batch_dir)
    if not TASK.fullmatch(batch.name) or batch.parent.name != 'character-review' or batch.parent.parent.name != 'cache':
        raise ValueError('batch must be cache/character-review/TASK_ID')
    root = batch.parents[2]
    claim_path = _under(root, 'cache/character-review/claim.json')
    claim = _load(claim_path)
    if claim.get('task_id') != batch.name or claim.get('book_dir') != str(root):
        raise ValueError('batch task/claim identity mismatch')
    env_task = os.environ.get('TASK_ID')
    if env_task and env_task != batch.name:
        raise ValueError('environment TASK_ID differs from claim')
    if _project_author(root) != claim['project_author']:
        raise ValueError('immutable project author values changed')
    for name, digest in claim['source_files'].items():
        path = _safe(name)
        if not path.is_file() or _digest(path) != digest:
            raise ValueError('immutable author/world source changed')
    return batch, root, claim


def _renderer(kind):
    library = _safe(Path(__file__).absolute().parents[2])
    group, script = ('xs2', 'short_preparation') if kind == 'compact' else ('nvl', 'json_to_md')
    candidates = []
    for directory in library.iterdir():
        if directory.name == group or directory.name.endswith('-' + group):
            candidate = directory / script / (script + '.py')
            if candidate.exists():
                candidate = _safe(candidate)
                if not candidate.is_relative_to(library) or not candidate.is_file():
                    raise ValueError('renderer escapes script-library')
                candidates.append(candidate)
    if len(candidates) != 1:
        raise ValueError('renderer missing or ambiguous in this script-library: ' + kind)
    return candidates[0]


def _run(script, args, cwd):
    result = subprocess.run([sys.executable, str(script), *map(str, args)], cwd=_safe(cwd),
                            capture_output=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('character renderer rejected candidate: ' + result.stderr.strip())


def render_full(draft_dir):
    """Run the existing full renderer CLI (also usable by synthetic integration tests)."""
    draft = _safe(draft_dir)
    renderer = _renderer('full')
    _run(renderer, ['--mode', 'character', '--book-dir', draft,
                    '--output', draft / METADATA[0]], draft)
    _run(renderer, ['--mode', 'voice', '--voice-json', draft / 'cache/character/voice.json',
                    '--output', draft / METADATA[1], '--title', '角色声音锚'], draft)


def render_compact(batch_dir):
    batch, _, _ = _context(batch_dir)
    draft = _under(batch, 'draft')
    _records(draft)  # validate v2 identities before renderer performs any deep lookup
    _run(_renderer('compact'), ['characters', '--input', 'cache/short/characters.json'], draft)
    return _variables(batch)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonempty text required')


def _plain(value):
    if isinstance(value, str):
        for line in value.splitlines():
            if re.match(r'^[ \t]{0,3}(?:#{1,6}(?:[ \t]|$)|`{3,}|~{3,})', line):
                raise ValueError('Markdown heading/fence is not allowed in card text')
    elif isinstance(value, dict):
        for item in value.values(): _plain(item)
    elif isinstance(value, list):
        for item in value: _plain(item)


def _identity(record, required=True):
    if not isinstance(record, dict):
        raise ValueError('character record must be an object')
    if required or 'name' in record:
        name = record.get('name')
        if (not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 60
                or re.search(r'[\x00-\x1f\x85\u2028\u2029/\\<>:"|?*#]', name) or name in {'.', '..'}):
            raise ValueError('unsafe character identity')
    aliases = record.get('aliases', [])
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip()
            or re.search(r'[\x00-\x1f\x85\u2028\u2029]', a) for a in aliases):
        raise ValueError('invalid aliases')
    if 'true_name' in record and (not isinstance(record['true_name'], str)
            or re.search(r'[\x00-\x1f\x85\u2028\u2029]', record['true_name'])):
        raise ValueError('invalid true_name')


def _semantic(record):
    if record.get('card_schema') != CARD or 'boundary' in record:
        raise ValueError('new cards require explicit supported v2 semantics')
    for field in ('facts', 'plot_constraints'):
        if not isinstance(record.get(field), list):
            raise ValueError(field + ' must be an array')
        for entry in record[field]: _text(entry)
    _text(record.get('personality'))
    _plain(record)


def _people(data, label):
    if not isinstance(data, dict) or set(data) != {'characters'} or not isinstance(data['characters'], list) or not data['characters']:
        raise ValueError(label + ' requires characters only')
    names = set()
    for record in data['characters']:
        _identity(record)
        if record['name'] in names:
            raise ValueError('duplicate character identity')
        names.add(record['name'])
    return data['characters']


def _records(draft):
    short = _under(draft, 'cache/short/characters.json')
    skeleton = _under(draft, 'cache/character/skeleton.json')
    compact = short.is_file()
    if not compact and not skeleton.is_file():
        raise ValueError('exactly one draft mode is required')
    main_path = short if compact else skeleton
    main = _people(_load(main_path), 'draft')
    # Every identity is checked before constructing any NAME_deep path.
    for record in main: _semantic(record)
    people = []
    known = {main_path.relative_to(draft).as_posix()}
    voices = None
    if not compact:
        voice_path = _under(draft, 'cache/character/voice.json')
        voices = _people(_load(voice_path), 'voice')
        known.add('cache/character/voice.json')
        if {v['name'] for v in voices} != {p['name'] for p in main}:
            raise ValueError('voice identities must exactly match skeleton')
    for record in main:
        name = record['name']
        sources = [(main_path.relative_to(draft).as_posix(), record)]
        if not compact:
            deep_path = _under(draft, f'cache/character/{name}_deep.json')
            if deep_path.exists():
                deep = _load(deep_path)
                _identity(deep, required=False)
                if 'name' in deep and deep['name'] != name:
                    raise ValueError('deep identity differs from skeleton')
                if 'card_schema' in deep: _semantic(deep)
                _plain(deep)
                for key in ('aliases', 'true_name'):
                    if key in deep and key in record and deep[key] != record[key]:
                        raise ValueError('deep identity differs from skeleton')
                sources.append((deep_path.relative_to(draft).as_posix(), deep))
                known.add(deep_path.relative_to(draft).as_posix())
        voice = record.get('voice') if compact else next(v for v in voices if v['name'] == name)
        if not isinstance(voice, dict):
            raise ValueError('voice must preserve an object shape')
        _plain(voice)
        people.append({'name': name, 'records': sources, 'voice': voice})
    beliefs = _under(draft, 'cache/character/beliefs.json')
    if beliefs.exists():
        known.add('cache/character/beliefs.json')
        _load(beliefs)
    if compact:
        # Compact renderer-derived files are frozen but never used as competing inputs.
        for relative in ('cache/character/skeleton.json', 'cache/character/voice.json'):
            if _under(draft, relative).exists(): known.add(relative)
        character = _under(draft, 'cache/character')
        if character.exists() and any(p.name not in ('skeleton.json', 'voice.json') for p in character.iterdir()):
            raise ValueError('mixed compact/full draft modes')
    for relative in METADATA:
        if _under(draft, relative).exists(): known.add(relative)
    actual = set()
    for path in draft.rglob('*'):
        _safe(path)
        if path.is_file(): actual.add(path.relative_to(draft).as_posix())
    if actual != known:
        raise ValueError('unsupported draft files or paths: ' + ', '.join(sorted(actual - known)))
    return 'compact' if compact else 'full', people, sorted(known)


def _frozen(batch, claim):
    mode, people, files = _records(_under(batch, 'draft'))
    renderers = {_renderer(mode)}
    return mode, people, files, {'claim_sha256': _digest(batch.parent / 'claim.json'),
        'source_files': claim['source_files'],
        'raw_files': {name: _digest(_under(batch / 'draft', name)) for name in files},
        'renderers': {str(path): _digest(path) for path in sorted(renderers)}}


def _persona_entries(record_path, record):
    """Enumerate only versioned expression leaves; never infer editable custom fields."""
    if record.get('card_schema') != CARD:
        return []
    paths = [[key] for key in PERSONA_ROOT if isinstance(record.get(key), str)]
    relationships = record.get('relationships', [])
    if isinstance(relationships, list):
        paths.extend(['relationships', index, 'dynamic'] for index, relationship in enumerate(relationships)
                     if isinstance(relationship, dict) and isinstance(relationship.get('dynamic'), str))
        if record_path.startswith('cache/character/'):
            for index, relationship in enumerate(relationships):
                if isinstance(relationship, dict):
                    paths.extend(['relationships', index, key] for key in
                                 ('meaning_to_character', 'hidden_tension', 'default_attitude')
                                 if isinstance(relationship.get(key), str))
    if record_path == 'cache/character/skeleton.json':
        for parent, leaf in (('world_position', 'stance_on_core_conflict'),
                             ('world_anchor', 'may_challenge_rule')):
            value = record.get(parent)
            if isinstance(value, dict) and isinstance(value.get(leaf), str):
                paths.append([parent, leaf])
    if record_path.endswith('_deep.json'):
        for parent, leaves in PERSONA_DEEP.items():
            value = record.get(parent)
            if isinstance(value, dict):
                paths.extend([parent, leaf] for leaf in leaves if isinstance(value.get(leaf), str))
    entries = []
    for path in paths:
        value = record
        for key in path: value = value[key]
        entries.append({'record_path': record_path, 'field_path': path, 'original': value})
    return entries


def _set_persona(record, field_path, value):
    # Called only with frozen allowlisted paths, not model-supplied arbitrary paths.
    for key in field_path[:-1]: record = record[key]
    record[field_path[-1]] = value


def prepare(batch_dir):
    batch, root, claim = _context(batch_dir)
    if _canonical(root):
        raise ValueError('canonical character output exists before review')
    mode, people, files, frozen = _frozen(batch, claim)
    sources = copy.deepcopy(claim['authority'])
    characters = []
    for person in people:
        locked, semantic, editable = [], [], []
        for path, record in person['records']:
            locked_record = copy.deepcopy({k: v for k, v in record.items() if k not in (*SEMANTICS, 'voice')})
            # Unversioned deep descriptions remain wholly immutable evidence.
            if record.get('card_schema') != CARD:
                locked_record = copy.deepcopy(record)
            entries = _persona_entries(path, record)
            for entry in entries:
                _set_persona(locked_record, entry['field_path'], None)
            editable.extend(entries)
            locked.append({'path': path, 'record': locked_record})
            if record.get('card_schema') == CARD:
                semantic.append({'path': path, **{field: record[field] for field in SEMANTICS}})
        sources['locked.' + person['name']] = _json(locked)
        sources['draft-persona.' + person['name']] = _json(editable)
        characters.append({'name': person['name'], 'semantic_records': semantic,
                           'locked_records': locked, 'voice': person['voice'], 'editable_persona': editable})
    beliefs = batch / 'draft/cache/character/beliefs.json'
    if beliefs.exists(): sources['locked.beliefs'] = beliefs.read_text(encoding='utf-8-sig')
    request = {'schema': INPUT_SCHEMA, 'task_id': batch.name,
               'mode': mode, 'sources': sources, 'characters': characters, 'frozen': frozen}
    # A self-describing JSON cannot hash its own SHA field. Bind the canonical
    # source document with only that field omitted; apply independently repeats it.
    binding = _sha(_json(request).encode('utf-8'))
    request['source_sha256'] = binding
    document = _json(request).encode('utf-8')
    input_file = batch / 'review-input.json'
    manifest = {'binding_sha256': binding, 'input_sha256': _sha(document), 'frozen': frozen}
    manifest_path = batch / 'prepared.json'
    if manifest_path.exists():
        if _load(manifest_path) != manifest or input_file.read_bytes() != document:
            raise ValueError('prepared baseline cannot be reset')
    else:
        if input_file.exists() or (batch / 'raw').exists():
            raise ValueError('unowned preparation artifacts already exist')
        for relative in files:
            _write_new(_under(batch / 'raw', relative), _under(batch / 'draft', relative).read_bytes())
        _write_new(input_file, document)
        _write_new(manifest_path, _json(manifest).encode('utf-8'))
    return {**_variables(batch), 'card_review_binding_sha': binding}


def _voice_shape(original, reviewed, key=''):
    if type(original) is not type(reviewed):
        raise ValueError('voice object types must be preserved')
    if isinstance(original, dict):
        if set(original) != set(reviewed):
            raise ValueError('voice keys must be preserved')
        for child in original:
            _voice_shape(original[child], reviewed[child], child)
    elif isinstance(original, list):
        if len(original) != len(reviewed):
            raise ValueError('voice list shape must be preserved')
        for before, after in zip(original, reviewed): _voice_shape(before, after, key)
    elif not isinstance(original, str) or key in {'name', 'true_name', 'aliases', 'with', 'target', 'owner', 'list_owner', 'character', 'avoid', 'forbidden_speech'}:
        if original != reviewed:
            raise ValueError('voice identity, relationship target or prohibition changed')
    _plain(reviewed)


def _review(request, result):
    if not isinstance(result, dict) or set(result) != {'schema', 'task_id', 'source_sha256', 'status', 'characters', 'blocking_issues'}:
        raise ValueError('unsupported review fields')
    if request.get('schema') != INPUT_SCHEMA or result['schema'] != SCHEMA or result['task_id'] != request['task_id'] or result['source_sha256'] != request['source_sha256']:
        raise ValueError('review schema/task/source mismatch')
    if result['status'] != 'accepted' or result['blocking_issues'] != []:
        raise ValueError('blocked review never publishes')
    characters = result['characters']
    expected = {person['name']: person for person in request['characters']}
    if not isinstance(characters, list) or len(characters) != len(expected):
        raise ValueError('all original people must occur exactly once')
    seen, missing_fields, quote_mismatches = set(), {}, []
    for person in characters:
        if not isinstance(person, dict) or set(person) != {'name', *SEMANTICS, 'voice', 'changes', 'persona_edits'}:
            raise ValueError('unsupported character review fields')
        name = person['name']
        if not isinstance(name, str) or name not in expected or name in seen:
            raise ValueError('missing, new, duplicate or renamed person')
        seen.add(name)
        original = expected[name]
        _semantic({'card_schema': CARD, **{field: person[field] for field in SEMANTICS}})
        _voice_shape(original['voice'], person['voice'])
        if not isinstance(person['changes'], list):
            raise ValueError('changes must be an array')
        evidenced = set()
        for change in person['changes']:
            if not isinstance(change, dict) or set(change) != {'field', 'reason', 'source_id', 'evidence_quote'}:
                raise ValueError('unsupported change evidence fields')
            field, source = change['field'], change['source_id']
            if field not in (*SEMANTICS, 'voice') or not isinstance(source, str) or source not in request['sources']:
                raise ValueError('unknown evidence field or authority source')
            try:
                _evidence(request, name, change, allow_draft=field in ('personality', 'voice'))
            except EvidenceQuoteMismatch:
                quote_mismatches.append({'name': name, 'field': field, 'source_id': source})
            # Row coverage and quote validity are separate diagnostics; either
            # defect below prevents publication until the full review is corrected.
            evidenced.add(field)
        changed = {field for field in SEMANTICS if any(record[field] != person[field] for record in original['semantic_records'])}
        if original['voice'] != person['voice']: changed.add('voice')
        if not changed <= evidenced:
            missing_fields[name] = sorted(changed - evidenced)
        edits = person['persona_edits']
        if not isinstance(edits, list):
            raise ValueError('persona_edits must be an array')
        allowed = {(entry['record_path'], tuple(entry['field_path'])): entry
                   for entry in original['editable_persona']}
        edited = set()
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {'record_path', 'field_path', 'before', 'after', 'reason', 'source_id', 'evidence_quote'}:
                raise ValueError('unsupported persona edit fields')
            path = edit['field_path']
            if (not isinstance(edit['record_path'], str) or not isinstance(path, list)
                    or any(type(key) not in (str, int) for key in path)):
                raise ValueError('persona path must match a frozen leaf')
            key = (edit['record_path'], tuple(path))
            entry = allowed.get(key)
            if entry is None or key in edited or edit['before'] != entry['original']:
                raise ValueError('unknown, duplicate or stale persona leaf')
            _text(edit['after'])
            _plain(edit['after'])
            try:
                _evidence(request, name, edit, allow_draft=True)
            except EvidenceQuoteMismatch:
                quote_mismatches.append({'name': name, 'record_path': edit['record_path'],
                                         'field_path': path, 'source_id': edit['source_id']})
            edited.add(key)
    if missing_fields or quote_mismatches:
        raise ReviewCorrectionNeeded(missing_fields, quote_mismatches)
    return {person['name']: person for person in characters}


def _evidence(request, name, change, *, allow_draft):
    source = change['source_id']
    if not isinstance(source, str) or source not in request['sources']:
        raise ValueError('unknown evidence source')
    authority = source in {'author.premise', 'author.human_intent', 'author.world_intent', 'world'} or source.startswith('locked.')
    if not authority and not (allow_draft and source == 'draft-persona.' + name):
        raise ValueError('draft persona is not fact or plot authority')
    _text(change['reason'])
    _text(change['evidence_quote'])
    if change['evidence_quote'] not in request['sources'][source]:
        raise EvidenceQuoteMismatch('evidence quote is not exact source text')


def _verify(batch, root, claim, binding):
    manifest = _load(batch / 'prepared.json')
    if binding != manifest['binding_sha256']:
        raise ValueError('stale binding SHA')
    input_file = _under(batch, 'review-input.json')
    if _digest(input_file) != manifest['input_sha256']:
        raise ValueError('review input changed')
    request = _load(input_file)
    unbound = {k: v for k, v in request.items() if k != 'source_sha256'}
    if request['source_sha256'] != binding or _sha(_json(unbound).encode('utf-8')) != binding:
        raise ValueError('request source binding differs')
    mode, _, _, frozen = _frozen(batch, claim)
    if frozen != manifest['frozen'] or mode != request['mode']:
        raise ValueError('draft, renderer, claim or source changed')
    for relative, digest in frozen['raw_files'].items():
        if _digest(_under(batch / 'raw', relative)) != digest:
            raise ValueError('preserved raw source changed')
    return request


def _candidate(batch, request, reviewed):
    candidate = _under(batch, 'candidate')
    if candidate.exists():
        raise ValueError('unowned candidate already exists')
    mode = request['mode']
    files = request['frozen']['raw_files']
    selected = ['cache/short/characters.json'] if mode == 'compact' else [name for name in files if name.startswith('cache/character/') and name.endswith('.json')]
    for relative in selected:
        data = _load(_under(batch / 'raw', relative))
        if relative.endswith('/skeleton.json') or relative == 'cache/short/characters.json':
            for record in data['characters']:
                update = reviewed[record['name']]
                for field in SEMANTICS: record[field] = copy.deepcopy(update[field])
                if mode == 'compact': record['voice'] = copy.deepcopy(update['voice'])
                for edit in update['persona_edits']:
                    if edit['record_path'] == relative:
                        _set_persona(record, edit['field_path'], edit['after'])
        elif relative.endswith('/voice.json'):
            data['characters'] = [copy.deepcopy(reviewed[record['name']]['voice']) for record in data['characters']]
        elif relative.endswith('_deep.json') and data.get('card_schema') == CARD:
            name = Path(relative).name[:-len('_deep.json')]
            for field in SEMANTICS: data[field] = copy.deepcopy(reviewed[name][field])
            for edit in reviewed[name]['persona_edits']:
                if edit['record_path'] == relative:
                    _set_persona(data, edit['field_path'], edit['after'])
        _write_new(_under(candidate, relative), _json(data).encode('utf-8'))
    if mode == 'compact':
        _run(_renderer(mode), ['characters', '--input', 'cache/short/characters.json'], candidate)
    else:
        render_full(candidate)
    allowed = set(selected) | set(METADATA)
    if mode == 'compact': allowed |= {'cache/character/skeleton.json', 'cache/character/voice.json'}
    actual = {p.relative_to(candidate).as_posix() for p in candidate.rglob('*') if p.is_file()}
    if actual != allowed:
        raise ValueError('renderer produced unsupported output paths')
    return candidate, {relative: _digest(_under(candidate, relative)) for relative in sorted(allowed)}


def _output_paths(request):
    paths = set(METADATA)
    if request['mode'] == 'compact':
        paths |= {'cache/short/characters.json', 'cache/character/skeleton.json', 'cache/character/voice.json'}
    else:
        paths |= {name for name in request['frozen']['raw_files']
                  if name.startswith('cache/character/') and name.endswith('.json')}
    return paths


def _published(root, batch, journal):
    """Existing files are owned only if still hardlinked to their frozen staging file."""
    for path in _canonical(root):
        relative = path.relative_to(root).as_posix()
        expected = journal['output_sha256'].get(relative)
        stage = _under(batch / 'publication', relative)
        if (not expected or not path.is_file() or not stage.is_file()
                or not os.path.samefile(path, stage) or _digest(path) != expected or _digest(stage) != expected):
            raise ValueError('canonical collision or later user edit preserved: ' + relative)


def apply(batch_dir, binding_sha, selected_output):
    """Validate saved review against the selected host output, render and first-publish."""
    batch, root, claim = _context(batch_dir)
    request = _verify(batch, root, claim, binding_sha)
    if not isinstance(selected_output, str) or len(selected_output.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('selected review exceeds UTF-8 input size bound')
    selected = _loads(selected_output)
    result_path = _under(batch, 'review-result.json')
    saved_digest = _digest(result_path)
    if selected != _load(result_path):
        raise ValueError('saved result differs from actual selected stdin JSON')
    try:
        reviewed = _review(request, selected)
    except ReviewCorrectionNeeded:
        # A correction must never replay into an existing candidate/publication or
        # conceal a user's canonical output. No artifacts are written on this path.
        if _canonical(root) or any((batch / name).exists() for name in ('candidate', 'publication', 'publication.json')):
            raise ValueError('review correction cannot bypass existing candidate or publication outputs')
        raise
    review_sha = _sha(_json(selected).encode('utf-8'))
    journal_path = batch / 'publication.json'
    if journal_path.exists():
        journal = _load(journal_path)
        if (not isinstance(journal, dict) or set(journal) != {'schema', 'task_id', 'source_sha256', 'review_sha256', 'output_sha256', 'completed'}
                or journal['schema'] != 'xs2.character.publication.v1' or type(journal['completed']) is not bool
                or not isinstance(journal['output_sha256'], dict) or set(journal['output_sha256']) != _output_paths(request)
                or journal.get('task_id') != batch.name or journal.get('source_sha256') != binding_sha or journal.get('review_sha256') != review_sha):
            raise ValueError('publication journal binding changed')
        _published(root, batch, journal)
        for relative, digest in journal['output_sha256'].items():
            if (_digest(_under(batch / 'publication', relative)) != digest
                    or _digest(_under(batch / 'candidate', relative)) != digest):
                raise ValueError('publication stage changed')
            if journal['completed'] and not _under(root, relative).is_file():
                raise ValueError('completed publication destination was removed')
    else:
        if _canonical(root):
            raise ValueError('canonical character destinations must be absent')
        candidate, hashes = _candidate(batch, request, reviewed)
        # Separate staged copies ensure later canonical edits cannot change candidate JSON.
        for relative in hashes:
            _write_new(_under(batch / 'publication', relative), _under(candidate, relative).read_bytes())
        journal = {'schema': 'xs2.character.publication.v1', 'task_id': batch.name,
                   'source_sha256': binding_sha, 'review_sha256': review_sha,
                   'output_sha256': hashes, 'completed': False}
        _write_new(journal_path, _json(journal).encode('utf-8'))
    _context(batch)
    _verify(batch, root, claim, binding_sha)
    if _digest(result_path) != saved_digest:
        raise ValueError('saved review changed during candidate rendering')
    _published(root, batch, journal)
    for relative in journal['output_sha256']:
        source, target = _under(batch / 'publication', relative), _under(root, relative)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Atomic *single-file*, exclusive creation. No cross-file transaction claim.
            os.link(source, target)
        except FileExistsError as error:
            raise ValueError('concurrent canonical file preserved: ' + relative) from error
    _context(batch)
    _verify(batch, root, claim, binding_sha)
    _published(root, batch, journal)
    journal['completed'] = True
    _save_owned(journal_path, journal)
    return journal


def _emit(variables):
    for name, value in variables.items():
        print(f'<WF_VAR>{name}:{value}</WF_VAR>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    command = actions.add_parser('preflight')
    for flag in ('premise', 'human-intent', 'world-intent'):
        command.add_argument('--' + flag, required=True)
    world = command.add_mutually_exclusive_group(required=True)
    world.add_argument('--world-file')
    world.add_argument('--world-file-stdin', action='store_true')
    for action in ('render-compact', 'prepare', 'apply'):
        command = actions.add_parser(action)
        command.add_argument('--batch-dir', required=True)
        if action == 'apply':
            command.add_argument('--binding-sha', required=True)
            command.add_argument('--retry-review', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'preflight':
            world_file = args.world_file
            if args.world_file_stdin:
                world_file = sys.stdin.read(32769)
                if (not world_file or len(world_file) > 32768 or '\x00' in world_file
                        or '\n' in world_file or '\r' in world_file):
                    raise ValueError('world path stdin must be a bounded raw path string')
            result = preflight(Path.cwd(), args.premise, args.human_intent, args.world_intent, world_file)
            _emit(result)
        elif args.action == 'render-compact': _emit(render_compact(args.batch_dir))
        elif args.action == 'prepare': _emit(prepare(args.batch_dir))
        else:
            result = apply(args.batch_dir, args.binding_sha, sys.stdin.read(8 * 1024 * 1024 + 1))
            print(_json(result), end='')
    except ReviewCorrectionNeeded as error:
        if args.action == 'apply' and args.retry_review:
            reason = html.escape(str(error), quote=False)
            print('<WF_REJECT_UPSTREAM target="agent_card_semantic_review">' + reason + '</WF_REJECT_UPSTREAM>')
            return
        parser.exit(1, 'character-review: ' + str(error) + '\n')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, 'character-review: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
