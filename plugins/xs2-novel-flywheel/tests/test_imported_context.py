import importlib.util
import json
from pathlib import Path

import pytest
from test_story_support import support


def archive():
    file=support.HERE.parents[1]/'nvl/local_archive/local_archive.py'
    spec=importlib.util.spec_from_file_location('imported_book_archive',file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('world',['传音每次耗一枚灵石，失去的记忆不能无代价恢复。','此航段信号单程四分钟，没有超光速备用信道。'])
def test_markdown_import_preserves_source_without_faking_six_dimensions(tmp_path,monkeypatch,world):
    monkeypatch.chdir(tmp_path);module=archive()
    support.write(tmp_path,'meta/world_foundation.md',world)
    support.write(tmp_path,'meta/character_profiles.md','林舟希望找到失去的同伴，行动基于他实际获知的信息。')
    support.write(tmp_path,'meta/character_voice.md','林舟说话有时犹豫，按当前处境写，不强加口头禅。')
    module._build_world_cache();module._build_character_cache()
    result=support.load(tmp_path,'cache/sync/world.json')
    assert result['source_format']=='author_markdown'
    assert result['foundation']['text']==support.read(tmp_path,'meta/world_foundation.md')
    assert result['foundation']['sha256']==support.digest(tmp_path,'meta/world_foundation.md')
    assert not list((tmp_path/'world').glob('*.json'))
    assert support.load(tmp_path,'cache/sync/characters.json')['profiles']['text']==support.read(tmp_path,'meta/character_profiles.md')


def test_partial_structured_world_is_still_rejected(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);module=archive()
    support.write(tmp_path,'meta/world_foundation.md','已有文字设定。')
    support.write(tmp_path,'world/core_laws.json',{'core_laws':['明确规则']})
    with pytest.raises(FileNotFoundError,match='世界观存档不完整'):module._build_world_cache()


def test_rolling_current_plan_precedes_legacy_near_term_cache(tmp_path,monkeypatch):
    from test_serial_p2 import serial,proposal
    rolling=serial();proposal(rolling,tmp_path);rolling.commit(tmp_path,'roll-1')
    support.write(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002'}})
    support.write(tmp_path,'cache/no/near_term.json',{'chapters':[{'number':1,'title':'旧章','summary':'只属于第一章的旧计划'}]})
    monkeypatch.chdir(tmp_path);archive()._render_near_term_context()
    result=support.read(tmp_path,'cache/sync/near_term_we.md')
    assert '在既有处境里犹豫' in result and '只属于第一章的旧计划' not in result


def test_imported_sources_survive_trimming_and_rendering(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);module=archive()
    support.write(tmp_path,'meta/world_foundation.md','世界规则：交换记忆需要代价，不能自行恢复。')
    support.write(tmp_path,'meta/character_profiles.md','林舟不愿拿同伴的记忆换取自己的安全。')
    module._build_world_cache();module._build_character_cache()
    file=support.HERE.parents[1]/'nvl/trimmer_post/trimmer_post.py'
    spec=importlib.util.spec_from_file_location('imported_trimmer',file)
    trimmer=importlib.util.module_from_spec(spec);spec.loader.exec_module(trimmer)
    world=support.load(tmp_path,'cache/sync/world.json');characters=support.load(tmp_path,'cache/sync/characters.json')
    trimmed_world,_=trimmer.trim_world(world,{'foundation':['text'],'characters':['林舟']})
    trimmed_characters,_=trimmer.trim_characters(characters,{'characters':['林舟']})
    support.write(tmp_path,'cache/trimmer/world.json',trimmed_world)
    support.write(tmp_path,'cache/trimmer/characters.json',trimmed_characters)
    module._render_files('cache/trimmer/world.json,cache/trimmer/characters.json','story/0002/world.md,story/0002/characters.md')
    assert '交换记忆需要代价' in support.read(tmp_path,'story/0002/world.md')
    assert '林舟不愿拿同伴的记忆' in support.read(tmp_path,'story/0002/characters.md')
    assert trimmed_characters['profiles']['sha256']==characters['profiles']['sha256']


def test_preparing_managed_indexes_keeps_rolling_sources_stable(tmp_path,monkeypatch):
    from test_serial_p2 import serial,proposal
    rolling=serial();proposal(rolling,tmp_path);rolling.commit(tmp_path,'roll-1')
    before={p:support.digest(tmp_path,p) for p in ('meta/hooks.md','meta/debts.md')}
    monkeypatch.chdir(tmp_path);archive()._render_indexes()
    assert rolling.need_plan(tmp_path,'0002')['ready']
    assert before=={p:support.digest(tmp_path,p) for p in before}
