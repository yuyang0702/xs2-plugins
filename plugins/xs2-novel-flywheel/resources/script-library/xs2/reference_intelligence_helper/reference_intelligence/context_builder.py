"""Context-aware builder for workflow integration.

Constructs tailored context for writing workflows based on current progress.
"""
import json
from typing import Dict, List, Any, Optional
from pathlib import Path


class ContextBuilder:
    """Context-aware builder for writing workflows."""
    
    def __init__(self, load_fn, save_fn):
        """Initialize context builder.
        
        Args:
            load_fn: Function to load JSON files
            save_fn: Function to save JSON files
        """
        self.load = load_fn
        self.save = save_fn
    
    def build_context_for_writing(
        self,
        workflow_stage: str,
        current_chapter: int,
        novel_state: Dict,
        max_techniques: int = 8
    ) -> str:
        """Build tailored context for writing workflow.
        
        Args:
            workflow_stage: mvp/outline/polish/post-hoc
            current_chapter: Current chapter number
            novel_state: Current novel state (progress, conflicts, etc.)
            max_techniques: Maximum techniques to include
            
        Returns:
            Formatted context string for workflow
        """
        # Load recommendations
        try:
            recommendations = self.load("learning/recommendations.json")
        except (OSError, ValueError):
            recommendations = {"recommendations": []}
        
        # Load adapted techniques
        try:
            adapted = self.load("learning/adapted_techniques.json")
        except (OSError, ValueError):
            adapted = {"adapted_techniques": []}
        
        # Load plot suggestions
        try:
            plot_suggestions = self.load("learning/plot_suggestions.json")
        except (OSError, ValueError):
            plot_suggestions = {"story_beats": []}
        
        # Filter and prioritize
        filtered_recs = self._filter_recommendations(
            recommendations.get("recommendations", []),
            workflow_stage,
            current_chapter,
            novel_state
        )
        
        # Build context sections
        sections = []
        
        # Section 1: Current position
        sections.append(self._build_position_section(
            current_chapter,
            novel_state,
            plot_suggestions
        ))
        
        # Section 2: Priority techniques
        sections.append(self._build_techniques_section(
            filtered_recs[:max_techniques],
            workflow_stage
        ))
        
        # Section 3: Plot guidance
        sections.append(self._build_plot_guidance_section(
            current_chapter,
            plot_suggestions,
            novel_state
        ))
        
        # Section 4: Warnings (if any)
        sections.append(self._build_warnings_section(
            filtered_recs,
            plot_suggestions
        ))
        
        return "\n\n".join(filter(None, sections))
    
    def _filter_recommendations(
        self,
        recommendations: List[Dict],
        workflow_stage: str,
        current_chapter: int,
        novel_state: Dict
    ) -> List[Dict]:
        """Filter recommendations by relevance.
        
        Args:
            recommendations: All recommendations
            workflow_stage: Current workflow stage
            current_chapter: Current chapter
            novel_state: Novel state
            
        Returns:
            Filtered and sorted recommendations
        """
        filtered = []
        
        for rec in recommendations:
            # Stage-specific filtering
            if workflow_stage == "mvp":
                # MVP: focus on plot and conflict
                if rec["category"] in ["plot", "conflict"]:
                    filtered.append(rec)
            elif workflow_stage == "outline":
                # Outline: all categories
                filtered.append(rec)
            elif workflow_stage == "polish":
                # Polish: focus on technique
                if rec["category"] in ["technique", "character"]:
                    filtered.append(rec)
            else:
                filtered.append(rec)
        
        # Sort by priority and relevance
        filtered.sort(
            key=lambda r: (r.get("priority", 0), r.get("relevance_score", 0)),
            reverse=True
        )
        
        return filtered
    
    def _build_position_section(
        self,
        current_chapter: int,
        novel_state: Dict,
        plot_suggestions: Dict
    ) -> str:
        """Build current position section.
        
        Args:
            current_chapter: Current chapter
            novel_state: Novel state
            plot_suggestions: Plot suggestions
            
        Returns:
            Formatted position section
        """
        total_chapters = novel_state.get("total_chapters", 100)
        progress = (current_chapter / total_chapters) * 100
        
        # Find nearest beat
        beats = plot_suggestions.get("story_beats", [])
        nearest_beat = None
        min_diff = float('inf')
        
        for beat in beats:
            diff = abs(beat["chapter_estimate"] - current_chapter)
            if diff < min_diff:
                min_diff = diff
                nearest_beat = beat
        
        section = f"""# 当前写作位置

章节：第 {current_chapter} 章 / 共 {total_chapters} 章
进度：{progress:.1f}%
剧情阶段：{novel_state.get('plot_stage', '未知')}
冲突状态：{novel_state.get('conflict_phase', '未知')}"""
        
        if nearest_beat:
            if abs(nearest_beat["chapter_estimate"] - current_chapter) <= 3:
                section += f"\n\n⚠️ 关键节点临近：{nearest_beat['event_type']} (第 {nearest_beat['chapter_estimate']} 章)"
                section += f"\n{nearest_beat['event_description']}"
        
        return section
    
    def _build_techniques_section(
        self,
        techniques: List[Dict],
        workflow_stage: str
    ) -> str:
        """Build techniques section.
        
        Args:
            techniques: Filtered techniques
            workflow_stage: Current workflow stage
            
        Returns:
            Formatted techniques section
        """
        if not techniques:
            return ""
        
        section = f"# 推荐技巧（适用于{workflow_stage}阶段）\n"
        
        for i, tech in enumerate(techniques, 1):
            priority_stars = "⭐" * tech.get("priority", 3)
            section += f"\n## {i}. {tech['technique_name']} {priority_stars}\n"
            section += f"**类别**：{tech['category']}\n"
            section += f"**推荐理由**：{tech['reason']}\n"
            section += f"**应用建议**：{tech['application_guidance']}\n"
            
            if tech.get("constraints"):
                section += f"**注意事项**：\n"
                for constraint in tech["constraints"][:3]:
                    section += f"- {constraint}\n"
        
        return section
    
    def _build_plot_guidance_section(
        self,
        current_chapter: int,
        plot_suggestions: Dict,
        novel_state: Dict
    ) -> str:
        """Build plot guidance section.
        
        Args:
            current_chapter: Current chapter
            plot_suggestions: Plot suggestions
            novel_state: Novel state
            
        Returns:
            Formatted plot guidance section
        """
        beats = plot_suggestions.get("story_beats", [])
        if not beats:
            return ""
        
        section = "# 剧情规划指引\n"
        
        # Find upcoming beats
        upcoming_beats = [
            b for b in beats 
            if b["chapter_estimate"] >= current_chapter
        ][:3]
        
        if upcoming_beats:
            section += "\n## 接下来的关键节点\n"
            for beat in upcoming_beats:
                chapters_away = beat["chapter_estimate"] - current_chapter
                section += f"\n### {beat['event_type']} (第 {beat['chapter_estimate']} 章，还有 {chapters_away} 章)\n"
                section += f"{beat['event_description']}\n"
                section += f"**张力等级**：{beat['tension_level']}/10\n"
                
                if beat.get("foreshadowing_required"):
                    section += f"**需要的伏笔**：{', '.join(beat['foreshadowing_required'])}\n"
        
        # Add recommendations
        recommendations = plot_suggestions.get("recommendations", [])
        if recommendations:
            section += "\n## 整体建议\n"
            for rec in recommendations[:3]:
                section += f"- {rec}\n"
        
        return section
    
    def _build_warnings_section(
        self,
        recommendations: List[Dict],
        plot_suggestions: Dict
    ) -> str:
        """Build warnings section.
        
        Args:
            recommendations: Filtered recommendations
            plot_suggestions: Plot suggestions
            
        Returns:
            Formatted warnings section
        """
        warnings = []
        
        # Collect warnings from recommendations
        for rec in recommendations:
            if rec.get("constraints"):
                for constraint in rec["constraints"][:1]:  # Only first constraint
                    if "禁止" in constraint or "注意" in constraint:
                        warnings.append(f"技巧 '{rec['technique_name']}'：{constraint}")
        
        # Add plot warnings
        plot_warnings = plot_suggestions.get("warnings", [])
        warnings.extend(plot_warnings[:3])
        
        if not warnings:
            return ""
        
        section = "# ⚠️ 重要提示\n"
        for warning in warnings[:5]:  # Max 5 warnings
            section += f"\n{warning}"
        
        return section
    
    def save_context(
        self,
        context: str,
        workflow_stage: str,
        current_chapter: int,
        output_path: str = None
    ) -> None:
        """Save built context to file.
        
        Args:
            context: Built context
            workflow_stage: Workflow stage
            current_chapter: Current chapter
            output_path: Output file path
        """
        if output_path is None:
            output_path = f"learning/context_{workflow_stage}_ch{current_chapter}.md"
        
        from pathlib import Path
        Path(output_path).write_text(context, encoding="utf-8")
    
    def build_minimal_context(
        self,
        current_chapter: int,
        focus_category: str = None
    ) -> str:
        """Build minimal context with specific focus.
        
        Args:
            current_chapter: Current chapter
            focus_category: Specific category to focus on (plot/character/conflict/technique)
            
        Returns:
            Minimal context string
        """
        try:
            recommendations = self.load("learning/recommendations.json")
        except (OSError, ValueError):
            return "# 无可用的写作参考\n\n请先完成参考作品的分析。"
        
        recs = recommendations.get("recommendations", [])
        
        if focus_category:
            recs = [r for r in recs if r["category"] == focus_category]
        
        # Top 3 recommendations
        recs = sorted(
            recs,
            key=lambda r: (r.get("priority", 0), r.get("relevance_score", 0)),
            reverse=True
        )[:3]
        
        context = f"# 第 {current_chapter} 章写作参考\n"
        
        if not recs:
            context += "\n本章节暂无特定推荐技巧，请发挥创意。\n"
            return context
        
        for i, rec in enumerate(recs, 1):
            context += f"\n## {i}. {rec['technique_name']}\n"
            context += f"{rec['application_guidance']}\n"
        
        return context
