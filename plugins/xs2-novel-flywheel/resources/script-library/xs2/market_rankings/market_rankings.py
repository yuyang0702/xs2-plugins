"""Deterministic Zhihu Salt Selection ranking importer for Workflow Workspace."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_URL = "https://api.zhihu.com/km-vip-zhihu-web/vip_tab/svip_story?modules=billboard"


def metric_value(value: object) -> int | float | str:
    text = str(value or "").replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|亿)?", text)
    if not match:
        return text
    number = float(match.group(1))
    if match.group(2) == "万":
        number *= 10_000
    elif match.group(2) == "亿":
        number *= 100_000_000
    return int(number) if number.is_integer() else number


def category_and_tags(value: object) -> tuple[str, list[str]]:
    parts = [item.strip() for item in str(value or "").split("·") if item.strip()]
    return (parts[0] if parts else "未分类", parts)


def parse_payload(payload: dict, limit: int) -> list[dict]:
    works: list[dict] = []
    for module in payload.get("data", []):
        if not isinstance(module, dict):
            continue
        data = ((module.get("module_data") or {}).get("data") or {}).get("data") or []
        if not isinstance(data, list):
            continue
        for ranking in data:
            if not isinstance(ranking, dict):
                continue
            ranking_name = str((ranking.get("head") or {}).get("title") or "榜单")
            for rank, item in enumerate(ranking.get("content_list") or [], 1):
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                category, tags = category_and_tags(item.get("label_text"))
                works.append(
                    {
                        "ranking_name": ranking_name,
                        "rank": rank,
                        "platform_work_id": str(item.get("business_id") or ""),
                        "title": html.unescape(str(item.get("title") or "").strip()),
                        "summary": str(item.get("description") or "").strip(),
                        "category": category,
                        "tags": tags,
                        "likes": metric_value(item.get("subtitle")),
                        "space_type": item.get("space_type"),
                        "cover_url": item.get("artwork"),
                        "detail_url": item.get("url"),
                    }
                )
                if len(works) >= limit:
                    return works
    return works


def refresh(url: str, limit: int) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.zhihu.com/fiore/h5/vip-web",
        },
    )
    with urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    works = parse_payload(payload, max(1, min(limit, 500)))
    if not works:
        raise RuntimeError("没有识别到知乎榜单作品，页面结构可能已变化")
    captured_at = datetime.now(timezone.utc).isoformat()
    result = {
        "source": "zhihu-salt",
        "source_name": "知乎盐选榜单",
        "captured_at": captured_at,
        "boundary": "结果仅反映当前抓取到的知乎公开榜单样本，不代表全网市场。",
        "work_count": len(works),
        "rankings": sorted({item["ranking_name"] for item in works}),
        "works": works,
    }
    output = Path("market/zhihu-ranking.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("refresh")
    command.add_argument("--top-n", type=int, default=100)
    command.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    if args.command == "refresh":
        result = refresh(args.url, args.top_n)
        print(json.dumps({"status": "success", "work_count": result["work_count"], "rankings": result["rankings"]}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
