"""Reviewable field-level migration of plugin-owned workflow behavior.

Keep user models, positions, variables and unrelated wording. A non-unique
message delta fails closed for explicit review instead of overwriting it.
"""
import copy
import difflib

PROTECTED={'model_override','model_params_override','position'}


def merge_message(before,after,current):
    if current==before:return after
    if current==after:return current
    result=current
    for tag,a,z,b,y in reversed(difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes()):
        if tag=='equal':continue
        old,new=before[a:z],after[b:y]
        if old:
            if result.count(old)!=1:raise ValueError('custom message delta is not unique; manual review required')
            result=result.replace(old,new,1)
        elif a==0:result=new+result
        elif a==len(before):result+=new
        else:
            anchor=before[a:a+120]
            if not anchor or result.count(anchor)!=1:raise ValueError('custom message insertion anchor is not unique; manual review required')
            result=result.replace(anchor,new+anchor,1)
    return result


def merge_definition(before,after,current):
    result=copy.deepcopy(current);old={n['id']:n for n in before['nodes']};actual={n['id']:n for n in result['nodes']}
    for node in after['nodes']:
        key=node['id']
        if key not in actual:
            result['nodes'].append(copy.deepcopy(node));actual[key]=result['nodes'][-1];continue
        if key not in old:continue
        for field,value in node.items():
            if field in PROTECTED or old[key].get(field)==value:continue
            if field=='first_message':actual[key][field]=merge_message(old[key].get(field,''),value,actual[key].get(field,''))
            elif field=='node_params':
                for name,new in value.items():
                    if old[key].get(field,{}).get(name)==new:continue
                    if name in ('model','model_params','temperature','max_tokens'):continue
                    prior=actual[key].setdefault(field,{}).get(name)
                    if prior not in (old[key].get(field,{}).get(name),new):raise ValueError('custom node parameter conflict: '+key+'/'+name)
                    actual[key][field][name]=copy.deepcopy(new)
            elif actual[key].get(field) in (old[key].get(field),value):actual[key][field]=copy.deepcopy(value)
            else:raise ValueError('custom node field conflict: '+key+'/'+field)
    variables={v['key'] for v in result.get('variables',[])}
    result.setdefault('variables',[]).extend(copy.deepcopy(v) for v in after.get('variables',[]) if v['key'] not in variables)
    prior_variables={v['key']:v for v in before.get('variables',[])}
    actual_variables={v['key']:v for v in result['variables']}
    for variable in after.get('variables',[]):
        prior=prior_variables.get(variable['key'])
        if prior is None:continue
        for field in ('source_type','type','required','hidden'):
            default={'source_type':'input','type':'text','required':False,'hidden':False}[field]
            if prior.get(field,default)==variable.get(field,default):continue
            actual_variable=actual_variables[variable['key']]
            if actual_variable.get(field,default) not in (prior.get(field,default),variable.get(field,default)):
                raise ValueError('custom variable metadata conflict: '+variable['key']+'/'+field)
            actual_variable[field]=copy.deepcopy(variable.get(field))
    # Interpose only our new guards on the effective graph, retaining custom
    # edges/conditions rather than replacing the user's graph wholesale.
    agents={n['id'] for n in after['nodes'] if n['node_type']=='agent'}
    for edge in result['edges']:
        if edge['source']=='__start__' and edge['target']!='script_production_start':edge['source']='script_production_start'
        if edge['target']=='__end__' and edge['source']!='script_production_finish':edge['target']='script_production_finish'
        if edge['target'] in agents and edge['source']!='script_budget_'+edge['target']:edge['target']='script_budget_'+edge['target']
    needed=[{'source':'__start__','target':'script_production_start'},{'source':'script_production_finish','target':'__end__'},
            *[{'source':'script_budget_'+key,'target':key} for key in sorted(agents)]]
    pairs={(e['source'],e['target']) for e in result['edges']}
    result['edges'].extend(e for e in needed if (e['source'],e['target']) not in pairs)
    for scheme in result.get('execution_schemes',[]):
        selected=scheme.get('selected_node_ids',[])
        if selected:scheme['selected_node_ids']=list(dict.fromkeys(['script_production_start','script_production_finish',*['script_budget_'+n for n in selected if n in agents],*selected]))
    # Enforce the user's existing settings byte-for-value after composition.
    for key,prior in {n['id']:n for n in current['nodes']}.items():
        for field in PROTECTED:
            if field in prior:assert actual[key].get(field)==prior[field]
    return result
