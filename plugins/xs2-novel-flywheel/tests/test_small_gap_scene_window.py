from test_length_quality import quality


def test_small_total_gap_does_not_require_hundreds_of_words_from_one_cue():
    q=quality()
    paragraphs=['第0001章 · 桌边', '她把纸摊开。'+ '纸页平放着。'*25,
                '他指着旧账，问她几时拿来的。'+ '页边有一处折痕。'*18,
                '“先看这页。”她说。',
                '他把纸转正，读到末尾才抬头。'+ '灯光落在桌上。'*18,
                '她将前一页压在桌角，等他把话说完。'+ '窗外风声渐歇。'*18,
                '他合上账本，答应按原数付钱。'+ '纸页翻动了一阵。'*18,
                '她取回账本。'+ '桌上没有别的东西。'*25]
    raw='\n\n'.join(paragraphs).encode('utf8')
    actual=q.count_prose(raw.decode('utf8'))
    result={'status':'short','actual':actual,'lower':actual+368,'upper':actual+668}
    fragment=q.fragment_anchor(raw,result)
    source=raw[fragment['start']:fragment['end']].decode('utf8')
    assert q.count_prose(source)>=184, '不能让一句话承载数倍于原段的补写'
    assert '\n\n' in source, '已有回应应纳入可替换范围，避免借用冻结后文造成重演'
    assert len(source)<len(raw) and not source.startswith('第0001章')


def test_small_gap_window_still_avoids_all_rejected_source_ranges():
    q=quality();paragraphs=['她将纸页压平。'+'灯照着桌面。'*35 for _ in range(8)]
    raw='\n\n'.join(paragraphs).encode('utf8');actual=q.count_prose(raw.decode('utf8'))
    result={'status':'short','actual':actual,'lower':actual+368,'upper':actual+668}
    first=q.fragment_anchor(raw,result)
    second=q.fragment_anchor(raw,result,[[first['start'],first['end']]])
    assert second['end']<=first['start'] or second['start']>=first['end']
