import json

from test_fragment_length import setup, commit
from test_length_quality import quality, policy, write


def test_rejected_copy_rotates_source_range_and_preserves_original_bytes(tmp_path):
    state, outputs, raw = setup(tmp_path)
    q = quality()
    guard = json.loads((tmp_path / outputs['length_commit_guard']).read_text(encoding='utf8'))
    selected = guard['fragment']
    copied = raw[selected['start']:selected['end']].decode('utf8') + '\n\n' + '丙' * 35
    _, receipt = commit(tmp_path, outputs, copied, 'task-copy-rejected')
    assert not receipt['accepted']
    assert (tmp_path / 'story/0001/chapter.md').read_bytes() == raw
    state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    write(tmp_path, '.novel-project.json', json.dumps(state))
    following = q.prepare_execution(tmp_path, '0001', '130-160', 'length_only')
    next_guard = json.loads((tmp_path / following['length_commit_guard']).read_text(encoding='utf8'))
    span = next_guard['fragment']
    assert span['end'] <= selected['start'] or span['start'] >= selected['end']
    assert '复制' in (tmp_path / following['length_execution_context']).read_text(encoding='utf8')


def test_focused_writer_finishes_with_selected_text_and_budget_after_author_instructions(tmp_path):
    state, outputs, raw = setup(tmp_path)
    text = (tmp_path / outputs['length_execution_context']).read_text(encoding='utf8')
    guard = json.loads((tmp_path / outputs['length_commit_guard']).read_text(encoding='utf8'))
    selected = raw[guard['fragment']['start']:guard['fragment']['end']].decode('utf8')
    tail = text.split('【本轮最终交付边界】')[-1]
    assert '【本轮最终交付边界】' in text
    assert selected in tail
    assert '仅' in tail and 'body' in tail
    assert text.rfind(selected) > text.index('【原始作者约束')
