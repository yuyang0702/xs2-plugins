"""Update plugin-owned creative guidance without changing workflow/model schemas."""
import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]


def update(root=PLUGIN):
    root = Path(root)
    spec = importlib.util.spec_from_file_location(
        'creative_latitude', root / 'resources/script-library/xs2/prose_policy/creative_latitude.py')
    policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)
    path = root / 'resources/prompts.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    characters = {'novel-short-character', 'novel-character-skeleton', 'novel-character-belief',
                  'novel-character-deep', 'novel-character-voice', 'novel-character-semantic-review'}
    planners = {'novel-director', 'novel-outliner', 'novel-volume-outliner', 'novel-story-planner',
                'novel-multi-scene-planner', 'xs2-serial-planner', 'xs2-composition-planner'}
    reviewers = {'novel-character-semantic-review', 'novel-self-critic', 'novel-polisher',
                 'novel-professional-polisher', 'xs2-reader-sim', 'xs2-blind-reader',
                 'xs2-draft-auditor', 'xs2-draft-repairer', 'xs2-fragment-reviewer',
                 'xs2-local-revision-critic', 'xs2-local-revision-writer', 'xs2-local-revision-reviewer',
                 'xs2-serial-reviewer', 'xs2-composition-reviewer', 'xs2-opening-lead-reviewer'}
    writers = {'novel-writer', 'novel-single-writer', 'novel-multi-scene-writer',
               'novel-storyboard-integrator', 'novel-dialogue-writer', 'novel-action-writer',
               'novel-internal-writer', 'novel-description-writer', 'novel-transition-writer', 'xs2-opening-lead'}
    other = {'novel-short-world', 'novel-style-profiler', 'novel-character-maintainer',
             'novel-observer', 'novel-chapter-observer', 'novel-settler', 'novel-intent-distributor',
             'xs2-reference-distiller', 'xs2-style-compatibility-advisor'}
    other.update(name for name in data['agents'] if name.startswith('novel-worldbuilder-'))
    for name in sorted(characters | planners | reviewers | writers | other):
        sections = data['agents'][name]['sections']
        content = policy.CONTEXT_GUIDANCE
        if name in characters: content += policy.CHARACTER_GUIDANCE
        if name in planners: content += policy.PLANNING_GUIDANCE
        if name in reviewers: content += policy.REVIEW_GUIDANCE
        existing = next((s for s in sections if s['name'] == 'creative_latitude'), None)
        if existing is None:
            existing = {'name': 'creative_latitude', 'cache_break': False, 'cache_break_reason': '',
                        'workflow_only': False, 'order': max((s.get('order', 0) for s in sections), default=0) + 1}
            sections.append(existing)
        existing.update(content=content, enabled=True, token_estimate=len(content))

    # Remove conflicting obligations rather than merely appending an exception.
    replacements = {
        '你是一位风格宪法起草人。': '你为本书整理风格档案，帮助写手理解作品的表达气质与可选择的参照。',
        '翻译**成一份风格宪法': '翻译**成一份风格档案',
        '你定义"什么能做、什么不能做"的边界，不定义"怎么做"。':
            '你描述本书的表达倾向与作者已明确的边界，不替作者新增禁令或规定执行话术。',
        '创作边界，每条定义不能做什么，3-6条，每条≤50字':
            '作者明确禁令或已确立的作品边界；允许为空数组，不凑数量',
        '创作边界。每一条定义的是**不能做什么**，而非**应该怎么做**。3-6条，每条≤50字。':
            '仅收作者明确禁令或已有设定中确立的作品边界，允许为空数组。模型推导的偏好写成倾向或可选建议，不放入commandments。',
        '硬约束：每条必须是创意层面的禁令；':
            '每条边界须能追溯至作者要求或已确立设定，不从题材惯例制造禁令；',
        '可选题材笔法——{{genre}}题材特有的创作惯例和禁忌，边界性质非执行指令，≤200字。无明确题材惯例时可省略为空字符串':
            '可选题材参考——{{genre}}中可能有用的阅读效果或惯例，不自动成为禁令；无相关内容时为空字符串',
        '{{genre}} 题材特有的创作惯例和禁忌——仍然是边界性质，而非执行指令。无明确题材惯例时可省略为空字符串 ""。≤200字。':
            '{{genre}} 中可能有用的阅读效果或惯例，仅作启发，不要求本书遵循。不得从题材标签推导新禁令；没有相关参考时填空字符串 ""。',
        '记录空间、资源、权限、时间与信息限制；保留现实成本及能力边界。':
            '记录本篇实际相关的空间、资源、时间与信息条件；仅在会影响事件时说明权限、成本和能力边界，不为每个维度新增障碍。',
        '甲重视手艺被尊重，既想独立作主，也舍不得熟客的信任；面对乙愿意说明自己的考虑，能否让步取决于条件和已有关系。':
            '甲看重自己的手艺，有些自负；想独立作主，又舍不得熟客的信任。',
        '熟悉手艺的事较愿意解释；感到被轻视时可能追问，也可能直说顾虑，表达随关系和处境变化。':
            '谈熟悉的手艺时口气笃定；不善安慰，容易留意物件的毛病。这里只描述倾向，不安排现场反应。',
        '因为有过修伞往来，可能用双方知道的事说明考虑，也可以直接回应眼前的问题；不规定交谈步骤。':
            '有过修伞往来，对乙熟悉又有些在意评价；亲近与不服气可能同时存在。',
    }
    for name in characters | {'novel-style-profiler', 'novel-short-world'}:
        for section in data['agents'][name]['sections']:
            for before, after in replacements.items():
                section['content'] = section['content'].replace(before, after)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    update()
