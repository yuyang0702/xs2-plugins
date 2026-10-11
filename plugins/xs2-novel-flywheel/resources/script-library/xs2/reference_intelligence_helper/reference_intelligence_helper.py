#!/usr/bin/env python3
"""
Reference Intelligence Script Wrapper
工作流脚本入口，封装intelligence_api的所有功能
"""
import argparse
import json
import sys
from pathlib import Path

# Import the intelligence API
sys.path.insert(0, str(Path(__file__).parent))
from reference_intelligence.intelligence_api import (
    recommend_for_chapter,
    adapt_to_genre,
    plan_structure,
    build_context,
    monitor_originality,
    load_json,
    save_json,
)


def init_intelligence(workspace: Path) -> dict:
    """
    初始化智能推荐系统
    在reference-distillation完成后调用
    """
    learning_dir = workspace / "learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if we have candidates
    candidates_file = learning_dir / "candidates.json"
    if not candidates_file.exists():
        return {
            "status": "skipped",
            "reason": "No candidates.json found, intelligence system not initialized"
        }
    
    candidates = load_json(candidates_file)
    
    # Create reference_analysis.json from candidates
    # This transforms candidates into the format expected by intelligence system
    analysis = {
        "source_title": candidates.get("reference_title", "Unknown"),
        "source_genre": candidates.get("source_genre", "未知"),
        "techniques": [],
        "plot_patterns": candidates.get("plot_patterns", []),
        "style_features": candidates.get("style_features", {}),
    }
    
    # Transform candidates to techniques
    for candidate in candidates.get("candidates", []):
        technique = {
            "id": candidate.get("id", ""),
            "name": candidate.get("name", ""),
            "category": candidate.get("category", "general"),
            "description": candidate.get("why_effective", ""),
            "examples": candidate.get("examples", []),
            "applicable_stages": ["rising", "climax"],  # Default, can be refined
            "effectiveness": candidate.get("confidence", 0.7),
        }
        analysis["techniques"].append(technique)
    
    # Save reference_analysis.json
    analysis_file = learning_dir / "reference_analysis.json"
    save_json(analysis_file, analysis)
    
    # Initialize novel_info.json if it doesn't exist
    novel_info_file = learning_dir / "novel_info.json"
    if not novel_info_file.exists():
        # Read from workspace manifest if available
        manifest_file = workspace / ".novel-project.json"
        manifest = load_json(manifest_file) if manifest_file.exists() else {}
        
        novel_info = {
            "genre": manifest.get("genre", "都市"),
            "total_chapters": manifest.get("target_chapters", 100),
            "current_chapter": 1,
            "pov": "third_person",
            "plot_stage": "setup",
            "conflict_phase": "introduction",
            "active_conflicts": [],
            "main_characters": [],
        }
        save_json(novel_info_file, novel_info)
    
    return {
        "status": "initialized",
        "analysis_file": str(analysis_file),
        "techniques_count": len(analysis["techniques"]),
    }


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
    
    # build-context command
    ctx_parser = subparsers.add_parser('build-context', help='Build smart context for workflow')
    ctx_parser.add_argument('--workflow', required=True, choices=['mvp', 'outline', 'polish'])
    ctx_parser.add_argument('--chapter', type=int, required=True)
    ctx_parser.add_argument('--workspace', default='.')
    ctx_parser.add_argument('--max-techniques', type=int, default=8)
    
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
            
        elif args.command == 'build-context':
            # Update state first
            update_novel_state(workspace, args.chapter)
            # Build context
            result = build_context(
                workflow=args.workflow,
                chapter_num=args.chapter,
                novel_state_path=str(learning_dir / "novel_info.json"),
                workspace_root=str(workspace),
                max_techniques=args.max_techniques
            )
            
        elif args.command == 'check-similarity':
            draft_path = f"story/{args.chapter}/chapter.md"
            result = monitor_originality(
                draft_path=draft_path,
                workspace_root=str(workspace),
                threshold=args.threshold
            )
            
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
