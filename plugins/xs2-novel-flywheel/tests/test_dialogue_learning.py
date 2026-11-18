"""Source dialogue is evidence; generation uses grounded, scoped adaptations."""
import importlib.util
import copy
import inspect
import json
from pathlib import Path
import sys
import subprocess
import asyncio
import threading
import uuid

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
RESOURCES = PLUGIN / 'resources'
REFERENCE = RESOURCES / 'script-library/xs2/reference_distill/reference_distill.py'


def reference():
    spec = importlib.util.spec_from_file_location('dialogue_learning_reference_tests', REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_sample():
    raw = '掌柜把账本合上，绣工仍站在柜前。\n掌柜说：“明日再来。”\n绣工问：“明日几时？”\n掌柜翻开账本，查了查日期。'
    window = {'window_id': 'window-0001', 'source_start': 0, 'source_end': len(raw)}
    sample = {'scene_type': '讨薪交涉', 'relationship': '雇主与绣工',
              'turns': [{'speaker': '掌柜', 'text': '明日再来。', 'intent': '推迟结算'},
                        {'speaker': '绣工', 'text': '明日几时？', 'intent': '追问具体时间'}],
              'transferable_moves': ['用追问收窄含糊的时间承诺'], 'limits': ['依双方关系调整称呼和追问力度']}
    for turn in sample['turns']:
        turn['evidence'] = {'window_id': window['window_id'], 'excerpt': turn['text']}
    return raw, window, sample


def checked(module, samples, window, raw):
    fn = getattr(module, 'normalize_dialogue_samples', None)
    assert callable(fn), 'distillation must preserve verified dialogue turns and surrounding source context'
    return fn(samples, window, raw, module.evidence_position)


def test_source_dialogue_keeps_turn_order_speakers_and_before_after_context():
    module = reference();raw, window, sample = source_sample()
    records = checked(module, [sample], window, raw)
    record = records[0]
    assert record['context']['text'] == raw
    assert record['context']['text'].startswith('掌柜把账本')
    assert record['context']['text'].endswith('查了查日期。')
    assert [t['speaker'] for t in record['turns']] == ['掌柜', '绣工']
    for turn in record['turns']:
        assert raw[turn['source_start']:turn['source_end']] == turn['text']
    assert record['source_sha256'] == module.digest(raw)
    assert checked(module, [sample], window, raw)[0]['sample_id'] == record['sample_id']


@pytest.mark.parametrize('change', ['invented_quote', 'invented_speaker', 'reverse_turns', 'one_speaker'])
def test_source_dialogue_rejects_unverifiable_or_non_conversational_samples(change):
    module = reference();raw, window, sample = source_sample()
    if change == 'invented_quote':sample['turns'][1]['text'] = '银子今晚给你。'
    if change == 'invented_speaker':sample['turns'][1]['speaker'] = '外来将军'
    if change == 'reverse_turns':sample['turns'].reverse()
    if change == 'one_speaker':sample['turns'][1]['speaker'] = '掌柜'
    fn = getattr(module, 'normalize_dialogue_samples', None)
    assert callable(fn), 'source dialogue verification is missing'
    with pytest.raises(ValueError):fn([sample], window, raw, module.evidence_position)


def test_legacy_candidates_need_no_synthetic_dialogue_sample():
    module = reference();raw, window, _ = source_sample()
    assert checked(module, None, window, raw) == []


def test_source_dialogue_cannot_omit_an_intervening_reply():
    module=reference();raw, window, sample=source_sample()
    raw=raw.replace('绣工问：', '掌柜又说：“不要催。”\n绣工问：')
    window['source_end']=len(raw)
    with pytest.raises(ValueError, match='中间回应'):
        checked(module, [sample], window, raw)


@pytest.mark.parametrize('excerpt', ['「被动」', '可有时候，「被动」不见得处于下位。'])
@pytest.mark.parametrize('nested_reason', [False, True])
def test_dialogue_exchange_can_classify_a_quoted_narrative_term(excerpt, nested_reason):
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：', '可有时候，「被动」不见得处于下位。\n绣工问：')
    window['source_end'] = len(raw)
    sample['non_dialogue_quotes'] = [{
        'evidence': {'window_id': window['window_id'], 'excerpt': excerpt},
        'reason': '叙述段落强调一个词语',
    }]
    if nested_reason:
        item = sample['non_dialogue_quotes'][0]
        item['evidence']['reason'] = item.pop('reason')
    record = checked(module, [sample], window, raw)[0]
    assert [turn['text'] for turn in record['turns']] == ['明日再来。', '明日几时？']
    assert record['non_dialogue_quotes'][0]['evidence']['excerpt'] == excerpt
    assert record['non_dialogue_quotes'][0]['reason'] == '叙述段落强调一个词语'


@pytest.mark.parametrize('reply', [
    '掌柜又说：“不要催。”', '掌柜又问：\n“不要催。”', '掌柜冷笑：\n\n“不要催。”',
    '“不要催。”掌柜反驳。', '“不要催。”\n掌柜反驳。', '“不要催。”\n\n掌柜反驳。',
])
def test_dialogue_cannot_classify_a_reply_with_a_speech_tag_as_narration(reply):
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：', reply + '\n绣工问：')
    window['source_end'] = len(raw)
    sample['non_dialogue_quotes'] = [{
        'evidence': {'window_id': window['window_id'], 'excerpt': '“不要催。”'},
        'reason': '叙述者使用引号强调',
    }]
    with pytest.raises(ValueError, match='中间回应'):
        checked(module, [sample], window, raw)


def test_source_dialogue_keeps_a_role_label_without_guessing_a_name():
    module = reference()
    raw, window, sample = source_sample()
    turn = sample['turns'][1]
    del turn['speaker']
    turn.update(speaker_label='来讨生活费的人', attribution='tentative')
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_tentative'
    assert record['turns'][1]['speaker_label'] == '来讨生活费的人'
    assert record['turns'][1]['attribution'] == 'tentative'
    turn.update(source_speaker='绣工', attribution='observed',
                attribution_evidence={'window_id': window['window_id'], 'excerpt': '绣工问：'})
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_verified'
    assert record['turns'][1]['speaker'] == '绣工'
    assert record['turns'][1]['speaker_label'] == '来讨生活费的人'
    turn['speaker'] = '外来将军'
    with pytest.raises(ValueError, match='人物姓名'):
        checked(module, [sample], window, raw)


@pytest.mark.parametrize(('tag', 'claim', 'source_speaker', 'expected'), [
    ('绣工闭了闭眼，咬牙道：', {'speaker': '绣工'}, None, '绣工'),
    ('绣工这才惊觉失言，连忙收敛失态，移开眼神，找补道：\n\n',
     {'speaker': '绣工'}, None, '绣工'),
    ('女修鄙夷道：', {'speaker_label': '女修'}, None, '女修'),
    ('绣工抬眼，女修低声问：', {'speaker_label': '女修'}, '女修', '女修'),
    ('对讲机里的绣工有点蒙了，问我：\n',
     {'speaker': '绣工', 'speaker_label': '无线电里的绣工'}, None, '对讲机里的绣工'),
    ('我死死盯着掌柜，没好气地说：\n',
     {'speaker_label': '叙述者'}, '我', '我'),
])
def test_attribution_uses_the_original_subject_and_adjacent_speech_tag(tag, claim, source_speaker, expected):
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：', tag)
    window['source_end'] = len(raw)
    turn = sample['turns'][1]
    del turn['speaker']
    turn.update(claim, attribution='observed',
                attribution_evidence={'window_id': window['window_id'], 'excerpt': tag.strip()})
    if source_speaker:
        turn['source_speaker'] = source_speaker
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_verified'
    assert record['turns'][1]['attribution'] == 'observed'
    assert record['turns'][1]['speaker'] == expected


@pytest.mark.parametrize(('tag', 'excerpt'), [
    ('绣工抬眼，掌柜问：', '绣工抬眼，掌柜问：'),
    ('绣工听掌柜问：', '绣工听掌柜问：'),
    ('他低声问：', '他低声问：'),
    ('绣工问：\n换了地方。\n', '绣工问：'),
    ('绣工问：\n6\n', '绣工问：'),
    ('\n', ''),
    ('绣工问：', '绣工'),
])
def test_attribution_cannot_use_another_subject_or_an_unlinked_mention(tag, excerpt):
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：“明日几时？”', tag + '“明日几时？”')
    window['source_end'] = len(raw)
    if excerpt == '绣工':
        start = raw.index('绣工问')
    else:
        start = raw.index(excerpt or '明日几时？')
    sample['turns'][1].update(source_speaker='绣工', attribution='observed', attribution_evidence={
        'window_id': window['window_id'], 'excerpt': excerpt or '明日几时？',
        'source_start': start, 'source_end': start + len(excerpt or '明日几时？'),
    })
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_tentative'
    assert record['turns'][1]['attribution'] == 'tentative'


def test_attribution_keeps_a_model_tentative_judgment_even_with_a_nearby_speech_tag():
    module = reference()
    raw, window, sample = source_sample()
    turn = sample['turns'][1]
    turn.update(speaker_label='暂定角色', attribution='tentative', source_speaker='绣工',
                attribution_evidence={'window_id': window['window_id'], 'excerpt': '绣工问：'})
    assert checked(module, [sample], window, raw)[0]['status'] == 'context_tentative'


def test_attribution_can_cite_only_the_clause_that_actually_names_the_speaker():
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：', '掌柜把账本一合，绣工回过头，低声问：')
    window['source_end'] = len(raw)
    sample['turns'][1].update(source_speaker='绣工', attribution='observed', attribution_evidence={
        'window_id': window['window_id'], 'excerpt': '绣工回过头，低声问：',
    })
    assert checked(module, [sample], window, raw)[0]['status'] == 'context_verified'


def test_original_role_does_not_require_a_second_display_label():
    module = reference()
    raw, window, sample = source_sample()
    turn = sample['turns'][1]
    del turn['speaker']
    turn.update(source_speaker='绣工', attribution='observed',
                attribution_evidence={'window_id': window['window_id'], 'excerpt': '绣工问：'})
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_verified'
    assert record['turns'][1]['speaker'] == '绣工'


def test_a_tag_introducing_the_next_quote_cannot_attribute_the_previous_quote():
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('掌柜说：“明日再来。”\n绣工问：', '“明日再来。”绣工问：')
    window['source_end'] = len(raw)
    sample['turns'][0].update(speaker='绣工', attribution='observed', source_speaker='绣工',
                              attribution_evidence={'window_id': window['window_id'], 'excerpt': '绣工问：'})
    sample['turns'][1].update(speaker_label='提问者')
    del sample['turns'][1]['speaker']
    assert checked(module, [sample], window, raw)[0]['turns'][0]['attribution'] == 'tentative'


def test_postposed_speech_tag_can_end_at_a_line_break_without_punctuation():
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('绣工问：“明日几时？”', '“明日几时？”绣工问')
    window['source_end'] = len(raw)
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_verified'


def test_copied_quote_delimiters_are_removed_from_legacy_turn_text():
    module = reference()
    raw, window, sample = source_sample()
    sample['turns'][0].update(text='“明日再来。”',
                              evidence={'window_id': window['window_id'], 'excerpt': '掌柜说：“明日再来。”'})
    turn = checked(module, [sample], window, raw)[0]['turns'][0]
    assert raw[turn['source_start']:turn['source_end']] == turn['text'] == '明日再来。'


def test_segmented_dialogue_preserves_exact_quotes_through_adoption(tmp_path):
    module = reference()
    raw, window, sample = source_sample()
    raw = raw.replace('“明日再来。”', '“明日再来。”掌柜又说：“账还没对完。”')
    window['source_end'] = len(raw)
    turn = sample['turns'][0]
    del turn['text'], turn['evidence']
    turn['segments'] = [
        {'text': text, 'evidence': {'window_id': window['window_id'], 'excerpt': text}}
        for text in ('明日再来。', '账还没对完。')
    ]
    record = checked(module, [sample], window, raw)[0]
    turn = record['turns'][0]
    assert raw[turn['source_start']:turn['source_end']] == turn['text'] == '明日再来。'
    assert [raw[s['source_start']:s['source_end']] for s in turn['segments']] == ['明日再来。', '账还没对完。']
    assert [s['text'] for s in turn['segments']] == ['明日再来。', '账还没对完。']

    adoption, selections, *_ = review_fixture(tmp_path)
    item = selections[0]
    item['candidate']['dialogue_samples'] = [record]
    item['library']['candidates']['source']['text_sha256'] = record['source_sha256']
    assert adoption.source_samples(item)[0]['turns'][0]['segments'] == turn['segments']
    narration = '掌柜又说：'
    start = raw.index(narration)
    turn['segments'][1] = {'text': narration, 'source_start': start, 'source_end': start + len(narration)}
    with pytest.raises(ValueError, match='无法核对'):
        adoption.source_samples(item)


def test_a_single_quote_requires_the_legacy_turn_form():
    module = reference()
    raw, window, sample = source_sample()
    turn = sample['turns'][0]
    turn['segments'] = [{'text': turn.pop('text'), 'evidence': turn.pop('evidence')}]
    with pytest.raises(ValueError, match='对白片段'):
        checked(module, [sample], window, raw)


def test_tentative_role_dialogue_does_not_block_abstract_adoption(tmp_path):
    module = reference()
    raw, window, sample = source_sample()
    turn = sample['turns'][1]
    del turn['speaker']
    turn['speaker_label'] = '来讨生活费的人'
    record = checked(module, [sample], window, raw)[0]
    adoption, selections, *_ = review_fixture(tmp_path)
    selections[0]['candidate']['dialogue_samples'] = [record]
    assert adoption.source_samples(selections[0]) == []


def test_wrong_speaker_in_real_surrounding_quote_is_never_verified():
    module = reference()
    raw, window, sample = source_sample()
    sample['turns'][0]['speaker'], sample['turns'][1]['speaker'] = '绣工', '掌柜'
    for turn in sample['turns']:
        turn['attribution'] = 'observed'
        turn['attribution_evidence'] = {'window_id': window['window_id'], 'excerpt': raw}
    record = checked(module, [sample], window, raw)[0]
    assert record['status'] == 'context_tentative'


def test_both_writer_modes_and_polish_receive_dialogue_learning_contract():
    prompts = json.loads((RESOURCES/'prompts.json').read_text(encoding='utf-8'))
    for name in ['novel-dialogue-writer', 'novel-storyboard-integrator', 'novel-polisher',
                 'novel-professional-polisher']:
        sections = prompts['agents'][name]['sections']
        contract = next((s for s in sections if s['name'] == 'dialogue_learning_contract'), None)
        assert contract and contract.get('enabled', True), f'{name} lacks the dialogue learning contract'
        assert '前后回应' in contract['content']
        assert '原作' in contract['content']
    workflow = json.loads((RESOURCES/'workflows/mvp/definition.json').read_text(encoding='utf-8'))
    single_writer = next(node for node in workflow['nodes'] if node['id'] == 'agent_sw')
    message = single_writer['first_message']
    assert '{{single_writer_context}}' in message
    assert '对方那句话的实际意图' in message
    assert '按场面重新组织台词' in message


@pytest.mark.parametrize('stage', ['mvp','polish'])
def test_workflows_build_current_chapter_dialogue_context_before_writers(stage):
    definition = json.loads((RESOURCES/'workflows'/stage/'definition.json').read_text(encoding='utf-8'))
    nodes = [n for n in definition['nodes'] if n.get('node_params', {}).get('script_name') == 'reference_distill'
             and n['node_params'].get('script_args', '').startswith('prepare-context')]
    assert nodes, f'{stage} must refresh adopted dialogue for this chapter'
    assert any(f'--scope {stage} --chapter {{{{chapter_number}}}}' in n['node_params']['script_args'] for n in nodes)
    variable = next(v for v in definition['variables'] if v['key']=='learning_context')
    assert variable['default'] == f'learning/context/{stage}.md'


def review_fixture(tmp_path):
    from test_quick_adoption import service, catalog, setup_book, decision
    setup_book(tmp_path, characters=True)
    profiles = tmp_path/'meta/character_profiles.md'
    profiles.write_text('## 许青\n许宁是许青的妹妹；许青谨慎重情，对许宁温和。\n\n## 许宁\n许青的妹妹，敏锐，常以反问掩饰恐惧。', encoding='utf-8')
    scene = tmp_path/'outline/near_term_outline.md';scene.parent.mkdir()
    scene.write_text('第0001章：许青向许宁追问矿井附近的见闻，许宁担心姐姐冒险。', encoding='utf-8')
    module = sys.modules[service().ReferenceAdoptionJobs.__module__]
    raw, window, sample = source_sample();ref = reference()
    source = checked(ref, [sample], window, raw)[0]
    library = catalog(layer='dialogue');library['candidates']['source']['text_sha256'] = ref.digest(raw)
    candidate = library['candidates']['candidates'][0]
    candidate['dialogue_samples'] = [source]
    selected = [{'library_id':'correct', 'candidate_id':'mechanism-correct', 'kind':'mechanism',
                 'name':'追问具体承诺', 'candidate':candidate, 'library':library}]
    project = json.loads((tmp_path/'.novel-project.json').read_text())
    characters = module._characters(tmp_path)
    situation = {'reference_id':'mechanism-correct', 'sample_id':source['sample_id'], 'status':'matched',
                 'interlocutor':'许宁', 'relationship_evidence':'许宁是许青的妹妹',
                 'scene_path':'outline/near_term_outline.md', 'scene_evidence':'许青向许宁追问矿井附近的见闻',
                 'scene_type':'亲人间追问', 'chapter':'0001',
                 'guidance':'许青先接住妹妹对冒险的顾虑，再围绕她亲眼见过的细节追问，不把温和写成替妹妹总结心情。'}
    response = {'decisions':[decision()], 'voice_adaptations':[{
        'character_name':'许青', 'profile_evidence':'许宁是许青的妹妹',
        'guidance':'许青对妹妹先确认顾虑，再以她已知的信息追问，保持谨慎重情的本书声线。',
        'reference_ids':['mechanism-correct'], 'dialogue_situations':[situation]}]}
    files = {'outline/near_term_outline.md':scene.read_text(encoding='utf-8')}
    return module, selected, project, characters, response, files


def parse_review(fixture):
    module, selected, project, characters, response, files = fixture
    assert 'book_files' in inspect.signature(module._parse_review).parameters, 'dialogue adoption lacks scene grounding'
    return module._parse_review(json.dumps(response, ensure_ascii=False), selected, project, characters, book_files=files)


def test_quick_adoption_keeps_grounded_role_relationship_and_scene_mapping(tmp_path):
    fixture = review_fixture(tmp_path)
    _, _, voices, _ = parse_review(fixture)
    situation = voices[0]['dialogue_situations'][0]
    assert situation['interlocutor'] == '许宁'
    assert situation['status'] == 'matched' and situation['chapter'] == '0001'
    assert situation['relationship_evidence'] == '许宁是许青的妹妹'


@pytest.mark.parametrize('invalid', ['missing', 'other_role', 'relationship', 'scene', 'sample', 'duplicate', 'wrong_chapter'])
def test_quick_adoption_cannot_claim_unverified_dialogue_adaptation(tmp_path, invalid):
    fixture = review_fixture(tmp_path)
    voice = fixture[4]['voice_adaptations'][0];situation = voice['dialogue_situations'][0]
    if invalid == 'missing':voice.pop('dialogue_situations')
    if invalid == 'other_role':situation['interlocutor'] = '原作掌柜'
    if invalid == 'relationship':situation['relationship_evidence'] = '许宁是她的生死仇人'
    if invalid == 'scene':situation['scene_evidence'] = '姐妹在宫宴上当众翻脸'
    if invalid == 'sample':situation['sample_id'] = 'unselected-sample'
    if invalid == 'duplicate':voice['dialogue_situations'].append(copy.deepcopy(situation))
    if invalid == 'wrong_chapter':situation['chapter']='0002'
    assert 'book_files' in inspect.signature(fixture[0]._parse_review).parameters, 'scene-grounded review is missing'
    with pytest.raises(ValueError):parse_review(fixture)


def test_new_book_without_a_planned_scene_can_explicitly_defer_dialogue_mapping(tmp_path):
    fixture = review_fixture(tmp_path)
    situation = fixture[4]['voice_adaptations'][0]['dialogue_situations'][0]
    fixture[4]['voice_adaptations'][0]['dialogue_situations'] = [{
        'reference_id':situation['reference_id'], 'sample_id':situation['sample_id'],
        'status':'pending_context', 'reason':'本书尚未确定对应交谈场景，只采用已审查的抽象方法。'}]
    _, _, voices, _ = parse_review(fixture)
    assert voices[0]['dialogue_situations'][0]['status'] == 'pending_context'


def adopt_scene(tmp_path, manifest=True):
    from test_quick_adoption import service, Model, merge, runner
    fixture = review_fixture(tmp_path)
    module, selected, project, characters, response, files = fixture
    if not manifest:(tmp_path/'.novel-project.json').unlink()
    model = Model(response)
    jobs = service().ReferenceAdoptionJobs(lambda **kw:model, lambda:[selected[0]['library']],
                                         merge, runner, threading.RLock())
    request_id = str(uuid.uuid4())
    async def execute():
        jobs.start(tmp_path, request_id, {'advisor_entry_id':'adviser-1'})
        await asyncio.gather(*list(jobs.tasks.values()))
    asyncio.run(execute())
    result = jobs.get(tmp_path, request_id)
    assert result['status'] == 'applied', result
    return fixture, model


def test_legacy_book_without_project_manifest_can_adopt_and_render_dialogue(tmp_path):
    fixture, _ = adopt_scene(tmp_path, manifest=False)
    assert not (tmp_path/'.novel-project.json').exists()
    guidance = fixture[4]['voice_adaptations'][0]['dialogue_situations'][0]['guidance']
    assert guidance in render(tmp_path)
    p=tmp_path/'learning/assistant-history.json'
    history=json.loads(p.read_text(encoding='utf-8'));history['entries'][0]['question']='新的故事方向已经改变。'
    p.write_text(json.dumps(history,ensure_ascii=False),encoding='utf-8')
    assert guidance not in render(tmp_path), 'changed adviser positioning must invalidate the fallback mapping'


def render(tmp_path, chapter='0001'):
    result = subprocess.run([sys.executable, str(REFERENCE), 'prepare-context', '--scope', 'mvp', '--chapter', chapter],
                            cwd=tmp_path, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    return (tmp_path/'learning/context/mvp.md').read_text(encoding='utf-8')


def test_actual_adoption_cli_publishes_scoped_dialogue_without_changing_novel_or_voices(tmp_path):
    fixture, model = adopt_scene(tmp_path)
    assert (tmp_path/'learning/dialogue_adaptations.json').is_file(), 'reviewed scene mappings must reach generation'
    content = render(tmp_path)
    assert fixture[4]['voice_adaptations'][0]['dialogue_situations'][0]['guidance'] in content
    assert '明日再来。' not in content and '掌柜' not in content
    assert '明日再来。' in str(model.messages), 'compatibility must read complete source dialogue context'
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8') == '用户已有正文'
    assert (tmp_path/'meta/character_voice.md').read_text(encoding='utf-8') == '原有声音不可覆盖'
    assert '许宁是许青的妹妹' in (tmp_path/'meta/character_profiles.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('change', ['chapter', 'profile', 'scene', 'positioning'])
def test_generation_does_not_apply_an_unrelated_or_stale_dialogue_scene(tmp_path, change):
    fixture, _ = adopt_scene(tmp_path)
    guidance = fixture[4]['voice_adaptations'][0]['dialogue_situations'][0]['guidance']
    if change == 'profile':
        p = tmp_path/'meta/character_profiles.md';p.write_text(p.read_text(encoding='utf-8')+'\n后来关系发生变化。',encoding='utf-8')
    if change == 'scene':(tmp_path/'outline/near_term_outline.md').write_text('场景已经重写。',encoding='utf-8')
    if change == 'positioning':
        p=tmp_path/'.novel-project.json';v=json.loads(p.read_text());v['values']['genre']='古风喜剧';p.write_text(json.dumps(v),encoding='utf-8')
    content = render(tmp_path, '0002' if change == 'chapter' else '0001')
    assert guidance not in content
    receipt = json.loads((tmp_path/'learning/receipts/mvp.json').read_text(encoding='utf-8'))
    assert receipt['dialogue']['applied'] == 0


def test_import_normalize_merge_profile_and_old_id_reanalysis_preserve_dialogue(tmp_path):
    from src.web.novel_library import enrich_candidates, profile_from_workspace
    from test_quick_adoption import service
    def cli(*args):
        result=subprocess.run([sys.executable,str(REFERENCE),*args],cwd=tmp_path,capture_output=True,text=True,encoding='utf-8')
        assert result.returncode==0,result.stderr
    def write(relative, value):
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    raw, _, sample=source_sample()
    (tmp_path/'source.txt').write_text(raw,encoding='utf-8')
    cli('split','--input','source.txt')
    manifest=json.loads((tmp_path/'learning/cache/windows.json').read_text(encoding='utf-8'))
    candidate={'mechanism':'交谈中追问具体承诺','layer':'dialogue',
               'transfer_guidance':'围绕对方刚刚给出的含糊回答，追问可落实的信息，并根据双方关系控制表达。',
               'constraints':['仅在人物所知和当前关系支持时使用'], 'scopes':['mvp','polish'], 'confidence':'high',
               'evidence':[{'window_id':'window-0001','excerpt':'掌柜说：“明日再来。”','reason':'含糊回答引出后续追问'}]}
    payload={'window_id':'window-0001','source_sha256':manifest['source']['text_sha256'],'candidates':[candidate]}
    write('learning/raw.json',payload);cli('normalize','--input','learning/raw.json','--window-id','window-0001');cli('merge')
    old=json.loads((tmp_path/'learning/candidates.json').read_text(encoding='utf-8'))
    candidate['dialogue_samples']=[sample]
    write('learning/raw.json',payload);cli('normalize','--input','learning/raw.json','--window-id','window-0001');cli('merge')
    new=json.loads((tmp_path/'learning/candidates.json').read_text(encoding='utf-8'))
    assert new['candidates'][0]['candidate_id']==old['candidates'][0]['candidate_id']
    assert new['candidates'][0]['dialogue_samples'][0]['context']['text']==raw
    sys.path.insert(0,str(REFERENCE.parent))
    import writing_dna
    summary={'source_sha256':manifest['source']['text_sha256'],
             'documents':{name:'仅分析当前样本的对白回应与人物关系；来源不支持的部分保留未知，不推断整本作品或其他人物。'*2
                          for name in writing_dna.DOCUMENTS}}
    write('learning/dna/summary.raw.json',summary);cli('finalize-dna')
    profile=profile_from_workspace(tmp_path)
    assert profile['dialogue_samples'][0]['candidate_id']==new['candidates'][0]['candidate_id']
    assert profile['dialogue_samples'][0]['context']['text']==raw
    # The legacy host merger retains old candidate IDs/content. The refreshed
    # source profile still carries the corresponding contextual analysis.
    merged=enrich_candidates(old,new,exact_ids=True)
    module=sys.modules[service().ReferenceAdoptionJobs.__module__]
    samples=module.source_samples({'candidate_id':merged['candidates'][0]['candidate_id'],
                                  'candidate':merged['candidates'][0],
                                  'library':{'candidates':merged,'profile':profile}})
    assert samples and samples[0]['context']['text']==raw


def test_re_adopting_the_same_writing_can_complete_a_previously_pending_scene(tmp_path):
    from test_quick_adoption import service, Model, merge, runner
    fixture=review_fixture(tmp_path)
    matched=copy.deepcopy(fixture[4])
    pending=copy.deepcopy(matched)
    s=pending['voice_adaptations'][0]['dialogue_situations'][0]
    pending['voice_adaptations'][0]['dialogue_situations']=[{
        'reference_id':s['reference_id'],'sample_id':s['sample_id'],'status':'pending_context',
        'reason':'暂不确认具体交谈的场景，稍后补充关系场景适配。'}]
    def perform(response):
        jobs=service().ReferenceAdoptionJobs(lambda **kw:Model(response),lambda:[fixture[1][0]['library']],
                                            merge,runner,threading.RLock())
        identifier=str(uuid.uuid4())
        async def execute():
            jobs.start(tmp_path,identifier,{'advisor_entry_id':'adviser-1'})
            await asyncio.gather(*list(jobs.tasks.values()))
        asyncio.run(execute())
        return jobs.get(tmp_path,identifier)
    pending_result=perform(pending)
    assert pending_result['status']=='applied'
    assert '待' in pending_result['summary'], 'pending scene adaptation must not be presented as fully applied'
    before=(tmp_path/'learning/active.json').read_bytes()
    assert perform(matched)['status']=='applied'
    assert (tmp_path/'learning/active.json').read_bytes()==before
    assert matched['voice_adaptations'][0]['dialogue_situations'][0]['guidance'] in render(tmp_path)


def test_overlapping_windows_and_reanalysis_keep_one_sample_and_analysis_variants(tmp_path):
    module=reference();raw,window,sample=source_sample()
    original=checked(module,[sample],window,raw)[0]
    revised=copy.deepcopy(original);revised['relationship']='保持客气的雇佣关系'
    revised['turns'][1]['intent']='把宽泛答复收窄到可确认的时间'
    merged=module.combine_samples([{'dialogue_samples':[original]},{'dialogue_samples':[revised]}])
    assert len(merged)==1, 'same source dialogue must retain one identity across overlapping windows'
    assert len(merged[0]['analysis_variants'])==2
    fixture=review_fixture(tmp_path)
    item=fixture[1][0]
    item['candidate']['dialogue_samples']=[original]
    item['library']['profile']={'dialogue_samples':[{**revised,'candidate_id':'mechanism-correct'}]}
    result=fixture[0].source_samples(item)
    assert len(result)==1 and len(result[0]['analysis_variants'])==2
