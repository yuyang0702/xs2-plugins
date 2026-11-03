---
name: prose_policy
description: Audit book-local expression rules, preview exact overrides, and prepare effective workflow context.
type: python
---

# 作品叙述偏好

默认 `inherit`。读、体检、预览和计算有效文字不创建文件、不调用模型。宿主必须先解析真实作品工作区，执行 owner、execution policy、手动控制和忙碌检查，再调用写接口。脚本不创建不存在的工作区。

在设置页先调用 `read` 取得修订号。用户可直接采用 `narrative_led`，也可在体检结果中选择一条可覆盖的表达建议，预览后提交完整凭证。可只切换模式，或用空列表撤回全部覆盖。原人物卡、声线、大纲、正文、已确认事实和模型设置始终保留。

## Python

通过文件 `prose_policy.py` 导入下列函数（支持 `importlib.util.spec_from_file_location`）。`root` 是现存作品工作区的 `Path` 或字符串；`chapter` 接受 1–6 位正整数文本或整数，返回至少四位的章节编号。输入错误或并发冲突抛出 `ValueError`；调用方应提示刷新或重新预览。

| 函数 | 返回 |
| --- | --- |
| `read(root)` | `{mode, revision, overrides, stale_overrides}` |
| `audit(root, chapter="0001")` | `{chapter, revision, sources, findings, stale_overrides}` |
| `preview_override(root, payload, expected_revision)` | 一条完整预览凭证 |
| `save(root, payload, expected_revision)` | 与 `read` 相同的最新视图 |
| `effective_text(root, source_id, text=None)` | 有效文字字符串；未指定 `text` 时读取指定原件。传入原件全文可复用调用方读取，派生或截断文字不会被搜索替换 |
| `effective_context(root, chapter="0001")` | `{mode, revision, instructions, stale_overrides}`；继承模式的 `instructions` 为空 |
| `prepare_runtime(root, chapter="0001", *, task_id)` | `{task_id, context, aliases, directory, prompt_file}`；`context` 同上，`aliases` 是原件相对路径到有效文件相对路径的映射。继承模式没有别名，`directory`、`prompt_file` 为空 |

体检的 `sources` 包含 `source_id`、`source_kind`、`source_sha256`、`status`（`present`、`missing`、`unavailable`）、`provenance`。每项 `findings` 含 `source_id`、`source_kind`、`source_sha256`、`source_category`、`provenance`、`review_status`、`quote`、`start`、`end`、`line`、`rule`、`reason`、`override_eligible`、`suggestion`。定位按 UTF-8 解码、去 BOM、保留原换行计算：行号从 1 起，字符区间 `[start, end)` 从 0 起。SHA-256 对原始文件字节计算。

`review_status="candidate"` 表示模式线索，须由作者核对。角色档案/声线、风格、故事规划、卷纲近纲、指定章节细纲/意图卡及共同上下文均纳入体检。 `source_category` 是格式边界提示（`expression_advice`、`protected`、`unknown`）；`provenance` 不凭目录名、正则命中或提示词猜测，未知时为 `unknown`。

### 预览与确认

1. 用 `preview_override(root, {"source_id": finding["source_id"], "quote": finding["quote"], "replacement": replacement}, revision)` 预览。必须是当前文件内唯一、完整、单行的表达建议。允许明确的表达类 Markdown 小节（如“表达建议”“表达倾向（非固定台词）”）。未标注、混有事实、来源不唯一、作者要求、已确认事实、身份、知识、世界规则、生成缓存或 JSON 记录只供核对。不会批量替换“必须/不得”等词。
2. 展示凭证的 `source_id`、`before` 和 `after`。完整凭证包含 `preview_id`、`revision`、`source_id`、`source_sha256`、`source_category`、`quote`、`replacement`、`start`、`end`、`before`、`after`。
3. 用户确认后调用 `save(root, {"mode": "narrative_led", "overrides": [preview]}, revision)`。列表代表全部保留的覆盖，可附上当前 `read` 返回的、仍有效的旧凭证。省略 `overrides` 保留现有列表；传 `[]` 撤回全部。切回 `inherit` 会停用已存覆盖。

凭证是无状态、可重算的确认载荷；服务按当前作品、偏好修订、原件哈希、原文位置和替代文字重新校验。请求缺少凭证、凭证遭编辑、偏好修订过期或原件已变时拒绝确认。原件后来变化时，`stale_overrides` 返回 `{preview_id, source_id, quote, reason}` 并停用该覆盖；保留旧记录供复核。只写 `learning/prose_policy/policy.json` 和同目录的进程锁，原子提交的文件同时记录被替换的修订；撤回用新的预览/确认，不回滚原件。

## CLI

在作品目录内运行 `python -X utf8 <script-library>/xs2/prose_policy/prose_policy.py <command>`。成功输出一行 UTF-8 JSON。

| 命令 | 参数或输入 |
| --- | --- |
| `read` | 无 |
| `audit` | `--chapter 0001`（可省） |
| `preview-override` | `--expected-revision <revision>`；标准输入为预览 payload JSON |
| `save` | `--expected-revision <revision>`；标准输入为确认 payload JSON |
| `effective-context` | `--chapter 0001`（可省） |
| `prepare-runtime` | `--task-id <id>`，可加 `--chapter 0001`；此命令会准备任务内文件 |

## 工作流消费

`story_support context` 在已采用模式下通过现有节点输出任务内偏好、共同上下文及确切的文件别名，规划、正文、润色与评估使用相同输入。隐藏输入仍绑定原路径，有效文件变量用 `pp_` 前缀；没有覆盖时仍由宿主读原路径。由另一文件派生的短篇上下文和历史缓存走各自的有效投影，原件与原有归档格式保持。当前已确认的正文和证据仍按原件核验；独立、未能证明同源的旧文件不会靠文字相同自动修改。

运行时副本只写入 `learning/prose_policy/runtime/<任务摘要>/<本次快照>/`。 `task_id` 必须是 1–128 个 ASCII 字母、数字、下划线或连字符，以字母或数字开始。每次准备使用独立快照目录；内部桥接按任务标识验证目录。无偏好时保留原上下文路径，保持模型配置、既有工作流节点和输出契约。
