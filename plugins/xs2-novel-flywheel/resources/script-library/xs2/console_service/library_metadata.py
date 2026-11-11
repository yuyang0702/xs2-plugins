"""Read-only source narration and transferable target viewpoint summaries."""

_VIEWS = {
    'first_person': 'first_person', '第一人称': 'first_person',
    'second_person': 'second_person', '第二人称': 'second_person',
    'third_person': 'third_person', '第三人称': 'third_person',
}
_MIXED = {'mixed', 'mixed_person', '混合', '混合人称', '混合视角'}


def _views(value):
    values = value if isinstance(value, list) else [value]
    known, mixed, unknown = set(), False, not bool(values)
    for item in values:
        token = item.strip().lower() if isinstance(item, str) else ''
        if token in _VIEWS:
            known.add(_VIEWS[token])
        elif token in _MIXED:
            mixed = True
        else:
            unknown = True
    return known, mixed, unknown


def library_metadata(manifest, profile, candidates):
    """Enrich a response without trusting a legacy project-derived ``pov`` tag.

    Profile source fields describe the original text. Candidate source fields
    provide a fallback; target fields describe reusable choices only. Their
    union never promises every choice can transfer to each listed viewpoint.
    """
    profile = profile if isinstance(profile, dict) else {}
    candidates = candidates if isinstance(candidates, dict) else {}
    entries = []
    for names in (('candidates',), ('style_choices', 'style_observations'),
                  ('conflict_choices', 'conflict_patterns')):
        value = next((candidates[name] for name in names if isinstance(candidates.get(name), list)), [])
        entries.extend(item for item in value if isinstance(item, dict))

    source, mixed, uncertain = set(), False, False
    profile_key = next((key for key in ('source_pov', 'narrative_pov') if key in profile), None)
    basis = 'profile' if profile_key else 'none'
    if profile_key:
        source, mixed, uncertain = _views(profile[profile_key])
    else:
        for item in entries:
            if 'source_pov' not in item:
                continue
            basis = 'candidates'
            views, is_mixed, is_unknown = _views(item['source_pov'])
            source.update(views)
            mixed = mixed or is_mixed
            uncertain = uncertain or is_unknown
    source_status = 'mixed' if mixed or len(source) > 1 else 'known' if source and not uncertain else 'unknown'

    target, incomplete = set(), False
    for item in entries:
        views, is_mixed, is_unknown = _views(item.get('target_pov'))
        target.update(views)
        incomplete = incomplete or is_mixed or is_unknown
    target_status = ('partial' if incomplete else 'known') if target else 'unknown'
    reading={'learning_direction':profile.get('learning_direction','general'),
        'reading_objective_count':sum(len(row.get('reading_objectives',[])) for row in entries if isinstance(row.get('reading_objectives',[]),list))}
    return {**manifest, **reading,'pov_metadata': {
        'source_pov': sorted(source), 'source_status': source_status, 'source_basis': basis,
        'target_pov': sorted(target), 'target_status': target_status,
    }}
