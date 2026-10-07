#!/usr/bin/env python3
"""
自动写作引擎 - 初始化/状态查询/节奏计算/方向评分
与 AI agent 配合使用：本脚本负责结构和数据，AI 负责创意和写作
"""

import sys
import os
import re
import yaml
import shutil
from pathlib import Path
from datetime import datetime

SKILL_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates"


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def count_chinese_chars(filepath):
    """Count actual Chinese characters + CJK punctuation in a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    return len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef]', text))


# ──────────────────── 初始化 ────────────────────

def cmd_init(args):
    """初始化自动写作项目"""
    name = args.get("name", "我的小说")
    base_dir = args.get("dir", os.path.join(os.getcwd(), name))
    mode = args.get("mode", "auto")
    project_dir = Path(base_dir)

    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"错误: 目录已存在且不为空: {project_dir}")
        sys.exit(1)

    # 创建目录结构
    (project_dir / "state").mkdir(parents=True)
    (project_dir / "chapters").mkdir(parents=True)
    (project_dir / "outlines").mkdir(parents=True)
    (project_dir / "state").mkdir(parents=True, exist_ok=True)

    # 复制模板
    templates = {
        "novel-project.yaml": project_dir / "novel-project.yaml",
        "characters.yaml": project_dir / "state" / "characters.yaml",
        "world.yaml": project_dir / "state" / "world.yaml",
        "threads.yaml": project_dir / "state" / "threads.yaml",
        "timeline.yaml": project_dir / "state" / "timeline.yaml",
        "automation-config.yaml": project_dir / "automation-config.yaml",
    }

    for tmpl_name, dest in templates.items():
        src = TEMPLATES_DIR / tmpl_name
        if src.exists():
            shutil.copy2(src, dest)
        else:
            save_yaml(str(dest), {})

    # 填入项目名
    project_data = load_yaml(str(project_dir / "novel-project.yaml"))
    project_data.setdefault("meta", {})["title"] = name
    project_data["meta"]["created_at"] = datetime.now().strftime("%Y-%m-%d")
    save_yaml(str(project_dir / "novel-project.yaml"), project_data)

    # 更新 automation-config 的 mode
    auto_config = load_yaml(str(project_dir / "automation-config.yaml"))
    auto_config["mode"] = mode
    save_yaml(str(project_dir / "automation-config.yaml"), auto_config)

    # 初始化 consistency-log
    save_yaml(str(project_dir / "state" / "consistency-log.yaml"), {
        "checks": [],
        "last_check_chapter": 0,
        "last_audit_chapter": 0,
    })

    # 初始化 arc-tracker
    save_yaml(str(project_dir / "state" / "arc-tracker.yaml"), {
        "current_arc": 1,
        "current_phase": "起势",
        "phase_start_chapter": 1,
        "phase_chapters_elapsed": 0,
        "recent_patterns": [],  # 近5章使用的发散模式
        "recent_hooks": [],     # 近5章的钩子类型
    })

    # 初始化 emotional-debts
    save_yaml(str(project_dir / "state" / "emotional-debts.yaml"), {
        "debts": [],
    })

    print(f"✅ 小说项目 '{name}' 初始化完成！（模式: {mode}）")
    print(f"   目录: {project_dir}")
    print(f"\n下一步:")
    if mode == "auto":
        print(f"  告诉 AI：'全自动写《{name}》，开头如下：[粘贴开头内容]'")
        print(f"  AI 将自动提取角色/世界观/线索并开始写作循环")
    else:
        print(f"  1. 编辑 state/characters.yaml 添加角色")
        print(f"  2. 编辑 state/world.yaml 设置世界观")
        print(f"  3. 编辑 state/threads.yaml 添加初始线索")
        print(f"  4. 开始写作！")


# ──────────────────── 状态查询 ────────────────────

def cmd_status(args):
    """查询自动写作项目的完整状态"""
    project_dir = Path(args.get("dir", "."))
    
    project = load_yaml(project_dir / "novel-project.yaml")
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    characters = load_yaml(project_dir / "state" / "characters.yaml").get("characters", [])
    threads = load_yaml(project_dir / "state" / "threads.yaml").get("threads", [])
    arc_tracker = load_yaml(project_dir / "state" / "arc-tracker.yaml")
    consistency_log = load_yaml(project_dir / "state" / "consistency-log.yaml")
    emotional_debts = load_yaml(project_dir / "state" / "emotional-debts.yaml")
    
    meta = project.get("meta", {})
    current_ch = int(meta.get("current_chapter", 0) or 0)
    current_words = int(meta.get("current_words", 0) or 0)
    target_words = int(meta.get("target_words", auto_config.get("target_words", 300000)))
    
    mode = auto_config.get("mode", "manual")
    mode_icon = "🤖" if mode == "auto" else "👤" if mode == "manual" else "⏸️"
    
    print(f"\n{'='*60}")
    print(f"📖 《{meta.get('title', '未命名')}》 — 自动写作状态")
    print(f"{'='*60}")
    print(f"\n{mode_icon} 模式: {mode}")
    sprint_config = auto_config.get("sprint", {})
    if sprint_config.get("enabled"):
        sprint_mode = sprint_config.get("mode", "organic")
        print(f"🏃 Sprint mode: ON ({sprint_mode})")
    print(f"📊 进度: 第{current_ch}章 | {current_words:,}字 / {target_words:,}字 ({current_words/max(target_words,1)*100:.1f}%)")
    
    # 弧线状态
    arc_phase = arc_tracker.get("current_phase", "起势")
    arc_num = arc_tracker.get("current_arc", 1)
    phase_start = arc_tracker.get("phase_start_chapter", 1)
    phase_elapsed = arc_tracker.get("phase_chapters_elapsed", 0)
    print(f"\n🎭 弧线: 第{arc_num}弧 | 阶段: {arc_phase} (第{phase_start}章起, 已{phase_elapsed}章)")
    
    # 近期模式
    recent = arc_tracker.get("recent_patterns", [])
    if recent:
        print(f"🔄 近{len(recent)}章模式: {' → '.join(recent[-5:])}")
    
    recent_hooks = arc_tracker.get("recent_hooks", [])
    if recent_hooks:
        print(f"🎣 近{len(recent_hooks)}章钩子: {' → '.join(recent_hooks[-5:])}")
    
    # 角色状态
    alive = sum(1 for c in characters if c.get("status") == "alive")
    dead = sum(1 for c in characters if c.get("status") == "dead")
    print(f"\n👤 角色: {len(characters)}人 (存活{alive} | 死亡{dead})")
    
    # 线索状态
    planted = [t for t in threads if t.get("resolved_chapter") is None]
    resolved = [t for t in threads if t.get("resolved_chapter") is not None]
    major_open = [t for t in planted if t.get("importance") == "major"]
    stale = [t for t in major_open if current_ch - int(t.get("planted_chapter", 0) or 0) > 15]
    
    print(f"\n🧵 线索: {len(threads)}条 (未收束{len(planted)} | 已收束{len(resolved)})")
    print(f"   ⚠️ 重要未收束: {len(major_open)}条")
    if stale:
        print(f"   🕰️ 停滞(>15章): {len(stale)}条")
        for t in stale[:3]:
            desc = t.get("description", "?")[:35]
            print(f"      - {desc}... (种下于第{t.get('planted_chapter', '?')}章)")
    
    # 情感债
    debts = emotional_debts.get("debts", [])
    outstanding = [d for d in debts if d.get("status") == "outstanding"]
    print(f"\n💔 情感债: {len(debts)}条 (未清偿{len(outstanding)})")
    
    # 一致性状态
    last_check = consistency_log.get("last_check_chapter", 0)
    last_audit = consistency_log.get("last_audit_chapter", 0)
    checks = consistency_log.get("checks", [])
    recent_errors = 0
    if checks:
        last = checks[-1]
        recent_errors = len(last.get("errors", []))
    
    check_interval = auto_config.get("consistency", {}).get("light_check_interval", 3)
    audit_interval = auto_config.get("consistency", {}).get("deep_audit_interval", 10)
    chapters_since_check = current_ch - last_check if last_check else current_ch
    chapters_since_audit = current_ch - last_audit if last_audit else current_ch
    
    print(f"\n🔍 一致性: 上次轻检第{last_check}章({chapters_since_check}章前)")
    print(f"          上次深审第{last_audit}章({chapters_since_audit}章前)")
    print(f"          轻检间隔{check_interval}章 | 深审间隔{audit_interval}章")
    if recent_errors:
        print(f"          ⚠️ 上次检查有{recent_errors}个错误")
    
    # 终局管理
    endgame_start = int(target_words * auto_config.get("endgame", {}).get("begin_at_percent", 80) / 100)
    if current_words >= endgame_start:
        print(f"\n🏁 终局管理已激活（目标{auto_config.get('endgame', {}).get('begin_at_percent', 80)}%时启动）")
        unres_major = len(major_open)
        if unres_major > 0:
            print(f"   ⚠️ 仍有{unres_major}条重要线索未收束")
    else:
        remaining = endgame_start - current_words
        print(f"\n📅 距终局管理: {remaining:,}字")
    
    print(f"\n{'='*60}")


# ──────────────────── 字数统计 ────────────────────

def cmd_wordcount(args):
    """扫描所有章节，统计中文字数并可更新 novel-project.yaml"""
    project_dir = Path(args.get("dir", "."))
    update = args.get("update", False)

    chapters_dir = project_dir / "chapters"
    if not chapters_dir.exists():
        print(f"❌ 章节目录不存在: {chapters_dir}")
        sys.exit(1)

    # 扫描所有章节文件（支持 .md 和 .txt）
    chapter_files = sorted(
        [f for f in chapters_dir.iterdir() if f.suffix in ('.md', '.txt')],
        key=lambda f: f.name
    )

    if not chapter_files:
        print(f"⚠️ 章节目录为空: {chapters_dir}")
        sys.exit(0)

    # 逐章统计
    total_chars = 0
    chapter_counts = []
    for f in chapter_files:
        count = count_chinese_chars(str(f))
        chapter_counts.append((f.name, count))
        total_chars += count

    chapter_count = len(chapter_files)
    avg_words = total_chars / chapter_count if chapter_count else 0

    # 读取目标字数
    project = load_yaml(project_dir / "novel-project.yaml")
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    meta = project.get("meta", {})
    target_words = int(meta.get("target_words", auto_config.get("target_words", 300000)))
    old_words = int(meta.get("current_words", 0) or 0)

    deviation = total_chars - target_words
    deviation_pct = (deviation / target_words * 100) if target_words else 0

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"📊 字数统计 — 《{meta.get('title', '未命名')}》")
    print(f"{'='*60}")
    print(f"\n  📄 章节数: {chapter_count}")
    print(f"  📝 总字数: {total_chars:,} 字")

    if old_words != total_chars:
        diff = total_chars - old_words
        sign = "+" if diff > 0 else ""
        print(f"  🔄 与记录差异: {sign}{diff:,} 字 (记录: {old_words:,})")
    else:
        print(f"  ✅ 与记录一致: {old_words:,} 字")

    print(f"  📏 篇均字数: {avg_words:,.0f} 字/章")
    print(f"  🎯 目标字数: {target_words:,} 字")

    if deviation >= 0:
        print(f"  📈 超出目标: +{deviation:,} 字 (+{deviation_pct:.1f}%)")
    else:
        print(f"  📉 距离目标: {deviation:,} 字 ({deviation_pct:.1f}%)")

    # 各章节明细
    print(f"\n{'─'*60}")
    print(f"  章节明细:")
    for name, count in chapter_counts:
        bar_len = min(30, max(1, count // (max(avg_words, 1) // 10 + 1)))
        bar = "█" * bar_len
        print(f"    {name:<30} {count:>6,} 字  {bar}")

    # 更新模式
    if update:
        project.setdefault("meta", {})["current_words"] = total_chars
        save_yaml(str(project_dir / "novel-project.yaml"), project)
        print(f"\n  ✅ 已更新 novel-project.yaml: current_words → {total_chars:,}")
    else:
        print(f"\n  🔍 DRY RUN — 使用 --update 参数写入 novel-project.yaml")

    print(f"\n{'='*60}")


# ──────────────────── 节奏计算 ────────────────────

def cmd_rhythm(args):
    """计算当前节奏状态和推荐下一章的发散模式"""
    project_dir = Path(args.get("dir", "."))
    
    project = load_yaml(project_dir / "novel-project.yaml")
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    
    # Sprint mode skip check
    if auto_config.get("sprint", {}).get("enabled") and auto_config.get("sprint", {}).get("skip_rhythm"):
        print("⏩ Sprint mode active — rhythm analysis skipped. Follow volume outline.")
        return
    
    threads = load_yaml(project_dir / "state" / "threads.yaml").get("threads", [])
    characters = load_yaml(project_dir / "state" / "characters.yaml").get("characters", [])
    arc_tracker = load_yaml(project_dir / "state" / "arc-tracker.yaml")
    
    meta = project.get("meta", {})
    current_ch = int(meta.get("current_chapter", 0) or 0)
    current_phase = arc_tracker.get("current_phase", "起势")
    recent_patterns = arc_tracker.get("recent_patterns", [])
    recent_hooks = arc_tracker.get("recent_hooks", [])
    
    rhythm_config = auto_config.get("rhythm", {})
    arc_phases = rhythm_config.get("arc_phases", {})
    
    print(f"\n{'='*60}")
    print(f"🎭 节奏分析 — 第{current_ch + 1}章规划")
    print(f"{'='*60}")
    
    # 当前阶段信息
    phase_cfg = arc_phases.get(current_phase, {})
    print(f"\n📍 当前阶段: {current_phase}")
    print(f"   预计章数: {phase_cfg.get('min', '?')}-{phase_cfg.get('max', '?')} (理想{phase_cfg.get('ideal', '?')})")
    
    # 张力检测
    print(f"\n📊 张力分析:")
    
    # 连续高张力检测
    if recent_patterns:
        consecutive_high = 0
        for p in reversed(recent_patterns):
            if p.get("tension", 0) >= 8:
                consecutive_high += 1
            else:
                break
        if consecutive_high >= rhythm_config.get("max_consecutive_high_tension", 2):
            print(f"   ⚠️ 连续{consecutive_high}章高张力，建议插入1章缓冲")
        
        consecutive_low = 0
        for p in reversed(recent_patterns):
            if p.get("tension", 0) < 4:
                consecutive_low += 1
            else:
                break
        if consecutive_low >= rhythm_config.get("max_consecutive_low_tension", 3):
            print(f"   ⚠️ 连续{consecutive_low}章低张力，下一章必须选高翻页驱动模式")
    
    # 钩子重复检测
    if len(recent_hooks) >= 2 and recent_hooks[-1] == recent_hooks[-2]:
        print(f"   ⚠️ 连续2章使用相同钩子类型({recent_hooks[-1]})，必须换类型")
    
    # 推荐模式
    phase_recommendations = {
        "起势": ["D3", "D6", "D12"],
        "升压": ["D1", "D2", "D7", "D10", "D12"],
        "假高潮": ["D8", "D4"],
        "二次爬升": ["D5", "D7", "D9", "D10", "D11"],
        "真高潮": ["D4", "D8", "D9", "D13", "D14"],
        "落幕": ["D6", "D13"],
    }
    
    # 处理过渡阶段名（如"起势→升压过渡"），提取基础阶段名
    base_phase = current_phase
    for known_phase in phase_recommendations:
        if known_phase in current_phase:
            base_phase = known_phase
            break
    
    recommended = phase_recommendations.get(base_phase, [])
    used_recent = [p.get("method", "") for p in recent_patterns[-3:]] if recent_patterns else []
    fresh_recommended = [r for r in recommended if r not in used_recent]
    
    if current_phase != base_phase:
        print(f"\n📍 注意: 阶段'{current_phase}'将按'{base_phase}'推荐模式")
    
    if fresh_recommended:
        print(f"\n💡 推荐发散模式（适合{base_phase}阶段 + 未近期使用）:")
        for m in fresh_recommended:
            print(f"   ✅ {m}")
    
    if recommended:
        print(f"\n📋 {base_phase}阶段全部适用模式: {', '.join(recommended)}")
    
    if not recommended:
        print(f"\n⚠️ 未找到'{current_phase}'的推荐模式。已知阶段: {', '.join(phase_recommendations.keys())}")
        print(f"   建议: 将 arc-tracker.yaml 的 current_phase 改为上述已知阶段之一")
    
    # 线索推进建议
    current_ch_for_threads = current_ch if current_ch else 0
    stale_threads = [t for t in threads 
                     if t.get("resolved_chapter") is None 
                     and t.get("importance") == "major"
                     and current_ch_for_threads - int(t.get("planted_chapter", 0) or 0) > rhythm_config.get("stale_thread_threshold", 15)]
    
    if stale_threads:
        print(f"\n🧵 需要推进的停滞线索（>{rhythm_config.get('stale_thread_threshold', 15)}章未推进）:")
        for t in stale_threads[:5]:
            desc = t.get("description", "?")[:40]
            print(f"   ⚡ {t.get('id', '?')}: {desc}...")
    
    # 缺席角色
    absent_chars = [c for c in characters 
                    if c.get("status") == "alive" 
                    and c.get("last_appeared") 
                    and current_ch_for_threads - int(c.get("last_appeared", 0) or 0) > rhythm_config.get("absent_char_threshold", 20)]
    
    if absent_chars:
        print(f"\n👤 长期缺席角色（>{rhythm_config.get('absent_char_threshold', 20)}章未出场）:")
        for c in absent_chars[:5]:
            last = c.get("last_appeared", "?")
            print(f"   👋 {c.get('name', '?')} (最后第{last}章)")
    
    print(f"\n{'='*60}")


# ──────────────────── 方向评分 ────────────────────

def cmd_score(args):
    """对候选方向进行评分（输入来自 AI 的发散输出）

    支持评分模式:
      --mode 8dim  (默认): 8维度评分，格式 method,8维度分数（9字段）
      --mode 7dim:         8dim 兼容别名
      --mode 3dim:         3维度简化评分，格式 method,3维度分数（4字段）
    """
    project_dir = Path(args.get("dir", "."))
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    
    # Sprint mode skip check
    if auto_config.get("sprint", {}).get("enabled") and auto_config.get("sprint", {}).get("skip_score"):
        print("⏩ Sprint mode active — score calculation skipped. Use narrative judgment.")
        return
    
    arc_tracker = load_yaml(project_dir / "state" / "arc-tracker.yaml")
    
    # 确定评分模式: --mode 参数优先, 否则读配置, 默认8dim
    mode = args.get("mode", "") or auto_config.get("selection", {}).get("scoring_mode", "8dim")
    if mode == "7dim":
        mode = "8dim"  # 兼容旧别名
    if mode not in ("8dim", "3dim"):
        print(f"⚠️ 未知评分模式 '{mode}'，使用默认 8dim")
        mode = "8dim"
    
    # ── 8dim 模式 ──
    if mode == "8dim":
        weights = auto_config.get("selection", {}).get("weights", {
            "rhythm_fit": 0.20,
            "drive_intensity": 0.15,
            "thread_advancement": 0.15,
            "emotional_utilization": 0.10,
            "consistency_score": 0.05,
            "novelty": 0.20,
            "hook_strength": 0.05,
            "surprise": 0.10,
        })
        
        # 用法: auto_write.py score --dir . --d1 "D7,5,4,3,3,5,4,4,5" ...
        # 格式: method,rhythm_fit,drive_intensity,thread_advancement,emotional_utilization,consistency_score,novelty,hook_strength,surprise
        # 兼容旧8字段（无 surprise）时，surprise 默认取 hook_strength
        
        directions = []
        i = 0
        while True:
            key = f"d{i+1}"
            if key not in args:
                break
            parts = args[key].split(",")
            if len(parts) < 8:
                print(f"⚠️ 方向{i+1}数据不足，跳过（需要至少8个值：method,7-8维度分数）")
                i += 1
                continue
            hook = float(parts[7])
            surprise = float(parts[8]) if len(parts) >= 9 else hook
            directions.append({
                "method": parts[0].strip(),
                "rhythm_fit": float(parts[1]),
                "drive_intensity": float(parts[2]),
                "thread_advancement": float(parts[3]),
                "emotional_utilization": float(parts[4]),
                "consistency_score": float(parts[5]),
                "novelty": float(parts[6]),
                "hook_strength": hook,
                "surprise": surprise,
            })
            i += 1
        
        if not directions:
            print("用法: auto_write.py score --dir . --mode 8dim --d1 'D7,5,4,3,3,5,4,4,5' --d2 'D1,3,4,5,3,4,3,3,4'")
            print("每个方向格式: method,rhythm_fit,drive_intensity,thread_advancement,emotional_utilization,consistency_score,novelty,hook_strength[,surprise]")
            return
        
        # 评分
        selection_config = auto_config.get("selection", {})
        merge_threshold = float(selection_config.get("merge_threshold", 0.5))
        min_score = float(selection_config.get("min_score", 2.5))
        
        print(f"\n{'='*60}")
        print(f"📊 方向评分结果 (8dim)")
        print(f"{'='*60}")
        
        scored = []
        for i, d in enumerate(directions):
            score = (
                weights.get("rhythm_fit", 0.20) * d["rhythm_fit"] +
                weights.get("drive_intensity", 0.15) * d["drive_intensity"] +
                weights.get("thread_advancement", 0.15) * d["thread_advancement"] +
                weights.get("emotional_utilization", 0.10) * d["emotional_utilization"] +
                weights.get("consistency_score", 0.05) * d["consistency_score"] +
                weights.get("novelty", 0.20) * d["novelty"] +
                weights.get("hook_strength", 0.05) * d["hook_strength"] +
                weights.get("surprise", 0.10) * d["surprise"]
            )
            
            # 排雷检查
            vetoed = False
            veto_reason = ""
            
            # 红灯一致性风险
            if d["consistency_score"] <= 1:
                vetoed = True
                veto_reason = "一致性风险过高"
            
            # 连续同模式
            recent_patterns = arc_tracker.get("recent_patterns", [])
            recent_methods = [p.get("method", "") for p in recent_patterns[-3:]]
            if recent_methods.count(d["method"]) >= selection_config.get("veto", {}).get("repeat_pattern_limit", 3):
                vetoed = True
                veto_reason = f"连续{selection_config.get('veto', {}).get('repeat_pattern_limit', 3)}章使用{d['method']}"
            
            scored.append({
                "index": i + 1,
                "method": d["method"],
                "score": round(score, 2),
                "vetoed": vetoed,
                "veto_reason": veto_reason,
                "details": d,
            })
        
        # 排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        
        for rank, s in enumerate(scored, 1):
            veto_mark = " ❌ VETO" if s["vetoed"] else ""
            star_count = min(5, max(1, int(s["score"])))
            stars = "★" * star_count + "☆" * (5 - star_count)
            print(f"\n  #{rank} {s['method']} — {stars} [{s['score']}分]{veto_mark}")
            d = s["details"]
            print(f"     节奏{d['rhythm_fit']} | 驱动{d['drive_intensity']} | 线索{d['thread_advancement']} | 情感{d['emotional_utilization']}")
            print(f"     安全{d['consistency_score']} | 新颖{d['novelty']} | 钩子{d['hook_strength']} | 惊讶{d.get('surprise', '-')}")
            if s["vetoed"]:
                print(f"     排雷原因: {s['veto_reason']}")
        
        # 选择建议
        viable = [s for s in scored if not s["vetoed"]]
        if not viable:
            print(f"\n⚠️ 所有方向均被排雷，请重新发散或调整参数")
        elif viable[0]["score"] < min_score:
            print(f"\n⚠️ 最高分{viable[0]['score']}低于质量线{min_score}，方向质量不足")
            print(f"   建议: 调整节奏阶段 / 重新发散 / 考虑合并方向")
        else:
            best = viable[0]
            if len(viable) >= 2 and best["score"] - viable[1]["score"] < merge_threshold:
                print(f"\n🔀 建议: 合并 TOP2 方向 ({best['method']} + {viable[1]['method']})，差距仅{best['score'] - viable[1]['score']:.2f}")
            else:
                print(f"\n✅ 选择: {best['method']} [{best['score']}分]")
        
        print(f"\n{'='*60}")
    
    # ── 3dim 模式: 简化3维度评分 ──
    elif mode == "3dim":
        weights_3dim = {
            "rhythm_fit": 0.40,      # 弧线阶段适配 + 张力平衡 (替换 rhythm_fit + drive_intensity + hook_strength)
            "thread_drive": 0.35,    # 线索推进 + 情感利用 (替换 thread_advancement + emotional_utilization)
            "safety_novelty": 0.25,  # 一致性安全 + 新颖度 (替换 consistency_score + novelty)
        }
        
        # 从参数中读取方向评分数据
        # 用法: auto_write.py score --dir . --mode 3dim --d1 "D7,4,5,4" --d2 "D10,5,3,4" ...
        # 每个方向的格式: method,rhythm_fit,thread_drive,safety_novelty
        
        directions = []
        i = 0
        while True:
            key = f"d{i+1}"
            if key not in args:
                break
            parts = args[key].split(",")
            if len(parts) < 4:
                print(f"⚠️ 方向{i+1}数据不足，跳过（需要4个值：method,3维度分数）")
                i += 1
                continue
            directions.append({
                "method": parts[0].strip(),
                "rhythm_fit": float(parts[1]),
                "thread_drive": float(parts[2]),
                "safety_novelty": float(parts[3]),
            })
            i += 1
        
        if not directions:
            print("用法: auto_write.py score --dir . --mode 3dim --d1 'D7,4,5,4' --d2 'D10,5,3,4'")
            print("每个方向格式: method,rhythm_fit,thread_drive,safety_novelty")
            return
        
        # 评分
        selection_config = auto_config.get("selection", {})
        merge_threshold = float(selection_config.get("merge_threshold", 0.5))
        min_score = float(selection_config.get("min_score", 2.5))
        
        print(f"\n{'='*60}")
        print(f"📊 方向评分结果 (3dim)")
        print(f"{'='*60}")
        
        scored = []
        for i, d in enumerate(directions):
            score = (
                weights_3dim["rhythm_fit"] * d["rhythm_fit"] +
                weights_3dim["thread_drive"] * d["thread_drive"] +
                weights_3dim["safety_novelty"] * d["safety_novelty"]
            )
            
            # 排雷检查
            vetoed = False
            veto_reason = ""
            
            # 一致性安全风险 (safety_novelty ≤ 1 表示一致性风险过高)
            if d["safety_novelty"] <= 1:
                vetoed = True
                veto_reason = "一致性风险过高"
            
            # 连续同模式
            recent_patterns = arc_tracker.get("recent_patterns", [])
            recent_methods = [p.get("method", "") for p in recent_patterns[-3:]]
            if recent_methods.count(d["method"]) >= selection_config.get("veto", {}).get("repeat_pattern_limit", 3):
                vetoed = True
                veto_reason = f"连续{selection_config.get('veto', {}).get('repeat_pattern_limit', 3)}章使用{d['method']}"
            
            scored.append({
                "index": i + 1,
                "method": d["method"],
                "score": round(score, 2),
                "vetoed": vetoed,
                "veto_reason": veto_reason,
                "details": d,
            })
        
        # 排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        
        for rank, s in enumerate(scored, 1):
            veto_mark = " ❌ VETO" if s["vetoed"] else ""
            star_count = min(5, max(1, int(s["score"])))
            stars = "★" * star_count + "☆" * (5 - star_count)
            print(f"\n  #{rank} {s['method']} — {stars} [{s['score']}分]{veto_mark}")
            d = s["details"]
            print(f"     节奏适配{d['rhythm_fit']} | 线索驱动{d['thread_drive']} | 安全新颖{d['safety_novelty']}")
            if s["vetoed"]:
                print(f"     排雷原因: {s['veto_reason']}")
        
        # 选择建议
        viable = [s for s in scored if not s["vetoed"]]
        if not viable:
            print(f"\n⚠️ 所有方向均被排雷，请重新发散或调整参数")
        elif viable[0]["score"] < min_score:
            print(f"\n⚠️ 最高分{viable[0]['score']}低于质量线{min_score}，方向质量不足")
            print(f"   建议: 调整节奏阶段 / 重新发散 / 考虑合并方向")
        else:
            best = viable[0]
            if len(viable) >= 2 and best["score"] - viable[1]["score"] < merge_threshold:
                print(f"\n🔀 建议: 合并 TOP2 方向 ({best['method']} + {viable[1]['method']})，差距仅{best['score'] - viable[1]['score']:.2f}")
            else:
                print(f"\n✅ 选择: {best['method']} [{best['score']}分]")
        
        print(f"\n{'='*60}")


# ──────────────────── 一致性门控判断 ────────────────────

def cmd_gate(args):
    """判断当前是否应触发一致性校验"""
    project_dir = Path(args.get("dir", "."))
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    project = load_yaml(project_dir / "novel-project.yaml")
    consistency_log = load_yaml(project_dir / "state" / "consistency-log.yaml")
    arc_tracker = load_yaml(project_dir / "state" / "arc-tracker.yaml")
    
    meta = project.get("meta", {})
    current_ch = int(meta.get("current_chapter", 0) or 0)
    
    consistency_config = auto_config.get("consistency", {})
    light_interval = int(consistency_config.get("light_check_interval", 3))
    deep_interval = int(consistency_config.get("deep_audit_interval", 10))
    
    last_check = int(consistency_log.get("last_check_chapter", 0) or 0)
    last_audit = int(consistency_log.get("last_audit_chapter", 0) or 0)
    
    checks = consistency_log.get("checks", [])
    last_had_errors = False
    if checks and checks[-1].get("errors"):
        last_had_errors = len(checks[-1]["errors"]) > 0
    
    # 判断触发条件
    should_check = False
    check_type = "none"
    reasons = []
    
    # 周期轻检
    if current_ch - last_check >= light_interval:
        should_check = True
        check_type = "check"
        reasons.append(f"距上次轻检已{current_ch - last_check}章（间隔{light_interval}）")
    
    # 周期深审
    if current_ch - last_audit >= deep_interval:
        should_check = True
        check_type = "audit"
        reasons.append(f"距上次深审已{current_ch - last_audit}章（间隔{deep_interval}）")
    
    # 上次有错误
    if last_had_errors:
        should_check = True
        if check_type != "audit":
            check_type = "check"
        reasons.append("上次检查有未确认的错误")
    
    # 弧线切换
    current_phase = arc_tracker.get("current_phase", "起势")
    phase_start_ch = int(arc_tracker.get("phase_start_chapter", 1) or 1)
    if current_ch > phase_start_ch:
        # 检查是否刚进入新阶段（前1-2章内）
        if current_ch - phase_start_ch <= 1:
            should_check = True
            check_type = "audit"
            reasons.append(f"刚进入{current_phase}阶段")
    
    print(f"\n{'='*60}")
    print(f"🚦 一致性门控 — 第{current_ch}章")
    print(f"{'='*60}")
    
    if should_check:
        print(f"\n✅ 触发校验！类型: {check_type}")
        print(f"   触发原因:")
        for r in reasons:
            print(f"   - {r}")
        print(f"\n   执行命令:")
        if check_type == "audit":
            print(f"   python3 scripts/consistency_checker.py audit {project_dir}")
        else:
            print(f"   python3 scripts/consistency_checker.py check {project_dir}")
    else:
        print(f"\n⏭️ 跳过校验，继续写作")
        print(f"   下次轻检: 第{last_check + light_interval}章（还有{last_check + light_interval - current_ch}章）")
        print(f"   下次深审: 第{last_audit + deep_interval}章（还有{last_audit + deep_interval - current_ch}章）")
    
    print(f"\n{'='*60}")


# ──────────────────── 终止检查 ────────────────────

def cmd_terminate(args):
    """检查是否应终止自动写作循环"""
    project_dir = Path(args.get("dir", "."))
    auto_config = load_yaml(project_dir / "automation-config.yaml")
    project = load_yaml(project_dir / "novel-project.yaml")
    threads = load_yaml(project_dir / "state" / "threads.yaml").get("threads", [])
    arc_tracker = load_yaml(project_dir / "state" / "arc-tracker.yaml")
    
    meta = project.get("meta", {})
    current_ch = int(meta.get("current_chapter", 0) or 0)
    current_words = int(meta.get("current_words", 0) or 0)
    target_words = int(meta.get("target_words", auto_config.get("target_words", 300000)))
    target_chapters = auto_config.get("target_chapters")
    
    endgame_config = auto_config.get("endgame", {})
    selection_config = auto_config.get("selection", {})
    
    should_terminate = False
    reasons = []
    
    # 字数达标
    if current_words >= target_words:
        should_terminate = True
        reasons.append(f"字数达标: {current_words:,} / {target_words:,}")
    
    # 章数达标
    if target_chapters and current_ch >= int(target_chapters):
        should_terminate = True
        reasons.append(f"章数达标: {current_ch} / {target_chapters}")
    
    # 所有major线索已收束 + 在落幕阶段
    major_open = [t for t in threads if t.get("importance") == "major" and t.get("resolved_chapter") is None]
    current_phase = arc_tracker.get("current_phase", "起势")
    if not major_open and current_phase == "落幕":
        should_terminate = True
        reasons.append("所有重要线索已收束 + 当前处于落幕阶段")
    
    # 创意枯竭
    min_score = float(selection_config.get("min_score", 2.5))
    # 这个需要外部传入最近评分，这里只能标记
    
    print(f"\n{'='*60}")
    print(f"🏁 终止检查 — 第{current_ch}章")
    print(f"{'='*60}")
    
    if should_terminate:
        print(f"\n✅ 满足终止条件！")
        for r in reasons:
            print(f"   ✓ {r}")
        print(f"\n📖 写作完成！")
        print(f"   总章数: {current_ch}")
        print(f"   总字数: {current_words:,}")
        print(f"   未收束重要线索: {len(major_open)}")
        if major_open:
            print(f"   ⚠️ 仍有未收束线索:")
            for t in major_open:
                print(f"      - {t.get('description', '?')[:40]}...")
    else:
        progress = current_words / max(target_words, 1) * 100
        print(f"\n⏩ 继续写作")
        print(f"   进度: {progress:.1f}% ({current_words:,}/{target_words:,}字)")
        print(f"   当前阶段: {current_phase}")
        print(f"   未收束重要线索: {len(major_open)}")
    
    print(f"\n{'='*60}")


# ──────────────────── CLI ────────────────────

def main():
    if len(sys.argv) < 2:
        print("自动写作引擎 - 用法:")
        print("  init   --name 名字 --dir 目录 [--mode auto|manual]  初始化项目")
        print("  status --dir 目录                                   查询完整状态")
        print("  wordcount --dir 目录 [--update]                    统计实际字数(干跑/更新)")
        print("  rhythm --dir 目录                                   节奏分析+推荐模式")
        print("  score  --dir 目录 [--mode 7dim|3dim] --d1 '...'      方向评分")
        print("  gate   --dir 目录                                   一致性门控判断")
        print("  terminate --dir 目录                                终止条件检查")
        sys.exit(0)
    
    command = sys.argv[1]
    
    # 解析参数
    args = {}
    i = 2
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                args[key] = sys.argv[i + 1]
                i += 2
            else:
                args[key] = True
                i += 1
        else:
            i += 1
    
    if command == "init":
        cmd_init(args)
    elif command == "status":
        cmd_status(args)
    elif command == "wordcount":
        cmd_wordcount(args)
    elif command == "rhythm":
        cmd_rhythm(args)
    elif command == "score":
        cmd_score(args)
    elif command == "gate":
        cmd_gate(args)
    elif command == "terminate":
        cmd_terminate(args)
    else:
        print(f"未知命令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
