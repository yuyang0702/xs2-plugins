"""Verify delivery of selective scene detail, not a numerical prose score."""
import copy
import json
import pytest
from test_length_quality import PLUGIN

ROLES=['novel-writer','novel-single-writer','novel-dialogue-writer',
       'novel-action-writer','novel-description-writer','novel-internal-writer',
       'novel-transition-writer','novel-multi-scene-writer','novel-storyboard-integrator',
       'novel-polisher','novel-professional-polisher','novel-self-critic','xs2-reader-sim']


@pytest.mark.parametrize('role',ROLES)
def test_actual_production_prompts_receive_one_scene_distance_contract(monkeypatch,role):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder
    resources=PLUGIN/'resources'
    agents=json.loads((resources/'agents.json').read_text(encoding='utf8'))['agents']
    prompts=json.loads((resources/'prompts.json').read_text(encoding='utf8'))['agents']
    definition=AgentDefinition(agent_type=role,**agents[role])
    monkeypatch.setattr('src.agent.definition.get_agent_definition',lambda _:definition)
    class Manager:
        def get_sections(self,key):return copy.deepcopy(prompts[key]['sections'])
    actual=PromptBuilder(Manager()).build(role,is_workflow=True,include_skills=False,include_rules=False)
    assert actual.count('## 叙述距离与详略')==1
    assert '工艺因果' in actual and '例行' in actual
    assert '手艺、验物、搬运等实际动作保留' not in actual
    assert '不冻结原稿的段落' in actual or role in ['novel-self-critic','xs2-reader-sim']


def test_scene_planner_allocates_attention_inside_existing_schema():
    prompts=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf8'))['agents']
    role=next(s['content'] for s in prompts['novel-multi-scene-planner']['sections']
              if s['name']=='novel_multi_scene_planner_role')
    assert 'turn' in role and '近看' in role and '概述' in role
    assert '不新增字段' in role and '知识边界' in role


def test_dialogue_learning_is_consolidated_without_losing_legacy_or_adapted_sources():
    prompts=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf8'))['agents']
    for role in ['novel-single-writer','novel-dialogue-writer','novel-storyboard-integrator',
                 'novel-polisher','novel-professional-polisher','novel-self-critic','xs2-reader-sim']:
        contract=next(s['content'] for s in prompts[role]['sections'] if s['name']=='dialogue_learning_contract')
        assert len(contract)<1000  # One canonical contract replaces duplicated paragraphs.
        for term in ['旧档','原作','前后回应','上一句话','必要的公开要求','有限证词','自我诊断','字数范围','场景终点','已经成立的信息']:
            assert term in contract
        assert '沈照夜' not in contract and '陆承远' not in contract


def test_review_does_not_turn_antagonistic_relationship_into_a_fixed_response():
    prompts=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf8'))['agents']
    for role,name in [('novel-self-critic','nsc_dimensions'),('xs2-reader-sim','payoff_and_naturalness')]:
        contract=next(s['content'] for s in prompts[role]['sections'] if s['name']==name)
        assert '临时合作' in contract and '实际承诺与记录' in contract
        assert '自然读感与戏剧张力偏好分开' in contract
