import asyncio
import importlib.util
from pathlib import Path
from langchain_openai import ChatOpenAI

ADOPTION = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/console_service/adoption.py'
import sys
package_spec = importlib.util.spec_from_file_location('transport_service', ADOPTION.parent / 'console_service.py', submodule_search_locations=[str(ADOPTION.parent)])
package = importlib.util.module_from_spec(package_spec)
sys.modules[package_spec.name] = package
package_spec.loader.exec_module(package)
spec = importlib.util.spec_from_file_location('transport_service.adoption', ADOPTION)
adoption = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adoption)


def test_adoption_does_not_close_langchain_shared_transports(monkeypatch):
    first = ChatOpenAI(api_key='offline-placeholder', base_url='http://127.0.0.1:1')
    second = ChatOpenAI(api_key='offline-placeholder', base_url='http://127.0.0.1:1')
    assert first.root_async_client._client is second.root_async_client._client
    assert first.root_client._client is second.root_client._client
    asyncio.run(adoption._close_model(first))
    assert not second.root_async_client._client.is_closed
    assert not second.root_client._client.is_closed
    import httpx
    async def respond(request):
        return httpx.Response(200, json={'id': 'offline', 'choices': [
            {'index': 0, 'message': {'role': 'assistant', 'content': 'healthy'},
             'finish_reason': 'stop'}]}, request=request)
    monkeypatch.setattr(second.root_async_client._client, '_transport', httpx.MockTransport(respond))
    # No socket: use the installed SDK and surviving HTTPX client against a mock transport.
    monkeypatch.setattr(second.root_async_client._client, '_mounts', {})
    async def request():
        result = await second.root_async_client.chat.completions.create(
            model='offline', messages=[{'role': 'user', 'content': 'test'}])
        assert result.choices[0].message.content == 'healthy'
    asyncio.run(request())



def test_explicit_owned_model_is_closed():
    class Owned:
        closed = False
        async def aclose(self):
            self.closed = True
    model = Owned()
    asyncio.run(adoption._close_model(model))
    assert model.closed


def test_diagnostics_redacts_arbitrary_provider_text():
    error = ConnectionError('secret-key https://secret.example/path')
    error.__cause__ = RuntimeError('Cannot send a request, as the client has been closed.')
    details = package.assistant._provider_diagnostics(error) if hasattr(package, 'assistant') else __import__('transport_service.assistant', fromlist=['_provider_diagnostics'])._provider_diagnostics(error)
    assert details['closed_client']
    assert 'secret' not in str(details)
    assert details['types'] == ['ConnectionError', 'RuntimeError']


def test_isolated_error_retains_only_safe_remote_diagnostics():
    error = ConnectionError('request child connection failed')
    error.provider_diagnostics = {'types': ['APIConnectionError', 'SSLEOFError', 'secret https://example.invalid'],
                                  'tls': True, 'closed_client': False, 'proxy': 'secret',
                                  'errnos': [8, 'secret'], 'payload': 'secret-key'}
    helper = __import__('transport_service.assistant', fromlist=['_provider_diagnostics'])
    details = helper._provider_diagnostics(error)
    assert 'SSLEOFError' in details['types'] and details['tls'] is True
    assert details['errnos'] == [8]
    assert 'secret' not in str(details) and details['proxy'] is False
