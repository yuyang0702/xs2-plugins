# XS2 Novel Flywheel

`xs2-novel-flywheel` 基于 `bishu-novel` 的本地小说生产流程改造，保留原有建书、规划、写作、后验和润色链路，并新增用户可选择的参考资料蒸馏。它把长链路写作流程拆成
独立 Agent Node、确定性脚本和文件检查点，所有小说资料都保存在用户选择的本地
Workflow Workspace（工作流工作区）中。

## 发布内容

| 本地 Workflow ID | 用途 |
|---|---|
| `reference-distillation` | 独立分析参考资料，生成风格、写法与冲突候选 |
| `style-compatibility-advisor` | 根据本书题材、视角和风格基线给出适配建议 |
| `adopt-reference` | 确认本书参考，追加保存已采用规则 |
| `build` | 构建世界观的六个核心维度 |
| `character` | 生成角色骨架、信念、深层维度和声音 |
| `story-plan` | 生成故事规划与风格档案 |
| `outline` | 生成卷纲和近纲 |
| `mvp` | 生产章节正文，支持单写手或多写手组合 |
| `post-hoc` | 根据成稿更新世界、角色、伏笔和叙事债务 |
| `polish` | 自审、人文化处理和专业润色 |

包内还包括：

- 34 个生产 Agent/Prompt，以及 Workflow 需要的 Script Library；
- `writing-assistant` Skill，让 Main 同时作为用户的写作助手和写作工作流主管；
- `world/`、`meta/`、`outline/`、`story/`、`archive/` 与 `cache/` 组成的本地存档；
- 工作区内的文件完整性检查、JSON 索引和 Markdown 渲染。

## 运行要求

- DeterminFlow Core `v0.1.0` 或兼容版本
- Core `main` Agent 使用的默认模型和凭据需要完成配置

安装后不需要数据库、迁移、API、HMAC Key 或 UUID。运行每条 Workflow 时，为同一本书
填写相同的 `workspace_override`，例如 `data/books/my-novel`。书籍目录名由用户自行决定，
无需注册或生成 ID。

建议依次运行：`build` → `character` → `story-plan` → `outline` → `mvp` →
可选 `polish` → `post-hoc`。每条流程会直接复用同一工作区中的已有文件；进入下一章前
应完成当前章的 `post-hoc`，让后续章节读取已更新的连续性状态。

通过 Chat Main 使用时，安装后的 `xs2-novel-flywheel-writing-assistant` Skill 默认启用并自动
注入 Main，会维护书籍上下文、选择下一条 Workflow、解释创作参数并监督落盘结果。用户仍可
在 Skill 页面关闭自动注入。同一 Main 会话创建不同 Task 时应使用相同的 `named_shared`
工作区名称；需要跨 Main 会话继续时，当前 Chat 工具不能仅凭同名 `workspace_ref` 重新连接
旧目录，应继续原会话，或通过 Web/API 使用固定的 `workspace_override`。

插件内的 Agent Definition（智能体定义）不固定模型，所有 Agent Node 默认继承 Core
`agents_config.json` 中 `main.model` 指向的模型。切换 Core 默认模型即可统一切换整套
工作流使用的模型，无需修改插件资源。

## 文档

- [Workflow 与资源](docs/workflows.md)
- [本地存档结构](docs/local-archive.md)
- [写作助手 Skill](resources/skill-bundles/writing-assistant/SKILL.md)

## License

XS2 Novel Flywheel 使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
## 参考资料蒸馏

运行 `reference-distillation` 后，脚本会把导入的 TXT/Markdown 语料按句子边界拆成窗口；导入时可标记为短篇全文、长篇章节样本或自动识别。每个窗口由 Agent 提取候选机制，再由本地脚本校验证据位置、来源哈希和输出结构。候选会标注语言、结构、叙事镜头、对话、意象、主题等层次，并记录来源视角、目标视角、适配建议、风险和篇幅适用范围（短篇全文、长篇开局、长篇章节、长篇卷级或通用）。跨窗口的相近机制会合并为一个候选，保留全部证据和变体，结果写入 `learning/candidates.json`，并生成 `learning/selection.html`。候选默认不会进入正文流程。

用户把下载的选择结果保存为 `learning/selection.json`，内容必须带有候选集哈希和 `selected_candidate_ids`。然后运行 `adopt-reference` Workflow，它会创建不可覆盖的 `learning/blueprints/vNNNN.json`，并生成 `learning/active_context.md`。`story-plan`、`outline`、`mvp`、`polish` 和 `post-hoc` 会读取这个文件；没有采用任何机制时，这些流程照常运行。

采用是追加操作：已确认机制和原来的使用边界持续保留，之后只合并明确选择的新增项。
空选择、子集选择和重复确认不会删除写法，也不会创建空的新版本。新来源不会覆盖之前的蓝图，
各来源记录随蓝图保留；候选更新仍需兼容判断和明确确认，不能修改旧机制来绕过确认。

生成流程只收到抽象机制、迁移建议和使用边界。参考资料正文、标题、人物、具体事件和原句不会进入创作上下文。

### 可选方向与跨作品写法库

小说创作流程从建书开始，不包含资料蒸馏、兼容分析和采用确认。没有参考资料时可以直接创作。

工作台的「资料蒸馏」是独立模块：资料保存在 `data/workspaces/reference-jobs/`，任务不会登记成小说，也不改变当前作品进度。完成后自动保存到 Core 的 `data/writing-library/`；切换工作台页面仍继续检查任务与入库，同来源的新分析由后端合并。关闭整个应用会停止页面轮询，下次打开会恢复任务并检查入库。

复用时，在「写法库」阅读具体内容并加入本书候选，再到「本书参考写法」检查适配、选择并确认。加入候选和已采用是两个状态。风格、写法、冲突分别显示已采用数量；确认后锁定已采用条目，后续只能新增，兼容顾问给出的建议不会自动采用。每本书的 `meta/style_profile.md` 仍由 `story-plan` 生成，是该书唯一的统一风格基线。

每本新书使用 `data/workspaces/books/<slug>` 独立工作区。写法库只保存可复用的抽象规则和证据摘要，不共享正文、角色或世界观；第一人称与第三人称不匹配时，工作台会提示需要适配或存在风险。

### Writing DNA 与小说适配

上游 `writing-dna-skill` 的真实指令、中文模板和 MIT 许可证保存在
`resources/script-library/xs2/reference_distill/vendor/writing-dna-skill/`，来源提交记录在
`UPSTREAM.json`。`NOVEL_ADAPTER.md` 说明小说样本、短长篇、证据和采用边界。
分窗提取之后汇总五份上游文档（语言、结构、视角、视觉、综合风格），另产出小说扩展
`人物写法.md`，结果在 `learning/dna/profile.json` 和写法库中可阅读。
文风以样本实际表现为依据，不预设固定专项；冲突链与人物写法必须有可核验的窗口证据。
特殊字体字符通过脚本生成的证据编号定位，仍严格校验原文；未出现的内容标明未知。
视觉资料缺失时不推断图片或页面设计。

风格、写法与冲突都可分别选择进入本书参考。风格条目使用抽象的迁移建议；冲突条目必须先填写本书适配方式，把原作事件改成有前因、选择、代价和回收的因果机制。顾问会帮助判断短长篇、题材与视角差异，并可将适配建议填入草稿供修改。当前书没有基线时也能获得暂定建议，不阻塞原创创作。本书基线仍由
`meta/style_profile.md` 决定，源风格不会自动覆盖它。写法库升级保留原候选编号；
更新本书候选时也保留已确认蓝图，新增规则需再次确认。

正文与润色复用人物档案、声线和持续更新的人物状态，从人物当前所知、欲望、顾虑、
关系和选择代价出发，读者检查具体的工具人化与无动机变化。没有蒸馏也执行这些检查。
表达参考不要求完全模仿，不设置固定句式、标点或修辞配额。场景通过人物所见、所做、所说与判断变化推进，避免写成模拟记录；配角保留自己的利益、拒绝理由与情绪后果。生成、润色和读者评估都会检查这些要求，并通过原有后验流程更新人物和伏笔状态。
短篇按全文完结审核；长篇 `chapter_ending_mode=continue` 默认保留主线，只完成局部推进，
明确设置为 `book_final` 才按全书终章审核。导出或自动批次的最后一章不等于全书完结。

