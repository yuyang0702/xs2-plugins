import importlib.util
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / 'resources/script-library/xs2/short_preparation/short_preparation.py'


def helper():
    assert SCRIPT.is_file(), '轻量准备入口尚未实现'
    spec = importlib.util.spec_from_file_location('short_preparation_tests', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def world():
    return {'core_laws': {'rules': ['现实都市，无超自然']}, 'space_time': {'places': ['旧照相馆']},
            'society': {'pressure': '合作资金与续租相关'}, 'history_culture': {},
            'existence': {}, 'information': {'limits': ['录屏只能证明实际覆盖的操作']}}


def cast():
    return {'characters': [
        {'name': '程见夏', 'role': '修复师', 'want': '取回署名', 'fear': '失去生计', 'boundary': '不否认自己的劳动',
         'contradiction': '仍期待丈夫认可', 'relationships': [{'with': '周予安', 'dynamic': '婚姻与经营绑定'}],
         'voice': {'baseline': '先追问经手细节，受伤时可能转问金额',
                   'by_relationship': [{'with': '周予安', 'guidance': '追问具体兑现期限'}], 'avoid': ['不代断他人内心']}},
        {'name': '周予安', 'role': '经营者', 'want': '先完成签约', 'fear': '无法续租', 'boundary': '不否认经营贡献',
         'contradiction': '想维持共同生活，却让妻子改口', 'relationships': [{'with': '程见夏', 'dynamic': '劝说与依赖并存'}],
         'voice': {'baseline': '谈共同生活，再把话题转到眼前成本',
                   'by_relationship': [{'with': '程见夏', 'guidance': '用延期承诺争取配合'}], 'avoid': ['不作反派式自白']}}
    ]}


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def ready(root):
    for relative, text in {
        'meta/world_foundation.md': '现实照相馆；材料只覆盖部分操作。',
        'meta/character_profiles.md': '## 程见夏\n想留名却怕失去生计。\n## 周予安\n想先完成签约。',
        'meta/character_voice.md': '程见夏追问兑现，周予安谈成本。',
        'meta/style_profile.md': '第一人称有限视角，动作和选择承载情绪。',
        'meta/story_plan.md': '取回名字，真实承担退款和失店代价。',
        'outline/volume_outline.md': '一章内完整收尾。',
        'outline/near_term_outline.md': '海报缺名→交涉受阻→更正→搬离，私人饭桌收束。',
        'learning/context/mvp.md': '已批准写法：各人为了当前目标选择话语。',
        'learning/candidates.json': '{"unapproved":"不得进入写手的候选原句"}',
        'meta/character_voice_adaptations.md': '已检查的关系适配：对父亲先问生计安排。',
    }.items():
        write(root, relative, text)


def test_compact_world_and_cast_feed_the_existing_local_archive(tmp_path, monkeypatch):
    module = helper()
    module.render_world(tmp_path, world())
    module.render_characters(tmp_path, cast())
    monkeypatch.chdir(tmp_path)
    archive_path = PLUGIN / 'resources/script-library/nvl/local_archive/local_archive.py'
    spec = importlib.util.spec_from_file_location('compact_archive_test', archive_path)
    archive = importlib.util.module_from_spec(spec); spec.loader.exec_module(archive)
    archive._prepare(SimpleNamespace(require='meta/world_foundation.md,meta/character_profiles.md,meta/character_voice.md', context=True))
    assert json.loads((tmp_path / 'cache/sync/world.json').read_text(encoding='utf-8'))['core_laws']['rules'] == ['现实都市，无超自然']
    cached = json.loads((tmp_path / 'cache/sync/characters.json').read_text(encoding='utf-8'))['characters']
    assert [item['name'] for item in cached] == ['程见夏', '周予安']
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    voice = (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert '## 程见夏' in profile and '仍期待丈夫认可' in profile
    assert '追问具体兑现期限' in voice and '用延期承诺争取配合' in voice
    assert '寿命' not in (tmp_path / 'meta/world_foundation.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('invalid', ['duplicate', 'missing_voice', 'unsafe_name'])
def test_invalid_cast_cannot_publish_partial_profiles(tmp_path, invalid):
    data = cast()
    if invalid == 'duplicate': data['characters'][1]['name'] = '程见夏'
    elif invalid == 'missing_voice': data['characters'][1].pop('voice')
    else: data['characters'][1]['name'] = '../另一本书'
    with pytest.raises(ValueError): helper().render_characters(tmp_path, data)
    assert not (tmp_path / 'meta/character_profiles.md').exists()
    assert not (tmp_path / 'cache/character/skeleton.json').exists()


def test_compact_preparation_never_replaces_existing_foundations(tmp_path):
    write(tmp_path, 'meta/world_foundation.md', '作者已有世界规则')
    with pytest.raises(ValueError, match='已有'):
        helper().render_world(tmp_path, world())
    assert (tmp_path / 'meta/world_foundation.md').read_text(encoding='utf-8') == '作者已有世界规则'
    assert not (tmp_path / 'world/core_laws.json').exists()


def test_compact_writer_context_keeps_complete_facts_voices_and_approved_writing(tmp_path):
    ready(tmp_path)
    helper().prepare_context(tmp_path, '0001')
    context = (tmp_path / 'cache/short/production_context.md').read_text(encoding='utf-8')
    for expected in ['想留名却怕失去生计', '已批准写法', '已检查的关系适配', '私人饭桌收束', '退款和失店代价']:
        assert expected in context
    assert '不得进入写手的候选原句' not in context
    assert '尚未发生' in (tmp_path / 'story/0001/world_events.md').read_text(encoding='utf-8')
    assert (tmp_path / 'cache/se/se_output.json').is_file()
    assert (tmp_path / 'story/0001/single_chapter_guide.md').is_file()
    assert not (tmp_path / 'story/0001/chapter.md').exists()


def test_compact_retry_has_a_new_context_when_only_derived_inputs_change(tmp_path):
    ready(tmp_path)
    helper().prepare_context(tmp_path, '0001', task_id='first-attempt')
    first = tmp_path / 'cache/short/first-attempt.md'
    assert first.is_file()
    write(tmp_path, 'cache/story-support/context.md', '新的任务级上下文')
    path, _ = helper().prepare_context(tmp_path, '0001', task_id='second-attempt')
    assert '新的任务级上下文' in (tmp_path / path).read_text(encoding='utf-8')
    assert '新的任务级上下文' not in first.read_text(encoding='utf-8')
    assert not (tmp_path / 'story/0001/chapter.md').exists()


def test_context_limit_stops_before_any_derived_files_are_written(tmp_path):
    ready(tmp_path)
    write(tmp_path, 'meta/character_profiles.md', '完整人物资料' * 5000)
    with pytest.raises(ValueError, match='完整'):
        helper().prepare_context(tmp_path, '0001')
    assert not (tmp_path / 'cache/short/production_context.md').exists()
    assert not (tmp_path / 'story/0001/world_events.md').exists()


def test_existing_body_and_nonfirst_chapter_cannot_enter_first_draft_shortcut(tmp_path):
    ready(tmp_path)
    write(tmp_path, 'story/0001/chapter.md', '作者已有正文')
    with pytest.raises(ValueError): helper().prepare_context(tmp_path, '0001')
    with pytest.raises(ValueError): helper().prepare_context(tmp_path, '0002')
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == '作者已有正文'


def test_missing_canonical_file_does_not_get_fabricated_from_candidates(tmp_path):
    ready(tmp_path)
    (tmp_path / 'meta/character_voice.md').unlink()
    with pytest.raises(ValueError, match='缺少'): helper().prepare_context(tmp_path, '0001')
    assert not (tmp_path / 'cache/short/production_context.md').exists()


def test_context_cli_binds_only_this_execution_and_writer_resolves_the_complete_file(tmp_path):
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    import asyncio
    ready(tmp_path)
    result = subprocess.run([sys.executable, str(SCRIPT), 'context'], cwd=tmp_path,
                            capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    outputs = _parse_wf_vars(result.stdout)
    assert outputs == {'short_context_file': 'cache/short/production_context.md'}
    expanded = asyncio.run(resolve_placeholders('{{short_context_file}}', outputs,
        [{'key': 'short_context_file', 'type': 'file', 'required': False}], str(tmp_path)))
    assert '已批准写法' in expanded and '已检查的关系适配' in expanded
    # A standard run has an empty output variable; stale files are not consumed.
    standard = asyncio.run(resolve_placeholders('{{short_context_file}}', {'short_context_file': ''},
        [{'key': 'short_context_file', 'type': 'file', 'required': False}], str(tmp_path)))
    assert standard == ''


def test_preparation_variable_contract_has_no_ambiguous_duplicate_defaults():
    for stage in ['build', 'character', 'mvp']:
        definition = json.loads((PLUGIN / f'resources/workflows/{stage}/definition.json').read_text(encoding='utf-8-sig'))
        keys = [item['key'] for item in definition['variables']]
        assert len(keys) == len(set(keys)), f'{stage} has duplicate variables'


def test_compact_single_writer_renders_each_source_once(tmp_path):
    import asyncio
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders

    ready(tmp_path)
    rule = '暗房仅有一扇向外开的铁门。'
    write(tmp_path, 'meta/world_foundation.md', rule)
    write(tmp_path, 'cache/story-support/context.md', '# 共用资料\n\n' + rule)
    write(tmp_path, 'cache/full-book.md', rule)
    write(tmp_path, 'meta/custom-guide.md', '她先去冲出最后一张底片。')
    write(tmp_path, 'meta/custom-voice.md', '她只在道歉时喊对方全名。')
    adopted = {'chapter':'0001','title':'收起备用钥匙','source_hashes':{}}
    write(tmp_path, 'planning/chapters/0001.json', json.dumps(adopted, ensure_ascii=False))
    outline = tmp_path / 'outline/near_term_outline.md'
    write(tmp_path, 'outline/near_term_outline.md', outline.read_text(encoding='utf-8') +
          '\n<!-- adopted-plan:0001 -->\n### 第 1 章 · 收起备用钥匙\n\n**前文依据**\n<!-- /adopted-plan:0001 -->')
    definition = json.loads((PLUGIN / 'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    node = next(node for node in definition['nodes'] if node['id'] == 'agent_sw')
    prepare = next(node for node in definition['nodes'] if node['id'] == 'script_short_context')
    variables = definition['variables']
    common = {row['key']: row.get('default', '') for row in variables}
    common.update(writer_type='single', prose_policy_runtime='', chapter_number='0001',
                  story_support_context='cache/story-support/context.md', book_contract_file='cache/full-book.md',
                  pp_learning_context='learning/context/mvp.md', guide_file='meta/custom-guide.md',
                  character_voice_adaptations_file='meta/custom-voice.md')

    async def render(value, settings):
        return await resolve_placeholders(value, settings, variables, str(tmp_path))

    argv_variables = [item for item in variables if item['key'] not in prepare['node_params']['script_argv_path_variables']]
    args = [asyncio.run(resolve_placeholders(arg, common, argv_variables, str(tmp_path)))
            for arg in prepare['node_params']['script_argv']]
    result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp_path, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    outputs = _parse_wf_vars(result.stdout)
    assert outputs['single_writer_plan'] == ''
    message = asyncio.run(render(node['first_message'], {**common, **outputs}))
    assert message.count(rule) == 1
    for phrase in ('已批准写法', '私人饭桌收束', '想留名却怕失去生计', '收起备用钥匙',
                   '她先去冲出最后一张底片。', '她只在道歉时喊对方全名。'):
        assert message.count(phrase) == 1
    full = asyncio.run(render(node['first_message'], {**common, 'wroter_context': '完整路径专用写手资料'}))
    assert '完整路径专用写手资料' in full and rule in full


def test_short_single_writer_projects_current_chapter_and_character_knowledge(tmp_path):
    ready(tmp_path)
    write(tmp_path, 'outline/near_term_outline.md', '# 近期大纲\n\n'
          '## 第 1 章 · 停电\n程见夏找到铁盒，周予安交还钥匙。\n\n'
          '## 第 2 章 · 南下\n宋八发动火车。')
    write(tmp_path, 'meta/character_profiles.md', '# 角色档案\n\n'
          '## 程见夏\n- 身份：修灯的人。\n### 已确认事实\n- 她只见过空铁盒。\n\n'
          '## 周予安\n### 作者情节边界\n- 他亲手把钥匙藏在铁盒夹层。\n\n'
          '## 宋八\n- 身份：开货车的人。')
    write(tmp_path, 'meta/character_voice.md', '# 角色声线\n\n'
          '## 程见夏\n她着急时会把话说到一半。\n\n## 宋八\n他称呼大家为旅客。')
    write(tmp_path, 'meta/world_foundation.md', '# 短篇世界基础\n\n'
          '## 核心规则\n### 物理条件\n- 铁盒有夹层。\n\n'
          '### 叙事规则\n- 段落都得先解释后行动。\n\n'
          '## 信息与认知边界\n### 周予安可知\n- 知道备用钥匙已经损坏。\n'
          '### 宋八可知\n- 最后一班货车已经出站。')
    write(tmp_path, 'meta/author.md', '最后只让姐姐明说一次她的决定。')
    path, _ = helper().prepare_context(tmp_path, '0001', single_writer=True,
                                      writer_overrides=('meta/author.md',))
    brief = (tmp_path / path).read_text(encoding='utf-8')
    for phrase in ('周予安交还钥匙', '她只见过空铁盒', '他亲手把钥匙藏在铁盒夹层',
                   '她着急时会把话说到一半', '铁盒有夹层', '知道备用钥匙已经损坏',
                   '最后只让姐姐明说一次她的决定'):
        assert phrase in brief
    for phrase in ('宋八', '发动火车', '开货车的人', '最后一班货车', '都得先解释后行动'):
        assert phrase not in brief


@pytest.mark.parametrize('mother_card', ['- 身份：林遥的母亲。', '### 已确认事实\n\n- 周岚是林遥的母亲。'])
def test_short_writer_keeps_cards_referred_to_by_an_alias_or_confirmed_relationship(tmp_path, mother_card):
    ready(tmp_path)
    write(tmp_path, 'outline/near_term_outline.md',
          '## 第 1 章 · 回家\n林遥回家向妈妈借钱，顺路把雨伞还给何师傅。')
    write(tmp_path, 'meta/character_profiles.md',
          '# 角色档案\n\n## 林遥\n- 身份：女儿。\n\n'
          f'## 周岚\n{mother_card}\n\n'
          '## 何庆\n- 别名：何师傅\n\n'
          '## 何敏\n- 别名：何师傅\n\n'
          '## 宋八\n- 身份：开货车的人。')
    write(tmp_path, 'meta/character_voice.md',
          '## 周岚\n生气时才叫女儿小名。\n\n'
          '## 何庆\n每次还伞都先问伞骨。\n\n'
          '## 何敏\n只管伞晾干没有。\n\n'
          '## 宋八\n他称呼大家为旅客。')

    path, _ = helper().prepare_context(tmp_path, '0001', single_writer=True)
    brief = (tmp_path / path).read_text(encoding='utf-8')
    for phrase in ('林遥的母亲', '生气时才叫女儿小名', '每次还伞都先问伞骨', '只管伞晾干没有'):
        assert phrase in brief
    assert '宋八' not in brief


def test_short_writer_world_keeps_story_constraints_without_numeric_audit_instructions(tmp_path):
    ready(tmp_path)
    world = ('# 短篇世界基础\n\n## 信息与认知边界\n\n### 叙事限制\n\n'
             '- 第一人称只能依据现场所见和可查的记录。\n'
             '- 冲印的照相纸最多两张，最后一张要留在店里。\n'
             '- 若引用现场话语中的字数或数量，必须以紧邻且唯一的纯汉字原话为依据；含标点、外文、嵌套引语或远距指代时，计数保持未知。\n')
    write(tmp_path, 'meta/world_foundation.md', world)
    write(tmp_path, 'meta/style_profile.md', '用照相馆的口吻说出选择。')
    path, _ = helper().prepare_context(tmp_path, '0001', single_writer=True)
    brief = (tmp_path / path).read_text(encoding='utf-8')
    assert '紧邻且唯一' not in brief
    for fact in ('第一人称只能依据现场所见', '照相纸最多两张', '用照相馆的口吻说出选择。'):
        assert fact in brief
    assert (tmp_path / 'meta/world_foundation.md').read_text(encoding='utf-8') == world


def test_short_writer_keeps_approved_composition_intent_without_planner_budgets(tmp_path):
    from test_composition_plan import module as composition

    ready(tmp_path)
    write(tmp_path, '.novel-project.json', json.dumps({'values': {'chapter_number': '0001', 'target_word_count': '400-500'}}))
    write(tmp_path, 'meta/length_policy.json', json.dumps({'schema': 1, 'ownership': 'author'}))
    planner = composition()
    request = planner.prepare(tmp_path, '0001', 'composition-test', '400-500')
    plan = {'request_digest': request['request_digest'], 'status': 'ready', 'reason': '仅供复查的规划说明',
            'minimum': 400, 'maximum': 500, 'segments': [
                {'id': 'door', 'purpose': '从追问转为愿意等待', 'development': '听见熟人的提醒后重新考虑',
                 'minimum': 400, 'maximum': 500},
            ]}
    review = {'request_digest': request['request_digest'], 'plan_digest': planner.identity(plan), 'verdict': 'approve',
              'scope_preserved': True, 'length_feasible': True, 'checks': [
                  {'segment_id': 'door', 'develops_function': True, 'style_basis': '亲见亲闻', 'reason': '改变关系'},
              ]}
    planner.accept(tmp_path, 'composition-test', plan, review)
    path, _ = helper().prepare_context(tmp_path, '0001', single_writer=True)
    brief = (tmp_path / path).read_text(encoding='utf-8')
    assert '从追问转为愿意等待' in brief and '听见熟人的提醒后重新考虑' in brief
    assert '仅供复查的规划说明' not in brief and 'request_digest' not in brief


def test_compact_character_model_receives_actual_world_and_confirmed_author_facts(tmp_path):
    from src.workflow.variable_resolution import resolve_placeholders
    import asyncio
    definition = json.loads((PLUGIN / 'resources/workflows/character/definition.json').read_text(encoding='utf-8-sig'))
    write(tmp_path, 'meta/world_foundation.md', '现实照相馆；原始记录不等于全部权属。')
    values = {item['key']: item.get('default', '') for item in definition['variables']}
    values.update(premise='程见夏31岁，唐小满22岁，保留师徒关系。', narrative_pov='first_person')
    node = next(item for item in definition['nodes'] if item['id'] == 'agent_short_character')
    expanded = asyncio.run(resolve_placeholders(node['first_message'], values, definition['variables'], str(tmp_path)))
    assert '现实照相馆；原始记录不等于全部权属。' in expanded
    assert '程见夏31岁，唐小满22岁，保留师徒关系。' in expanded


def test_flexible_voice_preserves_facts_values_and_optional_legacy_fields(tmp_path):
    data = cast()
    person = data['characters'][0]
    person['facts'] = ['程见夏救过周予安；周予安是受助者']
    person['voice'] = {'baseline': '通常先问细节', 'preferences': ['紧张时偏向短句'],
                       'when_adaptable': ['疲惫时可承认害怕，关系改善后可以求助'],
                       'boundaries': ['不以无辜者性命报复']}
    helper().render_characters(tmp_path, data)
    profile = (tmp_path / 'meta/character_profiles.md').read_text(encoding='utf-8')
    voice = (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert '已确认事实' in profile and person['facts'][0] in profile
    assert '价值底线' in profile and person['boundary'] in profile
    for phrase in ['表达倾向（非固定台词）', '可随情境调整', '疲惫时可承认害怕', '明确表达边界', '不以无辜者性命报复']:
        assert phrase in voice
    cached = json.loads((tmp_path / 'cache/character/skeleton.json').read_text(encoding='utf-8'))
    assert cached['characters'][0]['facts'] == person['facts']


def test_empty_legacy_voice_lists_are_compatible_and_boundaries_are_not_erased(tmp_path):
    data = cast()
    data['characters'][0]['voice'].update(by_relationship=[], avoid=[])
    helper().render_characters(tmp_path, data)
    voice = (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert '不作反派式自白' in voice
    assert '旧档表达约束（原文保留）' in voice


def test_structured_adaptable_voice_from_live_model_keeps_context_and_reaction(tmp_path):
    import copy
    data = cast()
    context = {'condition': '对客商谈修样', 'reaction': '说明自己能接的部分，也能承认忙不过来'}
    data['characters'][0]['voice']['when_adaptable'] = ['疲惫时可以求助', context]
    before = copy.deepcopy(data)
    helper().render_characters(tmp_path, data)
    text = (tmp_path / 'meta/character_voice.md').read_text(encoding='utf-8')
    assert '可随情境调整：对客商谈修样：说明自己能接的部分，也能承认忙不过来' in text
    assert '疲惫时可以求助' in text and "'condition'" not in text
    cached = json.loads((tmp_path / 'cache/character/voice.json').read_text(encoding='utf-8'))
    assert cached['characters'][0]['when_adaptable'][1] == context
    assert data == before


@pytest.mark.parametrize('entry', [{}, {'condition': '谈修样'},
    {'condition': '', 'reaction': '求助'}, {'condition': '疲惫', 'reaction': []}, 42])
def test_invalid_adaptable_voice_cannot_publish_partial_archives(tmp_path, entry):
    data = cast()
    data['characters'][0]['voice']['when_adaptable'] = [entry]
    with pytest.raises(ValueError):
        helper().render_characters(tmp_path, data)
    assert not (tmp_path / 'meta/character_profiles.md').exists()
    assert not (tmp_path / 'cache/character/voice.json').exists()


def test_new_character_output_checks_shape_and_does_not_invent_legacy_prohibitions():
    from src.workflow.output_selection import select_agent_output
    definition = json.loads((PLUGIN / 'resources/workflows/character/definition.json').read_text(encoding='utf-8'))
    params = next(n for n in definition['nodes'] if n['id'] == 'agent_short_character')['node_params']
    data = cast()
    for person in data['characters']:
        person['voice'].pop('avoid')
    data['characters'][0]['voice']['when_adaptable'] = [
        '疲惫时可以求助', {'condition': '面对熟人', 'reaction': '可以解释自己的顾虑'}]
    def select():
        return select_agent_output([{'type': 'user', 'content': '生成新档案'},
            {'type': 'assistant', 'content': json.dumps(data, ensure_ascii=False)}], params)
    selected, error = select()
    assert not error and json.loads(selected) == data
    data['characters'][0]['voice']['avoid'] = ['不透露自己的疲惫']
    assert select()[1], 'New generated profiles must not invent legacy prohibitions'
    data['characters'][0]['voice'].pop('avoid')
    data['characters'][0]['voice']['when_adaptable'] = [{'condition': '疲惫'}]
    assert select()[1], 'Malformed context must be rejected before publication script'


@pytest.mark.parametrize('value', [[42], [''], {'condition': '疲惫', 'reaction': '求助'}])
def test_full_voice_renderer_rejects_malformed_optional_context(value):
    script = PLUGIN / 'resources/script-library/nvl/json_to_md/json_to_md.py'
    spec = importlib.util.spec_from_file_location('invalid_voice_renderer_tests', script)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    with pytest.raises(ValueError):
        renderer.render_voice_char({'name': '程见夏', 'when_adaptable': value})


def test_existing_character_archive_is_never_rewritten_to_relax_rules(tmp_path):
    write(tmp_path, 'meta/character_voice.md', '## 程见夏\n不伤害无辜；永不背叛妹妹。\n')
    before = (tmp_path / 'meta/character_voice.md').read_bytes()
    with pytest.raises(ValueError, match='已有'):
        helper().render_characters(tmp_path, cast())
    assert (tmp_path / 'meta/character_voice.md').read_bytes() == before
    assert not (tmp_path / 'cache/character/skeleton.json').exists()


def test_character_prompts_distinguish_fact_direction_values_and_reactions():
    prompts = json.loads((PLUGIN / 'resources/prompts.json').read_text(encoding='utf-8-sig'))['agents']
    for name in ['novel-short-character', 'novel-character-skeleton', 'novel-character-belief', 'novel-character-deep', 'novel-character-voice']:
        content = '\n'.join(s['content'] for s in prompts[name]['sections'] if s.get('enabled', True))
        for phrase in ['谁救了谁', '价值底线', '疲惫', '回应对方', '不得照抄']:
            assert phrase in content, (name, phrase)
    compact = prompts['novel-short-character']['sections'][0]['content']
    assert 'by_relationship和avoid必须有具体内容' not in compact
    assert 'when_adaptable' in compact and 'facts' in compact


def test_full_voice_renderer_retains_legacy_boundaries_and_optional_context_without_mutation():
    import copy
    script = PLUGIN / 'resources/script-library/nvl/json_to_md/json_to_md.py'
    spec = importlib.util.spec_from_file_location('flexible_voice_renderer_tests', script)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    legacy = {'name': '程见夏', 'syntax_fingerprint': {'catchphrases': ['先等一等']},
              'forbidden_speech': ['不泄露妹妹住处'], 'emotion_patterns': {'anger': '有时沉默'}}
    original = copy.deepcopy(legacy)
    rendered = renderer.render_voice_char(legacy)
    assert '旧档表达约束（原文保留）' in rendered
    assert '不泄露妹妹住处' in rendered and '先等一等' in rendered
    assert '表达倾向（非固定台词）' in rendered
    assert legacy == original
    flexible = {'name': '程见夏', 'preferences': ['通常先问细节'],
                'when_adaptable': ['疲惫时可求助'], 'boundaries': ['不伤害无辜']}
    rendered = renderer.render_voice_char(flexible)
    assert '疲惫时可求助' in rendered and '可随情境调整' in rendered
    assert '不伤害无辜' in rendered and '明确表达边界' in rendered
    flexible['when_adaptable'] = [{'condition': '疲惫时', 'reaction': '可以求助'}]
    rendered = renderer.render_voice_char(flexible)
    assert '疲惫时：可以求助' in rendered and "'condition'" not in rendered
