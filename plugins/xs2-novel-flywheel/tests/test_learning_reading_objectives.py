import argparse
import copy
import json
from test_reference_distill import run,_load_module
from test_reading_contract import definition,module as reading


def source_candidates(root):
    source=root/'references/source.txt';source.parent.mkdir(parents=True)
    source.write_text('她发现列车表上的名字消失了。她决定在下一站问清楚。结尾她终于收到答复。',encoding='utf8')
    result=run(root,'split','--input','references/source.txt','--source-mode','short_full','--learning-direction','zhihu_short')
    assert result.returncode==0,result.stderr
    window=json.loads((root/'learning/cache/windows.json').read_text(encoding='utf8'))['windows'][0]
    item={'mechanism':'从异常形成阅读期待','transfer_guidance':'让本书异常改变人物接下来的选择。','constraints':['不复制样本事实。'],
        'scopes':['story-plan','outline','mvp','polish'],'confidence':'high','reading_objectives':[definition()],
        'evidence':[{'window_id':window['window_id'],'source_start':0,'source_end':14,'excerpt':window['text'][:14],'reason':'开篇建立疑问。'}]}
    raw={'window_id':window['window_id'],'source_sha256':window['source_sha256'],'candidates':[item]}
    (root/'learning/cache/raw.json').write_text(json.dumps(raw,ensure_ascii=False),encoding='utf8')
    return raw


def test_evidence_checked_goals_survive_selection_and_stage_context(tmp_path):
    source_candidates(tmp_path)
    for argv in [('normalize','--input','learning/cache/raw.json','--window-id','window-0001'),('merge',)]:
        result=run(tmp_path,*argv);assert result.returncode==0,result.stderr
    data=json.loads((tmp_path/'learning/candidates.json').read_text(encoding='utf8'));item=data['candidates'][0]
    assert item['reading_objectives']==[definition()]
    assert reading().for_book(tmp_path) is None
    selection={'candidates_sha256':data['candidates_sha256'],'selected_candidate_ids':[item['candidate_id']]}
    (tmp_path/'learning/selection.json').write_text(json.dumps(selection),encoding='utf8')
    result=run(tmp_path,'adopt');assert result.returncode==0,result.stderr
    goals=reading().for_book(tmp_path);assert goals['objectives'][0]['dimension']=='opening_promise'
    text=(tmp_path/'learning/active_context.md').read_text(encoding='utf8')
    assert goals['objectives'][0]['id'] in text and '本书已采用阅读目标' in text
    assert '她发现列车表上的名字消失了' not in text
    assert '知乎' in (tmp_path/'learning/dna/instructions.md').read_text(encoding='utf8')


def test_goal_text_cannot_copy_source_or_smuggle_unknown_instructions(tmp_path):
    raw=source_candidates(tmp_path)
    raw['candidates'][0]['reading_objectives'][0]['intent']='她发现列车表上的名字消失了。她决定在下一站问清楚。'
    (tmp_path/'learning/cache/raw.json').write_text(json.dumps(raw,ensure_ascii=False),encoding='utf8')
    result=run(tmp_path,'normalize','--input','learning/cache/raw.json','--window-id','window-0001')
    assert result.returncode!=0


def test_different_reading_goals_are_not_lost_in_lexical_merge():
    m=_load_module();base={'candidate_id':'a','mechanism':'异常改变后续选择','transfer_guidance':'让异常改变后续选择','evidence':[],
        'reading_objectives':[definition()]}
    other=copy.deepcopy(base);other['candidate_id']='b';other['reading_objectives'][0]['dimension']='voice'
    assert len(m._merge_similar([base,other]))==2
