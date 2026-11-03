# 人物中心 HTTP 契约

所有接口需要 `workflow_id` 和 `workspace`，GET 用查询参数，POST 用 JSON。路径沿用工作台工作区深链。成功返回 200，FastAPI 以 `{detail}` 返回错误，422 为请求校验，400 为无效范围，404 为不存在的工作区，409 为忙碌、过期、不可用服务或不能确认的预览。助手原有错误状态仍可返回 503。UI 应保留作者草稿，刷新后重新预览。

## 人物与原件

- `GET /api/humanware/characters?workflow_id=…&workspace=…&chapter=0002&q=…`。两个附加参数可省，默认最近可用的确认章节，搜索按姓名和原文做子串过滤。
- 返回 `{revision, chapter, chapters, stale_chapters, characters, world_facts, sources, warnings}`。修订号为 SHA-256 字符串。`chapter` 是当前查看编号或空字符串，`chapters` 和 `stale_chapters` 分别列出可用和失效章节编号。原件 `sources[]` 为 `{source_id, kind, status, revision, raw}`，其中 kind 为 profile 或 voice，status 为 present 或 missing，缺失时 revision 为 null。warnings 是文本数组。
- `characters[]` 为 `{id,name,title,status,warnings,sections,relationships,states,planned_arcs,raw}`。status 为 structured 或 legacy。raw 是 `{source_id,title,text}[]`。显示未识别的文字时可回到原文或既有声音编辑入口。
- `sections[]` 为 `{id,source_id,source_revision,group,label,text,editable,ai_editable,line}`。group 为 overview、motivation、relationships、voice、facts、constraints 或 plan。line 从 1 起。关联显示用 section 的 ID，切换档案后应重新读取。
- `relationships[]` 为 `{target,target_id,nature,meaning,tension,attitude,text,source_id,section_id,provenance}`，target_id 或 section_id 无法唯一定位时为 null。provenance 为 profile、voice 或 confirmed_state，方向为当前人物指向 target。
- `states[]` 为 `{chapter,source_chapter,source_id,evidence,snapshot,drives,knowledge,beliefs,relationships}`。chapter 是快照章，source_chapter 是正文证据章，source_id 是该章正文相对路径。结构不全的记录可省略，未知子字段无需推断。world_facts 为 `{description,source_chapter,source_id,evidence}[]`，与人物主观状态分开。
- `planned_arcs` 采用与 sections 相同的形状，属于计划。

## 局部修改与历史

- `POST /api/humanware/character-preview` 送 `{workflow_id,workspace,character_id,section_id,source_id,expected_revision,replacement}`，expected_revision 使用 characters 的 revision。回退可用 `{workflow_id,workspace,character_id,expected_revision,history_id}` 送同一入口。
- 返回 `{preview_id,revision,source_revision,source_id,character_id,section_id,before,after,line,impact,history_id}`。impact 是文本，普通预览的 history_id 为 null。助手建议的预览另带 `assistant_source`，以便确认时复查试写依据。该对象原样回传。凭证由当前服务进程签名，服务重启或升级后须重新预览。
- `POST /api/humanware/character-apply` 送 `{workflow_id,workspace,expected_revision,preview}`，preview 是未改动的完整预览。返回 `{status:"success",revision,entry}`。
- `GET /api/humanware/character-history` 接受可省略的 character_id。返回 `{entries}`，每条为 `{id,created_at,character_id,section_id,source_id,before,after,revision_before,revision_after,source_revision_before,source_revision_after,restored_from}`。最新记录在前。

## 本书叙述偏好

- `GET /api/humanware/prose-policy`、`GET /api/humanware/rule-audit?…&chapter=0001` 分别直接返回 SCRIPT.md 的 read 和 audit 结果（见同组 prose_policy）。
- `POST /api/humanware/prose-policy` 送 `{workflow_id,workspace,expected_revision,mode?,overrides?}`。模式为 inherit 或 narrative_led，省略 overrides 保留现有覆盖，`[]` 撤回。返回更新后的 read 结果。
- `POST /api/humanware/rule-audit` 送 `{workflow_id,workspace,expected_revision,source_id,quote,replacement}`，返回一份完整覆盖凭证，确认时把凭证原样放入 overrides。

## 可选助手

- `POST /api/novel-console/assistant` 送 `{workflow_id,workspace,request_id,purpose,question,chapter,character_id?,section_id?,character_ids?,baseline?,scene?,expected_revision}`。request_id 是 UUID，同次提交重发沿用 ID，失败后主动重试使用新 ID。character_edit 需要 character_id、section_id，dialogue_trial 需要 character_ids、baseline、scene。expected_revision 为人物总修订；chapter 为选择的章节。
- 返回 `{success:true,entry}`。轮询 `GET /api/novel-console/assistant/history?…` 得 `{entries}`。沿用助手条目的 id、purpose、chapter、status（running/completed/failed）、created_at、finished_at、attempt、message、error_code、model、elapsed_seconds。成功 character_edit 的 suggestion 是完整人物预览，正常确认流程采用。成功 dialogue_trial 的 trial 为 `{chapter,character_ids,scene,baseline,candidate,checks}`，checks 是文本数组。已过期的完成结果在读取时带 `stale:true`。
- `POST /api/novel-console/assistant/trial-accept` 送 `{workflow_id,workspace,entry_id,preferred,reason,carry_forward}`，返回 `{status:"success",preference}`。preference 为 `{entry_id,chapter,character_ids,scene,preferred,reason,carry_forward,created_at,production_match}`。preferred 为 baseline 或 candidate。`production_match=false` 表示已保存为同场景后续试读参考，目前大纲没有可唯一定位的场景及出场人物。生产使用需由本章大纲以 `### 场景：收伞` 一类的标题和同段 `出场人物：阿杏、掌柜` 精确绑定。

示例原件 `meta/character_voice.md` 内容如下。查询阿杏后可选中“表达倾向”，预览把原文替换为“与熟人说到手艺时会多解释几句”，再带同一预览和版本确认。

```md
## 阿杏

表达倾向（非固定台词）：说到手艺时愿意多解释。
- 关系情境参考（可随情境调整），面对掌柜：会问清他的顾虑。
```
