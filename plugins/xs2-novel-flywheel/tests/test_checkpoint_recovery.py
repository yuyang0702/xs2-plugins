import importlib.util
import json
import os
from pathlib import Path

import pytest
from test_length_quality import PLUGIN, write


def load(name):
    folder=Path(os.environ.get('XS2_VERIFY_SERVICE_DIR',str(PLUGIN/'resources/script-library/xs2/console_service')))
    spec=importlib.util.spec_from_file_location('checkpoint_test_'+name,folder/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def rendered(root,failed='script_check_originality'):
    write(root,'story/0001/chapter.md','她把灯放在桌边。\n')
    write(root,'cache/si/body.json',json.dumps({'body':'她把灯放在桌边。'},ensure_ascii=False))
    write(root,'cache/se/se_output.json','{}')
    nodes=[{'id':name,'node_type':kind,'node_params':{'script_name':script,'script_source':'library','script_type':'python'}}
           for name,kind,script in [('agent_aw','agent',''),('script_render_si','script','local_archive'),('sync_up_si','script','local_archive'),('script_check_originality','script','reference_intelligence_helper')]]
    state={'values':{'chapter_number':'0001','premise':'test'},'writerModel':'ark:writer','polishModel':'flare:polish'}
    task={'task_id':'rendered','status':'failed','workspace_override':str(root),'parameter_values':{'chapter_number':'0001','premise':'test'},
          'snapshot_definition':{'nodes':nodes},'node_states':{'script_render_si':{'status':'completed'},
          failed:{'status':'failed','error':'Script Library 已漂移'}}}
    if failed!='sync_up_si':task['node_states']['sync_up_si']={'status':'completed'}
    return state,task,{'nodes':nodes,'variables':[{'key':'chapter_number'},{'key':'premise'}]}


def test_checkpoint_rejects_same_named_inline_tail_script(tmp_path):
    import copy
    p=load('production');state,task,definition=rendered(tmp_path)
    state.update(p.recovery_action(state,'mvp',task,root=tmp_path)['updates'])
    changed=copy.deepcopy(definition)
    next(n for n in changed['nodes'] if n['id']=='script_check_originality')['node_params']['script_source']='inline'
    with pytest.raises(ValueError):p.checkpoint_options(tmp_path,state,'mvp',changed,task)


def test_checkpoint_uses_actual_renderer_newline_conversion(tmp_path):
    p=load('production');state,task,definition=rendered(tmp_path)
    value='她把灯放在桌边。\r\n\r\n他取出纸。'
    write(tmp_path,'cache/si/body.json',json.dumps({'body':value},ensure_ascii=False))
    write(tmp_path,'story/0001/chapter.md',value.rstrip()+'\n')
    action=p.recovery_action(state,'mvp',task,root=tmp_path)
    assert action['action']=='advance'
    state.update(action['updates'])
    assert p.checkpoint_options(tmp_path,state,'mvp',definition,task)['selected_node_ids']==['script_check_originality']


@pytest.mark.parametrize('failed,selected',[('sync_up_si',['sync_up_si','script_check_originality']),('script_check_originality',['script_check_originality'])])
def test_rendered_mvp_recovers_only_unfinished_tail_with_new_snapshot(tmp_path,failed,selected):
    p=load('production');state,task,definition=rendered(tmp_path,failed);before=(tmp_path/'story/0001/chapter.md').read_bytes()
    action=p.recovery_action(state,'mvp',task,root=tmp_path);state.update(action['updates'])
    p.launch_check(tmp_path,state,'mvp')
    definition['nodes'].append({'id':'new_writer','node_type':'agent'})
    options=p.checkpoint_options(tmp_path,state,'mvp',definition,task)
    assert options['selected_node_ids']==selected
    assert 'new_writer' not in options['selected_node_ids']
    assert options['parameter_values']=={'chapter_number':'0001','premise':'test'}
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==before


@pytest.mark.parametrize('path',['story/0001/chapter.md','cache/si/body.json'])
def test_checkpoint_never_authorizes_overwriting_a_later_edit(tmp_path,path):
    p=load('production');state,task,definition=rendered(tmp_path)
    action=p.recovery_action(state,'mvp',task,root=tmp_path);state.update(action['updates'])
    write(tmp_path,path,'后来编辑')
    with pytest.raises(ValueError):p.checkpoint_options(tmp_path,state,'mvp',definition,task)


def test_rejected_shortening_uses_a_different_original_paragraph(tmp_path):
    q=load('length_quality');raw=('甲'*180+'\n\n'+'乙'*160+'\n\n'+'丙'*100).encode('utf8')
    result={'status':'long','actual':440,'lower':300,'upper':400}
    first=q.fragment_anchor(raw,result)
    second=q.fragment_anchor(raw,result,[first['start'],first['end']])
    assert second['end']<=first['start'] or second['start']>=first['end']


def test_checkpoint_accepts_unchanged_older_body_only_after_tail_checks_then_is_consumed(tmp_path):
    p=load('production');state,source,definition=rendered(tmp_path)
    action=p.recovery_action(state,'mvp',source,root=tmp_path);state.update(action['updates'])
    task={'task_id':'continuation','created_at':'2099-01-01T00:00:00+00:00','snapshot_definition':definition,
          'disabled_node_ids':['agent_aw','script_render_si','sync_up_si'],
          'node_states':{'script_check_originality':{'status':'completed'}}}
    p.verify_completion(tmp_path,state,'mvp',task)
    task['node_states']['script_check_originality']['status']='skipped'
    with pytest.raises(ValueError):p.verify_completion(tmp_path,state,'mvp',task)
    state.update(p.next_action(tmp_path,state,'mvp')['updates'])
    assert state['automaticCheckpoint'] is None
    with pytest.raises(ValueError):p.launch_check(tmp_path,state,'mvp')
