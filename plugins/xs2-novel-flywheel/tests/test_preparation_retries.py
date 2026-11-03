import json
from pathlib import Path


def test_preparation_nodes_use_same_bounded_retry_policy_as_production():
    root = Path(__file__).resolve().parents[1] / 'resources/workflows'
    for stage in ['build', 'character', 'story-plan']:
        workflow = json.loads((root / stage / 'definition.json').read_text(encoding='utf-8'))
        for node in workflow['nodes']:
            if node.get('node_type') == 'agent':
                assert node.get('auto_retry_count', 0) == 2, (stage, node['id'])
                assert node.get('auto_retry_interval_seconds') == 5
                assert not node.get('fail_auto_skip', False)
