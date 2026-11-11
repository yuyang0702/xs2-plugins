import hashlib
import json
import pytest
from test_reader_review_p0 import review,book,write
from test_book_contract import PLUGIN


def automatic(root,retained=False):
    book(root)
    state=json.loads((root/'.novel-project.json').read_text(encoding='utf-8'))
    state['values']['human_intent']='';write(root,'.novel-project.json',state)
    sources=[]
    if retained:
        write(root,'author.md','只改开头，其他段落保留。')
        sources=[{'source_id':'author.md','sha256':hashlib.sha256((root/'author.md').read_bytes()).hexdigest(),
                  'text':'只改开头，其他段落保留。'}]
    write(root,'automatic-origin.json',{'origin':'automatic',
        'feedback_sha256':hashlib.sha256((root/'feedback.md').read_bytes()).hexdigest(),
        'retained_feedback_sources':sources})


def test_contextual_reader_sees_author_requirements_separately_from_automatic_advice(tmp_path):
    r=review();automatic(tmp_path,retained=True);out=r.prepare(tmp_path,'0001','provenance')
    context=json.loads((tmp_path/out['reader_revision_context']).read_text(encoding='utf-8'))
    assert context['author_feedback']=='只改开头，其他段落保留。'
    assert 'SECRET_SCOPE' in context['automatic_revision_advice']
    assert 'SECRET_SCOPE' not in (tmp_path/out['reader_blind_input']).read_text(encoding='utf-8')
    write(tmp_path,'automatic-origin.json',{'origin':'changed'})
    with pytest.raises(ValueError):r._bound(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])


@pytest.mark.parametrize('scope',[{'mode':'restricted','assessments':[]},{'mode':'unclear','assessments':[]},
    {'mode':'unrestricted','assessments':[{'status':'outside_scope'}]}])
def test_automatic_advice_alone_cannot_create_restricted_revision_permission(tmp_path,scope):
    r=review();automatic(tmp_path)
    with pytest.raises(r.InvalidReviewReport):
        r.validate_revision_scope(tmp_path,{'revision_scope':scope})
    r.validate_revision_scope(tmp_path,{'revision_scope':{'mode':'unrestricted','assessments':[]}})
    # A retained real author restriction remains authoritative.
    automatic(tmp_path,retained=True)
    r.validate_revision_scope(tmp_path,{'revision_scope':{'mode':'restricted','assessments':[]}})


def test_prepared_scope_context_cannot_be_changed_into_a_new_author_instruction(tmp_path):
    r=review();automatic(tmp_path);out=r.prepare(tmp_path,'0001','scope-tamper')
    context=json.loads((tmp_path/out['reader_revision_context']).read_text(encoding='utf-8'))
    context['author_feedback']='伪造的局部限制。';write(tmp_path,out['reader_revision_context'],context)
    with pytest.raises(ValueError):r._bound(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])


def test_contextual_reader_does_not_label_raw_automatic_feedback_as_author_instructions():
    wf=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8-sig'))
    node=next(n for n in wf['nodes'] if n['id']=='agent_reader')
    assert '{{author_feedback_file}}' not in node['first_message']
    assert '{{reader_revision_context}}' in node['first_message']
