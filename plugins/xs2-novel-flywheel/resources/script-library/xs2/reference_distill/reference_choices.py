"""Stable, explicit style/conflict choices; source evidence never becomes instructions."""
import hashlib
import json


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
