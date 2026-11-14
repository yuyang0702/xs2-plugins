import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest

from test_quick_adoption import service


def test_topic_selection_blinds_reader_and_recommends_highest_ranked_feasible_story(tmp_path):
    openings = ['收音机先报出了她的死讯。', '母亲把房契塞进我的饭盒。', '河水退了，渡船还在敲钟。']
    options = [dict(title=f'题名{i}', genre=genre, opening=opening, premise=f'构想{i}',
                    choice=f'抉择{i}', cost=f'代价{i}', middle=f'中段{i}', ending=f'结尾{i}')
               for i, (genre, opening) in enumerate(zip(('科幻', '家庭', '民俗'), openings))]
    calls = []

    class Model:
        async def ainvoke(self, messages):
            system, human = [value for _, value in messages]
            calls.append(system)
            if len(calls) == 1:
                assert '作者只给顾问看的偏好' in human
                return SimpleNamespace(content=json.dumps({'candidates': options}, ensure_ascii=False))
            data = json.loads(human)
            if 'openings' in data:
                assert set(data) == {'openings'}
                rows = data['openings']
                assert all(set(row) == {'id', 'opening'} for row in rows)
                assert set(row['opening'] for row in rows) == set(openings)
                assert not any(value in human for value in ('作者只给顾问看的偏好', '题名', '构想', '中段'))
                rows.sort(key=lambda row: openings.index(row['opening']))
                return SimpleNamespace(content=json.dumps({'ranking': [dict(id=row['id'], excerpt=row['opening'][:3],
                    reason='马上发生的意外让我想接着看。', question='她接下来怎么办？') for row in rows]}, ensure_ascii=False))
            assert set(data) == {'target_words', 'candidates'}
            assert data['target_words'] == '10000'
            rows = data['candidates']
            assert 'ranking' not in human and '作者只给顾问看的偏好' not in human
            return SimpleNamespace(content=json.dumps({'assessments': [dict(id=row['id'],
                verdict='too_thin' if row['title'] == '题名0' else 'fits', reason='中段有独立的后果。',
                development='先应付选择引发的后果，再让结尾回应代价。', risk='避免用背景解释填篇幅。')
                for row in rows]}, ensure_ascii=False))

    jobs = service().create_assistant(lambda **_: Model(), lambda **_: None)

    async def run():
        jobs.start(tmp_path, 'topics', {'purpose': 'advisor', 'advisor_task': 'topic_selection',
            'question': '作者只给顾问看的偏好', 'project': {'mode': 'short', 'values': {}}})
        await asyncio.gather(*jobs.tasks.values())
        return jobs.history(tmp_path)[0]

    entry = asyncio.run(run())
    assert entry['status'] == 'completed'
    result = entry['topic_selection']
    candidates = {row['id']: row for row in result['candidates']}
    assert candidates[result['ranking'][0]['id']]['opening'] == openings[0]
    assert candidates[result['recommended_id']]['opening'] == openings[1]
    assert len(calls) == 3
    assert not (tmp_path / 'story').exists()
    assert not (tmp_path / '.novel-project.json').exists()


def test_topic_selection_rejects_invented_reader_evidence_and_can_leave_recommendation_empty():
    topics = importlib.import_module(f'{service().__name__}.topic_selection')
    opening = '剪刀还在她手里，门铃又响了。'
    candidate = {'id': 'topic-1', 'title': '门铃', 'opening': opening}
    ranking = [{'id': 'B', 'excerpt': '剪刀落了地', 'reason': '马上有事发生', 'question': '谁来了？'}]
    with pytest.raises(ValueError, match='引文'):
        topics.parse_ranking(json.dumps({'ranking': ranking}), {'B': candidate})
    ranking[0]['excerpt'] = '门铃又响了'
    parsed = topics.parse_ranking(json.dumps({'ranking': ranking}), {'B': candidate})
    result = topics.assemble([candidate], parsed, [{'id': 'topic-1', 'verdict': 'too_thin'}], '10000')
    assert result['topic_selection']['ranking'][0]['id'] == 'topic-1'
    assert result['topic_selection']['recommended_id'] is None
