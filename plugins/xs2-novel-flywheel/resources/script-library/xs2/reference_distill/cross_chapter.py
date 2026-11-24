"""Bounded second reading of a whole novel, with snapshot-verified evidence."""
from collections import Counter, defaultdict
from bisect import bisect_right
import html
import json
import math
import re

from reference_distill import digest, load, manifest, path, save, text_field


ROOT = "learning/cache/cross"
PLAN = ROOT + "/plan.json"
REPORT = "learning/dna/cross_chapter.json"
SUMMARY = "learning/dna/cross_summary.json"
FOCUS_SIZE = 4
PASSAGE_CHARS = 300
PHASES = ("opening", "middle", "closing")
DIMENSIONS = ("foreshadowing", "character_arc", "phase_pacing", "conflict", "relationship", "plot")
SUPPORT = {
    "foreshadowing": "explicit_callback", "character_arc": "explicit_change",
    "phase_pacing": "observed_contrast", "conflict": "explicit_consequence",
    "relationship": "explicit_change", "plot": "explicit_consequence",
}
COMPARISON_SCOPE = "按连续章节分组，补充首尾、阶段代表章及罕见共词检索的远章。每章使用有界原文节选，未穷举全部章对。"
BATCH_SCOPE = "首轮逐章读取。基于首轮线索在整份原文中查找命中位置，选择部分线索与候选原文逐项回查。"
INSTRUCTIONS = (
    "passages 是待研究的原文数据，first_read_leads 是第一次阅读形成的待核对判断。逐一审读 focus_chapter_ids，对每章写 1～4 项带原文依据的具体局部观察。"
    "各章尝试识别未解线索、人物当时的目标/选择/代价、冲突、关系、信息揭示和场景节奏。"
    "对照不同章节的原文，提出并检验伏笔与回收、人物起点与后来选择、阶段节奏变化、冲突、关系及剧情因果。"
    "仅报告至少涉及一个焦点章且有两章原文的具体发现。没有跨章证据时 findings 为 []。"
    "evidence 按先后列出，两端 role 为 before 和 after。每个 excerpt 是对应 passage 内唯一的逐字短引（最多 240 字）。"
    "同词、同人、重复主题或相似行为至多为 possible/inferred；reason 说明证据如何区分呼应与巧合，limits 写未见环节。"
    "confirmed 要求前后文本直接支持论断。把后来一端明确回指、交代变化或说明因果的原文逐字片段填入 bridge_excerpt，"
    "并在 reason 解释它明确指向哪项先前事实。只有两个时间点的描述时不可确认成长或伏笔。"
    "节奏可凭不同阶段可见的叙述速度对照确认 observed_contrast，不能把句长或篇幅直接等同于紧迫感。"
    "遵守 source_limits。按 reply_schema 的字段返回 JSON。dimension、status、support_type 各选一个字符串。"
    "每条观察最多 3 处原文，每批最多 18 条跨章判断，每条 2～6 处原文。statement 最多 300 字，reason 和 limits 各不超过 500 字。"
    "可说明当前阶段未见的部分，禁止补造原文或用其他作品知识。"
)
REPLY_SCHEMA = {
    "batch_id": "照抄", "source_sha256": "照抄", "packet_sha256": "照抄",
    "chapter_observations": [{"chapter_id": "焦点章 ID", "observations": [{
        "dimension": list(DIMENSIONS), "statement": "本章观察", "evidence": [{"passage_id": "片段 ID", "excerpt": "原文"}]}]}],
    "findings": [{"dimension": list(DIMENSIONS), "status": ["confirmed", "possible"],
                  "statement": "跨章判断", "reason": "两个原文细节如何关联", "limits": "判断边界",
                  "support_type": [*sorted(set(SUPPORT.values())), "inferred"],
                  "bridge_excerpt": "confirmed 时从 after 引文逐字引用体现联系的部分，possible 时可省略",
                  "evidence": [{"role": "before", "passage_id": "较早片段 ID", "excerpt": "原文"},
                               {"role": "after", "passage_id": "较晚片段 ID", "excerpt": "原文"}]}],
}


def _phase(index, count):
    return PHASES[(2 * index + 1) * 3 // (2 * count)]


def _samples(body, chapter_start, hints):
    if not body.strip():
        return []
    centers = []
    # Prefer one literal proof per narrative dimension before the bookend samples.
    for hint in hints.values():
        centers.append(hint["position"] - chapter_start)
    centers.extend([0, len(body) // 2, len(body)])
    spans = []
    for center in centers:
        start = max(0, min(len(body) - PASSAGE_CHARS, center - PASSAGE_CHARS // 2))
        end = min(len(body), start + PASSAGE_CHARS)
        if any(abs(previous - start) < PASSAGE_CHARS // 2 for previous, _ in spans):
            continue
        if body[start:end].strip():
            spans.append((start, end))
    if not spans:
        start = len(body) - len(body.lstrip())
        spans.append((start, min(len(body), start + PASSAGE_CHARS)))
    return [(a + chapter_start, b + chapter_start, body[a:b]) for a, b in sorted(spans)]


def _terms(passages):
    # Rare shared phrases only nominate a chapter for rereading.
    tokens = set()
    for passage in passages:
        for run in re.findall(r"[\u3400-\u9fff]+|[a-zA-Z]{3,}", passage["text"]):
            if run.isascii():
                tokens.add(run.casefold())
            else:
                for width in (2, 3):
                    tokens.update(run[i:i + width] for i in range(len(run) - width + 1))
    return tokens


def _hints(mdata, raw):
    result = defaultdict(dict)
    for window in mdata["windows"]:
        key = window["chapter_id"]
        checked = load(f"learning/cache/{window['window_id']}.validated.json")
        if (checked.get("run_id") != mdata["run_id"] or checked.get("source_sha256") != mdata["source"]["text_sha256"]
                or checked.get("window_id") != window["window_id"]):
            raise ValueError("跨章复读遇到过期窗口")
        for group in ("conflict_patterns", "style_observations", "candidates"):
            for record in checked.get(group, []):
                label = record.get("layer") or record.get("dimension") or group
                if label in result[key] or len(result[key]) >= 3:
                    continue
                for proof in record["evidence"]:
                    a, b = proof["source_start"], proof["source_end"]
                    if not window["source_start"] <= a < b <= window["source_end"] or raw[a:b] != proof["excerpt"]:
                        raise ValueError("窗口依据与来源快照不一致")
                    summary = record.get("name") or record.get("rule") or record.get("mechanism")
                    result[key][label] = {"position": (a + b) // 2, "observation": (summary or "")[:180]}
                    break
    return result


def _read_chapters(rows, mdata, raw, hints=None):
    chapters, bindings, statistics = [], {}, Counter()
    if hints is None:
        hints = _hints(mdata, raw)
    previous = 0
    # TextIO cookies preserve character coordinates even with UTF-8 and Windows CRLF.
    with path(mdata["source"]["snapshot_path"]).open(encoding="utf-8") as source:
        for index, row in enumerate(rows):
            cid, start, end = row["id"], row["start"], row["end"]
            if cid in bindings or not previous <= start < end <= len(raw):
                raise ValueError("章节身份或原文区间无效")
            source.read(start - previous)
            cookie = source.tell()
            body = source.read(end - start)
            if body != raw[start:end]:
                raise ValueError("章节与冻结快照不一致")
            previous = end
            phase = _phase(index, len(rows)) if len(rows) > 1 else "undivided"
            spans = _samples(body, start, hints[cid])
            passages = [{"passage_id": f"p{index+1}-{i+1}", "source_start": a, "source_end": b, "text": quote}
                        for i, (a, b, quote) in enumerate(spans)]
            leads = [hint["observation"] for hint in hints[cid].values() if hint["observation"]]
            chapters.append({"chapter_id": cid, "title": row["title"][:160], "phase": phase,
                             "first_read_leads": leads, "passages": passages})
            bindings[cid] = {"start": start, "end": end, "cookie": cookie, "sha256": digest(body)}
            statistics[phase, "chapters"] += 1
            statistics[phase, "chars"] += len(re.sub(r"\s", "", body))
            sentences = [re.sub(r"\s", "", s) for s in re.split(r"[。！？!?]+|\.+(?=\s|$)", body)]
            statistics[phase, "sentences"] += sum(bool(sentence) for sentence in sentences)
            statistics[phase, "sentence_chars"] += sum(map(len, sentences))
    pacing = []
    for phase in PHASES:
        count = statistics[phase, "chapters"]
        if count:
            chars, sentences = statistics[phase, "chars"], statistics[phase, "sentences"]
            pacing.append({"phase": phase, "chapter_count": count, "character_count": chars,
                           "mean_chapter_chars": round(chars / count, 2),
                           "mean_sentence_chars": round(statistics[phase, "sentence_chars"] / sentences, 2) if sentences else 0})
    return chapters, bindings, pacing


def _batched_readings(data, raw):
    readings = defaultdict(list)
    hints = defaultdict(dict)
    for window in data["windows"]:
        checked = load(f"learning/cache/{window['window_id']}.validated.json")
        if (checked.get("run_id") != data["run_id"] or checked.get("window_id") != window["window_id"]
                or checked.get("source_sha256") != data["source"]["text_sha256"]):
            raise ValueError("跨章复读遇到过期窗口")
        notes = checked.get("chapter_readings", [])
        if len(notes) != len(window["chapter_segments"]):
            raise ValueError("合批阅读缺少章节片段")
        for note, segment in zip(notes, window["chapter_segments"], strict=True):
            cid, proof = segment["chapter_id"], note["evidence"]
            a, z = proof["source_start"], proof["source_end"]
            if (note["segment_id"] != segment["segment_id"] or proof["chapter_id"] != cid
                    or not segment["source_start"] <= a < z <= segment["source_end"] or raw[a:z] != proof["excerpt"]):
                raise ValueError("合批阅读证据与冻结快照不一致")
            readings[cid].append(note)
            if note["lead"] and len(hints[cid]) < 3:
                hints[cid][note["segment_id"]] = {"position": (a + z) // 2, "observation": note["lead"]}
    return readings, hints


def _targeted_packets(chapters, bindings, readings, raw, binding):
    starts = [bindings[row["chapter_id"]]["start"] for row in chapters]
    min_distance = min(25, max(1, len(chapters) // 8))
    cue_hits = {}

    def hits(cue):
        if cue not in cue_hits:
            matches = []
            offset = raw.find(cue)
            while offset >= 0 and len(matches) <= 32:
                i = bisect_right(starts, offset) - 1
                if i < 0:
                    offset = raw.find(cue, starts[0])
                    continue
                end = bindings[chapters[i]["chapter_id"]]["end"]
                if offset + len(cue) <= end:
                    matches.append((i, offset))
                # Import marker lines are outside the actual chapter ranges.
                offset = raw.find(cue, max(end, offset + len(cue)))
            cue_hits[cue] = matches if len(matches) <= 32 else []
        return cue_hits[cue]

    chosen = []
    for i, chapter in enumerate(chapters):
        options = []
        for note in readings[chapter["chapter_id"]]:
            cue = note["cue"].strip("「」“”《》 ")
            if not note["lead"] or not 2 <= len(cue) <= 24:
                continue
            matches = [(j, pos) for j, pos in hits(cue) if j >= i + min_distance]
            if matches:
                options.append((len(matches), cue, note["lead"], matches))
        if options:
            frequency, cue, lead, matches = min(options)
            choice = (frequency, i, cue, lead, sorted({matches[0], matches[-1]}))
            if not chosen or chosen[-1][1] // 8 != i // 8:
                chosen.append(choice)
            elif choice < chosen[-1]:
                chosen[-1] = choice

    for start in range(0, len(chosen), FOCUS_SIZE):
        included = {}
        pairs = []
        focus = []
        for _, i, cue, lead, matches in chosen[start:start + FOCUS_SIZE]:
            earlier = chapters[i]["chapter_id"]
            focus.append(earlier)
            earlier_row = included.setdefault(i, {**chapters[i], "passages": []})
            for passage in chapters[i]["passages"]:
                if passage["passage_id"] not in {p["passage_id"] for p in earlier_row["passages"]}:
                    earlier_row["passages"].append(passage)
            for j, offset in matches:
                later = chapters[j]["chapter_id"]
                bounds = bindings[later]
                a = max(bounds["start"], offset - PASSAGE_CHARS // 3)
                z = min(bounds["end"], a + PASSAGE_CHARS)
                pid = f"hit-{j+1}-{offset}"
                row = included.setdefault(j, {**chapters[j], "passages": []})
                if pid not in {p["passage_id"] for p in row["passages"]}:
                    row["passages"].append({"passage_id": pid, "source_start": a, "source_end": z, "text": raw[a:z]})
                pairs.append({"earlier_chapter": earlier, "later_chapter": later, "passage_id": pid,
                              "cue": cue, "lead": lead})
        packet = {**binding, "batch_id": f"cross-{start // FOCUS_SIZE + 1:05d}",
                  "focus_chapter_ids": focus, "research_targets": pairs,
                  "chapters": [included[i] for i in sorted(included)], "reply_schema": REPLY_SCHEMA,
                  "instructions": INSTRUCTIONS + "优先核对 research_targets 指定的片段，每个焦点章输出一条局部观察。"}
        packet["packet_sha256"] = digest(packet)
        yield packet


def _make_packets(chapters, binding):
    index = defaultdict(list)
    for i, chapter in enumerate(chapters):
        for term in _terms(chapter["passages"]):
            # Terms exceeding the posting limit are excluded from retrieval.
            if len(index[term]) <= 32:
                index[term].append(i)
    index = {term: matches for term, matches in index.items() if 2 <= len(matches) <= 32}
    n = len(chapters)
    for start in range(0, n, FOCUS_SIZE):
        focus = list(range(start, min(start + FOCUS_SIZE, n)))
        scores = Counter()
        for i in focus:
            for term in sorted(_terms(chapters[i]["passages"])):
                matches = index.get(term)
                if matches:
                    weight = math.log1p(n / len(matches))
                    for match in matches:
                        if match not in focus:
                            scores[match] += weight
        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        representatives = {0, n // 2, n - 1, max(start - 1, 0), min(focus[-1] + 1, n - 1)}
        included = sorted(set(focus) | representatives | set(ranked[:4]))
        batch = f"cross-{start // FOCUS_SIZE + 1:05d}"
        packet = {**binding, "batch_id": batch, "focus_chapter_ids": [chapters[i]["chapter_id"] for i in focus],
                  "chapters": [chapters[i] for i in included], "instructions": INSTRUCTIONS, "reply_schema": REPLY_SCHEMA}
        packet["packet_sha256"] = digest(packet)
        yield packet


def _receipt(batch, fingerprint):
    try:
        saved = load(f"{ROOT}/{batch}.validated.json")
        checksum = saved.pop("validated_sha256")
        if digest(saved) == checksum and saved["packet_sha256"] == fingerprint:
            return saved
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def prepare():
    data, raw = manifest()
    corpus = load("learning/candidates.json")
    if corpus["source"]["text_sha256"] != data["source"]["text_sha256"]:
        raise ValueError("候选与跨章原文来源不一致")
    binding = {"source_sha256": data["source"]["text_sha256"], "run_id": data["run_id"]}
    mode = corpus.get("source_mode") or load("learning/dna/metadata.json")["source_mode"]
    scope = corpus.get("source_coverage", {})
    limits = ["所有阶段和结论只对应导入顺序及可读章节，末段为导入文本末段。"]
    if scope.get("numbering_gaps"):
        limits.append("导入章节编号存在跳号，跨越缺章的推断可能遗漏中间环节。")
    if scope.get("catalog_complete") is False or scope.get("work_finished") is False:
        limits.append("目录覆盖或作品完结状态有限，本次末段不代表全书结局。")
    chapters, bindings, pacing = [], {}, []
    first_pass = []
    batched = bool(data.get("chapter_batch_limits"))
    if mode == "serial_full":
        rows = scope["chapters"]
        if not rows:
            raise ValueError("整本复读缺少章节目录")
        readings, hints = _batched_readings(data, raw) if batched else ({}, None)
        chapters, bindings, pacing = _read_chapters(rows, data, raw, hints)
        if batched:
            for row in rows:
                notes = readings[row["id"]]
                if not notes:
                    raise ValueError("首轮阅读缺少章节")
                first_pass.append({"chapter_id": row["id"], "title": row["title"], "observations": [
                    {"dimension": "plot", "statement": note["event"], "evidence": [note["evidence"]]}
                    | ({"character_state": note["state"], "lead": note["lead"]} if note["state"] or note["lead"] else {})
                    for note in notes
                ]})
        if len(rows) == 1:
            limits.append("只识别出一个章节单元，无法比较跨章变化或划分阶段。")
    batches, pending = {}, []
    context = {**binding, "source_limits": limits}
    packets = _targeted_packets(chapters, bindings, readings, raw, context) if batched else _make_packets(chapters, context)
    for packet in packets:
        batch, fingerprint = packet["batch_id"], packet["packet_sha256"]
        batches[batch] = fingerprint
        save(f"{ROOT}/{batch}.packet.json", packet)
        if _receipt(batch, fingerprint) is None:
            pending.append(batch)
            save(f"{ROOT}/{batch}.feedback.md", "")
    save(PLAN, {**binding, "source": data["source"], "source_mode": mode, "batches": batches,
                "chapters": bindings, "phase_pacing": pacing, "source_limits": limits}
         | ({"first_pass": first_pass} if batched else {}))
    print(f"<WF_VAR>cross_batch_ids:{json.dumps(pending)}</WF_VAR>")
    print(f"<script_out>跨章原文复核共 {len(batches)} 批，待处理 {len(pending)} 批。</script_out>")


def _array(record, key, maximum, minimum=0):
    values = record.get(key)
    if not isinstance(values, list) or not minimum <= len(values) <= maximum or any(not isinstance(v, dict) for v in values):
        raise ValueError(f"{key} 必须为 {minimum}～{maximum} 项对象数组")
    return values


def _dimension(record):
    if record.get("dimension") not in DIMENSIONS:
        raise ValueError("跨章观察维度无效")
    return record["dimension"]


def _check_reply(reply, packet, bodies):
    if not isinstance(reply, dict) or any(reply.get(key) != packet[key] for key in ("batch_id", "source_sha256", "packet_sha256")):
        raise ValueError("跨章回复的批次、来源或复读包哈希不符")
    chapters = {row["chapter_id"]: row for row in packet["chapters"]}
    passages = {p["passage_id"]: (row["chapter_id"], p) for row in chapters.values() for p in row["passages"]}
    focus = set(packet["focus_chapter_ids"])

    def evidence(record, maximum, minimum=1):
        verified = []
        for item in _array(record, "evidence", maximum, minimum):
            pid = text_field(item, "passage_id", 80)
            if pid not in passages:
                raise ValueError("未知原文片段 " + pid)
            cid, passage = passages[pid]
            excerpt = item.get("excerpt")
            if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 240:
                raise ValueError("请给出 1～240 字的原文短引")
            offset = passage["text"].find(excerpt)
            if offset < 0 or passage["text"].find(excerpt, offset + 1) >= 0:
                raise ValueError("引文必须在所指原文片段中逐字且唯一匹配：" + pid)
            a = passage["source_start"] + offset
            b = a + len(excerpt)
            origin, body = bodies[cid]
            if not origin <= a < b <= origin + len(body) or body[a - origin:b - origin] != excerpt:
                raise ValueError("跨章引文与重新打开的原章不符")
            verified.append({"chapter_id": cid, "source_start": a, "source_end": b, "excerpt": excerpt,
                             **({"role": item["role"]} if minimum == 2 else {})})
        return verified

    observations = {}
    for row in _array(reply, "chapter_observations", len(focus), len(focus)):
        cid = row.get("chapter_id")
        if cid not in focus or cid in observations:
            raise ValueError("每个焦点章必须各提交一次观察")
        checks = []
        for observation in _array(row, "observations", 4, 1):
            proofs = evidence(observation, 3)
            if any(p["chapter_id"] != cid for p in proofs):
                raise ValueError("本章观察引用了其他章节")
            checks.append({"dimension": _dimension(observation), "statement": text_field(observation, "statement", 300),
                           "evidence": proofs})
        observations[cid] = {"chapter_id": cid, "title": chapters[cid]["title"], "observations": checks}
    findings = []
    for row in _array(reply, "findings", 18):
        dimension = _dimension(row)
        proofs = evidence(row, 6, 2)
        if (not focus.intersection(p["chapter_id"] for p in proofs) or proofs[0]["role"] != "before"
                or proofs[-1]["role"] != "after" or any(p["role"] not in ("before", "intermediate", "after") for p in proofs)
                or proofs[0]["chapter_id"] == proofs[-1]["chapter_id"]
                or any(left["source_end"] > right["source_start"] for left, right in zip(proofs, proofs[1:]))):
            raise ValueError("跨章判断须按原文顺序引用不同章节，两端为 before/after，至少一端涉及焦点组")
        support, status = row.get("support_type"), row.get("status")
        if support not in (*SUPPORT.values(), "inferred") or status not in ("confirmed", "possible"):
            raise ValueError("判断状态或证明类型无效")
        bridge = row.get("bridge_excerpt", "")
        if not isinstance(bridge, str) or (bridge and bridge not in proofs[-1]["excerpt"]):
            raise ValueError("bridge_excerpt 须逐字见于后章 after 引文")
        if status == "confirmed" and (support != SUPPORT[dimension] or len(bridge.strip()) < 3):
            status = "possible"
        if dimension != "phase_pacing" and bridge and bridge in proofs[0]["excerpt"]:
            # An unchanged identifying phrase is not a later statement of linkage.
            status = "possible"
        if dimension == "phase_pacing" and chapters[proofs[0]["chapter_id"]]["phase"] == chapters[proofs[-1]["chapter_id"]]["phase"]:
            status = "possible"
        fields = {key: text_field(row, key, 500) for key in ("statement", "reason", "limits")}
        record = {"dimension": dimension, "status": status, **fields, "support_type": support,
                  "bridge_excerpt": bridge, "evidence": proofs}
        record["id"] = "link-" + digest([packet["source_sha256"], dimension, proofs])[:20]
        findings.append(record)
    return {"chapter_observations": [observations[cid] for cid in packet["focus_chapter_ids"]], "findings": findings}


def validate(batch_id):
    plan = load(PLAN)
    if batch_id not in plan["batches"]:
        raise ValueError("未知复读批次")
    prefix = f"{ROOT}/{batch_id}"
    packet = load(prefix + ".packet.json")
    fingerprint = packet.pop("packet_sha256")
    if fingerprint != plan["batches"][batch_id] or digest(packet) != fingerprint:
        raise ValueError("复读包损坏，请重新准备")
    packet["packet_sha256"] = fingerprint
    bodies = {}
    with path(plan["source"]["snapshot_path"]).open(encoding="utf-8") as source:
        for row in packet["chapters"]:
            cid = row["chapter_id"]
            binding = plan["chapters"][cid]
            source.seek(binding["cookie"])
            body = source.read(binding["end"] - binding["start"])
            if digest(body) != binding["sha256"]:
                raise ValueError("复读期间原章已变化")
            bodies[cid] = binding["start"], body
    try:
        checked = _check_reply(load(prefix + ".reply.json"), packet, bodies)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        message = f"请重新核对当前复读包后提交完整 JSON。{exc}"
        save(prefix + ".feedback.md", message)
        print('<WF_REJECT_UPSTREAM target="agent_cross_chapter">' + html.escape(message) + '</WF_REJECT_UPSTREAM>')
        return
    result = {"packet_sha256": fingerprint, **checked}
    save(prefix + ".validated.json", {**result, "validated_sha256": digest(result)})
    print(f"<script_out>已回查 {batch_id} 的章节原文。</script_out>")


def finalize():
    plan = load(PLAN)
    data, _ = manifest()
    if plan["run_id"] != data["run_id"] or plan["source_sha256"] != data["source"]["text_sha256"]:
        raise ValueError("跨章复读结果已过期")
    observations, findings = [], {}
    for batch, fingerprint in plan["batches"].items():
        receipt = _receipt(batch, fingerprint)
        if receipt is None:
            raise ValueError("跨章复读未完成：" + batch)
        observations.extend(receipt["chapter_observations"])
        for item in receipt["findings"]:
            # Resolve duplicate readings conservatively when reviewers disagree.
            if item["id"] not in findings or item["status"] == "possible":
                findings[item["id"]] = item
    first_pass = plan.get("first_pass")
    reviewed_count = len(observations)
    if first_pass is not None:
        by_chapter = {review["chapter_id"]: review["observations"] for review in observations}
        observations = [{**row, "observations": row["observations"] + by_chapter.get(row["chapter_id"], [])}
                        for row in first_pass]
    if [item["chapter_id"] for item in observations] != list(plan["chapters"]):
        raise ValueError("跨章观察未覆盖全部焦点章")
    limits = [BATCH_SCOPE if first_pass is not None else COMPARISON_SCOPE,
              "confirmed 表示复读模型给出直接文本依据，脚本仅核对原文位置与证明结构；possible 为待证解释。",
              "节奏阶段依导入章节顺序三等分。均值按非空白字符和句末标点计算，篇幅指标须结合场景解读。", *plan["source_limits"]]
    if plan["source_mode"] != "serial_full":
        limits = ["本次导入使用样本模式，未执行整本跨章复读。"]
    report = {"schema": "xs2.reference.cross_chapter.v1", "source_sha256": plan["source_sha256"], "run_id": plan["run_id"],
              "coverage": {"chapter_count": len(plan["chapters"]), "reviewed_chapter_count": reviewed_count,
                           "reviewed_batch_count": len(plan["batches"]), "comparison_scope": limits[0]},
              "chapter_observations": observations, "findings": list(findings.values()),
              "phase_pacing": plan["phase_pacing"], "limitations": limits}
    if first_pass is not None:
        report["coverage"]["first_pass_chapter_count"] = len(first_pass)
    save(REPORT, report)
    examples = []
    for dimension in DIMENSIONS:
        for status in ("confirmed", "possible"):
            match = next((f for f in findings.values() if f["dimension"] == dimension and f["status"] == status), None)
            if match:
                examples.append({key: match[key] for key in ("id", "dimension", "status", "statement", "limits")}
                                | {"evidence": [match["evidence"][0], match["evidence"][-1]]})
    sample_size = min(len(observations), 6)
    chapter_examples = []
    for i in range(sample_size):
        chapter = observations[i * (len(observations) - 1) // max(1, sample_size - 1)]
        sample = chapter["observations"][0]
        chapter_examples.append({"chapter_id": chapter["chapter_id"], "title": chapter["title"],
                                 "dimension": sample["dimension"], "statement": sample["statement"],
                                 "evidence": sample["evidence"][:1]})
    save(SUMMARY, {key: report[key] for key in ("schema", "source_sha256", "coverage", "phase_pacing", "limitations")}
         | {"findings": examples, "total_findings": len(findings), "chapter_examples": chapter_examples})
    print(f"<script_out>跨章复核已归档：{len(observations)} 章，{len(findings)} 项跨章判断。</script_out>")
