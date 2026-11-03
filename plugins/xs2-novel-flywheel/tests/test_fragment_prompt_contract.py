import copy
import json

from test_length_quality import PLUGIN, policy, quality, write
from test_fragment_length import setup


def render(sections, append, monkeypatch):
    from src.agent.definition import AgentDefinition
    from src.session.prompt_builder import PromptBuilder
    from src.prompts.orchestrator import PromptOrchestrator
    resource = json.loads((PLUGIN / 'resources/agents.json').read_text(encoding='utf-8'))['agents']['novel-professional-polisher']
    agent = AgentDefinition(agent_type='novel-professional-polisher', **resource)
    monkeypatch.setattr('src.agent.definition.get_agent_definition', lambda key: agent if key == agent.agent_type else None)
    class ResourceManager:
        def get_sections(self, template):
            assert template == agent.prompt_template
            return copy.deepcopy(sections)
    manager = ResourceManager()
    built = PromptBuilder(manager).build(agent.agent_type, custom_append=append, is_workflow=True, include_skills=False, include_rules=False)
    direct = PromptOrchestrator(manager).build_sub_agent_prompt(custom_append=append, agent_type=agent.agent_type,
        prompt_template=agent.prompt_template, is_workflow_node=True, include_skills=False, include_rules=False)
    assert built == direct
    return built


def test_real_professional_template_delivers_fragment_contract_once_after_full_chapter_rules(tmp_path, monkeypatch):
    _, outputs, _ = setup(tmp_path)
    contract = (tmp_path / outputs['length_execution_system']).read_text(encoding='utf-8')
    sections = json.loads((PLUGIN / 'resources/prompts.json').read_text(encoding='utf-8'))['agents']['novel-professional-polisher']['sections']
    final = render(sections, contract, monkeypatch)
    output_rule = next(s['content'] for s in sections if s['name'] == 'npp_output')
    assert final.count(contract) == 1
    assert final.index(contract) > final.index(output_rule)
    assert final.endswith(contract) and '{{custom_append}}' not in final


def test_empty_append_is_byte_identical_to_old_professional_prompt(monkeypatch):
    sections = json.loads((PLUGIN / 'resources/prompts.json').read_text(encoding='utf-8'))['agents']['novel-professional-polisher']['sections']
    old = [s for s in sections if s['name'] != 'custom_task_context']
    assert render(sections, '', monkeypatch) == render(old, '', monkeypatch)
    assert render(sections, '  ', monkeypatch) == render(old, '', monkeypatch)


def test_delivered_contract_strategy_gets_one_recorded_budget_migration(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '衣'*4360)
    state = {'readerRepairCount': 2, 'lengthRepairCycle': 2, 'lengthRepairCount': 3, 'lengthRepairTotal': 12,
             'lengthRepairStrategy': 'fragment-v2', 'autoLengthRepairLimit': 3,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    action = policy().next_action(tmp_path, state, 'polish')
    assert action['action'] == 'advance'
    state.update(action['updates'])
    assert state['lengthRepairStrategy'] == quality().LENGTH_REPAIR_STRATEGY == 'fragment-v6'
    assert state['lengthRepairTotal'] == 13 and state['lengthRepairCount'] == 1
    for _ in range(2): state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    assert policy().next_action(tmp_path, state, 'polish')['action'] == 'pause'
    assert state['readerRepairCount'] == 2 and state['lengthRepairTotal'] == 15
