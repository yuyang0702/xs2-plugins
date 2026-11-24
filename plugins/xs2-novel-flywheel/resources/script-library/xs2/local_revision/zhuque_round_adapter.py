"""Private stdin/stdout adapter for the post-polish node, using the publication patch format."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(data):
    here = Path(__file__).resolve().parent
    zhuque = load(here / 'zhuque_review.py')
    patches = load(here.parent / 'draft_guard' / 'revision_patch.py')
    body = data['body']
    if data['action'] == 'local-tone':
        tone = load(here / 'tone_review.py')
        protected = data.get('protected_phrases', ())
        return {key: tone.remaining(text, data.get('original_marks', {}).get(key, ()), protected)
                for key, text in data['texts'].items()}
    if data['action'] == 'local-patch':
        view, payload = data['view'], data['patch']
        source = view['source_body']
        if isinstance(source, dict):
            source = ''.join(p.get('before', '') + p['text'] for p in source['paragraphs']) + source.get('suffix', '')
        protected = view.get('book_contract', {}).get('protected_phrases', [])
        edits = payload['edits']
        patches.apply_patches(source, {'source_sha256':payload['source_sha256'], 'edits':edits}, protected_phrases=protected)
        local = load(here/'local_revision.py')
        rows = patches.paragraphs(source)
        review = view.get('local_tone') or {'mode':'contextual'}
        try:
            local.check_local_tone({'local_tone':review, 'paragraphs':rows,
                                    'book_contract':{'protected_phrases':protected}}, edits, edits)
        except ValueError as exc:
            return {'feedback':str(exc)}
        return {'feedback':''}
    if data['action'] == 'detect':
        report = zhuque.analyze(body, patches.paragraphs, os.environ.get('XS2_ZHUQUE_KEY_FILE', ''))
        paragraphs = patches.paragraphs(body)
        load(here / 'tone_review.py').annotate_rewrites(report, paragraphs, contextual=True)
        return {'report': report, 'paragraphs': paragraphs}
    if data['action'] == 'compose':
        edits = zhuque.compile_rewrites(data['report'], {'edits': [], 'rewrites': data['rewrites']})
        candidate = patches.apply_patches(body, {'source_sha256': patches.digest(body), 'edits': edits},
                                          protected_phrases=data['protected_phrases'])
        if data.get('length_bounds') is not None:
            quality = load(here.parent / 'console_service' / 'length_quality.py')
            measured = quality.measurement(candidate.encode(), '', data['length_bounds'])
            if quality.is_blocking(measured):
                raise ValueError('候选篇幅越过要求：' + json.dumps(measured, ensure_ascii=False))
        tone = load(here / 'tone_review.py')
        hints = {}
        for row in data['rewrites']:
            evidence = tone.fragment_review(row['replacement'], contextual=True)['hints']
            if evidence:
                hints[row['id']] = evidence
        rules = {h['rule'] for items in hints.values() for h in items}
        return {'candidate': candidate, 'lieflat_hints': hints,
                'semantic_criteria': {name: rows for name, rows in tone.semantic_rubric().items() if name in rules}}
    raise ValueError('未知整稿操作')


if __name__ == '__main__':
    try:
        result = run(json.loads(sys.stdin.buffer.read()))
    except (ValueError, KeyError, OSError, TypeError) as exc:
        sys.stderr.buffer.write(str(exc).encode())
        sys.exit(1)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode())
