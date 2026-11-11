"""Offline archive/recovery verification on copies of the five prior novels.

Uses sourced test fixtures, not a new model review or a prose-quality score.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys


PLUGIN = Path(__file__).resolve().parents[1]
SOURCE = PLUGIN / 'resources/script-library/xs2/story_support/story_support.py'


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def module(file, name):
    spec = importlib.util.spec_from_file_location(name, file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    global PLUGIN, SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plugin-root', type=Path, default=PLUGIN)
    parser.add_argument('--host-root', type=Path, required=True)
    args = parser.parse_args()
    PLUGIN = args.plugin_root.resolve()
    SOURCE = PLUGIN / 'resources/script-library/xs2/story_support/story_support.py'
    sys.path.insert(0, str(args.host_root))
    from src.workflow.variable_resolution import resolve_placeholders
    definition = json.loads((PLUGIN / 'resources/workflows/post-hoc/definition.json').read_text(encoding='utf-8'))
    nodes = {n['id']:n for n in definition['nodes']}
    args.output.mkdir(parents=True, exist_ok=False)
    originals = hashes(args.source_cases)
    support = module(SOURCE, 'p0_support')
    results = []
    for name in ('ancient', 'romance', 'apocalypse', 'scifi', 'fantasy'):
        source = args.source_cases / name / 'book'
        book = args.output / name
        shutil.copytree(source, book)
        body = (book / 'story/0001/chapter.md').read_bytes()
        contract = support.archive_store().contract(book)
        text = body.decode('utf-8-sig')
        excerpt = next(p.strip() for p in text.split('\n\n') if len(p.strip()) > 30)
        task_id = 'p0-copy-' + name
        os.environ['TASK_ID'] = task_id
        support.begin_review(book, '0001')
        variables = {'chapter_number':'0001', 'obs_output_file':support.review_file('0001','observer.json'),
            'archive_observer_path':support.review_file('0001','observer.json'),
            'archive_arbiter_path':support.review_file('0001','arbiter.json')}
        def resolve(template):
            return asyncio.run(resolve_placeholders(template, variables, definition['variables'], str(book)))
        assert resolve(nodes['agent_obs']['output_file_path']) == variables['archive_observer_path']
        assert resolve(nodes['agent_arb']['output_file_path']) == variables['archive_arbiter_path']
        support.write(book, support.review_file('0001', 'observer.json'), {'confirmed_state':{'characters':[], 'hooks':[], 'debts':[]}})
        support.write(book, support.review_file('0001', 'arbiter.json'), {'story_confirmed':{}, 'world_rulings':{'entries':[
            {'fact':excerpt, 'evidence':excerpt, 'verdict':'adopt'}]}})
        archive_cli = PLUGIN / 'resources/script-library/nvl/local_archive/local_archive.py'
        for argv in [
            shlex.split(resolve(nodes['script_sync_up']['node_params']['script_args'])),
            ['render','--inputs','story/0001/diff_story_confirmed.json',
             '--outputs','story/0001/diff_story_confirmed.md']]:
            saved = subprocess.run([sys.executable,str(archive_cli),*argv], cwd=book,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'),capture_output=True,text=True,encoding='utf-8',timeout=60)
            assert saved.returncode == 0, saved.stderr
        journal = support.archive_store()
        atomic = journal.atomic
        count = 0
        def fail(root, relative, content):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('injected archive interruption')
            atomic(root, relative, content)
        journal.atomic = fail
        try:
            support.commit(book, '0001')
            raise AssertionError('fault not triggered')
        except OSError as error:
            assert 'injected' in str(error)
        finally:
            journal.atomic = atomic
        assert support.confirmed(book)[0] == []
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        def cli(command):
            result = subprocess.run([sys.executable, str(SOURCE), command, '--chapter', '0001'],
                cwd=book, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
            assert result.returncode == 0, result.stderr
            (book / f'{command}-stdout.txt').write_text(result.stdout, encoding='utf-8')
        cli('recover')
        snapshot = support.confirmed(book)[0][0]
        cli('commit')
        assert support.confirmed(book)[0][0] == snapshot
        support.refresh_archive(book)
        production = module(PLUGIN / 'resources/script-library/xs2/console_service/production.py', 'p0_production')
        task = {'task_id':task_id, 'status':'completed', 'node_states':{'script_confirm_archive':{'status':'completed'}}}
        production.verify_completion(book, {'values':{'chapter_number':'0001'}}, 'post-hoc', task)
        assert (book / 'story/0001/chapter.md').read_bytes() == body
        assert journal.contract(book) == contract
        assert support.load(book, 'archive/current_status.json')['updated_chapter'] == '0001'
        results.append({'book':name, 'interruption_after_writes':count-1, 'restart_recovered':True,
            'duplicate_idempotent':True, 'task_bound_completion':True, 'host_path_resolution':True, 'body_unchanged':True,
            'book_contract_unchanged':True, 'archive_commit_id':snapshot['archive_commit_id'],
            'events':len(journal.events(book))})
    assert hashes(args.source_cases) == originals, 'source verification copies changed'
    report = {'kind':'offline sourced-fixture archive/recovery verification; no new model quality review',
        'source_files_checked':len(originals), 'source_files_unchanged':True, 'books':results}
    (args.output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
