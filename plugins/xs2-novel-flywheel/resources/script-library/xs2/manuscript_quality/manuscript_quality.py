"""Workflow entrypoint for the novel plugin's deterministic length evidence."""
import argparse
import importlib.util
import json
import os
from pathlib import Path


def quality():
    source = Path(__file__).resolve().parents[1] / 'console_service/length_quality.py'
    spec = importlib.util.spec_from_file_location('novel_length_quality_cli', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['guidance', 'draft-guidance', 'focused-ready', 'focused-commit', 'prepare-fragment-review', 'gate-reader'])
    parser.add_argument('--chapter', required=True)
    parser.add_argument('--target', default='')
    parser.add_argument('--scope', default='content', choices=['content', 'length_only'])
    parser.add_argument('--expected-body-sha', default='')
    parser.add_argument('--focused-guard', default='')
    parser.add_argument('--focused-guard-sha', default='')
    parser.add_argument('--review-result', default=None)
    parser.add_argument('--review-binding', default='')
    parser.add_argument('--review-binding-sha', default='')
    parser.add_argument('--policy-runtime', default='')
    parser.add_argument('--candidate', default='')
    parser.add_argument('--feedback', default=None)
    args = parser.parse_args()
    root = Path.cwd().resolve();q = quality()
    chapter = q.chapter_number(args.chapter)
    if args.action in {'guidance', 'draft-guidance', 'focused-ready', 'focused-commit', 'prepare-fragment-review'}:
        if args.action == 'draft-guidance':
            outputs = {'pp_length_context_file': q.prepare_draft_guidance(root, chapter, args.target, args.candidate)}
        elif args.action == 'focused-commit':
            outputs = q.focused_commit(root, chapter, args.expected_body_sha, args.focused_guard, args.focused_guard_sha, os.environ.get('TASK_ID', ''), args.review_binding, args.review_binding_sha, args.review_result)
        elif args.action == 'prepare-fragment-review':
            outputs = q.prepare_fragment_review(root, chapter, args.expected_body_sha, args.focused_guard, args.focused_guard_sha, os.environ.get('TASK_ID', ''))
        elif args.action == 'focused-ready':
            outputs = q.confirm_execution(root, chapter, args.expected_body_sha, args.focused_guard, args.focused_guard_sha)
        else:
            outputs = q.prepare_execution(root, chapter, args.target, args.scope,
                                          policy_runtime=args.policy_runtime.strip(), task_id=os.environ.get('TASK_ID'),feedback_path=args.feedback)
        for key, value in outputs.items():
            # The host's WF_VAR parser accepts a whitespace payload for empty values.
            print('<WF_VAR>' + key + ':' + (value or ' ') + '</WF_VAR>')
    else:
        path = q.safe_path(root, f'story/{chapter}/reader_report.json')
        report = json.loads(path.read_text(encoding='utf-8-sig'))
        if report.get('chapter_number') != chapter or not report.get('body_sha256'):
            raise ValueError('读者报告尚未绑定本章正文，请先登记评估结果')
        report = q.gate_report(root, chapter, args.target, report)
        text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        q.atomic_text(path, text)
        legacy = q.safe_path(root, 'quality/reader_report.json')
        if legacy.is_file():
            prior = json.loads(legacy.read_text(encoding='utf-8-sig'))
            if prior.get('chapter_number') == chapter and prior.get('body_sha256') == report['body_sha256']:
                q.atomic_text(legacy, text)
        q.atomic_text(q.safe_path(root, f'quality/length/{chapter}.json'), json.dumps(report['length_check'], ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'completed', 'chapter': chapter, 'action': args.action}, ensure_ascii=False))


if __name__ == '__main__':
    main()
