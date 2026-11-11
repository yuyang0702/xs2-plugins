"""Ground expression judgements in current prose and the book's chosen style."""
import copy
from itertools import combinations

LEGACY_DIMENSIONS=('semantic_increment','constraint_transcription','imagery_function','dialogue_function','ending_function','voice_alignment')
NARRATIVE_DIMENSIONS=('explanation_progression','turning_point_payoff')
SCENE_DIMENSIONS=('scene_conflict_progression','aftermath_transition')
DIMENSIONS=LEGACY_DIMENSIONS+NARRATIVE_DIMENSIONS+SCENE_DIMENSIONS
SCENE_PROBLEMS=('scene_conflict_stall','aftermath_transition_flat')
STAGED_PROBLEMS=('premature_explanation','convenient_dialogue','aftermath_checklist',
                 'dialogue_stall','post_action_restatement')+SCENE_PROBLEMS
CATEGORIES=('action_dilation','object_inventory','scripted_dialogue','semantic_redundancy',
            'generic_imagery','explanatory_psychology','ending_overstatement','constraint_transcription','voice_flattening','unnecessary_precision',
            'turning_point_summary')+STAGED_PROBLEMS

SCENE_CRAFT_GUIDANCE=(
    '在本书要求的叙述距离、节奏和信息顺序内安排读者的发现。关键选择或揭示之前保留理解所需的线索与压力；'
    '如果邻近对白或行动已经让读者能看出动机、决定或反差，先行解释只在能产生新的悬念、反讽或认识时保留。'
    '对白看人物当下想要什么、知道什么、愿意说什么，以及对方的回答怎样改变下一步。'
    '如果对话只让每个人依次递出主线需要的信息，优先调整造成这种效果的交流节点。'
    '转折之后概括交代次要手续，选择最影响信任、处境或下一步行动的一项后果，给它读者可辨的反应或变化。'
    '书信、纪实感、明确心理、预告、齐整对白、仪式性复沓、快切和有意概述均可承载阅读作用，按实际作用和本书风格判断。'
)

SCENE_CRAFT_CHECKS=(
    '用explanation_progression与turning_point_payoff区分有用铺垫和提前讲完转折，用dialogue_function检查话轮是否只为递剧情，'
    '用ending_function与turning_point_payoff检查善后各项是否只排列已完成的事项。'
    '发现有实际损害时可用premature_explanation、convenient_dialogue或aftermath_checklist。'
    '每个此类问题附两处不同的连续原文（解释与转折、对话的两个话轮、或善后概括与应当承接的变化），并给可执行的局部目标。'
    '对照后成立的预告、仪式感、简练问答或蒙太奇须说明它具体完成了什么。'
)

PROGRESSION_GUIDANCE=(
    '争执、谈判或盘问中先找已成立的主张，再看后续话轮是否改变对方可做的选择、公开立场、信息、风险或关系。'
    '同一问题可以反复问；迫使对方作答、揭露回避、改变攻守、形成节奏或有意表现僵局都有作用。'
    '如果双方换个说法仍回到原处，保留最有力度的交锋，把其余话轮交给当下已有的选择与后果，不靠新增争吵或转折填充。'
    '动作、物件或沉默已让读者看出一层意思时，核对紧随的旁白、内心话或对白还有没有第二层。'
    '只有复述同一层意思的说明优先压缩；有新判断、动机矛盾、视角偏差、声音或因果信息的明说仍有作用。'
    '慢场景、内心独白、喜剧重复、刻意停顿与有意复沓按本书的实际阅读作用判断。'
)

PROGRESSION_CHECKS=(
    '在dialogue_function对照同场已有的主张和后续话轮，指出实际新增的选择、压力、节奏或含义；'
    '对照后仍停在原地且损害读感时使用dialogue_stall。'
    '在semantic_increment或explanation_progression对照动作和后来对它的解说，'
    '确实只重复读者已经能懂的信息且损害读感时使用post_action_restatement。'
    '两类问题各引两处不同的当前原文，并说明具体哪一步没推进、或哪层含义已经由动作表达。'
)

WHOLE_SCENE_GUIDANCE=(
    '沿本书的节奏和叙述权限看完整冲突：找入场时的目标与筹码、哪一步改变了选择或代价、场面退出时留下什么。'
    '连续几轮各有新说法却都做同一件事时，保留能改变局势或累积压力的轮次。'
    '用原有事实、人物反应和下一步选择承接转折，无须添加升级事件。'
    '检查善后和过渡从旧场的后果如何抵达下一场的目标。让最影响处境、感受或决定的一步获得篇幅；'
    '次要交代可以合并、跳切或概述，留足读者理解时间、地点、人物责任和因果所需的信息。'
    '礼节往复、刻意僵局、慢场、技术或程序说明可以增加期待、压力、含义或可用信息，按本书阅读作用判断。'
    '场面不以段落、节号、句长、事件数量或第三方检测分数划界，不强制每句推进或每场升级。'
)

WHOLE_SCENE_CHECKS=(
    'scene_conflict_progression核对完整交锋的开端、压力变化与离场代价；'
    'aftermath_transition核对关键后果、承接细节和下一场目标。分别写明本书的阅读作用。'
    '可见作者指定范围或修订补丁时，优先核对与之相交的完整场面；盲读选择正文中作用最明显的场面。'
    '通过时按正文顺序引用开端和结果两处；发现实质问题用scene_conflict_stall或aftermath_transition_flat，'
    '在检查行依正文顺序引用开端、中间和结果三处，问题也附三处各自独立的当前原文，并给可执行的局部目标。'
    '局部选区证据不足时，使用实际可见的冻结上下文或交给整篇核对。无相关过程时填not_applicable并说明。'
)

NARRATIVE_GUIDANCE=(
    '跨段和跨场对照同一事实、动机或关系判断最初成立的位置与后一次表达。后一次要判断读者获得了什么新的信息、'
    '立场变化、情绪、节奏或回收。无新增作用且妨碍推进时，指出应保留哪次表达、后一次可承担什么新功能。'
    '检查改变主要目标、关系、认知或局势的转折。定位转折前的压力与选择，以及转折中或转折后读者能看见的变化或代价。'
    '若关键变化只靠事后概括或结果清单交代，且读者难以感到变化或理解其依据，指出最需要补足的一个环节。'
    '短写、跳切、留白、回环和有意复述按本书读者体验判断。有效的暗示或后果可以承载转折，无需强行补完整场景或解释。'
)
NARRATIVE_CHECKS=(
    'expression_checks另须提交explanation_progression和turning_point_payoff。分别核对远近两处对同一信息的处理，'
    '以及最关键的转折及其承接。每项标issue时引用至少两处可区分的当前原文，前后可位于不同场次。'
    '缺失的环节用前置与后果或概括句两侧定位，不能编造。实质影响理解或读感的问题设为medium/high，'
    '用可局部修复的问题编号与目标绑定。无相关可比较的表达或关键转折时可用not_applicable并说明。'
)

GUIDANCE='''逐项提交expression_checks，每项包含dimension、status(pass/issue/not_applicable)、excerpts、reason、style_basis、issue_ids。
维度：semantic_increment核对相邻动作、对白、心理、比喻与总结是否重复同一信息；constraint_transcription核对后台账本、选择分析或修订意见是否被直译进正文；imagery_function判断意象与此人此景的关系；dialogue_function判断对话在当前交流中的作用；ending_function判断结尾是否再次解释已完成的选择；voice_alignment核对本书声线与修改前的有效表达。
每项解释实际阅读作用，并联系本书风格。pass也给当前原文依据，不能只说本书允许就免检；issue必须指向实际issues编号，并说明已成立的信息、此处是否有新变化及影响。无对应内容才用not_applicable，voice_alignment始终适用。引用可选当前evidence_catalog编号。
有意回环、议论、心理、技术说明、华丽意象、全知与安静场景可以成立。比喻多、语句整齐或出现某个词不构成问题；风格允许也不能为同义复述自动免责。不要以第三方检测分数、禁词、标点或固定句长判断质量。
检查解决问题的净效果：补动机不能变成替人物答辩，补技术因果不能变成完整科普，删去重复不能换成同义说明或无关动作填回。保留充分的读者理解依据，不能为含蓄隐去真实争点。
在semantic_increment和voice_alignment中核对精确计数的叙事作用；无用计数可用unnecessary_precision类别给逐字依据、影响和局部目标。金额、期限、技术规则、资源账、人物计数习惯、夸张或本书风格需要的数字应保留；不设数字上限，不把数字多当成质量失败。'''


def schema(excerpt_schema=None):
    excerpt=excerpt_schema or {'type':'string','minLength':1}
    return {'type':'array','minItems':len(DIMENSIONS),'maxItems':len(DIMENSIONS),'items':{
        'type':'object','required':['dimension','status','excerpts','reason','style_basis','issue_ids'],
        'properties':{'dimension':{'enum':list(DIMENSIONS)},'status':{'enum':['pass','issue','not_applicable']},
            'excerpts':{'type':'array','items':copy.deepcopy(excerpt)},'reason':{'type':'string','minLength':1},
            'style_basis':{'type':'string','minLength':1},'issue_ids':{'type':'array','items':{'type':'string','minLength':1},'uniqueItems':True}},
        'additionalProperties':False}}


def _distinct_quotes(quotes):
    return all(a not in b and b not in a for a, b in combinations(quotes, 2))


def _ordered_quotes(body, quotes):
    offset = 0
    for quote in quotes:
        start = body.find(quote, offset)
        if start < 0:
            return False
        offset = start + len(quote)
    return True


def validate_narrative_issue(issue, context_excerpts=()):
    if issue.get('category') not in STAGED_PROBLEMS:
        return
    excerpts = [*issue.get('excerpts', []), *context_excerpts]
    if issue.get('category') in SCENE_PROBLEMS:
        if not any(_distinct_quotes(group) for group in combinations(excerpts, 3)):
            raise ValueError('表达验收的整场冲突或过渡问题须对照三处不同的当前原文')
    elif not any(_distinct_quotes(group) for group in combinations(excerpts, 2)):
        raise ValueError('表达验收的转折、对白或动作解释问题须对照两处不同的当前原文')


def validate_checks(report,body,required=False):
    if 'expression_checks' not in report:
        if required:raise ValueError('表达验收缺少逐维度原文与文风依据')
        return []
    rows=report['expression_checks']
    if not isinstance(rows,list):raise ValueError('表达验收维度缺失或重复')
    dimensions = LEGACY_DIMENSIONS+NARRATIVE_DIMENSIONS
    # Stored reports remain readable. Live agent schemas require the current dimensions.
    expected = set({len(LEGACY_DIMENSIONS): LEGACY_DIMENSIONS, len(dimensions): dimensions}.get(len(rows), DIMENSIONS))
    if len(rows)!=len(expected):raise ValueError('表达验收维度缺失或重复')
    resolved={r.get('issue_id') for r in report.get('blind_resolutions',[]) if isinstance(r,dict)}
    issues=[*report.get('issues',[]),*report.get('expression_review',{}).get('issues',[]),
            *[r for r in report.get('blind_review',{}).get('issues',[]) if r.get('id') not in resolved]]
    known={r.get('id') for r in issues if isinstance(r,dict) and isinstance(r.get('id'),str)}
    seen=set()
    for row in rows:
        if (not isinstance(row,dict) or row.get('dimension') not in expected or row['dimension'] in seen
                or row.get('status') not in ('pass','issue','not_applicable')
                or any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('reason','style_basis'))):
            raise ValueError('表达验收缺少有效维度、阅读作用或本书风格依据')
        seen.add(row['dimension']);quotes=row.get('excerpts');ids=row.get('issue_ids')
        if (not isinstance(quotes,list) or any(not isinstance(q,str) or not q.strip() or q not in body for q in quotes)
                or (row['status']!='not_applicable' and not quotes)):
            raise ValueError('表达验收引文不在当前正文，不能用风格标签代替原文依据')
        if row['dimension']=='voice_alignment' and row['status']=='not_applicable':raise ValueError('本书声线核对不能跳过')
        if row['dimension'] in NARRATIVE_DIMENSIONS and row['status']=='issue' and len(set(quotes))<2:
            raise ValueError('表达验收的重复解释或关键转折问题须对照两处不同的当前原文')
        if row['dimension'] in SCENE_DIMENSIONS and row['status'] != 'not_applicable':
            minimum = 3 if row['status'] == 'issue' else 2
            if len(quotes) < minimum or not _distinct_quotes(quotes) or not _ordered_quotes(body, quotes):
                raise ValueError('表达验收须按正文顺序对照整场的不同原文，成立至少两处，问题至少三处')
        if (not isinstance(ids,list) or any(not isinstance(k,str) for k in ids) or len(ids)!=len(set(ids))
                or any(k not in known for k in ids) or (row['status']=='issue')!=bool(ids)):
            raise ValueError('表达验收问题编号不存在或与维度结论不一致')
    return copy.deepcopy(rows)
