"""Model-visible shape contract; source truth remains in exact evidence checks."""

def schema():
    text={'type':'string','minLength':1}
    def texts(limit):return {'type':'array','maxItems':limit,'items':text}
    proof={'type':'object','required':['window_id','reason'],'properties':{
        'window_id':text,'reason':text,'evidence_id':{'type':'string','pattern':r'^window-\d{4}-e\d{4}$'},
        'source_start':{'type':'integer','minimum':0},'source_end':{'type':'integer','minimum':1},'excerpt':text},
        'anyOf':[{'required':['evidence_id']},{'required':['source_start','source_end','excerpt']}]}
    candidate={'type':'object','required':['mechanism','transfer_guidance','constraints','scopes','confidence','evidence'],
        'properties':{'mechanism':text,'transfer_guidance':text,'constraints':texts(16),'scopes':texts(16),
            'confidence':{'enum':['high','medium','low']},'evidence':{'type':'array','minItems':1,'maxItems':8,'items':proof},
            'source_pov':{'anyOf':[texts(4),{'type':'null'}]},'target_pov':{'anyOf':[texts(4),{'type':'null'}]},
            'risk_flags':{'anyOf':[texts(8),{'type':'null'}]},'application_scope':{'anyOf':[texts(5),{'type':'null'}]},
            'reading_objectives':{'type':'array','maxItems':8,'items':{'type':'object'}}}}
    return {'type':'object','required':['window_id','candidates'],'properties':{
        'window_id':text,'source_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
        'candidates':{'type':'array','maxItems':12,'items':candidate},
        'style_observations':{'type':'array','maxItems':12,'items':{'type':'object'}},
        'conflict_patterns':{'type':'array','maxItems':8,'items':{'type':'object'}}}}
