import json
import importlib.util
import shutil
import pytest
from test_book_contract import PLUGIN,put
from test_local_revision import setup,patch,approved,BODY,module


def test_installed_pending_profile_matches_source_and_detects_resource_changes(tmp_path):
    prepared=tmp_path/'prepared'
    scripts=prepared/'script-libraries/0/xs2-novel-flywheel-xs2'
    for folder in ('local_revision','prose_policy','production_guard'):
        shutil.copytree(PLUGIN/'resources/script-library/xs2'/folder,scripts/folder,
            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    configs={
        'prompts.json':prepared/'json/prompts/0.json',
        'workflows/polish/definition.json':prepared/'workflows/0/xs2-novel-flywheel-polish/definition.json',
    }
    for source,target in configs.items():
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((PLUGIN/'resources'/source).read_bytes())
    spec=importlib.util.spec_from_file_location('installed_pending',scripts/'local_revision/pending_revision.py')
    installed=importlib.util.module_from_spec(spec);spec.loader.exec_module(installed)
    assert installed.profile()==module().pending.profile()
    original=installed.profile()
    for path in (configs['prompts.json'],configs['workflows/polish/definition.json'],scripts/'prose_policy/book_contract.py'):
        content=path.read_bytes();path.write_bytes(content+b'\n')
        assert installed.profile()!=original
        path.write_bytes(content)
        assert installed.profile()==original
    configs['prompts.json'].unlink()
    with pytest.raises(FileNotFoundError):installed.profile()


def rejected_but_improved(root,*,fact=False):
    m,out=setup(root);patch(m,out,root);m.candidate(root,out['revision_dir'])
    report=json.loads(approved(m,out,root))
    if fact:
        report['compatible']=False
        report['issues']=[{'id':'f','candidate_quote':'第二段简明。','source_quote':'第二段重复说明。','reason':'候选改变事实。'}]
    else:
        report['expression_review']={'verdict':'revise','summary':'第一段仍需修订。','issues':[
            {'id':'remaining','category':'semantic_redundancy','location':'第一段','priority':'medium',
             'excerpts':['第一段保留。'],'impact':'第一段还有无作用复述。','goal':'改第一段，保留其他已改进部分。'}]}
        report['expression_checks'][0].update(status='issue',issue_ids=['remaining'],excerpts=['第一段保留。'])
    put(root,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as e:m.commit(root,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert e.value.target=='agent_pl'
    return m,out


def test_followup_and_process_restart_keep_useful_patch_without_repeating_it(tmp_path):
    m,out=rejected_but_improved(tmp_path)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    m=module() # independent process-equivalent module reload
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[
        {'paragraph_id':'p0001','old':'第一段保留。','occurrence':1,'replacement':'第一段仍旧保留。'}]})
    m.candidate(tmp_path,out['revision_dir'])
    ctx=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert ctx['candidate']==BODY.replace('第二段重复说明。','第二段简明。').replace('第一段保留。','第一段仍旧保留。')
    assert ctx['source_body']==BODY and len(ctx['edits'])==2
    report=json.loads(approved(m,out,tmp_path))
    for row in report['expression_checks']:row['excerpts']=['潮水会回来。']
    put(tmp_path,out['revision_review_path'],report);m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    task={'task_id':'local-test','parameter_values':{**out,'revision_review_result':json.dumps(report,ensure_ascii=False)}}
    m.verify_attempt(tmp_path,task)


def test_fact_rejected_edits_are_not_retained(tmp_path):
    m,out=rejected_but_improved(tmp_path,fact=True)
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[]})
    m.candidate(tmp_path,out['revision_dir'])
    assert json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))['candidate']==BODY


def test_retained_edit_explicit_replacement_still_needs_full_review(tmp_path):
    m,out=rejected_but_improved(tmp_path);patch(m,out,tmp_path,'第二段换成更好的表达。')
    m.candidate(tmp_path,out['revision_dir'])
    ctx=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert len(ctx['edits'])==1 and ctx['candidate']==BODY.replace('第二段重复说明。','第二段换成更好的表达。')
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_partial_overlap_of_retained_patch_is_rejected(tmp_path):
    m,out=rejected_but_improved(tmp_path)
    put(tmp_path,out['revision_patch_path'],{'source_sha256':m.sha(BODY.encode()),'edits':[
        {'paragraph_id':'p0002','old':'重复说明','occurrence':1,'replacement':'新内容'}]})
    with pytest.raises(m.Retry):m.candidate(tmp_path,out['revision_dir'])


def test_pending_material_tamper_cannot_inherit_review(tmp_path):
    m,out=rejected_but_improved(tmp_path)
    path=tmp_path/out['revision_dir']/'working.json'
    assert path.is_file()
    value=json.loads(path.read_text(encoding='utf8'));value['edits']=[];put(tmp_path,path.relative_to(tmp_path).as_posix(),value)
    with pytest.raises(ValueError):m.candidate(tmp_path,out['revision_dir'])


def test_missing_pending_file_cannot_silently_discard_retained_edits(tmp_path):
    m,out=rejected_but_improved(tmp_path)
    (tmp_path/out['revision_dir']/'working.json').unlink()
    with pytest.raises(ValueError):m.candidate(tmp_path,out['revision_dir'])


def test_pending_prompt_or_code_version_change_invalidates_reuse(tmp_path,monkeypatch):
    m,out=rejected_but_improved(tmp_path)
    monkeypatch.setattr(m.pending,'profile',lambda:'new-prompt-version')
    with pytest.raises(ValueError):m.candidate(tmp_path,out['revision_dir'])


def test_real_retry_feedback_delivers_the_verified_working_draft(tmp_path):
    m,out=rejected_but_improved(tmp_path)
    text=m.retry_feedback(tmp_path,out['revision_dir'],m.Retry('agent_pl','只处理剩余问题'))
    assert '待验收工作稿' in text and '第二段简明。' in text and 'retained_edits' in text


def test_length_gate_measures_cumulative_work_without_inferred_replanning(tmp_path):
    m,_=setup(tmp_path);out=m.prepare(tmp_path,'0001','goal-test','1-5000')
    put(tmp_path,'critic-goal.json',{'issues':[{'severity':'medium','suggestion':'处理第一段','evidence':['第一段保留。']}],'blocking_issues':[0]})
    m.writer_input(tmp_path,out['revision_dir'],'critic-goal.json');patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    report=json.loads(approved(m,out,tmp_path));report['issue_outcomes']=[{'id':'critic-0','status':'remaining','reason':'第一段仍需处理','excerpts':['第一段保留。']}]
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    for size in (6000,6001):
        payload={'source_sha256':m.sha(BODY.encode()),'edits':[{'paragraph_id':'p0001','old':'第一段保留。','occurrence':1,'replacement':'字'*size}]}
        put(tmp_path,out['revision_patch_path'],payload)
        with pytest.raises(m.Retry):m.candidate(tmp_path,out['revision_dir'])
        measured=json.loads((tmp_path/out['revision_dir']/'length-candidates.json').read_text(encoding='utf8'))[-1]['measurement']
        expected=BODY.replace('第二段重复说明。','第二段简明。').replace('第一段保留。','字'*size)
        assert measured['status']=='long' and measured['body_sha256']==m.sha(expected.encode())
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    payload['edits'][0]['replacement']='第一段处理后保留。'
    put(tmp_path,out['revision_patch_path'],payload);m.candidate(tmp_path,out['revision_dir'])
    fresh=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert '第一段处理后保留。' in fresh['candidate'] and '第二段简明。' in fresh['candidate']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
