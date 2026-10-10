"""
Reference Intelligence System for Novel Writing
参考作品智能分析与推荐系统

A comprehensive system for:
1. Analyzing imported reference novels (technical analysis, plot structure, style extraction)
2. Recommending techniques based on novel context and chapter position
3. Genre-specific adaptation of writing techniques
4. Smart context building for different workflows
5. Real-time originality monitoring to prevent plagiarism
"""

from .recommender import (
    TechniqueRecommender,
    NovelContext,
    PlotStage,
    ConflictPhase,
)

from .genre_adapter import (
    GenreAdapter,
)

from .plot_planner import (
    PlotPlanner,
)

from .context_builder import (
    ContextBuilder,
)

from .originality_monitor import (
    OriginalityMonitor,
)

from .intelligence_api import (
    recommend_for_chapter,
    adapt_to_genre,
    plan_structure,
    build_context,
    monitor_originality,
    cli_main,
)

__all__ = [
    # Recommender
    "TechniqueRecommender",
    "NovelContext",
    "PlotStage",
    "ConflictPhase",
    
    # Genre Adapter
    "GenreAdapter",
    
    # Plot Planner
    "PlotPlanner",
    
    # Context Builder
    "ContextBuilder",
    
    # Originality Monitor
    "OriginalityMonitor",
    
    # API
    "recommend_for_chapter",
    "adapt_to_genre",
    "plan_structure",
    "build_context",
    "monitor_originality",
    "cli_main",
]

__version__ = "0.1.0"
__author__ = "XS2 Novel System"
__description__ = "Reference Intelligence System for Novel Writing"
