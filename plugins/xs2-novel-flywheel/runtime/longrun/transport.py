"""Meter native host models without replacing their responses or tools."""
from contextlib import contextmanager
from contextvars import ContextVar
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

CONTEXT=ContextVar('longrun_request_context',default={})


def ledger():
    file=Path(__file__).resolve().parents[2]/'resources/script-library/xs2/longrun/ledger.py'
    spec=importlib.util.spec_from_file_location('longrun_transport_ledger',file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def normalize_usage(message):
    raw=getattr(message,'usage_metadata',None) or {}
    meta=getattr(message,'response_metadata',None) or {};response=meta.get('token_usage') or meta.get('usage') or {}
    raw=raw if isinstance(raw,dict) else {};response=response if isinstance(response,dict) else {}
    output={'raw_usage_metadata':raw,'raw_response_usage':response}
    details_in=raw.get('input_token_details') or {};details_out=raw.get('output_token_details') or {}
    prompt_details=response.get('prompt_tokens_details') or {};completion_details=response.get('completion_tokens_details') or {}
    sources={
        'prompt_tokens':[response.get('prompt_tokens'),response.get('input_tokens'),raw.get('input_tokens')],
        'completion_tokens':[response.get('completion_tokens'),response.get('output_tokens'),raw.get('output_tokens')],
        'total_tokens':[response.get('total_tokens'),raw.get('total_tokens')],
        'cached_tokens':[response.get('prompt_cache_hit_tokens'),prompt_details.get('cached_tokens'),details_in.get('cache_read')],
        'reasoning_tokens':[completion_details.get('reasoning_tokens'),details_out.get('reasoning')],
    }
    for key,values in sources.items():
        value=next((n for n in values if type(n) is int and n>=0),None)
        if value is not None:output[key]=value
    if not all(k in output for k in ('prompt_tokens','completion_tokens')):
        return {**output,'usage_status':'unknown'}
    output.setdefault('total_tokens',output['prompt_tokens']+output['completion_tokens'])
    valid=(output['total_tokens']==output['prompt_tokens']+output['completion_tokens']
        and output.get('cached_tokens',0)<=output['prompt_tokens'] and output.get('reasoning_tokens',0)<=output['completion_tokens'])
    output['usage_status']='complete' if valid else 'incomplete'
    return output


def refresh_pricing(root):
    from contextlib import closing
    from src.workflow.pricing import price_usage_calls
    log=ledger()
    with closing(log.connect(root)) as db:
        calls=log._call_rows(db);value=log.config(root,db)['config']
    priced=price_usage_calls(calls,pricing_config=value.get('pricing'))
    log.record_pricing(root,calls,priced)
    return priced


def usage_callback(root,model,metadata,max_output_tokens):
    from langchain_core.callbacks import AsyncCallbackHandler
    log=ledger()
    class Usage(AsyncCallbackHandler):
        raise_error=True
        def __init__(self):self.calls={}
        async def on_chat_model_start(self,serialized,messages,*,run_id,**kwargs):
            size=sum(len(str(getattr(message,'content','')).encode('utf-8')) for batch in messages for message in batch)
            # UTF-8 bytes plus protocol allowance is a conservative reservation,
            # not a reported measurement of actual provider tokens.
            projected_cost=None;value=log.config(root)['config']
            if value.get('limits',{}).get('max_configured_cost') is not None:
                from src.workflow.pricing import price_usage_calls
                refresh_pricing(root)
                reserved=size+max_output_tokens+8192;provider,name=model.split(':',1)
                projected=price_usage_calls([{'model_id':model,'provider':provider,'model':name,'timestamp':log.now(),
                    'usage_status':'complete','prompt_tokens':reserved,'completion_tokens':reserved,'total_tokens':2*reserved}],pricing_config=value.get('pricing'))['calls'][0]
                if projected.get('cost_status')=='priced':projected_cost=projected['cost']['amount']
            call=log.reserve_call(root,{**metadata,'model_id':model,'run_id':str(run_id)},size+max_output_tokens+8192,projected_cost)
            self.calls[str(run_id)]=call
            log.event(root,'request_start',{'call_id':call,'model_id':model,**metadata})
        async def on_llm_end(self,response,*,run_id,**kwargs):
            call=self.calls.get(str(run_id))
            if not call:return
            generation=response.generations[0][0] if response.generations and response.generations[0] else None
            message=getattr(generation,'message',None)
            if message is None:message=SimpleNamespace(usage_metadata={},response_metadata=getattr(response,'llm_output',{}) or {})
            data={'status':'completed',**normalize_usage(message)}
            log.finish_call(root,call,data)
        async def on_llm_error(self,error,*,run_id,**kwargs):
            call=self.calls.get(str(run_id))
            if call:log.finish_call(root,call,{'status':'failed','usage_status':'unknown','error_type':type(error).__name__})
    return Usage()


@contextmanager
def metered_models(root):
    import src.core.llm_client as client
    from src.core.model_manager import get_model_manager
    original=client.create_llm;log=ledger();value=log.config(root)['config']
    approved=value.get('routes',{})
    def create(*args,**kwargs):
        model=kwargs.get('model_override') or kwargs.get('model')
        if model not in value['models']:raise ValueError('长跑禁止未授权模型或隐式回退')
        manager=get_model_manager();provider=manager.get_provider(model.split(':',1)[0]) or {}
        expected=approved.get(model)
        if not expected or str(provider.get('base_url','')).rstrip('/')!=str(expected).rstrip('/'):
            raise ValueError('模型外发目的地与本次授权不符')
        kwargs['provider_retries_enabled']=False
        kwargs.setdefault('timeout',value.get('request_timeout_seconds',600))
        instance=original(*args,**kwargs)
        resolved=(getattr(instance,'metadata',None) or {}).get('determinflow_model_id')
        if resolved and resolved!=model:raise ValueError('模型实际解析路径不符')
        callback=usage_callback(root,model,dict(CONTEXT.get()),value.get('max_output_tokens',16000))
        instance.callbacks=[*(getattr(instance,'callbacks',None) or []),callback]
        return instance
    previous_context=getattr(client,'_xs2_longrun_context',None)
    client._xs2_longrun_context=CONTEXT;client.create_llm=create
    try:yield
    finally:
        client.create_llm=original
        if previous_context is None:delattr(client,'_xs2_longrun_context')
        else:client._xs2_longrun_context=previous_context


async def request(root,model,system,user,metadata):
    from langchain_core.messages import SystemMessage,HumanMessage
    import src.core.llm_client as client
    create_llm=client.create_llm;context=getattr(client,'_xs2_longrun_context',CONTEXT)
    value=ledger().config(root)['config'];token=context.set(metadata)
    try:
        # Match native workflow requests: receive streaming heartbeats/tokens,
        # then let ainvoke aggregate one complete response and usage record.
        model_client=create_llm(model_override=model,streaming=True,
            model_params={'max_tokens':value.get('max_output_tokens',16000)})
        response=await model_client.ainvoke([SystemMessage(content=system),HumanMessage(content=user)])
        content=response.content
        if isinstance(content,list):content=''.join(p.get('text','') for p in content if isinstance(p,dict))
        return str(content)
    finally:context.reset(token)
