import copy

from test_length_quality import policy


def test_new_book_recipe_resolves_current_provider_models_without_mutating_configuration(monkeypatch):
    p=policy();monkeypatch.setattr(p,'NEW_BOOK_DEFAULTS_ENABLED',True)
    providers={'ark-user':{'name':'火山方舟','base_url':'https://ark.cn-beijing.volces.com/api/v3','models':['new-writer']},
               'flare-user':{'name':'ModelFlare Anthropic','provider_type':'anthropic','base_url':'https://modelflare.dev/v1','models':['new-polisher']}}
    original=copy.deepcopy(providers)
    result=p.new_book_defaults(providers,'system:new-default')
    assert result=={'analysisModel':'system:new-default','writerModel':'ark-user:new-writer','polishModel':'flare-user:new-polisher','values':{'writer_type':'muti'}}
    assert providers==original


def test_unavailable_role_or_unverified_release_does_not_silently_substitute_a_provider(monkeypatch):
    p=policy();monkeypatch.setattr(p,'NEW_BOOK_DEFAULTS_ENABLED',True)
    assert p.new_book_defaults({},'system:default')=={}
    monkeypatch.setattr(p,'NEW_BOOK_DEFAULTS_ENABLED',False)
    assert p.new_book_defaults({'volcengine':{'models':['writer']}},'system:default')=={}
