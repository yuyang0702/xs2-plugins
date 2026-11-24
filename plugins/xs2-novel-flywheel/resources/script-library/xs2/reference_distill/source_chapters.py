"""Map imported books to ordered, exact ranges in the immutable text snapshot."""
import re

from dialogue_learning import SOURCE_BOUNDARY


CHAPTER_HEADING = re.compile(
    r"^[ \t　]*(?:#{1,6}[ \t　]*)?(?P<title>(?:"
    r"第[零〇一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟\d \t　]+[章回卷部篇节]"
    r"|(?:chapter|book|part)[ \t]+(?:\d+|[ivxlcdm]+)\b"
    r"|序章|楔子|引子|尾声|终章|后记|番外)"
    r"(?:[ \t　:：、.．—\-][^\n]{0,100}|[\u3400-\u9fff]{1,20})?)[ \t　]*$", re.I | re.M)
END_MARKER = re.compile(r"(?:^|\n)[ \t　]*[【（(\[]?(?:全书完|全文完|全本完|完本|THE END|END OF (?:THE BOOK|THE NOVEL))"
                        r"[】）)\]]?[。.！!]*[\s　]*\Z", re.I)


def chapter_number(title):
    match = re.match(r"第\s*([\d零〇一二两三四五六七八九十百千万]+)\s*[章回]|chapter\s+(\d+)\b", title, re.I)
    if not match:
        return None
    value = match[1] or match[2]
    if value.isdecimal():
        return int(value)
    digits = dict(zip("零一二三四五六七八九", range(10))) | {"〇": 0, "两": 2}
    if all(char in digits for char in value):
        return int("".join(str(digits[char]) for char in value))
    section = previous = total = 0
    for char in value:
        if char in digits:
            previous = digits[char]
        elif char == "万":
            total += (section + previous) * 10000
            section = previous = 0
        elif char in "十百千":
            section += (previous or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            previous = 0
        else:
            return None
    return total + section + previous


def numbering_gaps(chapters):
    gaps = []
    previous = None
    saw_number = False
    for chapter in chapters:
        number = chapter_number(chapter["title"])
        if not saw_number and number is not None:
            previous = 0
            saw_number = True
        if number is not None and previous is not None and number > previous + 1:
            gaps.append({"before_chapter_id": chapter["id"], "first_missing": previous + 1, "last_missing": number - 1})
        previous = number
    return gaps


def source_units(raw, mode):
    if mode not in {"auto", "short_full", "serial_chapters", "serial_full"}:
        raise ValueError("语料类型必须为 auto、short_full、serial_chapters 或 serial_full")
    markers = list(SOURCE_BOUNDARY.finditer(raw))
    if mode == "auto":
        if any("SOURCE CHAPTER" in marker[0] for marker in markers):
            mode = "serial_chapters"
        else:
            titles = [m["title"].strip() for m in CHAPTER_HEADING.finditer(raw)]
            numbered = [chapter_number(title) for title in titles]
            numbered = [number for number in numbered if number is not None]
            if titles:
                mode = "serial_chapters"
                if (len(numbered) >= 2 and numbered[0] in (0, 1) and END_MARKER.search(raw)
                        and all(b == a + 1 for a, b in zip(numbered, numbered[1:]))):
                    mode = "serial_full"
    ranges = []

    def append(title, start, end):
        if start < end and raw[start:end].strip():
            ranges.append({"id": f"chapter-{len(ranges) + 1:04d}", "title": title,
                           "start": start, "end": end})

    def segment(start, end, title, is_chapter):
        if mode == "serial_full" and is_chapter and not raw[start:end].strip():
            raise ValueError(f"章节「{title}」缺少正文。请补齐后分析全文。")
        headings = list(CHAPTER_HEADING.finditer(raw, start, end)) if mode in ("serial_chapters", "serial_full") and not is_chapter else []
        if not headings:
            append(title, start, end)
            return
        append("卷首文字", start, headings[0].start())
        for index, heading in enumerate(headings):
            stop = headings[index + 1].start() if index + 1 < len(headings) else end
            if mode == "serial_full" and chapter_number(heading["title"]) is not None and not raw[heading.end():stop].strip():
                raise ValueError(f"章节「{heading['title']}」缺少正文。请检查目录和正文是否混排。")
            append(heading["title"].strip(), heading.start(), stop)

    if markers:
        segment(0, markers[0].start(), "卷首文字", False)
        for index, marker in enumerate(markers):
            title = marker[0].strip("= ")
            label = title.partition(":")[2].strip() or title
            stop = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
            segment(marker.end(), stop, label, title.startswith("SOURCE CHAPTER"))
    else:
        segment(0, len(raw), "导入正文（无分章标记）", False)
    if not ranges:
        raise ValueError("导入文本中没有章节正文")
    return mode, ranges


def split_ranges(raw, start, stop, size, overlap):
    while start < stop:
        upper = min(stop, start + size)
        end = upper
        if upper < stop:
            punctuation = re.finditer(r"[。！？!?；;\n]", raw[start:upper])
            end = max((start + m.end() for m in punctuation if m.end() >= size // 2), default=upper)
        yield start, end
        if end == stop:
            break
        start = end - overlap


def chapter_batches(raw, chapters, max_chapters, max_chars, overlap):
    """Group consecutive chapters while keeping each original span identifiable."""
    pending = []
    for chapter in chapters:
        start, end = chapter["start"], chapter["end"]
        if pending and (len(pending) == max_chapters or end - pending[0]["source_start"] > max_chars):
            yield pending
            pending = []
        parts = list(split_ranges(raw, start, end, max_chars, min(overlap, max_chars // 4)))
        segments = [{"segment_id": f"{chapter['id']}-part-{index}", "chapter_id": chapter["id"],
                     "title": chapter["title"], "source_start": a, "source_end": b}
                    for index, (a, b) in enumerate(parts, 1)]
        if len(segments) > 1:
            for segment in segments:
                yield [segment]
        else:
            pending.extend(segments)
    if pending:
        yield pending


def coverage(chapters, windows, completed):
    by_chapter = {chapter["id"]: [] for chapter in chapters}
    for window in windows:
        for chapter_id in window["chapter_ids"]:
            by_chapter[chapter_id].append(window["window_id"])
    analyzed = [key for key, ids in by_chapter.items() if ids and all(i in completed for i in ids)]
    known = set(analyzed)
    missing = [key for key in by_chapter if key not in known]
    return {"chapters": chapters, "analyzed_chapters": analyzed, "missing_chapters": missing,
            "window_count": len(windows), "analyzed_window_count": len(completed),
            "complete": bool(chapters) and not missing and len(completed) == len(windows)}
