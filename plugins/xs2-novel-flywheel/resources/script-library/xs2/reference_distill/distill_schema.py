"""Model-visible shape contract; source truth remains in exact evidence checks."""

DIMENSIONS = ("structure", "voice", "topic", "case", "pacing", "layout", "expression")
EXPORT_LAYOUTS = ("preserve", "short_body_only")
LAYERS = ("language", "structure", "narrative_lens", "dialogue", "imagery", "theme", "character")
POV_COMPATIBILITY = ("direct", "adaptable", "risky")


def schema():
    text={'type':'string','minLength':1}
    def texts(limit):return {'type':'array','maxItems':limit,'items':text}
    evidence_id = {'type':'string','pattern':r'^window-\d{4}-e\d{4}$'}
    proof={'type':'object','required':['window_id','reason'],'properties':{
        'window_id':text,'reason':text,'evidence_id':evidence_id,'end_evidence_id':evidence_id,
        'source_start':{'type':'integer','minimum':0},'source_end':{'type':'integer','minimum':1},'excerpt':text},
        'dependentRequired': {'end_evidence_id': ['evidence_id']},
        'anyOf':[{'required':['evidence_id']},{'required':['excerpt']}]}
    quote_proof = {'$ref': '#/$defs/dialogueProof'}
    turn = {'type': 'object', 'required': ['speaker', 'text', 'intent', 'evidence'], 'properties': {
        'speaker': text, 'text': text, 'intent': text, 'evidence': quote_proof,
        'trigger': text, 'trigger_evidence': quote_proof, 'reaction': text, 'reaction_evidence': quote_proof,
        'attribution': {'enum': ['observed', 'tentative']}, 'attribution_evidence': quote_proof},
        'dependentRequired': {'trigger': ['trigger_evidence'], 'trigger_evidence': ['trigger'],
                              'reaction': ['reaction_evidence'], 'reaction_evidence': ['reaction'],
                              'attribution_evidence': ['attribution']},
        'if': {'required': ['attribution'], 'properties': {'attribution': {'const': 'observed'}}},
        'then': {'required': ['attribution_evidence']}}
    dialogue = {'type': 'object', 'required': ['scene_type', 'relationship', 'turns', 'transferable_moves', 'limits'],
                'properties': {'scene_type': text, 'relationship': text, 'relationship_evidence': quote_proof,
                               'turns': {'type': 'array', 'minItems': 2, 'maxItems': 8, 'items': turn},
                               'transferable_moves': {**texts(6), 'minItems': 1},
                               'limits': {**texts(6), 'minItems': 1}}}
    candidate={'type':'object','required':['mechanism','transfer_guidance','constraints','confidence','evidence'],
        'anyOf': [{'required': ['dimension']}, {'required': ['scopes']}],
        'if': {'required': ['export_layout']},
        'then': {'required': ['dimension'], 'properties': {'dimension': {'const': 'layout'}}},
        'properties':{'mechanism':text,'transfer_guidance':text,'constraints':texts(16),'scopes':texts(16),
            'dimension':{'enum':list(DIMENSIONS)}, 'layer':{'enum':list(LAYERS)},
            'export_layout':{'enum':list(EXPORT_LAYOUTS)},
            'confidence':{'enum':['high','medium','low']},'evidence':{'type':'array','minItems':1,'maxItems':8,'items':proof},
            'source_pov':{'anyOf':[texts(4),{'type':'null'}]},'target_pov':{'anyOf':[texts(4),{'type':'null'}]},
            'pov_compatibility':{'enum':list(POV_COMPATIBILITY)},'adaptation_guidance':{'type':'string','maxLength':800},
            'risk_flags':{'anyOf':[texts(8),{'type':'null'}]},'application_scope':{'anyOf':[texts(5),{'type':'null'}]},
            'dialogue_samples':{'anyOf':[{'type':'array','maxItems':3,'items':dialogue},{'type':'null'}]},
            'reading_objectives':{'type':'array','maxItems':8,'items':{'type':'object'}}}}
    observation = {'type': 'object', 'required': ['layer', 'rule', 'transfer_guidance', 'limits', 'confidence', 'evidence'],
                   'properties': {'limits': texts(16), 'layer': {'enum': list(LAYERS)}}}
    conflict = {'type': 'object', 'required': ['application_scope'],
                'properties': {'application_scope': {'enum': ['short_full', 'serial_opening',
                                                             'serial_chapter', 'serial_arc', 'general']}}}
    return {'type':'object','required':['window_id','candidates'],
        '$defs': {'dialogueProof': {**proof, 'required': ['window_id']}},
        'properties':{
        'window_id':text,'source_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
        'candidates':{'type':'array','maxItems':12,'items':candidate},
        'style_observations':{'type':'array','maxItems':12,'items':observation},
        'conflict_patterns':{'type':'array','maxItems':8,'items':conflict}}}
