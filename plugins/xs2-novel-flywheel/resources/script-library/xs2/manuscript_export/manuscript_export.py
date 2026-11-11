"""Assemble chapter markdown files into a portable manuscript artifact."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path


def chapter_key(path: Path) -> tuple[int, str]:
    stem = path.parent.name
    try:
        return int(stem), stem
    except ValueError:
        return 10**9, stem


def _execution_guard():
    entry=Path(__file__).resolve().parents[1]/'production_guard/production_guard.py'
    spec=importlib.util.spec_from_file_location('export_execution_guard',entry)
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    return guard


def _artifact_path(root,relative):
    requested=Path(relative);path=(root/requested).resolve()
    if requested.is_absolute() or not path.is_relative_to(root):
        raise ValueError('导出路径不能离开当前作品工作区')
    return path


def _atomic_text(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.export-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def build_manuscript(output: str, manifest: str) -> dict[str, object]:
    root = Path.cwd().resolve()
    target=_artifact_path(root,output);manifest_path=_artifact_path(root,manifest)
    if target==manifest_path:raise ValueError('正文导出与清单不能使用同一目标文件')
    boundary=(_execution_guard().publication(root)
              if os.environ.get('TASK_ID') and os.environ.get('WORKFLOW_ID') else nullcontext(None))
    with boundary as proof:
        chapters = sorted((root / "story").glob("*/chapter.md"), key=chapter_key)
        if any(not path.resolve().is_relative_to(root) for path in chapters):
            raise ValueError('章节来源不能离开当前作品工作区')
        if any(path.resolve() in (target,manifest_path) for path in chapters):
            raise ValueError('导出文件不能覆盖章节来源')
        sections: list[str] = [];exported: list[dict[str, object]] = [];sources={}
        for path in chapters:
            raw=path.read_bytes();sources[path]=raw
            content=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n').strip()
            if not content:continue
            chapter = path.parent.name
            first = content.splitlines()[0].strip()
            heading = re.sub(r'^#{1,6}\s*', '', first)
            has_title = bool(re.match(r'^第[一二三四五六七八九十百千零〇两0-9]+[章回节卷](?:\s|[·：:、.]|$)', heading))
            if has_title:sections.append(content if first.startswith('#') else '# ' + content)
            else:sections.append(f"# 第{chapter}章\n\n{content}")
            exported.append({"chapter": chapter, "path": path.relative_to(root).as_posix(), "characters": len(content)})
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "output": target.relative_to(root).as_posix(),"chapter_count": len(exported),"chapters": exported}
        if proof:report['execution_fence']=proof
        if (sorted((root/'story').glob('*/chapter.md'),key=chapter_key)!=chapters
                or any(path.read_bytes()!=raw for path,raw in sources.items())):
            raise ValueError('导出期间章节来源已有变化，未发布')
        _atomic_text(target,"\n\n---\n\n".join(sections) + ("\n" if sections else ""))
        _atomic_text(manifest_path,json.dumps(report,ensure_ascii=False,indent=2)+'\n')
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
