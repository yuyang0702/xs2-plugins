from test_length_quality import quality, write


def test_polish_review_receives_literal_repetition_candidates_without_forced_rewrite(tmp_path):
    chapter='她的指尖压住湿纸，免得接缝翘起来。\n\n她攥紧纸页，等他开口。\n\n指尖在账上停住。\n\n她攥紧袖口。\n\n指尖发凉，她又攥紧了手。'
    write(tmp_path,'story/0001/chapter.md',chapter)
    path=quality().prepare_guidance(tmp_path,'0001','100-150')
    guide=(tmp_path/path).read_text(encoding='utf8')
    assert '指尖压住湿纸' in guide and '攥紧袖口' in guide
    assert '候选' in guide and '手艺' in guide
    assert chapter==(tmp_path/'story/0001/chapter.md').read_text(encoding='utf8')


def test_isolated_necessary_hand_action_does_not_trigger_a_repetition_candidate(tmp_path):
    write(tmp_path,'story/0001/chapter.md','她用指尖压住纸角，等浆糊稍干便松开。')
    path=quality().prepare_guidance(tmp_path,'0001','10-40')
    assert '重复动作候选' not in (tmp_path/path).read_text(encoding='utf8')
