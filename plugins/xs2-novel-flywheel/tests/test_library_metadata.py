"""POV summaries preserve source observations and target applicability separately."""
import copy
import importlib.util
from pathlib import Path
import sys

import pytest


SERVICE = Path(__file__).resolve().parents[1] / 'resources/script-library/xs2/console_service/console_service.py'


@pytest.fixture
def metadata():
    spec = importlib.util.spec_from_file_location('library_metadata_tests', SERVICE,
                                               submodule_search_locations=[str(SERVICE.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.library_metadata


def test_manual_project_pov_never_overrides_source_observations(metadata):
    manifest = {'id': 'example', 'pov': ['third_person'], 'version': 4}
    profile = {'markdown': 'Source analysis'}
    candidates = {'candidates': [{'source_pov': ['first_person'],
                                  'target_pov': ['first_person', 'third_person']}]}
    before = copy.deepcopy((manifest, profile, candidates))
    result = metadata(manifest, profile, candidates)
    assert result['pov_metadata'] == {
        'source_pov': ['first_person'], 'source_status': 'known', 'source_basis': 'candidates',
        'target_pov': ['first_person', 'third_person'], 'target_status': 'known',
    }
    assert result['pov'] == ['third_person']
    assert (manifest, profile, candidates) == before


@pytest.mark.parametrize('source, expected, status', [
    ('第一人称', ['first_person'], 'known'),
    (['first_person', 'third_person'], ['first_person', 'third_person'], 'mixed'),
    ('mixed', [], 'mixed'),
    ('unknown', [], 'unknown'),
    (None, [], 'unknown'),
    ('unrecognized_view', [], 'unknown'),
])
def test_structured_source_profile_is_authoritative(metadata, source, expected, status):
    result = metadata({'pov': ['third_person']}, {'source_pov': source},
                      {'candidates': [{'source_pov': ['first_person'], 'target_pov': ['third_person']}]})
    assert result['pov_metadata']['source_pov'] == expected
    assert result['pov_metadata']['source_status'] == status
    assert result['pov_metadata']['source_basis'] == 'profile'


def test_source_views_can_be_mixed_across_candidates(metadata):
    result = metadata({}, {}, {'candidates': [{'source_pov': ['first_person']},
                                             {'source_pov': ['third_person']}]})
    assert result['pov_metadata']['source_status'] == 'mixed'
    assert result['pov_metadata']['source_pov'] == ['first_person', 'third_person']


def test_partial_target_coverage_does_not_claim_all_choices_support_a_view(metadata):
    result = metadata({}, {}, {'candidates': [{'target_pov': ['第一人称']}],
                               'style_choices': [{'target_pov': ['third_person']}],
                               'conflict_choices': [{'title': 'Unspecified conflict'}]})
    assert result['pov_metadata']['target_pov'] == ['first_person', 'third_person']
    assert result['pov_metadata']['target_status'] == 'partial'
    assert result['pov_metadata']['source_status'] == 'unknown'


@pytest.mark.parametrize('candidates', [{}, {'candidates': None}, {'candidates': [None, {}]},
                                        {'candidates': [{'target_pov': ['unknown']}]}])
def test_missing_or_invalid_pov_is_unknown_even_with_legacy_manifest_label(metadata, candidates):
    result = metadata({'pov': ['third_person']}, {}, candidates)['pov_metadata']
    assert result['source_status'] == 'unknown'
    assert result['source_pov'] == []
    assert result['target_status'] == 'unknown'
    assert result['target_pov'] == []
