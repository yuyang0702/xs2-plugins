"""Stable, explicit style/conflict choices; source evidence never becomes instructions."""
import hashlib
import json
from pathlib import Path


DIMENSION_SCOPES = {
    'structure': ('story-plan', 'outline'),
    'voice': ('character', 'mvp', 'polish'),
    'topic': ('novel-advisor',),
    'case': ('novel-advisor', 'story-plan', 'outline', 'mvp'),
    'pacing': ('outline', 'mvp'),
    'layout': ('mvp', 'export'),
    'expression': ('mvp', 'polish'),
}
DIMENSION_NAMES = {'structure': '结构', 'voice': '语感', 'topic': '选题', 'case': '案例写法',
                   'pacing': '节奏', 'layout': '排版', 'expression': '表达习惯'}


def mechanism_scopes(item):
    scopes = item.get('scopes') or ()
    dimension = item.get('dimension')
    if not dimension:
        return tuple(scopes)
    supported = DIMENSION_SCOPES[dimension]
    return tuple(stage for stage in supported if stage in scopes) or supported


def active_blueprint(root):
    root = Path(root).resolve()
    active = root / 'learning/active.json'
    if not active.is_file():
        return {}, {}
    if not active.resolve().is_relative_to(root):
        raise ValueError('采用记录越出本书工作区')
    entry = json.loads(active.read_text(encoding='utf-8-sig'))
    relative = Path(entry['blueprint_path'])
    target = (root / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root / 'learning/blueprints'):
        raise ValueError('采用蓝图路径无效')
    blueprint = json.loads(target.read_text(encoding='utf-8-sig'))
    if fingerprint(blueprint) != entry['blueprint_sha256']:
        raise ValueError('创作蓝图被修改，请重新确认')
    return entry, blueprint


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(filter(None, (text(item) for item in value)))
    return ""


def reference_choices(data):
    """IDs ignore evidence/window changes, but distinguish source and rule meaning."""
    source = data.get("source") or {}
    result = {}
    for kind, key in (("style", "style_observations"), ("conflict", "conflict_patterns")):
        choices = []
        for item in data.get(key, []):
            if not isinstance(item, dict):
                continue
            origin = item.get("source") or source
            meaningful = {k: v for k, v in item.items() if k not in {"evidence", "confidence", "source", "choice_id", "support_count"}}
            identifier = kind + "-" + fingerprint([origin.get("text_sha256"), meaningful])[:24]
            if any(choice["choice_id"] == identifier for choice in choices):
                continue
            guidance = text(item.get("transfer_guidance") or item.get("adaptation_guidance"))
            choices.append({**item, "choice_id": identifier, "kind": kind, "source": origin,
                            "title": text(item.get("name") or item.get("rule")) or ("风格特点" if kind == "style" else "冲突递进"),
                            "transfer_guidance": guidance,
                            "requires_adaptation": not bool(guidance) or kind == "conflict"})
        result[kind + "_choices"] = choices
    result["reference_choices_sha256"] = fingerprint([result["style_choices"], result["conflict_choices"]])
    return result


def with_reference_choices(data):
    return {**data, **reference_choices(data)}
