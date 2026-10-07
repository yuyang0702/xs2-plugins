"""Regression checks for short-story outline adaptation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

BASE = Path(__file__).resolve().parents[1] / "resources" / "script-library" / "nvl"

def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / name / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class ShortScopeTests(unittest.TestCase):
    def run_script(self, name, data, scope):
        with tempfile.TemporaryDirectory() as directory:
            before = Path.cwd()
            try:
                os.chdir(directory)
                Path("input.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
                with patch("sys.argv", [name, "--input", "input.json", "--volume-number", "1", "--scope", scope]):
                    load(name).main()
                cached = Path("cache/no/near_term.json" if name == "no_post" else "cache/vo/volume.json")
                return json.loads(cached.read_text(encoding="utf8"))
            finally:
                os.chdir(before)

    def test_short_preserves_all_story_beats_and_terminal_choice(self):
        data = {"volume_number": 1, "is_new_volume": True, "arc_name": "测试", "chapters": [
            {"number": 1, "title": "起因", "summary": "缺水", "time_advance": "+2小时"},
            {"number": 2, "title": "终局", "summary": "净水送达，伏笔回收", "time_advance": "+72小时"}],
            "decision_points": [{"chapter": 2, "choice": "承担代价"}]}
        result = self.run_script("no_post", data, "short_full")
        self.assertEqual(len(result["chapters"]), 1)
        self.assertEqual(result["chapter_range"], {"start": 1, "end": 1})
        self.assertIn("缺水", result["chapters"][0]["summary"])
        self.assertIn("伏笔回收", result["chapters"][0]["summary"])
        self.assertEqual(result["decision_points"][0]["chapter"], 1)

    def test_serial_keeps_separate_chapters(self):
        data = {"volume_number": 1, "is_new_volume": True, "chapters": [{"number": 1}, {"number": 2}]}
        result = self.run_script("no_post", data, "serial_opening")
        self.assertEqual(result["chapters"], data["chapters"])

    def test_short_volume_keeps_three_acts_in_one_chapter(self):
        data = {"volume_number": 1, "chapter_range": {"start": 1, "end": 5},
                "acts": {"establish": {"chapters": "1", "content": "起因"}, "resolve": {"chapters": "5", "content": "结局"}}}
        result = self.run_script("vo_post", data, "short_full")
        self.assertEqual(result["chapter_range"], {"start": 1, "end": 1})
        self.assertEqual(result["acts"]["resolve"]["content"], "结局")
        self.assertEqual(result["acts"]["resolve"]["chapters"], "第1章内的阶段")

if __name__ == "__main__":
    unittest.main()
