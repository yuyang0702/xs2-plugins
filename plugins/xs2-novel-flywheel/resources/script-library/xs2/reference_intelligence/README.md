# Reference Intelligence System (参考作品智能推荐系统)

## 概述

这是一个为小说创作系统设计的智能推荐引擎，能够根据小说的当前状态（类型、章节位置、剧情阶段等）自动推荐最相关的写作技巧，并提供跨类型适配、剧情规划和原创性监控功能。

## 核心模块 (7个文件)

### 1. recommender.py - 智能推荐器
**功能**：根据小说上下文智能推荐技巧
- 输入：小说类型、当前章节、总章节数、剧情阶段、冲突阶段、活跃冲突、主要角色
- 输出：优先级排序的技巧列表（1-5级，5最高）
- 推荐策略：
  - **章节位置**：开篇（前10%）推荐引入技巧，中段推荐冲突升级，高潮推荐反转
  - **剧情阶段**：setup/rising/climax/falling/resolution 各有侧重
  - **冲突阶段**：introduction/escalation/peak/resolution 对应不同技巧类型

### 2. genre_adapter.py - 类型适配器
**功能**：将参考作品技巧适配到目标小说类型
- 支持类型：都市、玄幻、悬疑、言情、科幻、历史
- 输出：每个技巧的兼容性评分（0-1）+ 状态标签
  - `direct`（0.9+）：直接可用
  - `adapt`（0.7-0.9）：需微调
  - `risky`（0.3-0.7）：慎用
  - `incompatible`（<0.3）：不兼容
- 附带类型特定的示例和警告

### 3. plot_planner.py - 剧情规划器
**功能**：基于参考作品规划9段式剧情结构
- 9个关键节点：
  1. Opening（开篇）
  2. Inciting Incident（激励事件）
  3. First Plot Point（第一转折）
  4. Rising Action（上升行动）
  5. Midpoint（中点）
  6. Climax Build（高潮构建）
  7. Climax（高潮）
  8. Resolution（解决）
  9. Epilogue（尾声）
- 输出：每个节点的建议章节位置、描述、关键技巧、节奏分析、注意事项

### 4. context_builder.py - 上下文构建器
**功能**：为不同工作流构建定制化上下文
- 支持工作流：
  - `mvp`：章节生产，侧重对话、动作、描写技巧
  - `outline`：大纲创作，侧重剧情、结构、伏笔技巧
  - `polish`：润色打磨，侧重风格、节奏、细节技巧
- 智能过滤：每个工作流只加载最相关的N个技巧（默认8个）
- 输出：Markdown格式的上下文文件，直接供Agent使用

### 5. originality_monitor.py - 原创性监控器
**功能**：实时检测草稿与参考作品的相似度
- 检测粒度：段落级（按换行符分割）
- 相似度算法：基于字符级n-gram（默认n=3）
- 严重程度：
  - `low`（<0.5）：安全
  - `medium`（0.5-0.75）：注意
  - `high`（0.75-0.9）：警告
  - `critical`（>0.9）：严重抄袭嫌疑
- 输出：Markdown报告 + JSON数据，包含重写建议

### 6. intelligence_api.py - 统一API
**功能**：CLI命令行接口 + Python函数调用API
- 5个命令：
  ```bash
  # 推荐技巧
  python intelligence_api.py recommend --chapter 15 --novel-info learning/novel_info.json
  
  # 适配类型
  python intelligence_api.py adapt-genre --genre 都市 --reference learning/reference_analysis.json
  
  # 规划结构
  python intelligence_api.py plan-plot --outline meta/story_plan.md --chapters 100
  
  # 构建上下文
  python intelligence_api.py build-context --workflow mvp --chapter 15 --novel-state learning/novel_info.json
  
  # 检查相似度
  python intelligence_api.py check-similarity --draft story/0015/chapter.md --workspace .
  ```

### 7. __init__.py - 模块导出
导出所有公共类和函数，支持包导入：
```python
from xs2.reference_intelligence import (
    TechniqueRecommender,
    GenreAdapter,
    PlotPlanner,
    ContextBuilder,
    OriginalityMonitor,
)
```

## 数据流

```
导入小说
    ↓
参考分析（reference-distillation工作流）
    ↓
learning/reference_analysis.json
    ↓
┌─────────────────────────────────────────┐
│  Reference Intelligence System          │
├─────────────────────────────────────────┤
│ 1. Recommender → recommendations.json   │
│ 2. GenreAdapter → adapted_techniques.json│
│ 3. PlotPlanner → plot_suggestions.json  │
│ 4. ContextBuilder → active_context.md   │
│ 5. OriginalityMonitor → (实时检测)      │
└─────────────────────────────────────────┘
    ↓
工作流（mvp/outline/polish）自动加载智能上下文
    ↓
生成高质量章节
```

## 输入数据格式

### novel_info.json（小说状态）
```json
{
  "genre": "都市",
  "total_chapters": 100,
  "current_chapter": 15,
  "pov": "third_person",
  "plot_stage": "rising",
  "conflict_phase": "escalation",
  "active_conflicts": ["职场竞争", "感情纠葛"],
  "main_characters": ["主角", "配角A", "反派B"]
}
```

### reference_analysis.json（参考分析）
```json
{
  "source_title": "某参考小说",
  "techniques": [
    {
      "id": "tech_001",
      "name": "冲突升级技巧",
      "category": "plot",
      "description": "通过连续小挫折累积压力...",
      "examples": ["示例1", "示例2"],
      "applicable_stages": ["rising", "climax"],
      "effectiveness": 0.85
    }
  ]
}
```

## 输出数据示例

### recommendations.json
```json
{
  "chapter": 15,
  "total_recommended": 8,
  "recommendations": [
    {
      "technique_id": "tech_001",
      "name": "冲突升级技巧",
      "priority": 5,
      "reason": "当前处于上升阶段第15章，适合使用冲突升级",
      "context_relevance": 0.92
    }
  ]
}
```

### adapted_techniques_都市.json
```json
{
  "target_genre": "都市",
  "adapted_count": 25,
  "techniques": [
    {
      "id": "tech_001",
      "compatibility": 0.95,
      "status": "direct",
      "genre_example": "都市职场可直接使用此冲突升级手法",
      "warnings": []
    }
  ]
}
```

### active_context.md（工作流上下文）
```markdown
# 当前章节推荐技巧（第15章）

## 高优先级技巧（Priority 5）

### 1. 冲突升级技巧
**类别**：剧情
**适用**：当前处于上升阶段，冲突正在升级
**描述**：通过连续小挫折累积压力...
**示例**：
- 示例1
- 示例2

## 中优先级技巧（Priority 3-4）
...
```

## 与现有系统集成

### 1. 导入模块自动触发
- 用户通过导入模块（URL/TXT）导入参考小说
- `reference-distillation` 工作流自动分析生成 `reference_analysis.json`
- Reference Intelligence System 自动生成推荐数据

### 2. 工作流自动加载
- MVP工作流读取 `learning/active_context.md`（由 ContextBuilder 生成）
- Outline工作流读取 `learning/plot_suggestions.json`
- Polish工作流读取 `learning/adapted_techniques_{genre}.json`

### 3. 实时监控
- 章节生成后，OriginalityMonitor 自动检测相似度
- 超过阈值（默认0.75）自动生成警告报告
- 前端展示相似段落 + 重写建议

## 关键设计

1. **非侵入性**：所有功能可选，不影响现有工作流
2. **智能过滤**：避免信息过载，每次只推荐最相关的8-10个技巧
3. **跨类型支持**：参考玄幻小说也能为都市小说提供抽象技巧
4. **原创性保障**：段落级相似度检测，防止无意抄袭
5. **向后兼容**：没有导入参考时，系统照常运行，只是没有推荐

## 未来扩展

- [ ] 集成到主系统的 `novel_routes.py` API
- [ ] 前端UI展示推荐技巧
- [ ] 支持百万字长篇小说导入（当前限制20章）
- [ ] 多参考作品混合推荐
- [ ] AI自动提取参考作品的"写法基因"
- [ ] 实时相似度检测的前端可视化

## 技术栈

- Python 3.10+
- 纯标准库实现（无外部依赖）
- 类型注解完整
- 文档字符串完善
- 支持CLI和包导入两种模式

## 文件大小

- recommender.py: ~550行
- genre_adapter.py: ~450行
- plot_planner.py: ~500行
- context_builder.py: ~350行
- originality_monitor.py: ~400行
- intelligence_api.py: ~300行
- __init__.py: ~70行
- **总计**: ~2600行代码

## 作者

XS2 Novel System Team

## 版本

v0.1.0 (2026-10-11)
