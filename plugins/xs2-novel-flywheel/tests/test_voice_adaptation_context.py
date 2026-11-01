import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'resources/workflows'
KEY = 'character_voice_adaptations_file'


def load(name):
    return json.loads((ROOT / name / 'definition.json').read_text(encoding='utf-8'))


def expand(text, values):
    for _ in range(3):
        for key, value in values.items():
            if isinstance(value, str):
                text = text.replace('{{' + key + '}}', value)
    return text


def test_confirmed_voice_adaptations_reach_writer_branches_and_reviewers():
    for stage, nodes in {
        'character': ['agent_voice'],
        'mvp': ['agent_cm', 'agent_se', 'agent_dw', 'agent_sw', 'agent_si'],
        'polish': ['agent_sc', 'agent_pl', 'agent_pp'],
        'reader-sim': ['agent_reader'],
    }.items():
        definition = load(stage)
        fields = {v['key']: v for v in definition['variables']}
        assert KEY in fields, f'{stage} cannot read adapted character voices'
        assert fields[KEY]['default'] == 'meta/character_voice_adaptations.md'
        assert fields[KEY]['type'] == 'file' and not fields[KEY]['required']
        values = {key: field.get('default', '') for key, field in fields.items()}
        values[KEY] = 'CONFIRMED_BOOK_ROLE_VOICE'
        for node in definition['nodes']:
            if node['id'] in nodes:
                assert 'CONFIRMED_BOOK_ROLE_VOICE' in expand(node.get('first_message', ''), values), (stage, node['id'])
