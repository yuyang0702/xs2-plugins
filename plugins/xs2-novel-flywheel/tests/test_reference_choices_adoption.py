import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
SCRIPT = Path(__file__).resolve().parents[1]/'resources/script-library/xs2/reference_distill/reference_distill.py'
sys.path.insert(0, str(SCRIPT.parent))
from reference_choices import with_reference_choices, fingerprint


class ReferenceAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); (self.root/'learning').mkdir()
        self.data=with_reference_choices({'source':{'text_sha256':'source'},'candidates':[], 'candidates_sha256':fingerprint([]),
            'style_observations':[{'rule':'原作特色文风','transfer_guidance':'以动作与话语取舍表现本书人物的迟疑','evidence':[{'excerpt':'原作独有句子'}]}],
            'conflict_patterns':[{'name':'原作专属事件','goal':'原作某人探查禁地','evidence':[{'excerpt':'原作独有句子'}]}]})
        (self.root/'learning/candidates.json').write_text(json.dumps(self.data),encoding='utf-8')
        self.style=self.data['style_choices'][0]['choice_id'];self.conflict=self.data['conflict_choices'][0]['choice_id']

    def run_adoption(self, styles=None, conflicts=None, guidance=None, expected=0, stale=False):
        selection={'candidates_sha256':self.data['candidates_sha256'],'selected_candidate_ids':[],
                   'reference_choices_sha256':'stale' if stale else self.data['reference_choices_sha256'],
                   'selected_style_ids':styles or [],'selected_conflict_ids':conflicts or [],'reference_adaptations':guidance or {}}
        result=subprocess.run([sys.executable,str(SCRIPT),'adopt','--selection-json',json.dumps(selection)],cwd=self.root,capture_output=True)
        self.assertEqual(result.returncode,expected,result.stderr.decode(errors='replace'))
        if expected==0:
            active=json.loads((self.root/'learning/active.json').read_text(encoding='utf-8'))
            return active,json.loads((self.root/active['blueprint_path']).read_text(encoding='utf-8'))

    def test_categories_are_explicit_and_source_plot_never_enters_context(self):
        first,_=self.run_adoption(styles=[self.style])
        self.run_adoption(conflicts=[self.conflict],expected=1)
        second,blueprint=self.run_adoption(conflicts=[self.conflict],guidance={self.conflict:'本书先由旧线索触发求生行动，解决后失去资源，由代价引出下一阻碍；短篇回收主线。'})
        self.assertEqual(second['version'],first['version']+1)
        self.assertEqual(blueprint['selected_style_ids'],[self.style])
        self.assertEqual(blueprint['selected_conflict_ids'],[self.conflict])
        context=(self.root/'learning/active_context.md').read_text(encoding='utf-8')
        self.assertIn('话语取舍',context);self.assertIn('旧线索',context)
        for source in ('原作独有句子','原作某人','原作专属事件','原作特色文风'):self.assertNotIn(source,context)
        self.assertEqual(self.run_adoption()[0],second)
        self.assertEqual(self.run_adoption(styles=[self.style],conflicts=[self.conflict])[0],second)

    def test_stale_analysis_does_not_get_adopted(self):
        self.run_adoption(styles=[self.style],stale=True,expected=1)
        self.assertFalse((self.root/'learning/active.json').exists())

    def test_original_can_prepare_context_without_creating_adoption(self):
        result=subprocess.run([sys.executable,str(SCRIPT),'prepare-context','--scope','mvp'],cwd=self.root,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('原创设定',(self.root/'learning/context/mvp.md').read_text(encoding='utf-8'))
        self.assertFalse((self.root/'learning/active.json').exists())


if __name__=='__main__': unittest.main()
