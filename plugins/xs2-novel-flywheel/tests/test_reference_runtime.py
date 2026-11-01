import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import shlex

ROOT = Path(__file__).resolve().parents[1] / 'resources'
SCRIPT = ROOT / 'script-library/xs2/reference_intelligence_helper/reference_intelligence_helper.py'


def run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args, '--workspace', str(root)],
                          capture_output=True, text=True, encoding='utf-8', cwd=root)


def context(root):
    workflow = json.loads((ROOT / 'workflows/mvp/definition.json').read_text(encoding='utf-8'))
    params = next(node for node in workflow['nodes'] if node['id'] == 'script_smart_context')['node_params']
    source = ROOT / 'script-library' / params['script_group'] / params['script_name']
    # A library executes with its own directory available, never siblings.
    isolated = root / 'isolated-library' / source.name
    if not isolated.exists():
        shutil.copytree(source, isolated)
    arguments = shlex.split(params['script_args'].replace('{{chapter_number}}', '0001'))
    return subprocess.run([sys.executable, str(isolated / (source.name + '.py')), *arguments],
                          capture_output=True, text=True, encoding='utf-8', cwd=root)


def test_every_script_reference_resolves_to_its_actual_entrypoint():
    for path in (ROOT / 'workflows').glob('*/definition.json'):
        for node in json.loads(path.read_text(encoding='utf-8'))['nodes']:
            params = node.get('node_params', {})
            if node.get('node_type') != 'script' or params.get('script_source') != 'library':
                continue
            name = params['script_name']
            entry = ROOT / 'script-library' / params['script_group'] / name / (name + '.py')
            assert entry.is_file(), f'{path.parent.name}:{node["id"]} cannot resolve {entry}'


def test_original_writing_without_references_succeeds(tmp_path):
    for result in [run(tmp_path, 'init'), context(tmp_path)]:
        assert result.returncode == 0, result.stderr or result.stdout
    assert '原创' in (tmp_path / 'learning/context/mvp.md').read_text(encoding='utf-8')
    (tmp_path / 'story/0001').mkdir(parents=True)
    (tmp_path / 'story/0001/chapter.md').write_text('原创正文', encoding='utf-8')
    result = run(tmp_path, 'check-similarity', '--chapter', '0001')
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)['status'] == 'skipped'


def test_context_uses_only_verified_adopted_blueprint(tmp_path):
    learning = tmp_path / 'learning'
    (learning / 'blueprints').mkdir(parents=True)
    (learning / 'candidates.json').write_text(json.dumps({'candidates': [{'name': 'NEVER_AUTO_ADOPT'}]}), encoding='utf-8')
    (learning / 'recommendations.json').write_text(json.dumps({'recommendations': [{'name': 'NEVER_AUTO_ADOPT'}]}), encoding='utf-8')
    blueprint = {'mechanisms': [{'mechanism': 'SELECTED_ONLY', 'transfer_guidance': 'approved guidance', 'scopes': ['mvp']}]}
    digest = hashlib.sha256(json.dumps(blueprint, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (learning / 'blueprints/v0001.json').write_text(json.dumps(blueprint), encoding='utf-8')
    (learning / 'active.json').write_text(json.dumps({'version': 1, 'blueprint_path': 'learning/blueprints/v0001.json', 'blueprint_sha256': digest}), encoding='utf-8')
    result = context(tmp_path)
    assert result.returncode == 0, result.stderr or result.stdout
    text = (learning / 'context/mvp.md').read_text(encoding='utf-8')
    assert 'SELECTED_ONLY' in text and 'NEVER_AUTO_ADOPT' not in text
    blueprint['mechanisms'][0]['transfer_guidance'] = 'tampered'
    (learning / 'blueprints/v0001.json').write_text(json.dumps(blueprint), encoding='utf-8')
    assert context(tmp_path).returncode != 0


def test_workflow_consumes_context_without_overwriting_it():
    mvp = json.loads((ROOT / 'workflows/mvp/definition.json').read_text(encoding='utf-8'))
    context = next(n for n in mvp['nodes'] if n['id'] == 'script_smart_context')
    variable = next(v for v in mvp['variables'] if v['key'] == 'learning_context')
    assert variable['default'] == 'learning/context/mvp.md'
    assert context['node_params']['script_name'] == 'reference_distill'
    assert context['node_params']['script_args'] == 'prepare-context --scope mvp'
    assert not context['save_output_to_file']
    for workflow in ['mvp', 'reference-distillation']:
        definition = json.loads((ROOT / f'workflows/{workflow}/definition.json').read_text(encoding='utf-8'))
        for node in definition['nodes']:
            if node.get('node_params', {}).get('script_name') == 'reference_intelligence_helper':
                assert not node['fail_auto_skip']


def test_existing_monitor_runs_against_actual_source_text(tmp_path):
    (tmp_path / 'learning/sources').mkdir(parents=True)
    (tmp_path / 'story/0001').mkdir(parents=True)
    excerpt = 'The character stopped in the doorway and chose to leave the letter unread. ' * 5
    (tmp_path / 'learning/sources/source.txt').write_text(excerpt, encoding='utf-8')
    (tmp_path / 'story/0001/chapter.md').write_text(excerpt, encoding='utf-8')
    result = run(tmp_path, 'check-similarity', '--chapter', '0001')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'checked'
    assert report['originality_report']['total_warnings'] > 0
