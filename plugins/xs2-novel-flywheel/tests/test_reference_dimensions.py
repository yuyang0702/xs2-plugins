import json
from copy import deepcopy

import pytest

from test_reference_distill import run, PLUGIN_ROOT


def split_source(root, raw, source_mode="auto"):
    source = root / "references/source.txt"
    source.parent.mkdir()
    source.write_text(raw, encoding="utf-8")
    result = run(root, "split", "--input", "references/source.txt", "--window", "800", "--overlap", "0",
                 "--source-mode", source_mode)
    assert result.returncode == 0, result.stderr
    return read_json(root, "learning/cache/windows.json")


def read_json(root, path):
    return json.loads((root / path).read_text(encoding="utf-8"))


def normalize(root, window, candidates):
    path = "learning/cache/analyst.raw.json"
    (root / path).write_text(json.dumps({
        "window_id": window["window_id"], "source_sha256": window["source_sha256"],
        "candidates": candidates,
    }, ensure_ascii=False), encoding="utf-8")
    return run(root, "normalize", "--input", path, "--window-id", window["window_id"])


def example(window, **fields):
    return {
        "mechanism": "把压力落到可判断的细节",
        "transfer_guidance": "按本书人物的选择与代价重新安排细节",
        "constraints": ["限于本书人物此刻能感知的内容"],
        "scopes": ["mvp"], "confidence": "medium",
        "evidence": [{"window_id": window["window_id"], "evidence_id": window["evidence_catalog"][0]["evidence_id"],
                      "reason": "压力通过新的动作变得可观察"}],
        **fields,
    }


def test_distinct_dimensions_survive_merge_and_keep_exact_layout_evidence(tmp_path):
    raw = "绣工把账本推回柜上。\n\n掌柜把手收了回去。"
    window = split_source(tmp_path, raw)["windows"][0]
    choices = [
        example(window, dimension=dimension, scopes=[scope])
        for dimension, scope in (
            ("structure", "outline"), ("voice", "mvp"), ("topic", "novel-advisor"),
            ("case", "mvp"), ("pacing", "mvp"), ("layout", "export"), ("expression", "mvp"),
        )
    ]
    choices[-2]["evidence"][0]["end_evidence_id"] = window["evidence_catalog"][1]["evidence_id"]
    result = normalize(tmp_path, window, choices)
    assert result.returncode == 0, result.stderr
    merged = run(tmp_path, "merge")
    assert merged.returncode == 0, merged.stderr
    document = read_json(tmp_path, "learning/candidates.json")
    candidates = {item["dimension"]: item for item in document["candidates"]}
    assert set(candidates) == {"structure", "voice", "topic", "case", "pacing", "layout", "expression"}
    assert len({item["candidate_id"] for item in candidates.values()}) == 7
    proof = candidates["layout"]["evidence"][0]
    assert proof["excerpt"] == raw
    assert raw[proof["source_start"]:proof["source_end"]] == proof["excerpt"]
    summary = read_json(tmp_path, "learning/dna/bundle.json")
    assert {item["dimension"] for item in summary["dimension_examples"]} == set(candidates)


def test_unknown_dimension_is_rejected_at_the_window_gate(tmp_path):
    window = split_source(tmp_path, "绣工把账本推回柜上。")["windows"][0]
    result = normalize(tmp_path, window, [example(window, dimension="invented")])
    assert result.returncode != 0
    assert "dimension" in result.stderr
    from jsonschema import validate, ValidationError
    workflow = read_json(PLUGIN_ROOT, "resources/workflows/reference-distillation/definition.json")
    node = next(item for item in workflow["nodes"] if item["id"] == "agent_distill_window")
    schema = node["node_params"]["json_output_schema"]
    response = {"window_id": window["window_id"], "candidates": [example(window)]}
    validate(response, schema)
    response["candidates"][0]["dimension"] = "invented"
    with pytest.raises(ValidationError):
        validate(response, schema)


def test_dimension_supplies_workflow_scope_without_model_guessing(tmp_path):
    window = split_source(tmp_path, '绣工把账本推回柜上。')['windows'][0]
    item = example(window, dimension='topic')
    del item['scopes']
    result = normalize(tmp_path, window, [item])
    assert result.returncode == 0, result.stderr
    result = run(tmp_path, 'merge')
    assert result.returncode == 0, result.stderr
    assert read_json(tmp_path, 'learning/candidates.json')['candidates'][0]['scopes'] == ['novel-advisor']


def sample(window, *, skip_middle=False):
    def anchor(excerpt):
        return {"window_id": window["window_id"], "excerpt": excerpt}

    turns = [
        {"speaker": "掌柜", "text": "明天再来。账还没对完。", "intent": "推迟结算",
         "evidence": anchor("掌柜说：“明天再来。账还没对完。”"),
         "trigger": "对方把账本推过来", "trigger_evidence": anchor("绣工把账本推到柜上。"),
         "attribution": "observed", "attribution_evidence": anchor("掌柜说：“明天再来。")},
        {"speaker": "绣工", "text": "明天几时？", "intent": "追问时间",
         "evidence": anchor("“明天几时？”"), "attribution": "tentative",
         "reaction": "对方重新查看日期", "reaction_evidence": anchor("掌柜翻开账本查日期。")},
    ]
    if not skip_middle:
        turns.insert(1, {"speaker": "掌柜", "text": "别等了。", "intent": "试图结束交谈", "evidence": anchor("“别等了。”")})
    return {"scene_type": "结算谈判", "relationship": "两人围绕结算时间发生拉扯",
            "turns": turns, "transferable_moves": ["把笼统推迟追问到可执行的时间"],
            "limits": ["归属有疑问时只作为阅读分析"]}


@pytest.mark.parametrize("skip_middle", [False, True])
def test_dialogue_quotes_and_continuous_replies_can_cross_a_window_edge(tmp_path, skip_middle):
    raw = "铺" * 775 + "\n绣工把账本推到柜上。\n掌柜说：“明天再来。账还没对完。”\n掌柜又说：“别等了。”\n“明天几时？”\n掌柜翻开账本查日期。"
    manifest = split_source(tmp_path, raw)
    window = manifest["windows"][0]
    assert window["source_end"] == raw.index("账还没对完。")
    choice = example(window, dimension="voice", dialogue_samples=[sample(window, skip_middle=skip_middle)])
    result = normalize(tmp_path, window, [choice])
    if skip_middle:
        assert result.returncode != 0 and "中间回应" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    checked = read_json(tmp_path, "learning/cache/window-0001.validated.json")
    dialogue = checked["candidates"][0]["dialogue_samples"][0]
    assert dialogue["status"] == "context_tentative"
    assert [turn["text"] for turn in dialogue["turns"]] == ["明天再来。账还没对完。", "别等了。", "明天几时？"]
    assert dialogue["turns"][0]["trigger"] == "对方把账本推过来"
    assert dialogue["turns"][-1]["reaction"] == "对方重新查看日期"
    proof = dialogue["turns"][-1]["reaction_evidence"]
    assert raw[proof["source_start"]:proof["source_end"]] == "掌柜翻开账本查日期。"


def test_unverified_reaction_excerpt_is_rejected(tmp_path):
    raw = "绣工把账本推到柜上。\n掌柜说：“明天再来。账还没对完。”\n掌柜又说：“别等了。”\n“明天几时？”\n掌柜翻开账本查日期。"
    window = split_source(tmp_path, raw)["windows"][0]
    dialogue = sample(window)
    dialogue["turns"][-1]["reaction_evidence"]["excerpt"] = "掌柜答应立即结钱。"
    result = normalize(tmp_path, window, [example(window, dimension="voice", dialogue_samples=[dialogue])])
    assert result.returncode != 0 and "证据摘录" in result.stderr


def test_dialogue_may_not_join_separate_source_units(tmp_path):
    raw = ("绣工把账本推到柜上。\n掌柜说：“明天再来。账还没对完。”\n===== SOURCE FILE 2 =====\n"
           "掌柜又说：“别等了。”\n“明天几时？”\n掌柜翻开账本查日期。")
    window = split_source(tmp_path, raw)["windows"][0]
    result = normalize(tmp_path, window, [example(window, dimension="voice", dialogue_samples=[sample(window)])])
    assert result.returncode != 0 and "来源单元" in result.stderr


def test_tentative_dialogue_does_not_block_selecting_its_abstract_writing(tmp_path):
    from test_dialogue_learning import review_fixture
    adoption, selections, *_ = review_fixture(tmp_path)
    item = selections[0]
    verified = deepcopy(item["candidate"]["dialogue_samples"][0])
    item["candidate"]["dialogue_samples"][0].update(status="context_tentative")
    item["candidate"]["dialogue_samples"][0]["turns"][-1]["attribution"] = "tentative"
    item["library"]["profile"] = {
        "dialogue_samples": [{**verified, "candidate_id": item["candidate_id"]}],
    }
    assert adoption.source_samples(item) == []


@pytest.mark.parametrize(("source_mode", "opening", "dimension", "expected"), [
    ("short_full", "绣工把账本推到柜上。", "layout", True),
    ("short_full", "第一章 回城", "layout", False),
    ("serial_chapters", "绣工把账本推到柜上。", "layout", False),
    ("short_full", "绣工把账本推到柜上。", "voice", False),
])
def test_body_only_export_requires_layout_evidence_of_a_complete_short_opening(
    tmp_path, source_mode, opening, dimension, expected,
):
    window = split_source(tmp_path, opening + "\n\n掌柜把手收了回去。", source_mode)["windows"][0]
    choice = example(window, dimension=dimension, export_layout="short_body_only",
                     scopes=["export"] if dimension == "layout" else ["mvp"])
    result = normalize(tmp_path, window, [choice])
    if expected:
        assert result.returncode == 0, result.stderr
        checked = read_json(tmp_path, "learning/cache/window-0001.validated.json")
        assert checked["candidates"][0]["export_layout"] == "short_body_only"
    else:
        assert result.returncode != 0 and "export_layout" in result.stderr
