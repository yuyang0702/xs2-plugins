"""Reuse source-bound observations without reusing an arbiter's verdict."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re


def native_proof(root, guard, task, observation, model):
    state = task.get('node_states', {}).get('agent_obs', {})
    session_id = state.get('session_id') or ''
    if state.get('status') != 'completed' or not re.fullmatch(r'[a-zA-Z0-9_-]+', session_id):
        return None
    data = guard.host_root() / Path(os.environ.get('DETERMINFLOW_DATA_DIR') or 'data').expanduser()
    directory = data / 'sessions'
    try:
        session = json.loads((directory / (session_id + '.json')).read_text(encoding='utf-8-sig'))
        record = session['record']
        if (
            session['session_id'] != session_id or session['task_id'] != task['task_id']
            or session['workflow_id'] != task['workflow_id'] or session['node_id'] != 'agent_obs'
            or Path(session['workspace_path']).resolve() != root.resolve()
            or session['model_id'] != model or [message['type'] for message in record] != ['user', 'assistant']
            or any(message.get('tool_calls') for message in record)
            or json.loads(record[-1]['content']) != observation
        ):
            return None
        return {
            'task_id': task['task_id'], 'session_id': session_id, 'model': model,
            'record_sha256': hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        }
    except (OSError, KeyError, TypeError, ValueError):
        return None


def identity(root, source, journal, guard):
    task_id = os.environ.get('TASK_ID')
    profile = guard.reuse_profile(root, ('agent_obs',))
    if not profile or not task_id or source['task_id'] != task_id:
        return None
    events = journal.events(root, kind='request_budget', task_id=task_id)
    budget = next((row['data']['budget'] for row in reversed(events)
                   if row['data'].get('node_id') == 'agent_obs'), None)
    if not budget or not budget.get('input_sha256') or ':' not in budget.get('model', ''):
        return None
    if budget['input_errors'] or budget['unresolved_variables'] or budget['capacity_status'] == 'over_budget':
        return None
    if any(item.startswith(('host_agent_definition:', 'host_prompt_template:', 'host_builtin:'))
           for item in budget['unknown_components']):
        return None
    if any(journal.digest(root, file['path']) != file['sha256'] for file in budget['input_files'].values()):
        return None
    source_key = {name: value for name, value in source.items() if name != 'task_id'}
    prefix = f"cache/story-support/reviews/{task_id}/{source['chapter']}/"
    source_key['source_hashes'] = {
        name.removeprefix(prefix) if name.startswith(prefix) else name: value
        for name, value in source['source_hashes'].items()
    }
    return {
        'key': journal.identity(['archive-observation-v1', profile, budget['input_sha256'], source_key]),
        'model': budget['model'],
    }


def previous(root, source, binding, journal):
    if binding is None:
        return None
    snapshot_path = journal.path(root, f"story/{source['chapter']}/confirmed_state.json")
    if not snapshot_path.is_file():
        return None
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8-sig'))
        commit_id = snapshot.get('archive_commit_id')
        with journal.verification_reader(root) as reader:
            if not commit_id or journal.existing(root, commit_id, reader=reader) != snapshot:
                return None
            row = reader['db'].execute("SELECT content FROM publications WHERE id=? AND status='complete'",
                                       (commit_id,)).fetchone()
        inputs = json.loads(row['content'])['inputs']
        receipt = inputs.get('observation_reuse')
        observation = inputs['observer_candidate']
        if (not receipt or receipt['binding'] != binding
                or receipt['observer_sha256'] != journal.identity(observation)):
            return None
        return observation, receipt, commit_id
    except (OSError, KeyError, TypeError, ValueError):
        return None


def provenance(root, source, observation, journal, guard):
    binding = identity(root, source, journal, guard)
    if binding is None:
        return None
    task_id = source['task_id']
    native = guard._native(root, os.environ['WORKFLOW_ID'], task_id)
    proof = native_proof(root, guard, native, observation, binding['model'])
    digest = journal.identity(observation)
    if proof:
        return {'binding': binding, 'observer_sha256': digest, 'native': proof}
    prior = previous(root, source, binding, journal)
    if prior and prior[0] == observation:
        for event in journal.events(root, kind='archive_observation_reuse', task_id=task_id):
            if event['data'] == {'task_id': task_id, 'origin_commit_id': prior[2], 'observer_sha256': digest}:
                return prior[1]
    return None
