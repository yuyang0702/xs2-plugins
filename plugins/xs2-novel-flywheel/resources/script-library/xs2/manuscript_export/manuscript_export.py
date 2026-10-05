"""Assemble chapter markdown files into a portable manuscript artifact."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def chapter_key(path: Path) -> tuple[int, str]:
    stem = path.parent.name
    try:
        return int(stem), stem
    except ValueError:
        return 10**9, stem


def build_manuscript(output: str, manifest: str) -> dict[str, object]:
    root = Path.cwd()
    chapters = sorted((root / "story").glob("*/chapter.md"), key=chapter_key)
    target = root / output
    target.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    exported: list[dict[str, object]] = []
    for path in chapters:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        chapter = path.parent.name
        sections.append(f"# 第{chapter}章\n\n{content}")
        exported.append({"chapter": chapter, "path": path.relative_to(root).as_posix(), "characters": len(content)})
    target.write_text("\n\n---\n\n".join(sections) + ("\n" if sections else ""), encoding="utf-8")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output": target.relative_to(root).as_posix(),
        "chapter_count": len(exported),
        "chapters": exported,
    }
    manifest_path = root / manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", default="export/manuscript.md")
    build.add_argument("--manifest", default="export/manifest.json")
    args = parser.parse_args()
    if args.command == "build":
        report = build_manuscript(args.output, args.manifest)
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
