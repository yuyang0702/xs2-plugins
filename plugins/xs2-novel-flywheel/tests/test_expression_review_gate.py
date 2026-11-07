import copy
import pytest
from test_length_quality import quality, write


def report(priority='medium'):
    return {'verdict': 'pass', 'continue_reading_score': 95, 'issues': [],
            'fact_review': {'verdict': 'pass', 'summary': '情节和金额成立'},
            'expression_review': {'verdict': 'revise', 'summary': '重复解释使交谈停住',
                'issues': [{'location': '改署名交谈', 'priority': priority,
                            'excerpts': ['她不再等他认错。', '她等的已经不是一句认错。'],
                            'impact': '后段再次解释已经成立的决定，没有新反应。',
                            'goal': '保留决定，合并重复解释。'}]}}


def test_fact_pass_and_high_score_cannot_hide_grounded_expression_problem(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '她不再等他认错。\n\n她等的已经不是一句认错。')
    source = report(); before = copy.deepcopy(source)
    gated = quality().gate_report(tmp_path, '0001', '', source)
    assert gated['verdict'] == 'revise'
    assert gated['issues'][0]['excerpts'] == source['expression_review']['issues'][0]['excerpts']
    assert source == before
    assert quality().gate_report(tmp_path, '0001', '', gated) == gated


def test_low_suggestion_and_legacy_report_do_not_force_rewrite(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '她不再等他认错。她等的已经不是一句认错。')
    low = report('low'); low['expression_review']['verdict'] = 'pass'
    assert quality().gate_report(tmp_path, '0001', '', low)['verdict'] == 'pass'
    assert quality().gate_report(tmp_path, '0001', '', {'verdict': 'pass', 'issues': []})['verdict'] == 'pass'


@pytest.mark.parametrize('excerpts', [[], ['原文中没有这句话。'], ['她不再等……认错。']])
def test_expression_review_cannot_ground_verdict_in_invented_or_spliced_quotes(tmp_path, excerpts):
    write(tmp_path, 'story/0001/chapter.md', '她不再等他认错。她等的已经不是一句认错。')
    data = report(); data['expression_review']['issues'][0]['excerpts'] = excerpts
    with pytest.raises(ValueError, match='表达审稿'):
        quality().gate_report(tmp_path, '0001', '', data)


def test_separate_fact_rejection_still_blocks_publication(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '灯留在桌上。')
    data = {'verdict': 'pass', 'issues': [],
            'fact_review': {'verdict': 'revise', 'summary': '人物提前知道账目'},
            'expression_review': {'verdict': 'pass', 'summary': '表达无实质问题', 'issues': []}}
    assert quality().gate_report(tmp_path, '0001', '', data)['verdict'] == 'revise'
