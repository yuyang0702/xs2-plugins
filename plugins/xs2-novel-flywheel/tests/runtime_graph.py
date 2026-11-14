"""Legacy literary-chain tests contract transparent native boundary nodes.

Native task persistence/fencing/budgets are exercised separately by
test_native_preflight and the real API copy acceptance. These engine fixtures
mock Tasks in memory and deliberately lack native on-disk task ownership.
"""
import copy


def literary_graph(definition):
    result=copy.deepcopy(definition)
    guards={n['id'] for n in result['nodes'] if n['id'].startswith('script_budget_') or n['id'] in ('script_production_start','script_production_finish') or n.get('node_type')=='novel_rehearsal'}
    for key in guards:
        incoming=[e for e in result['edges'] if e['target']==key]
        outgoing=[e for e in result['edges'] if e['source']==key]
        result['edges']=[e for e in result['edges'] if e['source']!=key and e['target']!=key]
        result['edges']+=[{**a,'target':b['target']} for a in incoming for b in outgoing]
    result['nodes']=[n for n in result['nodes'] if n['id'] not in guards]
    for scheme in result.get('execution_schemes',[]):scheme['selected_node_ids']=[n for n in scheme.get('selected_node_ids',[]) if n not in guards]
    return result
