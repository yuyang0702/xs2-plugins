#!/usr/bin/env python3
"""NO 后处理：读 no_output.json，根据 is_new_volume 覆盖或追加 near_term_outline.md。

用法:
  python no_post.py --input cache/no/no_output.json [--volume-number 2]
  --volume-number 传入时，若 is_new_volume=true 则覆盖写入该卷近纲。
"""

import argparse
import json
import os


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean(text):
    return text.replace("——", "，")


def render_chapter(ch):
    lines = [
        f"### 第{ch.get('number', '?')}章 · {ch.get('title', '')}",
        f"- **情节摘要**：{ch.get('summary', '—')}",
        f"- **节奏**：{ch.get('rhythm', '—')}",
        f"- **世界时间推进**：{ch.get('time_advance', '?')}",
    ]
    return "\n".join(lines)


def render_full(data):
    """首次跑该卷/重写该卷：输出完整近纲。"""
    cr = data.get("chapter_range", {})
    start = cr.get("start", "?")
    end = cr.get("end", "?")
    arc = data.get("arc_name", "")

    lines = [f"# 近期大纲（第{start}-{end}章）"]
    if arc:
        lines.extend(["", f"## 当前弧线 · {arc}"])

    for ch in data.get("chapters", []):
        lines.extend(["", render_chapter(ch)])

    char_arcs = data.get("character_arcs", [])
    if char_arcs:
        lines.extend(["", "## 角色弧线"])
        for ca in char_arcs:
            lines.append(f"- **{ca.get('name', '?')}**：{ca.get('from', '?')} → {ca.get('to', '?')} → {ca.get('change', '?')}")

    dp = data.get("decision_points", [])
    if dp:
        lines.extend(["", "## 关键决策点"])
        for d in dp:
            lines.append(f"- 第{d.get('chapter', '?')}章：{d.get('character', '?')}面临{d.get('choice', '?')}，将影响{d.get('impact', '?')}")

    return clean("\n".join(lines)) + "\n"



def validate_output(data, expected_volume=None):
    """Reject unusable output before any published outline or cache is changed."""
    from jsonschema import Draft202012Validator
    # Historical renderers accept missing descriptive fields and render placeholders.
    # The generating node requires usable text; retain old archived input compatibility.
    schema = json.loads(json.dumps(OUTPUT_SCHEMA))
    schema["properties"]["chapters"]["items"]["required"] = ["number"]
    Draft202012Validator(schema).validate(data)
    if data.get("volume_number") is not None and expected_volume is not None and data["volume_number"] != expected_volume:
        raise ValueError("大纲卷号与请求卷号不一致")
    chapter_range = data.get("chapter_range")
    if chapter_range and chapter_range["start"] > chapter_range["end"]:
        raise ValueError("章节范围起点不得大于终点")
    chapters = data["chapters"]
    numbers = [chapter["number"] for chapter in chapters]
    if numbers != sorted(set(numbers)):
        raise ValueError("章节号必须递增且不重复")
    if chapter_range and numbers and (numbers[0] < chapter_range["start"] or numbers[-1] > chapter_range["end"]):
        raise ValueError("章节号超出声明范围")
    if any(point["chapter"] not in numbers for point in data.get("decision_points", []) if "chapter" in point):
        raise ValueError("决策点章节不在本次规划章节中")


OUTPUT_SCHEMA = {'type': 'object', 'properties': {'volume_number': {'type': 'integer', 'minimum': 1}, 'is_new_volume': {'type': 'boolean'}, 'arc_name': {'type': 'string'}, 'chapter_range': {'type': 'object', 'properties': {'start': {'type': 'integer', 'minimum': 1}, 'end': {'type': 'integer', 'minimum': 1}}, 'required': ['start', 'end']}, 'chapters': {'type': 'array', 'items': {'type': 'object', 'properties': {'number': {'type': 'integer', 'minimum': 1}, 'title': {'type': 'string', 'minLength': 1}, 'summary': {'type': 'string', 'minLength': 1}, 'rhythm': {'type': 'string'}, 'time_advance': {'type': 'string'}}, 'required': ['number', 'title', 'summary']}}, 'character_arcs': {'type': 'array', 'items': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'from': {'type': 'string'}, 'to': {'type': 'string'}, 'change': {'type': 'string'}}, 'required': []}}, 'decision_points': {'type': 'array', 'items': {'type': 'object', 'properties': {'chapter': {'type': 'integer', 'minimum': 1}, 'character': {'type': 'string'}, 'choice': {'type': 'string'}, 'impact': {'type': 'string'}}, 'required': []}}}, 'required': ['chapters'], 'anyOf': [{'properties': {'chapters': {'maxItems': 0}}}, {'required': ['volume_number'], 'properties': {'chapters': {'minItems': 1}}}]}


def main():
    parser = argparse.ArgumentParser(description="NO 输出渲染")
    parser.add_argument("--input", required=True, help="no_output.json 路径")
    parser.add_argument("--volume-number", type=int, default=None, help="目标卷号（用于日志，不影响行为——行为由 agent 的 is_new_volume 控制）")
    parser.add_argument("--scope", default="serial_chapter", help="short_full 将阶段合并为短篇全文单章")
    args = parser.parse_args()

    data = load_json(args.input)
    validate_output(data, args.volume_number)
    chapters = data.get("chapters", [])
    if args.scope == "short_full" and chapters:
        if len(chapters) > 1:
            data["chapters"] = [{
                "number": 1, "title": data.get("arc_name") or chapters[0].get("title", "短篇全文"),
                "summary": "；".join(f"阶段{i + 1}·{chapter.get('title', '')}：{chapter.get('summary', '')}" for i, chapter in enumerate(chapters)),
                "rhythm": "起因→递进阻碍→高潮→关键伏笔回收→终局（同一短篇全文）",
                "time_advance": "篇内按阶段推进：" + "、".join(str(chapter.get("time_advance", "")) for chapter in chapters),
            }]
        data["chapter_range"] = {"start": 1, "end": 1}
        data["is_new_volume"] = True
        for point in data.get("decision_points", []):
            point["chapter"] = 1
        chapters = data["chapters"]

    if not chapters:
        print("[OK] 无新增章，跳过")
        return

    volume_path = "cache/vo/volume.json"
    if os.path.isfile(volume_path):
        volume = load_json(volume_path)
        if volume.get("volume_number") != data.get("volume_number"):
            raise ValueError("近纲卷号与已确认卷纲不一致")
        bounds = volume.get("chapter_range", {})
        if chapters[0]["number"] < bounds.get("start", 1) or chapters[-1]["number"] > bounds.get("end", chapters[-1]["number"]):
            raise ValueError("近纲章节号超出已确认卷纲范围")
    previous_path = "cache/no/near_term.json"
    if not data.get("is_new_volume", False) and os.path.isfile(previous_path):
        previous = load_json(previous_path)
        if previous.get("volume_number") == data.get("volume_number"):
            previous_numbers = [chapter["number"] for chapter in previous.get("chapters", [])]
            if previous_numbers and chapters[0]["number"] <= max(previous_numbers):
                raise ValueError("追加近纲不得重复或倒退既有章节号")

    outpath = "outline/near_term_outline.md"
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)

    if data.get("is_new_volume", False):
        # 新卷或重写：覆盖写入
        md = render_full(data)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(md)
        action = "覆盖"
    else:
        # 追加新章到末尾
        chunks = []
        for ch in chapters:
            chunks.append(render_chapter(ch))
        md = clean("\n\n".join(chunks)) + "\n"

        existing = ""
        if os.path.exists(outpath):
            with open(outpath, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(existing + "\n" + md)
        action = "追加"

    # JSON 缓存
    os.makedirs("cache/no", exist_ok=True)
    with open("cache/no/near_term.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    vn = data.get("volume_number", "?")
    size = len(md.encode("utf-8"))
    print(f"[OK] 卷{vn} {action} {len(chapters)} 章 → {outpath} (+{size}B)")


if __name__ == "__main__":
    main()
