"""Novel adapter for the vendored writing-dna-skill instructions and templates.

Only source analysis lives here. Adoption still uses reference_distill's explicit
selection and versioned, abstract generation context.
"""
from collections import Counter
from pathlib import Path
import json
import re

UPSTREAM_DOCUMENTS = ("语言DNA.md", "文章结构模板.md", "写作视角与认知框架.md", "视觉风格指南.md", "Writing-DNA.md")
DOCUMENTS = (*UPSTREAM_DOCUMENTS, "人物写法.md")
LAYERS = {"language", "structure", "narrative_lens", "dialogue", "imagery", "theme", "character"}


def prepare(raw, source, mode, save):
    vendor = Path(__file__).parent / "vendor" / "writing-dna-skill"
    skill = (vendor / "SKILL.md").read_text(encoding="utf-8-sig")
    templates = "\n\n".join("# 模板：" + name + "\n" + (vendor / "templates" / "author-corpus" / "zh" / name).read_text(encoding="utf-8-sig") for name in UPSTREAM_DOCUMENTS)
    templates += "\n\n# 小说扩展：人物写法.md\n分析人物自己的欲望与顾虑、性格矛盾、压力下的选择与代价、情绪的行为表现、对话声线、关系变化和配角的独立目标。每项给出窗口依据、置信度、迁移建议与未见环节；不复制原作人物。来源若工具人化也如实指出，不作为推荐规则。"
    adapter = (Path(__file__).parent / "NOVEL_ADAPTER.md").read_text(encoding="utf-8-sig")
    save("learning/dna/instructions.md", skill + "\n\n" + adapter)
    save("learning/dna/templates.md", templates)
    marker = re.compile(r"^===== SOURCE (?:CHAPTER|FILE).*?=====$", re.M)
    markers = list(marker.finditer(raw))
    units = [{"title": match.group(0).strip("= "), "source_start": match.end(), "source_end": markers[i + 1].start() if i + 1 < len(markers) else len(raw)} for i, match in enumerate(markers)]
    if not units:
        units = [{"title": "导入文本（完整性待核实）", "source_start": 0, "source_end": len(raw)}]
    if mode not in {"auto", "short_full", "serial_chapters"}:
        raise ValueError("语料类型必须为 auto、short_full 或 serial_chapters")
    inferred = "serial_chapters" if mode == "auto" and "===== SOURCE CHAPTER" in raw else mode
    # Exclude import wrappers from language measurements, but keep source offsets.
    body = marker.sub("", raw)
    sentences = [re.sub(r"\s", "", s) for s in re.split(r"[。！？!?]+", body) if s.strip()]
    paragraphs = [re.sub(r"\s", "", p) for p in body.splitlines() if p.strip()]
    lengths = [len(s) for s in sentences]
    punct = {char: body.count(char) for char in "，。！？；：—（）“”「」…"}
    terms = Counter()
    for run in re.findall(r"[\u4e00-\u9fff]+", body):
        terms.update(run[i:i+2] for i in range(len(run)-1))
    stats = {"characters": len(re.sub(r"\s", "", body)), "sentence_count": len(lengths),
             "mean_sentence_chars": round(sum(lengths)/len(lengths), 2) if lengths else 0,
             "short_sentence_ratio": round(sum(n <= 15 for n in lengths)/len(lengths), 3) if lengths else 0,
             "long_sentence_ratio": round(sum(n >= 50 for n in lengths)/len(lengths), 3) if lengths else 0,
             "mean_paragraph_chars": round(sum(map(len, paragraphs))/len(paragraphs), 2) if paragraphs else 0,
             "punctuation_counts": punct, "frequent_character_pairs": terms.most_common(30),
             "font_obfuscated_chars": len(re.findall(r"[\uE000-\uF8FF]", body)),
             "method": "按句末标点划句；按非空行划段；高频字串不是词性分词结果。"}
    metadata = {"source": source, "source_mode": inferred, "source_units": units,
                "coverage_note": "只分析本次导入样本；章节样本不能代表完整长篇结局或作者全部作品。",
                "statistics": stats}
    save("learning/dna/metadata.json", metadata)


def checked_extras(payload, window, raw, text_field, strings, evidence_position):
    def evidence(item):
        values = item.get("evidence")
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise ValueError("风格观察与冲突链均需要 1～8 处原文证据")
        output = []
        for proof in values:
            start, end, quote, _ = evidence_position(proof, window, raw)
            output.append({"window_id": window["window_id"], "source_start": start, "source_end": end,
                           "excerpt": quote, "reason": text_field(proof, "reason")})
        return output
    def values(key, limit):
        items = payload.get(key, [])
        if not isinstance(items, list) or len(items) > limit or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"{key} 必须为至多 {limit} 项的对象数组")
        return items
    observations = []
    for item in values("style_observations", 12):
        if item.get("layer") not in LAYERS or item.get("confidence") not in {"high", "medium", "low"}:
            raise ValueError("风格观察的层次或置信度无效")
        observations.append({"layer": item["layer"], "rule": text_field(item, "rule"),
                             "transfer_guidance": text_field(item, "transfer_guidance"),
                             "limits": strings(item, "limits"), "confidence": item["confidence"],
                             "evidence": evidence(item)})
    patterns = []
    for item in values("conflict_patterns", 8):
        fields = {key: text_field(item, key) for key in ("name", "goal", "foreshadowing", "obstacle", "resolution", "cost", "next_obstacle", "causal_link", "payoff")}
        if item.get("application_scope") not in {"short_full", "serial_opening", "serial_chapter", "serial_arc", "general"}:
            raise ValueError("冲突链的篇幅范围无效")
        if item.get("confidence") not in {"high", "medium", "low"}:
            raise ValueError("冲突链的置信度无效")
        patterns.append({**fields, "application_scope": item["application_scope"],
                         "confidence": item["confidence"], "evidence": evidence(item)})
    return observations, patterns


def bundle(data, candidates, observations, patterns, load, save):
    metadata = load("learning/dna/metadata.json")
    # Every window is analyzed and the full checked results remain in candidates.
    # Global synthesis uses bounded representatives instead of overflowing a
    # model context on a long book. Preserve the counts and sampling boundary.
    ordered = sorted(observations, key=lambda item: item.get("confidence") != "high")
    selected = []
    layer_counts = Counter()
    for item in ordered:
        if layer_counts[item["layer"]] < 6 and not any(item["rule"] == old["rule"] for old in selected):
            selected.append({**item, "evidence": item["evidence"][:2]})
            layer_counts[item["layer"]] += 1
    selected_patterns = []
    for item in sorted(patterns, key=lambda item: item.get("confidence") != "high"):
        if len(selected_patterns) < 12 and not any(item["name"] == old["name"] for old in selected_patterns):
            selected_patterns.append({**item, "evidence": item["evidence"][:2]})
    # Whole records are kept, never truncated in the middle of JSON or evidence.
    budget = 48000
    def bounded(items):
        nonlocal budget
        result = []
        for item in items:
            size = len(json.dumps(item, ensure_ascii=False))
            if size <= budget:
                result.append(item)
                budget -= size
        return result
    selected_patterns = bounded(selected_patterns)
    selected = bounded(selected)
    result = {**metadata, "covered_window_ids": data["covered_window_ids"],
              "style_observations": selected, "conflict_patterns": selected_patterns,
              "analysis_counts": {"all_observations": len(observations), "all_conflicts": len(patterns),
                                  "summary_observations": len(selected), "summary_conflicts": len(selected_patterns)},
              "summary_scope": "各窗口完整分析后，从各层抽取高置信代表进行总览；全部证据保存在候选档案。",
              "candidate_names": [item["mechanism"] for item in candidates[:80]]}
    save("learning/dna/bundle.json", result)


def finalize(args, load, save, digest):
    analysis = load(args.input)
    packet = load("learning/dna/bundle.json")
    if not isinstance(analysis, dict) or analysis.get("source_sha256") != packet["source"]["text_sha256"]:
        raise ValueError("风格汇总的来源哈希不一致")
    documents = analysis.get("documents")
    if not isinstance(documents, dict) or set(documents) != set(DOCUMENTS):
        raise ValueError("风格汇总必须包含五份上游文档和人物写法小说扩展")
    for name, text in documents.items():
        if not isinstance(text, str) or not 40 <= len(text.strip()) <= 16000 or re.search(r"待填写|TODO|Lorem ipsum", text, re.I):
            raise ValueError(f"{name} 内容为空、不完整或超出长度限制")
    # All validation precedes writes. Conflicts remain the evidence-checked window
    # results; the summarizer cannot invent new chains or alter candidate selection.
    limits = ["仅适用于本次导入的样本；未覆盖部分不能推断。", "分析结果供阅读与兼容判断，未经选择的风格不进入正文规则。"]
    if packet["statistics"].get("font_obfuscated_chars"):
        limits.append("来源含特殊字体编码，词汇与细微语感结论置信度受限；未自行猜测还原字符。")
    profile = {"schema": "xs2.reference.dna.v1", "source_sha256": analysis["source_sha256"],
               "upstream": load("learning/dna/upstream.json"), "source_mode": packet["source_mode"],
               "documents": documents, "limitations": limits,
               "statistics": packet["statistics"], "conflict_count": len(packet["conflict_patterns"])}
    profile["analysis_sha256"] = digest(profile)
    for name, text in documents.items():
        save("learning/dna/" + name, text)
    overview = "# 参考样本风格分析\n\n" + "\n".join("- " + item for item in limits) + "\n\n" + documents["Writing-DNA.md"]
    save("learning/reference_profile.md", overview)
    save("learning/dna/profile.json", profile)
    # The existing candidates contract and IDs are deliberately left unchanged.
    print(f"<script_out>Writing DNA 分析完成：五份上游风格文档、人物写法扩展、{len(packet['conflict_patterns'])} 条有证据的冲突链。尚未自动采用。</script_out>")
