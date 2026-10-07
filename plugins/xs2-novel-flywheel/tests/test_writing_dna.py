import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/reference_distill/reference_distill.py'
spec = importlib.util.spec_from_file_location('distill_under_test', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WritingDNATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        Path('references').mkdir()
        Path('references/source.txt').write_text('修理工先发现供水减少。此前松动的接头终于漏水。他堵住裂口，却耗尽备用材料。', encoding='utf-8')
        module.split(argparse.Namespace(input='references/source.txt', window=4200, overlap=400, source_mode='short_full'))

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def payload(self):
        manifest, raw = module.manifest()
        proof = {'window_id': 'window-0001', 'source_start': 0, 'source_end': 12, 'excerpt': raw[:12], 'reason': '开局先建立明确资源目标'}
        return {'window_id': 'window-0001', 'source_sha256': manifest['source']['text_sha256'], 'candidates': [],
                'style_observations': [{'layer': 'structure', 'rule': '行动与资源消耗形成递进', 'transfer_guidance': '让局部解决改变后续资源条件', 'limits': ['仅单篇样本'], 'confidence': 'medium', 'evidence': [proof]}],
                'conflict_patterns': [{'name': '修复带来资源压力', **{key: '抽象条件' for key in ('goal', 'foreshadowing', 'obstacle', 'resolution', 'cost', 'next_obstacle', 'causal_link', 'payoff')}, 'application_scope': 'short_full', 'confidence': 'medium', 'evidence': [proof]}]}

    def test_real_upstream_instructions_stats_and_evidence_are_used(self):
        instruction = Path('learning/dna/instructions.md').read_text(encoding='utf-8')
        self.assertIn('蒸馏的六个层次', instruction)
        self.assertIn('小说工作流适配约定', instruction)
        self.assertEqual(module.load('learning/dna/metadata.json')['source_mode'], 'short_full')
        payload = self.payload()
        module.save('learning/cache/window-0001.raw.json', payload)
        module.normalize(argparse.Namespace(input='learning/cache/window-0001.raw.json', window_id='window-0001'))
        module.merge(argparse.Namespace())
        result = module.load('learning/candidates.json')
        self.assertEqual(len(result['conflict_patterns']), 1)
        self.assertEqual(len(result['style_observations']), 1)
        self.assertFalse(Path('learning/active.json').exists())
        payload['style_observations'][0]['evidence'][0]['excerpt'] = '完全不存在的原文证据'
        module.save('learning/cache/window-0001.raw.json', payload)
        with self.assertRaises(ValueError):
            module.normalize(argparse.Namespace(input='learning/cache/window-0001.raw.json', window_id='window-0001'))

    def test_summary_source_guard_and_all_five_documents(self):
        module.save('learning/cache/window-0001.raw.json', self.payload())
        module.normalize(argparse.Namespace(input='learning/cache/window-0001.raw.json', window_id='window-0001'))
        module.merge(argparse.Namespace())
        docs = {name: '# 样本分析\n\n' + '这是针对当前样本的可观察规则；未覆盖内容不作推断。' * 3 for name in module.writing_dna.DOCUMENTS}
        module.save('learning/dna/summary.raw.json', {'source_sha256': 'wrong', 'documents': docs})
        with self.assertRaises(ValueError):
            module.writing_dna.finalize(argparse.Namespace(input='learning/dna/summary.raw.json'), module.load, module.save, module.digest)
        self.assertFalse(Path('learning/reference_profile.md').exists())
        before = module.load('learning/candidates.json')['candidates_sha256']
        module.save('learning/dna/summary.raw.json', {'source_sha256': self.payload()['source_sha256'], 'documents': docs})
        module.writing_dna.finalize(argparse.Namespace(input='learning/dna/summary.raw.json'), module.load, module.save, module.digest)
        self.assertEqual(module.load('learning/candidates.json')['candidates_sha256'], before)
        self.assertTrue(all(Path('learning/dna', name).is_file() for name in docs))

    def test_evidence_ids_preserve_font_characters_and_reject_fabricated_ids(self):
        Path('references/source.txt').write_text('她\ue123着空桶，停在门边。她没有求他，只把桶\ue456了一点。', encoding='utf-8')
        module.split(argparse.Namespace(input='references/source.txt', window=4200, overlap=400, source_mode='short_full'))
        manifest, raw = module.manifest()
        window = manifest['windows'][0]
        proof = {'window_id': window['window_id'], 'evidence_id': window['evidence_catalog'][0]['evidence_id'], 'reason': '动作呈现不愿恳求的情绪'}
        start, end, quote, _ = module.evidence_position(proof, window, raw)
        self.assertEqual(quote, raw[start:end])
        self.assertIn('\ue123', quote)
        proof['evidence_id'] = 'window-0002-e0001'
        with self.assertRaises(ValueError): module.evidence_position(proof, window, raw)
        proof['evidence_id'] = window['evidence_catalog'][0]['evidence_id']
        window['evidence_catalog'][0]['excerpt'] = '杜撰摘录'
        with self.assertRaises(ValueError): module.evidence_position(proof, window, raw)

    def test_misplaced_known_application_scope_is_reclassified_not_invented(self):
        data, raw = module.manifest()
        proof = {'window_id':'window-0001','evidence_id':data['windows'][0]['evidence_catalog'][0]['evidence_id'],'reason':'原文有行动与代价'}
        item={'mechanism':'让选择改变后续资源条件','transfer_guidance':'局部解决须留下新的限制','constraints':[], 'scopes':['mvp','serial_chapter'], 'confidence':'medium','layer':'character','evidence':[proof]}
        payload={'window_id':'window-0001','source_sha256':data['source']['text_sha256'],'candidates':[item]}
        module.save('learning/cache/window-0001.raw.json',payload)
        module.normalize(argparse.Namespace(input='learning/cache/window-0001.raw.json',window_id='window-0001'))
        candidate=module.load('learning/cache/window-0001.validated.json')['candidates'][0]
        self.assertEqual(candidate['scopes'],['mvp'])
        self.assertEqual(candidate['application_scope'],['serial_chapter'])
        item['scopes']=['mvp','invented-stage']
        module.save('learning/cache/window-0001.raw.json',payload)
        with self.assertRaises(ValueError): module.normalize(argparse.Namespace(input='learning/cache/window-0001.raw.json',window_id='window-0001'))


if __name__ == '__main__':
    unittest.main()
