"""Adapted upstream pure functions. See UPSTREAM.json and ADAPTER.md."""
import re

def parse_markdown_chunks(content: str, topic: str, source: str):
    """按 ## 标题分块"""
    chunks = []
    parts = re.split(r"^## ", content, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split("\n")
        title = re.sub(r"^#+\s*", "", lines[0].strip())
        body = "\n".join(lines[1:]).strip()
        if title and len(body) >= 10:
            chunks.append({
                "topic": topic,
                "title": title[:255],
                "content": body,
                "tags": [],
                "source": source,
            })
    return chunks

def story_state_text(state: dict, mode: str = "deep") -> str:
    """作品状态包文本。

    mode="standard"：精简动态层（默认，控制 ~2-3k token）——
      主线前500字、人物一行卡（身份+当前状态）、最近3章摘要、
      未回收伏笔、关系图（≤15条）、时间线（最近5条）。
    mode="deep"：完整层——全量大纲、人物全文、完整时间线/关系/伏笔。
    """
    parts = []
    o = state.get("outline") or {}

    if mode == "deep":
        labels = [("main_storyline", "主线剧情"), ("world_setting", "世界设定"), ("volume_plans", "分卷规划"),
                  ("key_plot_points", "关键情节"), ("foreshadowing", "伏笔"), ("other_notes", "其他备注")]
        blocks = [f"【{label}】\n{o.get(key) or ''}" for key, label in labels if o.get(key)]
        if blocks:
            parts.append("## 大纲\n" + "\n\n".join(blocks))
    else:
        # 精简：主线前500字
        mainline = (o.get("main_storyline") or "").strip()
        if mainline:
            parts.append("## 主线\n" + mainline[:500])
        ws = (o.get("world_setting") or "").strip()
        if ws:
            parts.append("## 世界设定（摘要）\n" + ws[:300])

    # 人物卡
    chars = state.get("characters") or []
    if mode == "deep":
        blocks = []
        for c in chars:
            lines = [f"===== {c['name']} ====="]
            for key, label in [("identity", "身份"), ("current_status", "当前状态"),
                               ("motivation", "动机"), ("personality", "性格"),
                               ("background", "背景"), ("relationships", "人物关系"),
                               ("speech_style", "说话风格"), ("appearance", "外貌")]:
                if c.get(key):
                    lines.append(f"{label}：{c[key]}")
            if c.get("other_info"):
                lines.append(f"动态记录：{c['other_info']}")
            blocks.append("\n".join(lines))
        parts.append("## 人物卡（含最新状态）\n" + "\n\n".join(blocks))
    else:
        # 精简一行卡：名字｜身份｜当前状态（只注入最关键的动态字段）
        lines = []
        for c in chars[:15]:
            ident = (c.get("identity") or "").strip()
            status = (c.get("current_status") or "").strip()
            if status:
                lines.append(f"{c['name']}｜{ident}｜{status}")
            elif ident:
                lines.append(f"{c['name']}｜{ident}")
            else:
                lines.append(f"{c['name']}")
        if lines:
            parts.append("## 人物（一行卡）\n" + "\n".join(lines))

    # 关系图
    rels = state.get("relationships") or []
    rels_show = rels[:15] if mode == "standard" else rels
    if rels_show:
        lines = [f"{r['char_a']} — {r['char_b']}：{r.get('relation') or ''}（{r.get('sentiment') or 'neutral'}，{r.get('trend') or 'stable'}）" for r in rels_show]
        parts.append("## 人物关系\n" + "\n".join(lines))

    # 时间线（标准只最近5条）
    tl = state.get("timeline") or []
    tl_show = tl[-5:] if mode == "standard" else tl
    if tl_show:
        lines = [f"第{t['chapter_number']}章@{t.get('location') or '?'}：{(t.get('events') or '')[:150]}" for t in tl_show]
        parts.append("## 剧情时间线\n" + "\n".join(lines))

    # 伏笔：只注入未回收（已回收的不注入，省 token）
    of = state.get("foreshadowing_open") or []
    if of:
        lines = [f"（第{f['planted_chapter']}章埋）{f['description']}" for f in of]
        parts.append("## 未回收伏笔\n" + "\n".join(lines))
    if mode == "deep":
        rf = state.get("foreshadowing_resolved") or []
        if rf:
            lines = [f"（第{f['planted_chapter']}章埋，第{f['resolved_chapter']}章回收）{f['description']}" for f in rf]
            parts.append("## 已回收伏笔\n" + "\n".join(lines))

    # 最近章节摘要
    rc = state.get("recent_chapters") or []
    if rc:
        lines = [f"第{c['chapter_number']}章 {c['title']}\n摘要：{c.get('summary') or ''}" for c in rc]
        parts.append("## 最近章节摘要\n" + "\n\n".join(lines))

    return "\n\n".join(parts)
