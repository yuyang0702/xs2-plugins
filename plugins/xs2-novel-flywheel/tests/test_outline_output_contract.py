import json
from pathlib import Path


def test_outline_declares_current_turn_structured_output_contract():
    definition = json.loads((Path(__file__).parents[1] / "resources/workflows/outline/definition.json").read_text(encoding="utf-8"))
    agents = [node for node in definition["nodes"] if node["node_type"] == "agent"]
    assert {node["id"] for node in agents} == {"agent_vo", "agent_no", "agent_rolling_plan", "agent_rolling_review"}
    for node in agents:
        assert node["auto_flow"] is True
        assert node["enable_complete_node_task"] is False
        assert node["require_non_empty_output"] is True
        assert node["node_params"]["output_selection"] == "completion_tool_message"
        assert node["node_params"]["json_repair_policy"] == "validate_only"
        assert node["node_params"]["json_output_schema"]["type"] == "object"
        assert not node.get("model_override")


def test_outline_schemas_reject_null_and_keep_terminal_contract():
    import pytest
    from jsonschema import Draft202012Validator, ValidationError
    definition = json.loads((Path(__file__).parents[1] / "resources/workflows/outline/definition.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in definition["nodes"]}
    no = Draft202012Validator(nodes["agent_no"]["node_params"]["json_output_schema"])
    no.validate({"chapters": []})
    no.validate({"volume_number": 1, "is_new_volume": True, "chapters": [{"number": 1, "title": "title", "summary": "summary"}]})
    for invalid in [{"volume_number": 1, "chapters": None}, {"chapters": [None]}, {"volume_number": 1, "is_new_volume": True, "chapters": [{"number": None}]}]:
        with pytest.raises(ValidationError): no.validate(invalid)
    vo = Draft202012Validator(nodes["agent_vo"]["node_params"]["json_output_schema"])
    with pytest.raises(ValidationError): vo.validate({"volume_number": None,"title": None,"chapter_range": None})



def test_postprocessors_validate_before_publishing(tmp_path):
    import subprocess
    import sys
    import pytest
    root = Path(__file__).parents[1]
    invalid_cases = [('no', {"volume_number": 1, "chapters": None}),
                     ('no', {"volume_number": 2, "is_new_volume": True, "chapters": [{"number": 1,"title": "t","summary": "s"}]}),
                     ('no', {"volume_number": 1, "is_new_volume": True, "chapters": [{"number": 2,"title": "t","summary": "s"},{"number": 1,"title": "t","summary": "s"}]}),
                     ('vo', {"volume_number": None, "title": None, "chapter_range": None}),
                     ('vo', {"volume_number": 2, "title": "t", "chapter_range": {"start": 1, "end": 1}}),
                     ('vo', {"volume_number": 1, "title": "t", "chapter_range": {"start": 3, "end": 1}})]
    for index, (kind, payload) in enumerate(invalid_cases):
        workspace = tmp_path / str(index)
        workspace.mkdir()
        source = workspace / 'input.json'
        source.write_text(json.dumps(payload), encoding='utf-8')
        outline = workspace / 'outline' / ('near_term_outline.md' if kind == 'no' else 'volume_outline.md')
        outline.parent.mkdir()
        outline.write_text('original outline', encoding='utf-8')
        script = root / f'resources/script-library/nvl/{kind}_post/{kind}_post.py'
        result = subprocess.run([sys.executable, str(script), '--input', str(source), '--volume-number', '1'], cwd=workspace, capture_output=True)
        assert result.returncode != 0, (kind, payload)
        assert outline.read_text(encoding='utf-8') == 'original outline'
        assert not (workspace / 'cache').exists()


def test_no_terminal_output_skips_publication(tmp_path):
    import subprocess
    import sys
    source = tmp_path / 'input.json'
    source.write_text('{"chapters": []}', encoding='utf-8')
    script = Path(__file__).parents[1] / 'resources/script-library/nvl/no_post/no_post.py'
    result = subprocess.run([sys.executable, str(script), '--input', str(source), '--volume-number', '1'], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'outline').exists()
    assert not (tmp_path / 'cache').exists()



def test_no_rejects_out_of_volume_and_duplicate_append_before_write(tmp_path):
    import subprocess
    import sys
    for label, number, is_new, prior in [('outside', 3, True, None), ('duplicate', 1, False, {"volume_number": 1,"chapters": [{"number": 1}]})]:
        workspace = tmp_path / label
        (workspace / 'cache/vo').mkdir(parents=True)
        volume = workspace / 'cache/vo/volume.json'
        volume.write_text('{"volume_number": 1,"chapter_range": {"start": 1,"end": 2}}',encoding='utf-8')
        if prior:
            (workspace / 'cache/no').mkdir()
            (workspace / 'cache/no/near_term.json').write_text(json.dumps(prior),encoding='utf-8')
        (workspace / 'outline').mkdir()
        target = workspace / 'outline/near_term_outline.md'
        target.write_text('original',encoding='utf-8')
        source = workspace / 'input.json'
        source.write_text(json.dumps({"volume_number": 1,"is_new_volume": is_new,"chapters": [{"number": number,"title": "t","summary": "s"}]}),encoding='utf-8')
        before = {str(path.relative_to(workspace)): path.read_bytes() for path in workspace.rglob('*') if path.is_file()}
        script = Path(__file__).parents[1] / 'resources/script-library/nvl/no_post/no_post.py'
        result = subprocess.run([sys.executable,str(script),'--input',str(source),'--volume-number','1'],cwd=workspace,capture_output=True)
        assert result.returncode != 0, result.stdout
        assert before == {str(path.relative_to(workspace)): path.read_bytes() for path in workspace.rglob('*') if path.is_file()}
