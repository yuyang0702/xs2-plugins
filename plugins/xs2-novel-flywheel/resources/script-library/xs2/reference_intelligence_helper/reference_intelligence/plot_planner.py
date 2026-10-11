"""Plot planning advisor for story structure optimization.

Suggests optimal plot structure based on reference works and current outline.
"""
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ArcPosition(Enum):
    """Position in story arc."""
    OPENING = (0.0, 0.15)        # 0-15%
    INCITING_INCIDENT = (0.15, 0.25)  # 15-25%
    RISING = (0.25, 0.60)        # 25-60%
    MIDPOINT = (0.45, 0.55)      # 45-55%
    RISING_CLIMAX = (0.60, 0.75) # 60-75%
    CLIMAX = (0.75, 0.85)        # 75-85%
    RESOLUTION = (0.85, 1.0)     # 85-100%


@dataclass
class PlotSuggestion:
    """A single plot structure suggestion."""
    position_percentage: float     # 0-1 (where in the story)
    chapter_estimate: int          # Estimated chapter number
    event_type: str               # turning_point/climax/resolution etc
    timing_note: str              # 时机说明
    event_description: str        # 事件描述
    foreshadowing_required: List[str]  # 需要前置的伏笔
    payoff_timing: str            # 回收时机
    tension_level: int            # 1-10 (tension intensity)
    priority: int                 # 1-5 (how important)
    reference_example: str        # 参考作品的例子


@dataclass
class PlotStructureAnalysis:
    """Analysis of optimal plot structure."""
    total_chapters: int
    story_beats: List[PlotSuggestion]
    pacing_analysis: Dict[str, Any]  # Pacing breakdown
    turning_points: List[int]      # Suggested chapter numbers for turning points
    warnings: List[str]           # Potential issues
    recommendations: List[str]    # Key recommendations


class PlotPlanner:
    """Plot planning advisor."""
    
    def __init__(self, load_fn, save_fn):
        """Initialize planner.
        
        Args:
            load_fn: Function to load JSON files
            save_fn: Function to save JSON files
        """
        self.load = load_fn
        self.save = save_fn
    
    def suggest_plot_structure(
        self,
        my_outline: Dict,
        target_chapters: int,
        reference_analysis: Dict
    ) -> PlotStructureAnalysis:
        """Suggest optimal plot structure.
        
        Args:
            my_outline: Current outline data
            target_chapters: Target number of chapters
            reference_analysis: Reference work analysis
            
        Returns:
            Detailed plot structure suggestions
        """
        suggestions = []
        
        # Extract reference patterns
        ref_conflicts = reference_analysis.get("analyses", {}).get("conflict", {}).get("conflict_dimensions", {}).get("conflict_chains", {}).get("chains", [])
        ref_plot = reference_analysis.get("analyses", {}).get("plot", {}).get("plot_dimensions", {})
        
        # Analyze current outline
        current_events = my_outline.get("events", [])
        main_conflicts = my_outline.get("main_conflicts", [])
        
        # Generate story beats
        beats = self._generate_story_beats(
            target_chapters,
            ref_conflicts,
            ref_plot,
            current_events
        )
        
        # Analyze pacing
        pacing = self._analyze_pacing(beats, target_chapters)
        
        # Identify turning points
        turning_points = self._identify_turning_points(beats, target_chapters)
        
        # Generate warnings
        warnings = self._generate_warnings(beats, current_events, target_chapters)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(beats, ref_conflicts)
        
        return PlotStructureAnalysis(
            total_chapters=target_chapters,
            story_beats=beats,
            pacing_analysis=pacing,
            turning_points=turning_points,
            warnings=warnings,
            recommendations=recommendations
        )
    
    def _generate_story_beats(
        self,
        target_chapters: int,
        ref_conflicts: List[Dict],
        ref_plot: Dict,
        current_events: List[Dict]
    ) -> List[PlotSuggestion]:
        """Generate story beats based on reference patterns.
        
        Args:
            target_chapters: Total chapters
            ref_conflicts: Reference conflict chains
            ref_plot: Reference plot analysis
            current_events: Current outline events
            
        Returns:
            List of story beats
        """
        beats = []
        
        # Opening beat
        beats.append(PlotSuggestion(
            position_percentage=0.1,
            chapter_estimate=max(1, int(target_chapters * 0.05)),
            event_type="opening_hook",
            timing_note="前1-5%，建立基本世界观和主角",
            event_description="设置故事背景，介绍主要角色，制造初始问题或冲突",
            foreshadowing_required=[],
            payoff_timing="整部作品",
            tension_level=3,
            priority=5,
            reference_example=self._find_reference_beat(ref_plot, "opening")
        ))
        
        # Inciting incident
        beats.append(PlotSuggestion(
            position_percentage=0.2,
            chapter_estimate=max(2, int(target_chapters * 0.15)),
            event_type="inciting_incident",
            timing_note="15-25%，引入主要冲突",
            event_description="发生改变故事方向的事件，主角被迫踏上冒险",
            foreshadowing_required=["初始背景设置"],
            payoff_timing="中间和结尾",
            tension_level=5,
            priority=5,
            reference_example=self._find_reference_beat(ref_plot, "inciting")
        ))
        
        # First escalation
        beats.append(PlotSuggestion(
            position_percentage=0.35,
            chapter_estimate=int(target_chapters * 0.35),
            event_type="first_escalation",
            timing_note="30-40%，第一次冲突升级",
            event_description="第一个重要的发展或转折，问题变得更复杂",
            foreshadowing_required=["主要冲突的基础"],
            payoff_timing="第二次升级前",
            tension_level=6,
            priority=4,
            reference_example=self._extract_escalation_pattern(ref_conflicts, 0)
        ))
        
        # Midpoint reversal
        beats.append(PlotSuggestion(
            position_percentage=0.5,
            chapter_estimate=int(target_chapters * 0.5),
            event_type="midpoint_reversal",
            timing_note="50%，中点反转",
            event_description="形势反转或出现意外转折，改变故事走向",
            foreshadowing_required=["前期伏笔"],
            payoff_timing="高潮前的冲刺",
            tension_level=7,
            priority=5,
            reference_example=self._find_reference_beat(ref_plot, "midpoint")
        ))
        
        # Second escalation
        beats.append(PlotSuggestion(
            position_percentage=0.65,
            chapter_estimate=int(target_chapters * 0.65),
            event_type="second_escalation",
            timing_note="60-70%，第二次升级",
            event_description="冲突再次升级，局势变得更加危急",
            foreshadowing_required=["中点反转"],
            payoff_timing="高潮前",
            tension_level=8,
            priority=4,
            reference_example=self._extract_escalation_pattern(ref_conflicts, 1)
        ))
        
        # Climax preparation
        beats.append(PlotSuggestion(
            position_percentage=0.75,
            chapter_estimate=int(target_chapters * 0.75),
            event_type="climax_preparation",
            timing_note="75%，高潮准备",
            event_description="最后的准备，所有线索汇聚，决战在即",
            foreshadowing_required=["所有主要伏笔"],
            payoff_timing="高潮时刻",
            tension_level=9,
            priority=5,
            reference_example=self._find_reference_beat(ref_plot, "climax_prep")
        ))
        
        # Climax
        beats.append(PlotSuggestion(
            position_percentage=0.80,
            chapter_estimate=int(target_chapters * 0.80),
            event_type="climax",
            timing_note="75-85%，高潮时刻",
            event_description="最紧张的对抗，主角面临最大的考验",
            foreshadowing_required=["所有伏笔和铺垫"],
            payoff_timing="立即在下一个beat",
            tension_level=10,
            priority=5,
            reference_example=self._find_reference_beat(ref_plot, "climax")
        ))
        
        # Resolution
        beats.append(PlotSuggestion(
            position_percentage=0.90,
            chapter_estimate=int(target_chapters * 0.90),
            event_type="resolution",
            timing_note="85-95%，冲突解决",
            event_description="主要冲突得到解决，局势明朗",
            foreshadowing_required=["高潮事件"],
            payoff_timing="结局铺垫",
            tension_level=6,
            priority=4,
            reference_example=self._find_reference_beat(ref_plot, "resolution")
        ))
        
        # Epilogue
        beats.append(PlotSuggestion(
            position_percentage=0.98,
            chapter_estimate=target_chapters,
            event_type="epilogue",
            timing_note="95-100%，收尾",
            event_description="展示故事结果，回答残留的问题，结局意境",
            foreshadowing_required=["所有主线"],
            payoff_timing="无",
            tension_level=2,
            priority=3,
            reference_example=self._find_reference_beat(ref_plot, "epilogue")
        ))
        
        return beats
    
    def _analyze_pacing(
        self,
        beats: List[PlotSuggestion],
        target_chapters: int
    ) -> Dict[str, Any]:
        """Analyze pacing distribution.
        
        Args:
            beats: Story beats
            target_chapters: Total chapters
            
        Returns:
            Pacing analysis
        """
        intervals = []
        for i in range(len(beats) - 1):
            start_pos = beats[i].position_percentage
            end_pos = beats[i + 1].position_percentage
            chapter_count = int((end_pos - start_pos) * target_chapters)
            intervals.append({
                "from": beats[i].event_type,
                "to": beats[i + 1].event_type,
                "percentage": (end_pos - start_pos) * 100,
                "chapters": chapter_count
            })
        
        return {
            "intervals": intervals,
            "accelerating_sections": [i["from"] for i in intervals if i["percentage"] < 10],
            "normal_sections": [i["from"] for i in intervals if 10 <= i["percentage"] < 20],
            "extended_sections": [i["from"] for i in intervals if i["percentage"] >= 20],
        }
    
    def _identify_turning_points(
        self,
        beats: List[PlotSuggestion],
        target_chapters: int
    ) -> List[int]:
        """Identify key turning point chapters.
        
        Args:
            beats: Story beats
            target_chapters: Total chapters
            
        Returns:
            List of chapter numbers for turning points
        """
        turning_points = []
        
        for beat in beats:
            if beat.event_type in ["inciting_incident", "midpoint_reversal", "second_escalation", "climax"]:
                turning_points.append(beat.chapter_estimate)
        
        return sorted(turning_points)
    
    def _generate_warnings(
        self,
        beats: List[PlotSuggestion],
        current_events: List[Dict],
        target_chapters: int
    ) -> List[str]:
        """Generate potential warnings.
        
        Args:
            beats: Story beats
            current_events: Current outline events
            target_chapters: Total chapters
            
        Returns:
            List of warnings
        """
        warnings = []
        
        # Check if climax is too close to end
        climax_beat = next((b for b in beats if b.event_type == "climax"), None)
        if climax_beat and (1.0 - climax_beat.position_percentage) * target_chapters < 5:
            warnings.append("⚠️ 高潮出现过晚，冲突解决和结局空间不足")
        
        # Check for missing beats
        current_events_types = {e.get("type") for e in current_events}
        required_beats = {"opening", "inciting_incident", "climax", "resolution"}
        missing = required_beats - current_events_types
        if missing:
            warnings.append(f"⚠️ 大纲缺少以下关键环节：{', '.join(missing)}")
        
        # Check pacing distribution
        beat_intervals = []
        for i in range(len(beats) - 1):
            interval = beats[i + 1].position_percentage - beats[i].position_percentage
            beat_intervals.append(interval)
        
        if max(beat_intervals) > 0.3:
            warnings.append("⚠️ 部分章节间隔过长，可能导致故事节奏松散")
        
        if min(beat_intervals) < 0.05:
            warnings.append("⚠️ 部分章节间隔过短，可能导致故事节奏过快")
        
        return warnings
    
    def _generate_recommendations(
        self,
        beats: List[PlotSuggestion],
        ref_conflicts: List[Dict]
    ) -> List[str]:
        """Generate key recommendations.
        
        Args:
            beats: Story beats
            ref_conflicts: Reference conflict patterns
            
        Returns:
            List of recommendations
        """
        recommendations = []
        
        # General recommendations
        recommendations.append("确保每个关键转折点都有充分的铺垫")
        recommendations.append("使用伏笔连接各个情节点，增强因果链")
        recommendations.append("在高潮前适当放缓节奏，为读者喘息机会")
        recommendations.append("高潮后不要拖沓，迅速进入解决阶段")
        
        # Based on reference patterns
        if ref_conflicts:
            first_conflict = ref_conflicts[0] if ref_conflicts else {}
            if first_conflict.get("application_scope") in ["serial_opening", "serial_chapter"]:
                recommendations.append("参考作品的冲突设计适合长篇连载，注意节奏的起伏")
        
        return recommendations
    
    def _find_reference_beat(self, ref_plot: Dict, beat_type: str) -> str:
        """Find reference example for a beat type.
        
        Args:
            ref_plot: Reference plot analysis
            beat_type: Type of beat
            
        Returns:
            Reference example description
        """
        insights = ref_plot.get("transferable_insights", [])
        
        if beat_type == "opening" and insights:
            return insights[0] if insights else "参考作品以有吸引力的开局吸引读者"
        elif beat_type == "midpoint" and insights:
            return "参考作品在中点设置了意料之外的转折"
        elif beat_type == "climax":
            return "参考作品的高潮包含了充分的冲突和情感"
        
        return "参考作品的相应阶段设计"
    
    def _extract_escalation_pattern(self, conflicts: List[Dict], index: int) -> str:
        """Extract escalation pattern from reference.
        
        Args:
            conflicts: Conflict patterns
            index: Index of pattern
            
        Returns:
            Pattern description
        """
        if index < len(conflicts):
            conflict = conflicts[index]
            return f"参考作品：{conflict.get('name', '冲突')}"
        return "参考作品的升级模式"
    
    def save_plot_suggestions(
        self,
        analysis: PlotStructureAnalysis,
        output_path: str = "learning/plot_suggestions.json"
    ) -> None:
        """Save plot suggestions to file.
        
        Args:
            analysis: Plot structure analysis
            output_path: Output file path
        """
        data = {
            "schema": "xs2.plot.suggestions.v1",
            "total_chapters": analysis.total_chapters,
            "story_beats": [
                {
                    "position_percentage": b.position_percentage,
                    "chapter_estimate": b.chapter_estimate,
                    "event_type": b.event_type,
                    "timing_note": b.timing_note,
                    "event_description": b.event_description,
                    "foreshadowing_required": b.foreshadowing_required,
                    "payoff_timing": b.payoff_timing,
                    "tension_level": b.tension_level,
                    "priority": b.priority,
                    "reference_example": b.reference_example
                }
                for b in analysis.story_beats
            ],
            "pacing_analysis": analysis.pacing_analysis,
            "turning_points": analysis.turning_points,
            "warnings": analysis.warnings,
            "recommendations": analysis.recommendations
        }
        
        import json
        from pathlib import Path
        Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
