# XS2 Novel Flywheel Workflows

本插件的生产与参考 Workflow 使用包内本地 ID，加载时由 DeterminFlow Core 的
Resource Resolver（资源解析器）映射为最终 ID；插件代码不拼接资源前缀。

| Workflow | 主要阶段 | 主要落盘内容 |
|---|---|---|
| `reference-distillation` | 独立资料分窗、Writing DNA 分析、机制与冲突提取、证据校验 | 资料任务的 `learning/`；完成后进入共享写法库 |
| `style-compatibility-advisor` | 准备三类候选，按本书基线、题材、视角和篇幅判断适配 | `learning/compatibility_report.json` |
| `adopt-reference` | 保留已采用项，确认新增风格、写法与本书冲突适配 | `learning/blueprints/`、`learning/active_context.md` |
| `build` | 六维世界观并行生成、校验、合并 | `world/` 与 `meta/world_foundation.md` |
| `character` | 角色骨架、信念、深层维度、声音 | 角色 JSON 与角色档案 |
| `story-plan` | 故事宏观规划、风格提取 | 故事规划与风格档案 |
| `outline` | 卷纲、近纲 | 大纲版本与 Markdown |
| `mvp` | 世界状态、导演、角色状态、写手、整合 | 章节正文与中间状态 |
| `post-hoc` | 章节观察、裁决、状态回写 | 世界/角色差异、伏笔与债务 |
| `polish` | 自审、两阶段润色 | 新的章节正文版本 |

新书建议按 `build` → `character` → `story-plan` → `outline` 建立生产前置。单章循环建议按
`mvp` → 可选 `polish` → `post-hoc` 执行，再进入下一章。若先做 `post-hoc`、后续润色又
改变了情节事实，应重新运行该章 `post-hoc`，避免连续性状态与最终正文不一致。

## 资源边界

- `resources/agents.json` 与 `resources/prompts.json` 只包含以上 Workflow 实际引用的资源。
- `resources/script-library/` 只包含生产流程使用的确定性脚本。
- Workflow Node 类型由 Core 提供，Plugin 只组合现有 Node。

## 运行前置

为同一本书运行不同 Workflow 时，必须填写相同的 `workspace_override`。本地存档脚本会
检查前置文件、构建章节上下文并保存结构化索引，不连接数据库，也不需要书籍 ID。

Agent Definition 不声明模型，Workflow 也不设置 `model_override`，因此所有 Agent Node
继承 Core `agents_config.json` 中的 `main.model`。每个 Agent Node 仍使用独立会话、
模型参数和工具权限，脚本节点负责确定性转换与本地落盘。

## Chat Main 协作

插件随包提供 `writing-assistant` Skill，安装后有效 ID 通常为
`xs2-novel-flywheel-writing-assistant`；若安装时覆盖了资源 Prefix，应以 `get_skills` 返回的
实际 ID 为准。该 Skill 默认加入 Core `default` 组并开启自动注入；用户可以在 Skill
页面覆盖这一默认值。它要求 Main 在操作前读取实际 Workflow 定义，并以写作助手和工作流
主管的身份帮助用户选择流程、收集必要创作输入、监督 Task 和核验文件结果。

Chat Main 的 `create_and_attach_task` 不直接接收 `workspace_override`。为了让各条 Workflow
共享同一本书，同一 Main 会话内应使用 `workspace_mode=named_shared`，并为这本书的每个
Task 复用相同 `workspace_ref`。`named_shared` 以 Main 会话隔离，新会话不能只凭同名
`workspace_ref` 连接旧目录；跨会话使用应继续原会话，或由 Web/API 复用同一个
`workspace_override`。

## 参考学习

小说生产不要求先蒸馏。资料在独立任务中分析，再从共享写法库加入本书候选；「本书参考写法」提供可选的兼容分析与采用确认，不占用小说生产步骤。

选择结果包含 `selected_candidate_ids`、`selected_style_ids`、`selected_conflict_ids` 及对应候选集哈希。新增冲突必须在 `reference_adaptations` 中提供本书的抽象适配，未提供迁移建议的风格也必须适配。确认脚本校验编号、哈希与适配内容，追加生成版本化蓝图；重复确认不生成新版本，已有规则不会被取消或覆盖。

已确认的风格表达原则、叙事机制和因果冲突进入故事规划、大纲、章节生产、润色和后验的文件上下文。原作情节、人物与证据原句不作为写作指令。人物档案、当前状态和本书风格基线决定具体写法；短篇回收核心冲突，长篇普通章节保持主线连续。

