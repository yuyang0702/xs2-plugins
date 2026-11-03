#!/usr/bin/env python3
"""从 skeleton JSON 中提取角色名列表，产出 list 变量供循环网关使用。

用法:
    python extract_names.py --file cache/character/skeleton.json

产出:
    <WF_VAR>character_names:["张三","李四","王五"]</WF_VAR>
"""

import argparse
import json
import re
import sys


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if not text:
        return text
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, count=1)
    text = re.sub(r'\n?```\s*$', '', text, count=1)
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')
    text = text.replace('\u201e', '"').replace('\u201a', "'")
    text = text.replace('\uff02', '"')
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text.strip()


def _drop_obvious_orphan_lines(text: str) -> str:
    """Drop lines that are clearly not JSON tokens.

    LLM output occasionally contains a dangling fragment like:
        寻者",
    inside an object.  It is better to drop that line and keep the rest of the
    valid structure than to fail the whole character pipeline.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if stripped[0] in '{[}]':
            kept.append(line)
            continue
        if stripped.startswith('"') and ':' in stripped:
            kept.append(line)
            continue
        if stripped.startswith('"') and stripped.rstrip(',').endswith('"'):
            kept.append(line)
            continue
        # Any other line is likely an orphan natural-language fragment.
    return "\n".join(kept)


def _load_json_tolerant(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    text = _extract_json(raw)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        repaired = _drop_obvious_orphan_lines(text)
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
        data = json.loads(repaired, strict=False)
        # Persist the repaired JSON so downstream nodes read valid JSON too.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("[extract_names] 已修复 skeleton JSON 中的孤立文本行", file=sys.stderr)
        return data


def _validate_v2_identities(characters, *, require_v2=False):
    """Validate the whole v2 batch before names can become deep-cache paths.

    Keep these standalone identity rules aligned with the v2 renderer. Legacy
    records remain unmodified; a declared version must be explicitly supported.
    """
    names = [c.get("name").strip() for c in characters
             if isinstance(c, dict) and isinstance(c.get("name"), str)]
    for character in characters:
        if not isinstance(character, dict):
            raise ValueError("角色记录必须是对象")
        if "card_schema" not in character:
            if require_v2:
                raise ValueError("新人物卡必须显式声明card_schema=xs2.character.v2")
            continue
        if character["card_schema"] != "xs2.character.v2":
            raise ValueError("不支持的card_schema；请使用xs2.character.v2或保留无版本旧档")
        name = character.get("name")
        if (not isinstance(name, str) or not name.strip() or len(name) > 60
                or re.search(r'[\x00-\x1f\x85\u2028\u2029/\\<>:"|?*#]', name)
                or name.strip() in {".", ".."}):
            raise ValueError("v2人物姓名name必须是非空安全字符串，不能包含路径或标题字符")
        aliases = character.get("aliases", [])
        if not isinstance(aliases, list) or any(
                not isinstance(alias, str) or not alias.strip()
                or re.search(r'[\x00-\x1f\x85\u2028\u2029]', alias) for alias in aliases):
            raise ValueError("v2的aliases必须是非空单行字符串数组")
        true_name = character.get("true_name", "")
        if (not isinstance(true_name, str)
                or re.search(r'[\x00-\x1f\x85\u2028\u2029]', true_name)):
            raise ValueError("v2的true_name必须是单行字符串；真名未知可留空")
        for text in [name, true_name, *aliases]:
            if require_v2 and ("{{" in text or "}}" in text):
                raise ValueError("新人物卡身份不能包含工作流占位符分隔符")
            if (re.match(r'^[ \t]{0,3}#{1,6}(?:[ \t]|$)', text)
                    or re.match(r'^[ \t]{0,3}(?:`{3,}|~{3,})', text)):
                raise ValueError("v2身份文本不能包含Markdown标题或代码围栏")
        if names.count(name.strip()) != 1:
            raise ValueError("v2人物姓名重复；请使用不同name区分角色")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="skeleton JSON 文件路径")
    parser.add_argument("--require-v2", action="store_true", help="新建工作流拒绝未声明v2的人物记录")
    args = parser.parse_args()

    try:
        if args.require_v2:
            # AgentNode has already saved JSON. Preserve its exact source bytes;
            # smart quotes inside valid strings are data, not JSON delimiters.
            with open(args.file, "r", encoding="utf-8") as source:
                data = json.load(source)
            if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
                raise ValueError("新人物卡必须是包含characters数组的JSON对象")
        else:
            data = _load_json_tolerant(args.file)
        characters = data.get("characters", [])
        _validate_v2_identities(characters, require_v2=args.require_v2)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"角色骨架校验失败: {e}", file=sys.stderr)
        sys.exit(1)

    names = [c["name"] for c in characters if c.get("name")]

    if not names:
        print("[extract_names] 错误：未找到角色名", file=sys.stderr)
        sys.exit(1)

    # 输出 list 变量（双引号 JSON 数组）
    names_json = json.dumps(names, ensure_ascii=False)
    print(f"<WF_VAR>character_names:{names_json}</WF_VAR>")
    print(f"<script_out>已提取 {len(names)} 个角色: {', '.join(names)}</script_out>")


if __name__ == "__main__":
    main()
