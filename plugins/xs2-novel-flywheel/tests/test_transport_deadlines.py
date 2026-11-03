"""Offline regressions for whole-request deadlines and cancellation/publication."""
import asyncio
import copy
import json
import sys
import threading
import uuid
from types import SimpleNamespace

import pytest

from test_quick_adoption import service, setup_book, catalog, merge, runner, decision


class Clock:
    def __init__(self):
        self.now = 100.0
        self.delays = []
        self.after_sleep = None

    def time(self):
        return self.now

    async def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay
        if self.after_sleep:
            self.after_sleep()


class AsyncClock:
    """Replace only the service's clock; the actual asyncio event loop stays real."""
    def __init__(self, clock):
        self.clock = clock

    def get_running_loop(self):
        return self.clock

    async def sleep(self, delay):
        await self.clock.sleep(delay)

    def __getattr__(self, name):
        return getattr(asyncio, name)


class Reply:
    def __init__(self, response, before=None):
        self.response = response
        self.before = before
        self.closed = False

    async def ainvoke(self, messages):
        if self.before:
            self.before()
        if isinstance(self.response, BaseException):
            raise self.response
        return SimpleNamespace(content=self.response)

    async def aclose(self):
        self.closed = True


def jobs_for(kind, root, factory, clock, monkeypatch, libraries=None, guard=None, publish=None):
    plugin = service()
    if kind == 'assistant':
        jobs = plugin.NovelAssistantJobs(factory, lambda **kwargs: None)
        payload = {'question': 'Explain this scene', 'purpose': 'general'}
    else:
        setup_book(root)
        jobs = plugin.ReferenceAdoptionJobs(factory, lambda: libraries if libraries is not None else [catalog()],
                                           merge, publish or runner, threading.RLock(), guard=guard)
        payload = {'advisor_entry_id': 'adviser-1'}
    module = sys.modules[type(jobs).__module__]
    monkeypatch.setattr(module, 'asyncio', AsyncClock(clock))
    return jobs, payload


def execute(jobs, root, payload):
    identifier = str(uuid.uuid4())
    async def run():
        jobs.start(root, identifier, payload)
        await asyncio.gather(*list(jobs.tasks.values()))
    asyncio.run(run())
    result = (next(entry for entry in jobs.history(root) if entry['id'] == identifier)
              if hasattr(jobs, 'history') else jobs.get(root, identifier))
    return result


@pytest.mark.parametrize('kind', ['assistant', 'adoption'])
def test_retry_delay_cannot_exceed_total_budget_or_construct_second_model(tmp_path, monkeypatch, kind):
    clock = Clock()
    created = []
    def factory(**kwargs):
        created.append(kwargs)
        return Reply(ConnectionError('transient'), before=lambda: setattr(clock, 'now', clock.now + 599))
    jobs, payload = jobs_for(kind, tmp_path, factory, clock, monkeypatch)
    result = execute(jobs, tmp_path, payload)
    assert result['status'] == 'failed'
    assert len(created) == 1
    assert clock.delays == []
    assert not (tmp_path / 'learning/active.json').exists()
    assert not result.get('reply')


@pytest.mark.parametrize('kind', ['assistant', 'adoption'])
def test_cancelled_model_is_never_retried_or_published(tmp_path, monkeypatch, kind):
    clock = Clock()
    created = []
    started = None
    class Waiting(Reply):
        async def ainvoke(self, messages):
            started.set()
            await asyncio.Future()
    def factory(**kwargs):
        created.append(kwargs)
        return Waiting('not publishable')
    jobs, payload = jobs_for(kind, tmp_path, factory, clock, monkeypatch)
    identifier = str(uuid.uuid4())
    async def run():
        nonlocal started
        started = asyncio.Event()
        jobs.start(tmp_path, identifier, payload)
        tasks = list(jobs.tasks.values())
        await started.wait()
        tasks[0].cancel()
        await asyncio.gather(*tasks)
    asyncio.run(run())
    result = (next(entry for entry in jobs.history(tmp_path) if entry['id'] == identifier)
              if kind == 'assistant' else jobs.get(tmp_path, identifier))
    assert result['status'] == 'failed'
    assert result['error_code'] == 'interrupted'
    assert len(created) == 1 and clock.delays == []
    assert not result.get('reply') and not (tmp_path / 'learning/active.json').exists()


@pytest.mark.parametrize('changed', ['source', 'owner'])
def test_adoption_rechecks_source_and_owner_before_retry_request(tmp_path, monkeypatch, changed):
    clock = Clock()
    libraries = [catalog()]
    allowed = True
    created = []
    def guard(root):
        if not allowed:
            raise ValueError('owner no longer authorizes this workspace')
    def factory(**kwargs):
        created.append(kwargs)
        return Reply(ConnectionError('transient') if len(created) == 1 else json.dumps(
            {'decisions': [decision()], 'voice_adaptations': []}, ensure_ascii=False))
    jobs, payload = jobs_for('adoption', tmp_path, factory, clock, monkeypatch, libraries=libraries, guard=guard)
    def change_binding():
        nonlocal allowed
        if changed == 'source':
            libraries[0]['profile']['markdown'] = 'source replaced during retry delay'
        else:
            allowed = False
    clock.after_sleep = change_binding
    result = execute(jobs, tmp_path, payload)
    assert len(created) == 1, 'do not send book/source context after ownership or source binding changed'
    assert result['status'] in {'failed', 'review_required'}
    assert not (tmp_path / 'learning/active.json').exists()


@pytest.mark.parametrize('kind', ['assistant', 'adoption'])
def test_success_after_transient_uses_remaining_budget_and_publishes_once(tmp_path, monkeypatch, kind):
    clock = Clock()
    created = []
    publications = []
    answer = ('Use the existing conflict to develop their relationship.' if kind == 'assistant'
              else json.dumps({'decisions': [decision()], 'voice_adaptations': []}, ensure_ascii=False))
    def factory(**kwargs):
        created.append(kwargs)
        return Reply(ConnectionError('transient'), before=lambda: setattr(clock, 'now', clock.now + 150)) if len(created) == 1 else Reply(answer)
    def publish(root, selection):
        publications.append(copy.deepcopy(selection))
        runner(root, selection)
    jobs, payload = jobs_for(kind, tmp_path, factory, clock, monkeypatch, publish=publish)
    result = execute(jobs, tmp_path, payload)
    assert len(created) == 2 and clock.delays == [2]
    assert created[0]['timeout'] == 600
    assert created[1]['timeout'] == 448
    assert all(call['provider_retries_enabled'] is False for call in created)
    if kind == 'assistant':
        assert result['status'] == 'completed' and result['reply'] == answer
        assert len([entry for entry in jobs.history(tmp_path) if entry.get('status') == 'completed']) == 1
    else:
        assert result['status'] == 'applied'
        assert len(publications) == 1
        active = json.loads((tmp_path / 'learning/active.json').read_text(encoding='utf-8'))
        assert (tmp_path / active['blueprint_path']).is_file()
        assert len(list((tmp_path / 'learning/blueprints').glob('v*.json'))) == 1


def test_adoption_transport_retry_is_global_across_validation_correction(tmp_path, monkeypatch):
    clock = Clock()
    created = []
    requests = []
    class Review(Reply):
        async def ainvoke(self, messages):
            requests.append(messages)
            if len(requests) in {1, 3}:
                raise ConnectionError('transient')
            return SimpleNamespace(content='{"decisions": []}')
    def factory(**kwargs):
        created.append(kwargs)
        return Review('unused')
    jobs, payload = jobs_for('adoption', tmp_path, factory, clock, monkeypatch)
    result = execute(jobs, tmp_path, payload)
    assert result['status'] == 'failed'
    assert len(created) == 2 and len(requests) == 3
    assert clock.delays == [2], 'a validation correction must not reset the transport retry allowance'
    assert not (tmp_path / 'learning/active.json').exists()


def test_adoption_correction_cannot_reset_total_deadline(tmp_path, monkeypatch):
    clock = Clock()
    created = []
    requests = []
    class Review(Reply):
        async def ainvoke(self, messages):
            requests.append(messages)
            clock.now += 601
            return SimpleNamespace(content='{"decisions": []}')
    def factory(**kwargs):
        created.append(kwargs)
        return Review('unused')
    jobs, payload = jobs_for('adoption', tmp_path, factory, clock, monkeypatch)
    result = execute(jobs, tmp_path, payload)
    assert result['status'] == 'failed'
    assert len(requests) == 1, 'do not issue the correction request after the whole-request deadline'
    assert len(created) == 1 and clock.delays == []
    assert not (tmp_path / 'learning/active.json').exists()


@pytest.mark.parametrize('outcome', ['success', 'retry', 'cancel'])
def test_assistant_closes_each_explicit_owned_model(tmp_path, monkeypatch, outcome):
    clock = Clock()
    models = []
    class Owned(Reply):
        close_count = 0
        async def aclose(self):
            self.close_count += 1
            await super().aclose()
    def factory(**kwargs):
        response = (ConnectionError('transient') if outcome == 'retry' and not models else
                    asyncio.CancelledError() if outcome == 'cancel' else 'Useful scene advice.')
        model = Owned(response)
        models.append(model)
        return model
    jobs, payload = jobs_for('assistant', tmp_path, factory, clock, monkeypatch)
    result = execute(jobs, tmp_path, payload)
    assert result['status'] == ('failed' if outcome == 'cancel' else 'completed')
    assert len(models) == (2 if outcome == 'retry' else 1)
    assert all(model.closed and model.close_count == 1 for model in models)


def test_early_assistant_context_failure_finishes_receipt_without_constructing_model(tmp_path, monkeypatch):
    clock = Clock()
    created = []
    jobs, payload = jobs_for('assistant', tmp_path, lambda **kwargs: created.append(kwargs), clock, monkeypatch)
    def broken_context(**kwargs):
        raise RuntimeError('context unavailable')
    jobs.support_loader = broken_context
    result = execute(jobs, tmp_path, payload)
    assert result['status'] == 'failed' and result.get('finished_at')
    assert created == [] and not result.get('reply')


def test_provider_diagnostics_survives_hostile_exception_and_model_properties(tmp_path, monkeypatch):
    clock = Clock()
    jobs, _ = jobs_for('assistant', tmp_path, lambda **kwargs: None, clock, monkeypatch)
    module = sys.modules[type(jobs).__module__]
    class HostileError(Exception):
        def __str__(self):
            raise RuntimeError('must not replace the provider failure')
        @property
        def errno(self):
            raise RuntimeError('hostile errno')
    class HostileModel:
        @property
        def root_async_client(self):
            raise RuntimeError('hostile model property')
    diagnostic = module._provider_diagnostics(HostileError(), HostileModel())
    assert diagnostic['types'] == ['HostileError']
    assert diagnostic['transports_closed'] == [] and diagnostic['errnos'] == []
