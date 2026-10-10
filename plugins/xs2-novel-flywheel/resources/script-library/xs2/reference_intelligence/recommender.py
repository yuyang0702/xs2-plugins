"""Intelligent technique recommendation engine.

Recommends writing techniques based on novel context and current progress.
"""
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class PlotStage(Enum):
    """Plot development stage."""
    OPENING = "opening"           # 开局 (1-20%)
    RISING = "rising"             # 发展 (20-60%)
    CLIMAX = "climax"             # 高潮 (60-80%)
    RESOLUTION = "resolution"     # 结局 (80-100%)
    UNKNOWN = "unknown"


class ConflictPhase(Enum):
    """Conflict development phase."""
    INTRODUCTION = "introduction"  # 引入
    ESCALATION = "escalation"      # 升级
    PEAK = "peak"                  # 顶峰
    RESOLUTION = "resolution"      # 解决
    UNKNOWN = "unknown"


@dataclass
class NovelContext:
    """Current novel writing context."""
    genre: str                      # 类型：都市/玄幻/悬疑等
    total_chapters: int             # 总章节数
    current_chapter: int            # 当前章节
    pov: str                        # 视角：first_person/third_person
    target_length: int              # 目标字数
    current_length: int             # 当前字数
    plot_stage: PlotStage           # 剧情阶段
    conflict_phase: ConflictPhase   # 冲突阶段
    active_conflicts: List[str]     # 当前激活的冲突
    main_characters: List[str]      # 主要角色


@dataclass
class Recommendation:
    """A single technique recommendation."""
    technique_id: str
    technique_name: str
    category: str                   # plot/character/conflict/technique
    priority: int                   # 1-5, 5 highest
    relevance_score: float          # 0-1
    reason: str                     # 推荐理由
    application_guidance: str       # 具体应用建议
    source: str                     # 来源参考作品
    constraints: List[str]          # 使用限制


class TechniqueRecommender:
    """Intelligent technique recommendation engine."""
    
    def __init__(self, load_fn, save_fn):
        """Initialize recommender.
        
        Args:
            load_fn: Function to load JSON files
            save_fn: Function to save JSON files
        """
        self.load = load_fn
        self.save = save_fn
    
    def recommend_for_chapter(
        self,
        novel_context: NovelContext,
        max_recommendations: int = 10
    ) -> List[Recommendation]:
        """Recommend techniques for current chapter.
        
        Args:
            novel_context: Current novel writing context
            max_recommendations: Maximum number of recommendations
            
        Returns:
            List of recommendations sorted by priority and relevance
        """
        # Load reference analysis
        try:
            ref_analysis = self.load("learning/reference_analysis.json")
            candidates = self.load("learning/candidates.json")
        except (OSError, ValueError):
            return []
        
        # Calculate plot progress
        progress = novel_context.current_chapter / novel_context.total_chapters
        
        # Collect candidate techniques
        recommendations = []
        
        # Recommend plot techniques
        plot_recs = self._recommend_plot_techniques(
            ref_analysis, novel_context, progress
        )
        recommendations.extend(plot_recs)
        
        # Recommend character techniques
        char_recs = self._recommend_character_techniques(
            ref_analysis, novel_context
        )
        recommendations.extend(char_recs)
        
        # Recommend conflict techniques
        conflict_recs = self._recommend_conflict_techniques(
            ref_analysis, novel_context, progress
        )
        recommendations.extend(conflict_recs)
        
        # Recommend writing techniques
        technique_recs = self._recommend_writing_techniques(
            ref_analysis, novel_context
        )
        recommendations.extend(technique_recs)
        
        # Sort by priority and relevance
        recommendations.sort(
            key=lambda r: (r.priority, r.relevance_score),
            reverse=True
        )
        
        return recommendations[:max_recommendations]
    
    def _recommend_plot_techniques(
        self,
        ref_analysis: Dict,
        context: NovelContext,
        progress: float
    ) -> List[Recommendation]:
        """Recommend plot-related techniques."""
        recommendations = []
        
        try:
            plot_dims = ref_analysis["analyses"]["plot"]["plot_dimensions"]
        except KeyError:
            return recommendations
        
        # Recommend conflict escalation
        if context.plot_stage in [PlotStage.OPENING, PlotStage.RISING]:
            escalation = plot_dims.get("conflict_escalation", {})
            patterns = escalation.get("patterns", [])
            
            for i, pattern in enumerate(patterns[:3]):
                priority = 5 if i == 0 else (4 if i == 1 else 3)
                recommendations.append(Recommendation(
                    technique_id=f"plot_conflict_{i}",
                    technique_name=pattern.get("mechanism", ""),
                    category="plot",
                    priority=priority,
                    relevance_score=0.9 - i * 0.1,
                    reason=f"当前处于{context.plot_stage.value}阶段，适合使用冲突升级模式",
                    application_guidance=pattern.get("transfer_guidance", ""),
                    source=ref_analysis.get("source", {}).get("title", "参考作品"),
                    constraints=pattern.get("constraints", [])
                ))
        
        # Recommend foreshadowing
        if progress < 0.7:  # Before climax
            foreshadow = plot_dims.get("foreshadowing", {})
            patterns = foreshadow.get("patterns", [])
            
            for i, pattern in enumerate(patterns[:2]):
                recommendations.append(Recommendation(
                    technique_id=f"plot_foreshadow_{i}",
                    technique_name=pattern.get("mechanism", ""),
                    category="plot",
                    priority=4,
                    relevance_score=0.85,
                    reason="当前阶段适合埋设伏笔，为后续情节做铺垫",
                    application_guidance=pattern.get("transfer_guidance", ""),
                    source=ref_analysis.get("source", {}).get("title", "参考作品"),
                    constraints=pattern.get("constraints", [])
                ))
        
        # Recommend reversals near climax
        if context.plot_stage == PlotStage.CLIMAX:
            reversals = plot_dims.get("reversals", {})
            patterns = reversals.get("patterns", [])
            
            for i, pattern in enumerate(patterns[:2]):
                recommendations.append(Recommendation(
                    technique_id=f"plot_reversal_{i}",
                    technique_name=pattern.get("mechanism", ""),
                    category="plot",
                    priority=5,
                    relevance_score=0.95,
                    reason="高潮阶段，反转能显著增强戏剧张力",
                    application_guidance=pattern.get("transfer_guidance", ""),
                    source=ref_analysis.get("source", {}).get("title", "参考作品"),
                    constraints=pattern.get("constraints", [])
                ))
        
        return recommendations
    
    def _recommend_character_techniques(
        self,
        ref_analysis: Dict,
        context: NovelContext
    ) -> List[Recommendation]:
        """Recommend character-related techniques."""
        recommendations = []
        
        try:
            char_dims = ref_analysis["analyses"]["character"]["character_dimensions"]
        except KeyError:
            return recommendations
        
        # Recommend character arcs
        arcs = char_dims.get("character_arcs", {})
        patterns = arcs.get("patterns", [])
        
        for i, pattern in enumerate(patterns[:3]):
            priority = 4 if context.plot_stage in [PlotStage.RISING, PlotStage.CLIMAX] else 3
            recommendations.append(Recommendation(
                technique_id=f"char_arc_{i}",
                technique_name=pattern.get("mechanism", ""),
                category="character",
                priority=priority,
                relevance_score=0.8,
                reason="角色弧光贯穿全篇，持续关注角色成长",
                application_guidance=pattern.get("transfer_guidance", ""),
                source=ref_analysis.get("source", {}).get("title", "参考作品"),
                constraints=pattern.get("constraints", [])
            ))
        
        # Recommend relationship dynamics
        relationships = char_dims.get("relationships", {})
        patterns = relationships.get("patterns", [])
        
        for i, pattern in enumerate(patterns[:2]):
            recommendations.append(Recommendation(
                technique_id=f"char_rel_{i}",
                technique_name=pattern.get("mechanism", ""),
                category="character",
                priority=3,
                relevance_score=0.75,
                reason="人物关系变化增强故事层次",
                application_guidance=pattern.get("transfer_guidance", ""),
                source=ref_analysis.get("source", {}).get("title", "参考作品"),
                constraints=pattern.get("constraints", [])
            ))
        
        return recommendations
    
    def _recommend_conflict_techniques(
        self,
        ref_analysis: Dict,
        context: NovelContext,
        progress: float
    ) -> List[Recommendation]:
        """Recommend conflict-related techniques."""
        recommendations = []
        
        try:
            conflict_dims = ref_analysis["analyses"]["conflict"]["conflict_dimensions"]
        except KeyError:
            return recommendations
        
        # Recommend escalation paths
        if context.conflict_phase in [ConflictPhase.INTRODUCTION, ConflictPhase.ESCALATION]:
            escalation = conflict_dims.get("escalation_paths", {})
            patterns = escalation.get("patterns", [])
            
            for i, pattern in enumerate(patterns[:3]):
                recommendations.append(Recommendation(
                    technique_id=f"conflict_escalate_{i}",
                    technique_name=pattern.get("mechanism", ""),
                    category="conflict",
                    priority=5,
                    relevance_score=0.9,
                    reason=f"冲突{context.conflict_phase.value}阶段，需要持续升级",
                    application_guidance=pattern.get("transfer_guidance", ""),
                    source=ref_analysis.get("source", {}).get("title", "参考作品"),
                    constraints=pattern.get("constraints", [])
                ))
        
        # Recommend cost and stakes
        stakes = conflict_dims.get("cost_and_stakes", {})
        patterns = stakes.get("patterns", [])
        
        for i, pattern in enumerate(patterns[:2]):
            recommendations.append(Recommendation(
                technique_id=f"conflict_stakes_{i}",
                technique_name=pattern.get("mechanism", ""),
                category="conflict",
                priority=4,
                relevance_score=0.85,
                reason="明确展示行动代价，增强读者投入",
                application_guidance=pattern.get("transfer_guidance", ""),
                source=ref_analysis.get("source", {}).get("title", "参考作品"),
                constraints=pattern.get("constraints", [])
            ))
        
        return recommendations
    
    def _recommend_writing_techniques(
        self,
        ref_analysis: Dict,
        context: NovelContext
    ) -> List[Recommendation]:
        """Recommend writing craft techniques."""
        recommendations = []
        
        try:
            tech_dims = ref_analysis["analyses"]["technique"]["technique_dimensions"]
        except KeyError:
            return recommendations
        
        # Recommend dialogue techniques
        dialogue = tech_dims.get("dialogue_craft", {})
        patterns = dialogue.get("patterns", [])
        
        for i, pattern in enumerate(patterns[:2]):
            recommendations.append(Recommendation(
                technique_id=f"tech_dialogue_{i}",
                technique_name=pattern.get("mechanism", ""),
                category="technique",
                priority=3,
                relevance_score=0.7,
                reason="对话是推进情节和展示人物的重要手段",
                application_guidance=pattern.get("transfer_guidance", ""),
                source=ref_analysis.get("source", {}).get("title", "参考作品"),
                constraints=pattern.get("constraints", [])
            ))
        
        # Recommend scene construction
        scene = tech_dims.get("scene_construction", {})
        patterns = scene.get("patterns", [])
        
        for i, pattern in enumerate(patterns[:2]):
            recommendations.append(Recommendation(
                technique_id=f"tech_scene_{i}",
                technique_name=pattern.get("mechanism", ""),
                category="technique",
                priority=3,
                relevance_score=0.7,
                reason="场景构建增强代入感",
                application_guidance=pattern.get("transfer_guidance", ""),
                source=ref_analysis.get("source", {}).get("title", "参考作品"),
                constraints=pattern.get("constraints", [])
            ))
        
        return recommendations
    
    def save_recommendations(
        self,
        recommendations: List[Recommendation],
        output_path: str = "learning/recommendations.json"
    ) -> None:
        """Save recommendations to file.
        
        Args:
            recommendations: List of recommendations
            output_path: Output file path
        """
        data = {
            "schema": "xs2.technique.recommendations.v1",
            "recommendations": [
                {
                    "technique_id": r.technique_id,
                    "technique_name": r.technique_name,
                    "category": r.category,
                    "priority": r.priority,
                    "relevance_score": r.relevance_score,
                    "reason": r.reason,
                    "application_guidance": r.application_guidance,
                    "source": r.source,
                    "constraints": r.constraints
                }
                for r in recommendations
            ]
        }
        
        self.save(output_path, data)
