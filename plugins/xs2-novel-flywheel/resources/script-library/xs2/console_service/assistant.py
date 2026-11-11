"""Workspace-scoped novel adviser requests that survive browser navigation."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from types import SimpleNamespace

from .configuration import ADVISOR_PROMPT, CONFIGURATION_PROMPT, advisor_catalog, parse_advisor, parse_configuration
from .production import length_quality

logger = logging.getLogger(__name__)
ANALYSIS_TIMEOUT_SECONDS = 180
ADVISOR_COMPLETION_TIMEOUT_SECONDS = 600
# The provider can occasionally drop a connection after a long handshake or
# response wait.  One bounded retry is enough to absorb that transient without
# turning a single click into an unbounded queue of requests.
TRANSIENT_RETRY_DELAYS_SECONDS = (2,)
HISTORY_LIMIT = 80
HISTORY_PATH = "learning/assistant-history.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _close_model(model):
    """Close only an explicit model lifecycle; nested SDK transports are borrowed."""
    try:
        close = getattr(model, 'aclose', None) or getattr(model, 'close', None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
    except Exception:
        pass


def _safe_attribute(value, name, default=None):
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _provider_diagnostics(error, model=None):
    """Only allowlisted classifications leave the exception boundary."""
    result = {'types': [], 'closed_client': False, 'tls': False, 'proxy': False,
              'dns': False, 'errnos': [], 'transports_closed': []}
    seen = set()
    while error is not None and id(error) not in seen and len(seen) < 12:
        seen.add(id(error))
        name = type(error).__name__
        result['types'].append(name if name.isidentifier() else 'Exception')
        try:
            text = str(error).lower()
        except Exception:
            text = ''
        result['closed_client'] |= 'client has been closed' in text or 'client is closed' in text
        result['tls'] |= 'ssl' in name.lower() or 'certificate_verify_failed' in text
        result['proxy'] |= 'proxy' in name.lower()
        result['dns'] |= name == 'gaierror' or 'getaddrinfo failed' in text
        errno = _safe_attribute(error, 'errno')
        if type(errno) is int:
            result['errnos'].append(errno)
        remote = _safe_attribute(error, 'provider_diagnostics')
        if isinstance(remote, dict):
            names = remote.get('types', [])
            if isinstance(names, list):
                names = [value for value in names[:12] if isinstance(value, str)
                         and value.isidentifier() and len(value) <= 80]
                result['types'].extend(names)
                result['tls'] |= any('ssl' in value.lower() for value in names)
                result['proxy'] |= any('proxy' in value.lower() for value in names)
                result['dns'] |= 'gaierror' in names
            for flag in ('closed_client', 'tls', 'proxy', 'dns'):
                if type(remote.get(flag)) is bool:
                    result[flag] |= remote[flag]
            if isinstance(remote.get('errnos'), list):
                result['errnos'].extend(value for value in remote['errnos'][:12] if type(value) is int)
        error = _safe_attribute(error, '__cause__') or _safe_attribute(error, '__context__')
    result['types'] = result['types'][:24]
    for name in ('root_async_client', 'root_client', '_async_client', '_client'):
        client = _safe_attribute(model, name)
        value = _safe_attribute(_safe_attribute(client, '_client', client), 'is_closed')
        if type(value) is bool:
            result['transports_closed'].append(value)
    return result


def _error_details(error: Exception) -> tuple[str, str]:
    """Return actionable errors without provider payloads or credentials."""
    name = type(error).__name__
    status = getattr(error, "status_code", None)
    if isinstance(error, TimeoutError) or "Timeout" in name:
        return "timeout", "模型连接长时间无响应，或本次分析超过等待上限，请重试或缩小问题范围。"
    if "Credential" in name or "Configuration" in name:
        return "configuration", "默认模型或凭据尚未配置，请在模型设置中检查。"
    if status in {401, 403} or "Authentication" in name or "PermissionDenied" in name:
        return "authentication", "模型服务拒绝了当前凭据，请在模型设置中检查凭据和权限。"
    if status == 429 or "RateLimit" in name:
        return "rate_limit", "模型服务当前限流或额度不足，请稍后重试并检查额度。"
    if "Connection" in name:
        return "connection", "无法连接模型服务，请检查网络和供应商地址后重试。"
    if status is not None:
        return "provider", f"模型服务返回 HTTP {status}，请稍后重试。"
    return "provider", "模型分析未完成，请重试；之前的分析记录仍然保留。"


def _is_transient_provider_error(error: Exception) -> bool:
    """Whether retrying the same assistant request is safe and useful."""
    name = type(error).__name__
    status = getattr(error, "status_code", None)
    if status in {401, 403, 404, 422}:
        return False
    if status == 429 or (isinstance(status, int) and status >= 500):
        return True
    return (
        isinstance(error, (TimeoutError, ConnectionError))
        or name in {"APIConnectionError", "ConnectError", "ReadTimeout", "WriteTimeout"}
        or "Connection" in name
        or "Timeout" in name
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        # Reasoning/tool blocks are not a final answer.
        return "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            and part.get("type", "text") in {"text", "output_text"}
        ).strip()
    return ""


async def _receive_model_reply(llm: Any, messages: list, on_output) -> Any:
    """Keep the transport alive while providers perform longer reasoning.

    Only final text blocks are collected. Preserve whitespace across chunks so
    JSON strings and readable Markdown aren't changed at token boundaries.
    """
    stream = getattr(llm, 'astream', None)
    if not callable(stream):
        return await llm.ainvoke(messages)
    parts = []
    notified = False
    async for chunk in stream(messages):
        content = getattr(chunk, 'content', None)
        if isinstance(content, str):
            part = content
        elif isinstance(content, list):
            part = ''.join(block.get('text', '') for block in content
                           if isinstance(block, dict) and isinstance(block.get('text'), str)
                           and block.get('type', 'text') in {'text', 'output_text'})
        else:
            part = ''
        if part:
            parts.append(part)
            if not notified:
                on_output()
                notified = True
    return SimpleNamespace(content=''.join(parts))


CHARACTER_PURPOSES = {'character_edit', 'dialogue_trial'}


class NovelAssistantJobs:
    def __init__(self, model_factory, support_loader, catalog_loader=None, character_loader=None) -> None:
        self.model_factory = model_factory
        self.support_loader = support_loader
        self.catalog_loader = catalog_loader
        self.character_loader = character_loader
        self._tasks: dict[tuple[Path, str], asyncio.Task] = {}

    @property
    def tasks(self):
        return {request_id: task for (_, request_id), task in self._tasks.items()}

    def _write(self, root: Path, entries: list[dict]) -> None:
        target = self._target(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="assistant-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "entries": entries[-HISTORY_LIMIT:]}, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _target(self, root):
        target = root.resolve() / HISTORY_PATH
        if target != target.resolve():
            raise ValueError("助手记录不能位于链接目录或文件。")
        return target

    def history(self, root: Path, *, check_freshness=False) -> list[dict]:
        root = root.resolve()
        target = self._target(root)
        if not target.is_file():
            return []
        data = json.loads(target.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("助手分析记录格式无效")
        changed = False
        for entry in entries:
            if entry.get("status") == "running" and (root, entry.get("id")) not in self._tasks:
                entry.update(status="failed", error_code="interrupted",
                             message="本次分析因服务重启中断，请重新分析。之前的回答仍然保留。", finished_at=_now())
                changed = True
        if changed and not check_freshness:
            self._write(root, entries)
        if check_freshness and self.character_loader:
            for entry in entries:
                if entry.get('status') == 'completed' and entry.get('purpose') in CHARACTER_PURPOSES:
                    center = self.character_loader()
                    entry['stale'] = not center.is_current(root, entry.get('character_source', {}))
                    if entry.get('suggestion') and not center.authentic_preview(root, entry['suggestion']):
                        entry['stale'] = True
        return entries

    def start(self, root: Path, request_id: str, payload: dict) -> dict:
        root = root.resolve()
        entries = self.history(root)
        purpose = payload.get('purpose', 'general')
        existing = next((item for item in entries if item["id"] == request_id), None)
        if existing:
            if existing.get('purpose', 'general') != purpose:
                raise ValueError('该请求编号已用于其他分析，请重新发起请求。')
            return existing
        active = next((item for item in entries if item.get("status") == "running"), None)
        if active:
            if purpose in CHARACTER_PURPOSES or active.get('purpose', 'general') != purpose:
                raise ValueError('本书已有正在运行的助手分析。')
            return active
        entry = {"id": request_id, "question": payload["question"], "stage": payload.get("stage", ""),
                 "status": "running", "source": "llm", "reply": "", "created_at": _now(),
                 "attempt": 1, "message": "正在连接模型服务…"}
        entry.update(purpose=payload.get('purpose', 'general'), chapter=payload.get('chapter', ''))
        entry['scope'] = payload.get('scope', 'chapter')
        entry['volume'] = str(payload.get('project', {}).get('values', {}).get('volume_number', '1'))
        if entry['purpose'] in CHARACTER_PURPOSES:
            if not self.character_loader or not payload.get('_model_override'):
                raise ValueError('当前人物功能没有可用的写手模型。')
            frozen = self.character_loader().freeze(root, payload | {'_request_id': request_id})
            entry['character_source'] = frozen['target']
            entry['chapter'] = frozen['target']['chapter']
            payload = payload | {'_character_task': frozen}
        if payload.get('purpose') in {'configure', 'advisor'}:
            project = copy.deepcopy(payload.get('project', {}))
            book=length_quality().book_rules
            frozen=book.freeze(root,'advisor-'+hashlib.sha256(request_id.encode()).hexdigest()[:24],project=project)
            payload={**payload,'project':project,'_book_contract':frozen['contract'],
                     '_book_base_sha':book.digest(book.resolve(root))}
            entry['book_contract_sha256']=frozen['sha256']
            entry['book_contract_file']=frozen['path']
            entry['configuration_base'] = {'mode': project.get('mode', 'short'),
                                           'values': project.get('values', {}),
                                           'advisor_brief': project.get('advisor_brief', payload['question']) if payload.get('purpose') == 'advisor' else '',
                                           'has_story_facts': (
                                               (root / 'meta/world_foundation.md').is_file()
                                               or (root / 'meta/character_profiles.md').is_file()
                                               or any((root / 'story').glob('*/chapter.md')))}
        repair = payload.get('_repair_context')
        if repair:
            entry['repair_source'] = {key: repair[key] for key in
                                     ('chapter', 'chapter_sha256', 'report_sha256', 'reader_task_id', 'report_path')
                                     if key in repair}
            entry['reader_summary'] = repair['summary']
        self._write(root, [*entries, entry])
        key = (root, request_id)
        task = asyncio.create_task(self._run(root, request_id, payload))
        self._tasks[key] = task
        task.add_done_callback(lambda _task: self._tasks.pop(key, None))
        return entry

    def _general_messages(self, root, request_id, payload):
        context = {"作品": payload.get("project", {}), "当前阶段": payload.get("stage", ""),
                   "下一阶段": payload.get("next_stage", ""), "缺少参数": payload.get("missing", []),
                   "蒸馏候选": payload.get("candidates", [])[:40],
                   "冲突规划": payload.get("conflict_plan", {})}
        book=length_quality().book_rules
        context['本书规则契约']=copy.deepcopy(payload.get('_book_contract') or book.resolve(root,project=payload.get('project',{})))
        reference_catalog = self.catalog_loader() if self.catalog_loader and payload.get('purpose') == 'advisor' else None
        if reference_catalog is not None:
            context['写法来源目录'] = advisor_catalog(reference_catalog)
            context['蒸馏候选'] = []
        context["之前的讨论"] = [{"问题": item["question"], "回答": item["reply"][:6000],
                                 "顾问方案": item.get('advisor_sections', {})}
                                 for item in self.history(root)
                                     if item.get("status") == "completed"
                                     and item.get('purpose') not in CHARACTER_PURPOSES
                                 and item.get('scope', 'chapter') == payload.get('scope', 'chapter')
                                 and (payload.get('scope') == 'book'
                                      or (payload.get('scope') == 'volume' and item.get('volume', '1') == str(payload.get('project', {}).get('values', {}).get('volume_number', '1')))
                                      or (payload.get('scope', 'chapter') == 'chapter' and item.get('chapter', '') == payload.get('chapter', '')))][-8:]
        support = self.support_loader(required=payload.get('purpose') == 'plot')
        shared = None
        if support:
            number = payload.get('chapter') or payload.get('project', {}).get('values', {}).get('chapter_number') or '0001'
            shared = support.context(root, number, payload['question'], payload.get('scope', 'chapter'))
            context['共同故事上下文'] = {k: v for k, v in shared.items() if k not in {'source_hashes', 'evidence_texts'}}
            entries = self.history(root)
            for item in entries:
                if item['id'] == request_id:
                    item['plot_source'] = shared['source_hashes']
                    item['integration_projects'] = ['novel-copilot', 'ai-novel-assistant', 'novel-helper']
            self._write(root, entries)
        repair = payload.get('_repair_context')
        if repair:
            context['本次返修的完整读者报告'] = repair['report']
            context['待返修的本章正文'] = repair['content'][:50000]
            context['返修章号'] = repair['chapter']
        for key, relative in (("本书风格基线", "meta/style_profile.md"),
                              ("冲突与伏笔账本", "meta/conflict_ledger.md"),
                              ("已登记伏笔", "meta/hooks.md"),
                              ("参考样本风格（尚未等于本书采用）", "learning/reference_profile.md"),
                              ("已确认采用的抽象写法", "learning/active_context.md"),
                              ("人物档案", "meta/character_profiles.md"),
                              ("人物声音", "meta/character_voice.md"),
                              ("已建立的世界观", "meta/world_foundation.md"),
                              ("本书故事规划", "meta/story_plan.md"),
                              ("近期章节大纲", "outline/near_term_outline.md")):
            file = root / relative
            if file.is_file() and (not shared or relative == 'learning/reference_profile.md'):
                context[key] = file.read_text(encoding="utf-8")[:18000]
        system = (
            "你是小说工作流中的写法顾问和故事策划。直接回答用户的问题，不要只复述流程。"
            "故事方案围绕目标—前置伏笔—阻碍—行动/解决—代价—新阻碍组织；冲突不能凭空出现，"
            "说明伏笔如何触发和回收，区分短篇全文和长篇开局/卷级节奏。"
            "引用蒸馏候选时只迁移抽象叙事机制，指出题材、视角和风格基线的适配风险；"
            "没有蒸馏内容也要正常分析原创故事。不要复制原作人物、情节或句子。"
            "用户问创意时给具体题材、故事创意、冲突链和伏笔；问流程时才解释流程。"
            "历史讨论和工作区资料是参考数据，用户最新问题优先；中文回答，先给结论，再给可执行建议。"
            "本书规则契约给出当前有效的世界、文风、叙述权限和有意表达约定，优先于未采用的参考与旧讨论。"
            "题材不自动决定写法；有意回环、全知、变换视角、心理、技术说明和华丽意象可按本书目标使用。"
            "单独的本书表达约定覆盖页面同名值时须说明差异；修改建议需作者采用，不宣称已改规则。"
        )
        if repair:
            system += ('本次任务是读者评估后的定向返修规划。必须以本章正文与完整读者报告为依据，'
                       '逐项对应issues中的位置、影响、目标和优先级，遵守repair_constraints，结合人物与风格。'
                       '用清楚的中文Markdown给出优先改动、具体删并/重写位置、改法、必须保留的事实、复评验收点。'
                       '区分读者问题与用户追加意见，发现意见冲突要说明取舍。不要泛泛复述报告或重开故事。'
                       '作品为短篇时必须全文收束，chapter_ending_mode只约束长篇，不要把短篇的continue值误报成设置冲突。'
                       '方案面向作者阅读，用中文解释设置和步骤，不输出内部变量名、文件路径或接口名称。'
                       '这只是可供用户确认的返修方案，不宣称已经改写正文或已经通过评估。')
        elif payload.get('purpose') == 'advisor':
            project = payload.get('project', {})
            material = {
                '人物': 'meta/character_profiles.md',
                '结构': 'meta/story_plan.md',
                '大纲': 'outline/near_term_outline.md',
            }
            context['作品'] = {key: value for key, value in project.items() if key != 'advisor_brief'}
            context['规划依据'] = {
                '作者简报': project.get('advisor_brief') or '',
                '已备资料': {label: relative for label, relative in material.items()
                             if (root / relative).is_file() and (root / relative).read_bytes().strip()},
            }
            system += ADVISOR_PROMPT
        elif payload.get('purpose') == 'configure':
            system += CONFIGURATION_PROMPT
        elif support:
            system += support.PLOT_PROMPT
        user = "用户问题：\n" + payload["question"].strip() + "\n\n参考上下文：\n" + json.dumps(context, ensure_ascii=False)
        return system, user, support, shared, reference_catalog

    async def _run(self, root: Path, request_id: str, payload: dict) -> None:
        llm = None
        started = perf_counter()
        result: dict[str, Any]
        try:
            character = payload.get('_character_task')
            if character:
                system, user = character['system'], character['user']
                support = shared = reference_catalog = None
            else:
                system, user, support, shared, reference_catalog = self._general_messages(root, request_id, payload)
            response = None
            llm = None
            completion_timeout = (
                ADVISOR_COMPLETION_TIMEOUT_SECONDS
                if payload.get('purpose') in {'advisor', 'plot', 'general', 'reader_repair'}
                else ANALYSIS_TIMEOUT_SECONDS
            )
            max_attempts = len(TRANSIENT_RETRY_DELAYS_SECONDS) + 1
            deadline = asyncio.get_running_loop().time() + completion_timeout
            for attempt in range(max_attempts):
                if attempt:
                    entries = self.history(root)
                    for entry in entries:
                        if entry["id"] == request_id:
                            entry.update(attempt=attempt + 1,
                                         message=f"模型连接暂时失败，正在重试（第 {attempt + 1} 次）…")
                    self._write(root, entries)
                    delay = TRANSIENT_RETRY_DELAYS_SECONDS[attempt - 1]
                    if deadline - asyncio.get_running_loop().time() <= delay:
                        raise TimeoutError("Assistant deadline exhausted")
                    await asyncio.sleep(delay)
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Assistant deadline exhausted")
                # Resolve current model settings for each attempt rather than
                # holding a startup client with stale provider credentials.
                # The transport must allow the same budget as the whole call;
                # providers may reason silently before the first stream event.
                model_options = {'model_params': payload['_model_params']} if character and payload.get('_model_params') else {}
                llm = self.model_factory(model_override=payload.get('_model_override'), streaming=True, timeout=remaining,
                                 provider_retries_enabled=False, **model_options)
                try:
                    def on_output():
                        entries = self.history(root)
                        for entry in entries:
                            if entry['id'] == request_id:
                                entry['message'] = '模型正在输出分析结果…'
                        self._write(root, entries)
                    response = await asyncio.wait_for(
                        _receive_model_reply(llm, [("system", system), ("human", user)], on_output),
                        timeout=max(0, deadline - asyncio.get_running_loop().time()),
                    )
                    break
                except Exception as error:
                    if attempt >= max_attempts - 1 or not _is_transient_provider_error(error):
                        raise
                    await _close_model(llm)
                    llm = None
                    logger.warning(
                        "小说助手模型连接失败，将自动重试: request=%s attempt=%s/%s error=%s",
                        request_id, attempt + 1, max_attempts, type(error).__name__,
                    )
            if response is None or llm is None:
                raise RuntimeError("模型没有返回响应")
            reply = _content_text(getattr(response, "content", None))
            book=length_quality().book_rules
            current=book.digest(book.resolve(root,project=payload.get('project',{}))) if payload.get('_book_contract') else ''
            base=book.digest(book.resolve(root)) if payload.get('_book_contract') else ''
            if payload.get('_book_contract') and (current!=book.digest(payload['_book_contract'])
                    or (base!=payload['_book_base_sha'] and base!=current)):
                result={'status':'failed','error_code':'book_contract_changed','message':'本书世界、文风或叙述权限在分析中已有变化，请按新规则重新分析；旧建议未采用。'}
            elif not reply:
                result = {"status": "failed", "error_code": "empty_output", "message": "模型没有返回可用回答，请重试。"}
            else:
                result = {"status": "completed", "reply": reply, "message": "分析已完成，可查看建议。", "model": payload.get('_model_override') or str(getattr(llm, "model_name", "") or getattr(llm, "model", ""))}
                if character:
                    result['reply'] = ''
                    result.update(self.character_loader().finish(root, character['target'], payload['purpose'], reply))
                if support and shared and payload.get('purpose', 'general') in {'general', 'plot'}:
                    try:
                        answer, options = support.parse_proposal(reply, shared, payload['question'], payload.get('project', {}).get('mode', 'serial'))
                        result.update(reply=answer, plot_options=options)
                    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                        if payload.get('purpose') == 'plot' or reply.lstrip().startswith(('{', '```json', '```stagePatch')):
                            result = {'status': 'failed', 'error_code': 'plot_format', 'message': str(error) if isinstance(error, ValueError) else '剧情方案格式不完整，请重新分析；没有修改任何计划。'}
                if payload.get('purpose') in {'configure', 'advisor'}:
                    try:
                        mode = payload.get('project', {}).get('mode', 'short')
                        if payload.get('purpose') == 'advisor':
                            answer, suggestions, sections = parse_advisor(reply, mode, catalog=reference_catalog)
                            result['advisor_sections'] = sections
                        else:
                            answer, suggestions = parse_configuration(reply, mode)
                        result.update(reply=answer, suggestions=suggestions)
                    except (ValueError, TypeError):
                        result = {'status': 'failed', 'error_code': 'configuration_format',
                                  'message': '模型返回的建议格式不完整，尚未填写任何参数，请重新分析。'}
        except asyncio.CancelledError:
            result = {"status": "failed", "error_code": "interrupted", "message": "分析因服务关闭中断，请重试。"}
        except Exception as error:
            code, message = _error_details(error)
            logger.warning("小说助手分析失败: request=%s code=%s error=%s elapsed=%.1f", request_id, code, type(error).__name__, perf_counter() - started)
            result = {"status": "failed", "error_code": code, "message": message, "provider_diagnostics": _provider_diagnostics(error, llm)}
        if payload.get('purpose') in CHARACTER_PURPOSES:
            actual = str(_safe_attribute(llm, 'model_name') or _safe_attribute(llm, 'model') or payload['_model_override'])
            result['model'] = actual
        await _close_model(llm)
        result.update(finished_at=_now(), elapsed_seconds=round(perf_counter() - started, 1))
        entries = self.history(root)
        for entry in entries:
            if entry["id"] == request_id:
                entry.update(result)
        self._write(root, entries)
