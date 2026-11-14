#!/usr/bin/env python3
"""Manage Bishu's file-only workspace archive.

The current workflow workspace is the single source of truth. This helper only
validates, combines, renders, and indexes files below that workspace. Canonical
rendering uses the plugin's existing archive database publication lock.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import tempfile
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path
from typing import Any


WORLD_DIMENSIONS = (
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
)
INDEX_PATHS = {
    "hooks": "archive/hooks.json",
    "debts": "archive/debts.json",
}


@lru_cache(maxsize=1)
def _policy():
    group = Path(__file__).resolve().parents[1]
    if group.name == "nvl":
        sibling = "xs2"
    elif group.name.endswith("-nvl"):
        sibling = group.name.removesuffix("-nvl") + "-xs2"
    else:
        raise ValueError("无法识别归档脚本所属的资源组。")
    entry = (group.parent / sibling / "prose_policy/prose_policy.py").resolve()
    if not entry.is_relative_to(group.parent / sibling):
        raise ValueError("叙述偏好脚本越过当前插件资源组。")
    spec = importlib.util.spec_from_file_location("xs2_archive_prose_policy", entry)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _execution_guard():
    # _policy resolves the exact xs2 sibling in source and prepared layouts.
    entry=Path(_policy().__file__).resolve().parents[1]/'production_guard/production_guard.py'
    spec=importlib.util.spec_from_file_location('xs2_archive_render_execution_guard',entry)
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    return guard


def _workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    workspace = Path.cwd().resolve()
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"路径不能离开工作区: {raw_path}")
    return resolved


def _split_paths(raw_paths: str) -> list[str]:
    return [item.strip() for item in raw_paths.split(",") if item.strip()]


def _read_json(raw_path: str) -> Any:
    path = _workspace_path(raw_path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(raw_path: str, value: Any) -> None:
    path = _workspace_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_text(raw_path: str, value: str) -> None:
    path = _workspace_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.render-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(value.rstrip()+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def _require_files(raw_paths: str) -> None:
    missing = []
    empty = []
    for raw_path in _split_paths(raw_paths):
        path = _workspace_path(raw_path)
        if not path.is_file():
            missing.append(raw_path)
        elif path.stat().st_size == 0:
            empty.append(raw_path)
    if missing:
        raise FileNotFoundError("缺少本地存档文件: " + ", ".join(missing))
    if empty:
        raise ValueError("本地存档文件为空: " + ", ".join(empty))


def _normalize_chapter(raw_chapter: str) -> str:
    if not re.fullmatch(r"\d{1,6}", raw_chapter):
        raise ValueError("章节号必须是 1-6 位数字")
    return f"{int(raw_chapter):04d}"


def _ensure_indexes() -> None:
    for raw_path in INDEX_PATHS.values():
        path = _workspace_path(raw_path)
        if not path.exists():
            _write_json(raw_path, [])


def _merge_index(index_name: str, source_path: str) -> int:
    if not source_path:
        return 0
    source = _read_json(source_path)
    if not isinstance(source, list):
        raise ValueError(f"{source_path} 必须是数组")

    target_path = INDEX_PATHS[index_name]
    current = _read_json(target_path)
    if not isinstance(current, list):
        raise ValueError(f"{target_path} 必须是数组")

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in current + source:
        if not isinstance(item, dict):
            raise ValueError(f"{index_name} 条目必须是对象")
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise ValueError(f"{index_name} 条目缺少 id")
        if item_id not in by_id:
            order.append(item_id)
        by_id[item_id] = {**by_id.get(item_id, {}), **item}

    _write_json(target_path, [by_id[item_id] for item_id in order])
    return len(source)


def _build_world_cache() -> None:
    combined: dict[str, Any] = {}
    missing = []
    for dimension in WORLD_DIMENSIONS:
        raw_path = f"world/{dimension}.json"
        path = _workspace_path(raw_path)
        if not path.is_file():
            missing.append(raw_path)
            continue
        data = _read_json(raw_path)
        combined[dimension] = (
            data.get(dimension, data) if isinstance(data, dict) else data
        )
    if missing:
        if len(missing)==len(WORLD_DIMENSIONS):
            source=_markdown_source('meta/world_foundation.md')
            if source:
                _write_json('cache/sync/world.json',{'source_format':'author_markdown','foundation':source,
                    'boundary':'原有文字设定，不是假装齐全的六维结构。未声明细节保持未知，不能据此改变本书规则。'})
                return
        raise FileNotFoundError("世界观存档不完整: " + ", ".join(missing))
    _write_json("cache/sync/world.json", combined)


def _markdown_source(relative):
    file=_workspace_path(relative)
    if not file.is_file():return None
    text=file.read_text(encoding='utf-8')
    if not text.strip():return None
    return {'source_id':relative,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'text':text}


@lru_cache(maxsize=1)
def _story_support():
    entry=Path(_policy().__file__).resolve().parents[1]/'story_support/story_support.py'
    spec=importlib.util.spec_from_file_location('xs2_managed_archive_source',entry)
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support);return support


def _named_items(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    items = value.get(key, [])
    if not isinstance(items, list):
        return {}
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("character") or "").strip()
        if name:
            result[name] = item
    return result


def _build_character_cache(policy_runtime="", policy_characters_file="") -> None:
    if not _workspace_path('cache/character/skeleton.json').is_file():
        profiles=_markdown_source('meta/character_profiles.md')
        if profiles:
            _write_json('cache/sync/characters.json',{'source_format':'author_markdown','profiles':profiles,
                'voice':_markdown_source('meta/character_voice.md'),
                'boundary':'原有角色文字资料；不冒充已提取的完整人物列表。人物实际状态与认知须结合可信前文核对。'})
            return
    skeleton = _read_json("cache/character/skeleton.json")
    if not isinstance(skeleton, dict) or not isinstance(
        skeleton.get("characters"), list
    ):
        raise ValueError("cache/character/skeleton.json 缺少 characters 数组")

    beliefs_path = _workspace_path("cache/character/beliefs.json")
    voice_path = _workspace_path("cache/character/voice.json")
    beliefs = (
        _named_items(_read_json("cache/character/beliefs.json"), "beliefs")
        if beliefs_path.is_file()
        else {}
    )
    voice_document = _read_json("cache/character/voice.json") if voice_path.is_file() else {}
    voices = _named_items(voice_document, "characters")

    characters = []
    for base in skeleton["characters"]:
        if not isinstance(base, dict):
            continue
        name = str(base.get("name", "")).strip()
        if not name:
            continue
        deep_path = _workspace_path(f"cache/character/{name}_deep.json")
        deep = _read_json(f"cache/character/{name}_deep.json") if deep_path.is_file() else {}
        characters.append(
            {
                **base,
                "belief": beliefs.get(name, {}),
                "deep": deep,
                "voice": voices.get(name, {}),
            }
        )
    if not characters:
        raise ValueError("角色本地存档中没有有效角色")
    _write_json("cache/sync/characters.json", {"characters": characters})
    if policy_runtime and policy_characters_file == "cache/sync/characters.json" and voices:
        _effective_character_cache(policy_runtime, voice_document, characters)


def _effective_character_cache(directory, voice_document, characters):
    policy, root, task_id = _policy(), Path.cwd(), os.environ.get("TASK_ID")
    renderer = Path(__file__).resolve().parents[1] / "json_to_md/json_to_md.py"
    spec = importlib.util.spec_from_file_location("xs2_archive_voice_renderer", renderer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    effective = policy.voice_mirror(root, directory, voice_document, module.render_voice_char, task_id=task_id)
    if effective != voice_document:
        voices = _named_items(effective, "characters")
        data = {"characters": [{**row, "voice": voices.get(row["name"], {})} for row in characters]}
        alias = policy.runtime_file(root, directory, "characters.json",
                                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", task_id=task_id)
        print(f"<WF_VAR>pp_characters_json_file:{alias}</WF_VAR>")


def _render_near_term_context(policy_runtime="", policy_near_term_file="") -> None:
    project=_workspace_path('.novel-project.json')
    if project.is_file():
        state=_read_json('.novel-project.json');number=str(state.get('values',{}).get('chapter_number','0001')).zfill(4)
        plan_file=f'planning/chapters/{number}.json'
        if re.fullmatch(r'[0-9]{4}',number) and _workspace_path(plan_file).is_file():
            plan=_read_json(plan_file)
            if isinstance(plan,dict) and plan.get('origin')=='rolling':
                support=_story_support()
                if not support.serial().need_plan(Path.cwd(),number).get('ready'):raise ValueError('当前滚动计划已失效，不能使用旧近期缓存代替')
                _write_text('cache/sync/near_term_we.md','# 当前章采用计划（待写意图，不是已发生事实）\n\n'+support.render_plan(plan))
                return
    source_path = _workspace_path("cache/no/near_term.json")
    if source_path.is_file():
        data = _read_json("cache/no/near_term.json")
        chapters = data.get("chapters", []) if isinstance(data, dict) else []
        lines = ["# 近期大纲（世界引擎摘录）", ""]
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            lines.extend(
                [
                    f"## 第{chapter.get('number', '?')}章 · {chapter.get('title', '')}",
                    f"- 情节摘要：{chapter.get('summary', '')}",
                    f"- 世界时间推进：{chapter.get('time_advance', '')}",
                    "",
                ]
            )
        _write_text("cache/sync/near_term_we.md", "\n".join(lines))
        return

    outline_path = _workspace_path("outline/near_term_outline.md")
    if outline_path.is_file():
        _write_text(
            "cache/sync/near_term_we.md",
            outline_path.read_text(encoding="utf-8"),
        )
        if policy_runtime and policy_near_term_file == "cache/sync/near_term_we.md":
            policy, root, task_id = _policy(), Path.cwd(), os.environ.get("TASK_ID")
            original = "outline/near_term_outline.md"
            alias = policy.runtime_alias(root, policy_runtime, original, task_id=task_id)
            if alias != original:
                print(f"<WF_VAR>pp_near_term_we_file:{alias}</WF_VAR>")


def _title(raw_path: str) -> str:
    stem = Path(raw_path).stem.replace("_", " ")
    return stem.strip().title() or "存档"


def _render_scalar(value: Any) -> str:
    if value is None or value == "":
        return "（空）"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _render_value(value: Any, level: int = 2) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = str(key).replace("_", " ")
            if isinstance(child, (dict, list)):
                lines.extend([f"{'#' * min(level, 6)} {label}", ""])
                lines.extend(_render_value(child, level + 1))
            else:
                lines.append(f"- {label}：{_render_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return ["（无）"]
        for index, child in enumerate(value, start=1):
            if isinstance(child, dict):
                label = child.get("name") or child.get("title") or child.get("id")
                lines.extend(
                    [
                        f"{'#' * min(level, 6)} {label or f'条目 {index}'}",
                        "",
                    ]
                )
                lines.extend(_render_value(child, level + 1))
            else:
                lines.append(f"- {_render_scalar(child)}")
        return lines
    return [_render_scalar(value)]


def _adopted_style_references():
    if not _workspace_path('learning/active.json').is_file():
        return None
    active = _read_json('learning/active.json')
    relative = active['blueprint_path']
    if not _workspace_path(relative).is_relative_to(_workspace_path('learning/blueprints')):
        raise ValueError('采用蓝图路径无效')
    blueprint = _read_json(relative)
    if _execution_guard().digest(blueprint) != active['blueprint_sha256']:
        raise ValueError('采用蓝图与风格档案来源不一致')
    styles = blueprint.get('styles', [])
    mechanisms = blueprint.get('mechanisms', [])
    if ([item['choice_id'] for item in styles] != blueprint.get('selected_style_ids', []) or
            [item['candidate_id'] for item in mechanisms] != blueprint.get('selected_candidate_ids', [])):
        raise ValueError('采用蓝图与参考条目不一致')
    return [
        *({'id': item['choice_id'], 'style': item['title'], 'guidance': item['guidance']} for item in styles),
        *({'id': item['candidate_id'], 'mechanism': item['mechanism']} for item in mechanisms),
    ]


def _render_document(raw_path: str, value: Any) -> str:
    if Path(raw_path).name == "body.json" and isinstance(value, dict):
        return str(value.get("body", "")).rstrip() + "\n"
    if Path(raw_path).as_posix() == 'cache/story_plan/style_profile.json' and isinstance(value, dict):
        adopted = _adopted_style_references()
        if adopted is not None:
            value = {**value, 'references': adopted}
    lines = [f"# {_title(raw_path)}", ""]
    lines.extend(_render_value(value))
    return "\n".join(lines).rstrip() + "\n"


def _render_files(inputs: str, outputs: str) -> int:
    input_paths = _split_paths(inputs)
    output_paths = _split_paths(outputs)
    if len(input_paths) != len(output_paths):
        raise ValueError("--inputs 与 --outputs 数量必须一致")
    boundary=(_execution_guard().publication(Path.cwd())
              if os.environ.get('TASK_ID') and os.environ.get('WORKFLOW_ID') else nullcontext(None))
    with boundary:
        rendered=[(output_path,_render_document(input_path,_read_json(input_path)))
                  for input_path,output_path in zip(input_paths,output_paths,strict=True)]
        for output_path,text in rendered:
            _workspace_path(output_path)  # Validate every destination before the first replacement.
        for output_path,text in rendered:_write_text(output_path,text)
    return len(input_paths)


def _render_indexes() -> None:
    root=Path.cwd()
    if (root/'archive/longform.sqlite3').is_file():
        support=_story_support();states,_=support.confirmed(root)
        if any(state.get('archive_commit_id') for state in states):
            # P0 owns these derived views. Reuse its canonical renderer so
            # preparation cannot invalidate plans merely by reformatting them.
            support.refresh_archive(root)
            return
    _render_files(
        "archive/hooks.json,archive/debts.json",
        "meta/hooks.md,meta/debts.md",
    )


def _prepare(args: argparse.Namespace) -> None:
    if args.require:
        _require_files(args.require)
    _ensure_indexes()
    _render_indexes()
    if args.context:
        _build_world_cache()
        runtime = getattr(args, "policy_runtime", "").strip()
        _build_character_cache(runtime, getattr(args, "policy_characters_file", ""))
        _render_near_term_context(runtime, getattr(args, "policy_near_term_file", ""))


def _rebind(args: argparse.Namespace) -> None:
    directory = getattr(args, "policy_runtime", "").strip()
    if not directory or not getattr(args, "policy_rebind", []):
        return
    policy, root, task_id = _policy(), Path.cwd(), os.environ.get("TASK_ID")
    for binding in args.policy_rebind:
        key, sep, source = binding.partition("=")
        if not sep or not re.fullmatch(r"pp_[a-z_]+", key):
            raise ValueError("无效的工作流叙述资料别名。")
        alias = policy.runtime_alias(root, directory, source.replace("\\", "/"), task_id=task_id)
        # Avoid placing user-controlled relative paths in the stdout tag protocol.
        # All rebound files here have a fixed producer path in the workflow.
        if alias and re.fullmatch(r"[A-Za-z0-9_./-]+", alias):
            print(f"<WF_VAR>{key}:{alias}</WF_VAR>")


def _checkpoint(args: argparse.Namespace) -> None:
    if args.files:
        _require_files(args.files)
    changed = False
    if args.merge_hooks:
        _ensure_indexes()
        _merge_index("hooks", args.merge_hooks)
        changed = True
    if args.merge_debts:
        _ensure_indexes()
        _merge_index("debts", args.merge_debts)
        changed = True
    if changed:
        _render_indexes()
    _rebind(args)


def _post_hoc(args: argparse.Namespace) -> None:
    chapter = _normalize_chapter(args.chapter)
    arbiter = _read_json(args.arbiter)
    observer = _read_json(args.observer)
    if not isinstance(arbiter, dict) or not isinstance(observer, dict):
        raise ValueError("后验输出必须是 JSON 对象")

    _write_json(
        f"story/{chapter}/diff_world_resolved.json",
        arbiter.get("world_rulings", {"entries": []}),
    )
    _write_json(
        f"story/{chapter}/diff_story_confirmed.json",
        arbiter.get(
            "story_confirmed",
            {"landed": [], "missed": [], "deviated": [], "unplanned": []},
        ),
    )
    _write_json(
        f"story/{chapter}/diff_character.json",
        observer.get("character_diff", {}),
    )

    _ensure_indexes()
    _write_json("archive/post_hoc_hooks.json", arbiter.get("new_hooks", []))
    _write_json("archive/post_hoc_debts.json", arbiter.get("new_debts", []))
    # story_support.commit validates exact body evidence and the review revision
    # before these proposals are allowed into the confirmed indexes.


def _render(args: argparse.Namespace) -> None:
    _render_files(args.inputs, args.outputs)
    _rebind(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="笔枢纯本地存档工具")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="检查并准备本地工作区")
    prepare.add_argument("--require", default="", help="必须存在的相对文件，逗号分隔")
    prepare.add_argument("--context", action="store_true", help="构建章节生产上下文")
    prepare.add_argument("--policy-runtime", default="")
    prepare.add_argument("--policy-near-term-file", default="")
    prepare.add_argument("--policy-characters-file", default="")
    prepare.set_defaults(handler=_prepare)

    checkpoint = commands.add_parser("checkpoint", help="校验并索引阶段产物")
    checkpoint.add_argument(
        "--files",
        default="",
        help="必须存在的相对文件，逗号分隔",
    )
    checkpoint.add_argument("--merge-hooks", default="", help="要合并的伏笔 JSON")
    checkpoint.add_argument("--merge-debts", default="", help="要合并的债务 JSON")
    checkpoint.add_argument("--policy-runtime", default="")
    checkpoint.add_argument("--policy-rebind", action="append", default=[])
    checkpoint.set_defaults(handler=_checkpoint)

    render = commands.add_parser("render", help="将本地 JSON 渲染为 Markdown")
    render.add_argument("--inputs", required=True, help="输入 JSON，逗号分隔")
    render.add_argument("--outputs", required=True, help="输出 Markdown，逗号分隔")
    render.add_argument("--policy-runtime", default="")
    render.add_argument("--policy-rebind", action="append", default=[])
    render.set_defaults(handler=_render)

    post_hoc = commands.add_parser("post-hoc", help="归档章节后验结果")
    post_hoc.add_argument("--chapter", required=True, help="章节号")
    post_hoc.add_argument('--observer', default='cache/observer/obs_output.json')
    post_hoc.add_argument('--arbiter', default='cache/arbiter/arb_output.json')
    post_hoc.set_defaults(handler=_post_hoc)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
