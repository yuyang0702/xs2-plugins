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


def test_confirmed_voice_adaptations_reach_writer_branches_and_reviewers(tmp_path):
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
        if stage=='polish':
            from test_local_revision import module
            from test_book_contract import put
            put(tmp_path,'story/0001/chapter.md','正文。')
            put(tmp_path,'meta/character_voice_adaptations.md','CONFIRMED_BOOK_ROLE_VOICE')
            m=module();outputs=m.prepare(tmp_path,'0001','voice-input','1-5000')
            put(tmp_path,'critique.json',{'feels_human':True,'issues':[]})
            m.writer_input(tmp_path,outputs['revision_dir'],'critique.json')
            for key in ('revision_source_model','revision_editor_model'):
                values[key]=(tmp_path/outputs[key]).read_text(encoding='utf8')
        for node in definition['nodes']:
            if node['id'] in nodes:
                assert 'CONFIRMED_BOOK_ROLE_VOICE' in expand(node.get('first_message', ''), values), (stage, node['id'])
