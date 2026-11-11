"""One classified retry entry point for plugin-owned reject-upstream routes."""
import html
import importlib.util
import os
from pathlib import Path
import re


def logical_step(target):
    if target.startswith('agent_composition_'):return 'composition'
    if target.startswith('agent_guard_'):return 'draft-review'
    if target in ('agent_sc','agent_pl','agent_local_review'):return 'local-revision'
    if target in ('agent_blind_reader','agent_context_reader','agent_reader'):return 'reader-review'
    if target in ('agent_obs','agent_arb'):return 'archive-review'
    if 'rolling' in target:return 'rolling-plan'
    if 'card' in target:return 'character-review'
    return 'scene-writing'


def guard():
    spec=importlib.util.spec_from_file_location('shared_rejection_guard',Path(__file__).with_name('production_guard.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def emit(message):
    match=re.fullmatch(r'<WF_REJECT_UPSTREAM target="([A-Za-z0-9_-]+)">([\s\S]*)</WF_REJECT_UPSTREAM>',message)
    if not match:raise ValueError('Invalid plugin rejection transport')
    task=os.environ.get('TASK_ID');workflow=os.environ.get('WORKFLOW_ID')
    if task and workflow:
        target,reason=match.groups()
        guard().retry(Path.cwd(),logical_step(target)+'/'+task,target,html.unescape(reason))
    print(message)
