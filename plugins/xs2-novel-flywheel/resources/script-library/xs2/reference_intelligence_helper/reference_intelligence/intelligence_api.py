#!/usr/bin/env python3
"""
Reference Intelligence System - Unified API
统一入口：CLI + 函数调用接口
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Import all modules - supporting both package and CLI modes
try:
    from .recommender import TechniqueRecommender, NovelContext, PlotStage, ConflictPhase
    from .genre_adapter import GenreAdapter
    from .plot_planner import PlotPlanner
    from .context_builder import ContextBuilder
    from .originality_monitor import OriginalityMonitor
except ImportError:
    # CLI mode
    from recommender import TechniqueRecommender, NovelContext, PlotStage, ConflictPhase
    from genre_adapter import GenreAdapter
    from plot_planner import PlotPlanner
    from context_builder import ContextBuilder
    from originality_monitor import OriginalityMonitor


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON with error handling"""
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def save_json(path: Path, data: Dict[str, Any]) -> None:
    """Save JSON with pretty formatting"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def recommend_for_chapter(
    chapter_num: int,
    novel_info_path: str,
    workspace_root: Optional[str] = None
) -> Dict[str, Any]:
    """为指定章节推荐技巧"""
    novel_info_file = Path(novel_info_path)
    workspace = Path(workspace_root) if workspace_root else novel_info_file.parent.parent
    learning_dir = workspace / "learning"
    
    novel_info = load_json(novel_info_file)
    if not novel_info:
        return {"error": "Failed to load novel_info.json"}
    
    analysis_data = load_json(learning_dir / "reference_analysis.json")
    if not analysis_data:
        return {"error": "No reference analysis found"}
    
    context = NovelContext(
        genre=novel_info.get("genre", "都市"),
        total_chapters=novel_info.get("total_chapters", 100),
        current_chapter=chapter_num,
        pov=novel_info.get("pov", "third_person"),
        plot_stage=PlotStage(novel_info.get("plot_stage", "rising")),
        conflict_phase=ConflictPhase(novel_info.get("conflict_phase", "escalation")),
        active_conflicts=novel_info.get("active_conflicts", []),
        main_characters=novel_info.get("main_characters", [])
    )
    
    recommender = TechniqueRecommender(
        reference_data=analysis_data,
        load_fn=load_json,
        save_fn=save_json
    )
    
    result = recommender.recommend(context, workspace)
    return {"success": True, "recommendations": result}


def adapt_to_genre(
    my_genre: str,
    reference_path: str,
    workspace_root: Optional[str] = None
) -> Dict[str, Any]:
    """将参考作品技巧适配到目标类型"""
    reference_file = Path(reference_path)
    workspace = Path(workspace_root) if workspace_root else reference_file.parent.parent
    
    analysis_data = load_json(reference_file)
    if not analysis_data:
        return {"error": "Failed to load reference analysis"}
    
    adapter = GenreAdapter(load_fn=load_json, save_fn=save_json)
    result = adapter.adapt(my_genre, analysis_data, workspace)
    
    return {"success": True, "adapted_techniques": result}


def plan_structure(
    outline_path: str,
    target_chapters: int,
    workspace_root: Optional[str] = None
) -> Dict[str, Any]:
    """根据大纲和参考作品规划剧情结构"""
    outline_file = Path(outline_path)
    workspace = Path(workspace_root) if workspace_root else outline_file.parent.parent
    
    learning_dir = workspace / "learning"
    analysis_data = load_json(learning_dir / "reference_analysis.json")
    
    outline_content = ""
    if outline_file.exists():
        outline_content = outline_file.read_text(encoding='utf-8')
    
    planner = PlotPlanner(
        reference_data=analysis_data,
        load_fn=load_json,
        save_fn=save_json
    )
    
    result = planner.plan(outline_content, target_chapters, workspace)
    return {"success": True, "plot_suggestions": result}


def build_context(
    workflow: str,
    chapter_num: int,
    novel_state_path: str,
    workspace_root: Optional[str] = None,
    max_techniques: int = 8
) -> Dict[str, Any]:
    """为指定工作流构建智能上下文"""
    novel_state_file = Path(novel_state_path)
    workspace = Path(workspace_root) if workspace_root else novel_state_file.parent.parent
    
    novel_state = load_json(novel_state_file)
    if not novel_state:
        return {"error": "Failed to load novel state"}
    
    learning_dir = workspace / "learning"
    recommendations = load_json(learning_dir / "recommendations.json")
    
    builder = ContextBuilder(load_fn=load_json, save_fn=save_json)
    result = builder.build(
        workflow=workflow,
        chapter_num=chapter_num,
        novel_state=novel_state,
        recommendations=recommendations,
        workspace=workspace,
        max_techniques=max_techniques
    )
    
    return {"success": True, "context": result}


def monitor_originality(
    draft_path: str,
    workspace_root: str,
    threshold: float = 0.75
) -> Dict[str, Any]:
    """检测草稿与参考作品的相似度"""
    workspace = Path(workspace_root)
    draft_file = workspace / draft_path
    
    if not draft_file.exists():
        return {"error": f"Draft file not found: {draft_path}"}
    
    draft_content = draft_file.read_text(encoding='utf-8')
    
    learning_dir = workspace / "learning"
    reference_texts = []
    
    candidates_file = learning_dir / "candidates.json"
    if candidates_file.exists():
        candidates = load_json(candidates_file)
        for ref in candidates.get("source_references", []):
            if ref.get("full_text"):
                reference_texts.append(ref["full_text"])
    
    if not reference_texts:
        return {"warning": "No reference texts available for comparison"}
    
    monitor = OriginalityMonitor(
        reference_texts=reference_texts,
        threshold=threshold,
        load_fn=load_json,
        save_fn=save_json
    )
    
    result = monitor.check(draft_content, draft_path, workspace)
    return {"success": True, "originality_report": result}


def cli_main():
    """命令行主入口"""
    parser = argparse.ArgumentParser(description="Reference Intelligence System CLI")
    subparsers = parser.add_subparsers(dest='command')
    
    rec_parser = subparsers.add_parser('recommend')
    rec_parser.add_argument('--chapter', type=int, required=True)
    rec_parser.add_argument('--novel-info', required=True)
    rec_parser.add_argument('--workspace')
    
    adapt_parser = subparsers.add_parser('adapt-genre')
    adapt_parser.add_argument('--genre', required=True)
    adapt_parser.add_argument('--reference', required=True)
    adapt_parser.add_argument('--workspace')
    
    plan_parser = subparsers.add_parser('plan-plot')
    plan_parser.add_argument('--outline', required=True)
    plan_parser.add_argument('--chapters', type=int, required=True)
    plan_parser.add_argument('--workspace')
    
    context_parser = subparsers.add_parser('build-context')
    context_parser.add_argument('--workflow', required=True, choices=['mvp', 'outline', 'polish'])
    context_parser.add_argument('--chapter', type=int, required=True)
    context_parser.add_argument('--novel-state', required=True)
    context_parser.add_argument('--workspace')
    context_parser.add_argument('--max-techniques', type=int, default=8)
    
    check_parser = subparsers.add_parser('check-similarity')
    check_parser.add_argument('--draft', required=True)
    check_parser.add_argument('--workspace', required=True)
    check_parser.add_argument('--threshold', type=float, default=0.75)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        if args.command == 'recommend':
            result = recommend_for_chapter(args.chapter, args.novel_info, args.workspace)
        elif args.command == 'adapt-genre':
            result = adapt_to_genre(args.genre, args.reference, args.workspace)
        elif args.command == 'plan-plot':
            result = plan_structure(args.outline, args.chapters, args.workspace)
        elif args.command == 'build-context':
            result = build_context(args.workflow, args.chapter, args.novel_state, args.workspace, args.max_techniques)
        elif args.command == 'check-similarity':
            result = monitor_originality(args.draft, args.workspace, args.threshold)
        else:
            parser.print_help()
            sys.exit(1)
        
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("success") else 1)
            
    except Exception as e:
        error_result = {"error": str(e), "type": type(e).__name__}
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
