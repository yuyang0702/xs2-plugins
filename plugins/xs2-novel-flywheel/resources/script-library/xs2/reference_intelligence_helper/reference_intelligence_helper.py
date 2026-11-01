#!/usr/bin/env python3
"""
Reference Intelligence Script Wrapper
工作流脚本入口，封装intelligence_api的所有功能
"""
import argparse
import json
import sys
import re
from pathlib import Path

# Import the intelligence API
sys.path.insert(0, str(Path(__file__).parent))
from reference_intelligence.intelligence_api import (
    recommend_for_chapter,
    adapt_to_genre,
    plan_structure,
    monitor_originality,
    load_json,
    save_json,
)


def init_intelligence(workspace: Path) -> dict:
    """Distillation is a proposal, never authorization to adopt candidates."""
    return {"success": True, "status": "ready" if (workspace / "learning/candidates.json").exists() else "skipped",
            "message": "Reference candidates require explicit adoption before use."}


def check_originality(workspace: Path, chapter: str, threshold: float) -> dict:
    """Run the existing lexical monitor only when source snapshots are available."""
    if not re.fullmatch(r'[0-9]{4}', chapter) or chapter == '0000':
        raise ValueError('chapter must be a four-digit positive chapter number')
    draft = workspace / f'story/{chapter}/chapter.md'
    if not draft.is_file():
        raise ValueError('Chapter file does not exist')
    if not 0 < threshold <= 1:
        raise ValueError('threshold must be within (0, 1]')
    sources = []
    for source in sorted((workspace / 'learning/sources').glob('*.txt')):
        if not source.resolve().is_relative_to(workspace.resolve()):
            raise ValueError('Reference source must stay inside workspace')
        text = source.read_text(encoding='utf-8-sig')
        if text.strip():
            sources.append({'candidate_id': source.stem, 'evidence': {'raw_text': text}})
    if not sources:
        return {"success": True, "status": "skipped", "reason": "No reference text snapshots available; no similarity assessment performed."}
    from reference_intelligence.originality_monitor import OriginalityMonitor
    monitor = OriginalityMonitor(load_fn=lambda _: {'candidates': sources})
    report = monitor.check_full_chapter(draft.read_text(encoding='utf-8-sig'), threshold)
    return {"success": True, "status": "checked", "method": "lexical_overlap", "originality_report": report}


def update_novel_state(workspace: Path, chapter_num: int) -> dict:
    """
    更新小说状态（根据章节号自动推断阶段）
    """
    learning_dir = workspace / "learning"
    novel_info_file = learning_dir / "novel_info.json"
    
    if not novel_info_file.exists():
        return {"error": "novel_info.json not found"}
    
    novel_info = load_json(novel_info_file)
    total_chapters = novel_info.get("total_chapters", 100)
    
    # Auto-detect plot stage based on chapter position
    progress = chapter_num / total_chapters
    
    if progress < 0.15:
        plot_stage = "setup"
        conflict_phase = "introduction"
    elif progress < 0.4:
        plot_stage = "rising"
        conflict_phase = "escalation"
    elif progress < 0.6:
        plot_stage = "climax"
        conflict_phase = "peak"
    elif progress < 0.85:
        plot_stage = "falling"
        conflict_phase = "resolution"
    else:
        plot_stage = "resolution"
        conflict_phase = "resolution"
    
    # Update state
    novel_info["current_chapter"] = chapter_num
    novel_info["plot_stage"] = plot_stage
    novel_info["conflict_phase"] = conflict_phase
    
    save_json(novel_info_file, novel_info)
    
    return {
        "status": "updated",
        "chapter": chapter_num,
        "plot_stage": plot_stage,
        "conflict_phase": conflict_phase,
    }


def main():
    parser = argparse.ArgumentParser(description="Reference Intelligence Workflow Script")
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # init command
    init_parser = subparsers.add_parser('init', help='Initialize intelligence system after distillation')
    init_parser.add_argument('--workspace', default='.')
    
    # update-state command
    update_parser = subparsers.add_parser('update-state', help='Update novel state for current chapter')
    update_parser.add_argument('--chapter', type=int, required=True)
    update_parser.add_argument('--workspace', default='.')
    
    # recommend command
    rec_parser = subparsers.add_parser('recommend', help='Recommend techniques for chapter')
    rec_parser.add_argument('--chapter', type=int, required=True)
    rec_parser.add_argument('--workspace', default='.')
    
    # check-similarity command
    check_parser = subparsers.add_parser('check-similarity', help='Check originality')
    check_parser.add_argument('--chapter', required=True)
    check_parser.add_argument('--workspace', default='.')
    check_parser.add_argument('--threshold', type=float, default=0.75)
    
    # adapt-genre command
    adapt_parser = subparsers.add_parser('adapt-genre', help='Adapt techniques to target genre')
    adapt_parser.add_argument('--genre', required=True)
    adapt_parser.add_argument('--workspace', default='.')
    
    # plan-plot command
    plan_parser = subparsers.add_parser('plan-plot', help='Plan plot structure')
    plan_parser.add_argument('--workspace', default='.')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    workspace = Path(args.workspace).resolve()
    learning_dir = workspace / "learning"
    
    try:
        if args.command == 'init':
            result = init_intelligence(workspace)
            
        elif args.command == 'update-state':
            result = update_novel_state(workspace, args.chapter)
            
        elif args.command == 'recommend':
            # First update state
            update_novel_state(workspace, args.chapter)
            # Then recommend
            result = recommend_for_chapter(
                chapter_num=args.chapter,
                novel_info_path=str(learning_dir / "novel_info.json"),
                workspace_root=str(workspace)
            )
            
        elif args.command == 'check-similarity':
            result = check_originality(workspace, args.chapter, args.threshold)

        elif args.command == 'adapt-genre':
            result = adapt_to_genre(
                my_genre=args.genre,
                reference_path=str(learning_dir / "reference_analysis.json"),
                workspace_root=str(workspace)
            )
            
        elif args.command == 'plan-plot':
            outline_path = workspace / "meta" / "story_plan.md"
            manifest = load_json(workspace / ".novel-project.json")
            total_chapters = manifest.get("target_chapters", 100)
            
            result = plan_structure(
                outline_path=str(outline_path),
                target_chapters=total_chapters,
                workspace_root=str(workspace)
            )
        
        # Output result
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("success") or result.get("status") == "initialized" else 1)
        
    except Exception as e:
        error_result = {
            "error": str(e),
            "type": type(e).__name__,
            "command": args.command
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
