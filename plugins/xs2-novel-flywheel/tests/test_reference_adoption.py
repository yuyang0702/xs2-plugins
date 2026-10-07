import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/reference_distill/reference_distill.py'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def candidates(self, ids, source='first', guidance='original'):
        items = [{'candidate_id': item, 'mechanism': item, 'transfer_guidance': guidance, 'scopes': ['polish']} for item in ids]
        self.data = {'source': {'text_sha256': source}, 'candidates': items, 'candidates_sha256': digest(items)}
        folder = self.root / 'learning'
        folder.mkdir(exist_ok=True)
        (folder / 'candidates.json').write_text(json.dumps(self.data), encoding='utf-8')

    def adopt(self, ids, succeeds=True):
        selection = {'candidates_sha256': self.data['candidates_sha256'], 'selected_candidate_ids': ids}
        result = subprocess.run([sys.executable, str(SCRIPT), 'adopt', '--selection-json', json.dumps(selection)], cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stderr)
        active = json.loads((self.root / 'learning/active.json').read_text())
        return active, json.loads((self.root / active['blueprint_path']).read_text())

    def test_empty_and_subset_do_not_remove_or_create_versions(self):
        self.candidates(['one', 'two'])
        first, _ = self.adopt(['one', 'two'])
        self.assertEqual(self.adopt([])[0], first)
        self.assertEqual(self.adopt(['two'])[0], first)
        self.assertEqual(len(list((self.root / 'learning/blueprints').glob('*.json'))), 1)

    def test_new_source_adds_without_replacing_old_definition(self):
        self.candidates(['one'])
        _, first = self.adopt(['one'])
        self.candidates(['two'], source='second')
        _, second = self.adopt(['one', 'two'])
        self.assertEqual(second['selected_candidate_ids'], ['one', 'two'])
        self.assertEqual(second['mechanisms'][0], first['mechanisms'][0])
        self.assertEqual({item['text_sha256'] for item in second['sources']}, {'first', 'second'})
        self.candidates(['one', 'two'], guidance='changed')
        unchanged, third = self.adopt(['one', 'two'])
        self.assertEqual(unchanged['version'], 2)
        self.assertEqual(third, second)

    def test_corrupt_active_or_unknown_new_id_never_overwrites(self):
        self.candidates(['one'])
        first, _ = self.adopt(['one'])
        self.adopt(['unknown'], succeeds=False)
        self.assertEqual(json.loads((self.root / 'learning/active.json').read_text()), first)
        target = self.root / first['blueprint_path']
        target.write_text('{}')
        self.adopt([], succeeds=False)
        self.assertEqual(json.loads((self.root / 'learning/active.json').read_text()), first)

    def test_original_without_adoption_is_supported(self):
        self.candidates([])
        active, blueprint = self.adopt([])
        self.assertEqual(active['version'], 1)
        self.assertEqual(blueprint['mechanisms'], [])
