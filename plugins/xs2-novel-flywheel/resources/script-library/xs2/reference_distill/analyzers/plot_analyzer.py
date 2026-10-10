"""Plot analysis module for reference novels.

Extracts plot structure, foreshadowing, pacing, and reversals from reference novels.
"""
import json
from typing import Dict, List, Any


def analyze_plot_structure(candidates: List[Dict], source_metadata: Dict) -> Dict[str, Any]:
    """Extract plot-level patterns from candidates.
    
    This function organizes conflict patterns, foreshadowing chains, and pacing
    observations from the existing candidates.json data.
    
    Args:
        candidates: List of candidate mechanisms from candidates.json
        source_metadata: Metadata from learning/dna/metadata.json
        
    Returns:
        Dictionary with plot analysis organized by dimensions
    """
    
    # Extract conflict patterns from candidates
    conflict_mechanisms = [c for c in candidates if 'conflict' in c.get('mechanism', '').lower() 
                          or c.get('layer') == 'conflict']
    
    # Extract foreshadowing patterns
    foreshadowing = [c for c in candidates if '伏笔' in c.get('mechanism', '') 
                    or '铺垫' in c.get('mechanism', '')
                    or 'foreshadow' in c.get('mechanism', '').lower()]
    
    # Extract pacing observations
    pacing = [c for c in candidates if '节奏' in c.get('mechanism', '') 
             or '推进' in c.get('mechanism', '')
             or 'pacing' in c.get('mechanism', '').lower()]
    
    # Extract reversal/twist patterns
    reversals = [c for c in candidates if '反转' in c.get('mechanism', '') 
                or '转折' in c.get('mechanism', '')
                or 'twist' in c.get('mechanism', '').lower()
                or 'reversal' in c.get('mechanism', '').lower()]
    
    # Organize by story arc position
    arc_analysis = _analyze_story_arc(candidates, source_metadata)
    
    # Analyze tension escalation
    tension_patterns = _analyze_tension(conflict_mechanisms)
    
    result = {
        "schema": "xs2.reference.plot_analysis.v1",
        "source": source_metadata.get("source", {}),
        "plot_dimensions": {
            "conflict_escalation": {
                "patterns": [_extract_pattern(c) for c in conflict_mechanisms[:15]],
                "count": len(conflict_mechanisms),
                "transferable_insights": _generate_conflict_insights(conflict_mechanisms)
            },
            "foreshadowing": {
                "patterns": [_extract_pattern(f) for f in foreshadowing[:12]],
                "count": len(foreshadowing),
                "setup_payoff_distance": _analyze_setup_payoff(foreshadowing),
                "transferable_insights": _generate_foreshadowing_insights(foreshadowing)
            },
            "pacing": {
                "patterns": [_extract_pattern(p) for p in pacing[:10]],
                "count": len(pacing),
                "rhythm_analysis": _analyze_rhythm(pacing, source_metadata),
                "transferable_insights": _generate_pacing_insights(pacing)
            },
            "reversals": {
                "patterns": [_extract_pattern(r) for r in reversals[:8]],
                "count": len(reversals),
                "twist_mechanics": _analyze_twist_mechanics(reversals),
                "transferable_insights": _generate_reversal_insights(reversals)
            }
        },
        "story_arc": arc_analysis,
        "tension_curve": tension_patterns,
        "application_notes": [
            "剧情分析提取的是抽象设计模式，不是具体情节",
            "应用时需要根据本书人物、世界观和已有伏笔重新设计",
            "冲突升级模式需要匹配本书的篇幅和节奏",
            "不要复制参考作品的具体事件或台词"
        ]
    }
    
    return result


def _extract_pattern(candidate: Dict) -> Dict:
    """Extract transferable pattern from a candidate mechanism."""
    return {
        "mechanism": candidate.get("mechanism", ""),
        "transfer_guidance": candidate.get("transfer_guidance", ""),
        "constraints": candidate.get("constraints", []),
        "application_scope": candidate.get("application_scope", ["general"]),
        "confidence": candidate.get("confidence", "medium"),
        "risk_flags": candidate.get("risk_flags", [])
    }


def _analyze_story_arc(candidates: List[Dict], metadata: Dict) -> Dict:
    """Analyze story arc structure."""
    source_mode = metadata.get("source_mode", "auto")
    units = metadata.get("source_units", [])
    
    # Detect arc structure based on source mode
    if source_mode == "serial_chapters" and len(units) >= 3:
        return {
            "type": "multi_chapter_serial",
            "unit_count": len(units),
            "arc_notes": "长篇连载样本，分析基于部分章节，无法推断完整结局弧线"
        }
    elif source_mode == "short_full":
        return {
            "type": "complete_short_work",
            "arc_notes": "完整短篇或中篇，包含完整起承转合"
        }
    else:
        return {
            "type": "unknown",
            "arc_notes": "样本结构未知，谨慎应用分析结果"
        }


def _analyze_tension(conflicts: List[Dict]) -> Dict:
    """Analyze tension escalation patterns."""
    if not conflicts:
        return {"pattern": "insufficient_data", "notes": "冲突样本不足"}
    
    # Simple heuristic: count mechanisms with escalation keywords
    escalation_count = sum(1 for c in conflicts 
                          if any(kw in c.get('mechanism', '') 
                                for kw in ['升级', '加剧', '恶化', 'escalate']))
    
    return {
        "escalation_ratio": round(escalation_count / len(conflicts), 2) if conflicts else 0,
        "total_conflicts": len(conflicts),
        "notes": "张力曲线基于冲突机制的升级关键词比例"
    }


def _analyze_setup_payoff(foreshadowing: List[Dict]) -> Dict:
    """Analyze setup-payoff distance in foreshadowing."""
    if not foreshadowing:
        return {"average_distance": None, "notes": "无伏笔数据"}
    
    # This is a placeholder - real implementation would track actual distances
    return {
        "notes": "伏笔回收距离需要从完整文本中标注提取，当前为候选机制统计",
        "pattern_count": len(foreshadowing)
    }


def _analyze_rhythm(pacing: List[Dict], metadata: Dict) -> Dict:
    """Analyze pacing rhythm."""
    stats = metadata.get("statistics", {})
    
    return {
        "mean_sentence_length": stats.get("mean_sentence_chars", 0),
        "short_sentence_ratio": stats.get("short_sentence_ratio", 0),
        "long_sentence_ratio": stats.get("long_sentence_ratio", 0),
        "pacing_mechanism_count": len(pacing),
        "notes": "节奏分析结合句长统计和节奏机制观察"
    }


def _analyze_twist_mechanics(reversals: List[Dict]) -> List[Dict]:
    """Analyze how reversals/twists are constructed."""
    return [
        {
            "mechanism": r.get("mechanism", ""),
            "setup_requirements": r.get("constraints", []),
            "application_scope": r.get("application_scope", ["general"])
        }
        for r in reversals[:5]
    ]


def _generate_conflict_insights(conflicts: List[Dict]) -> List[str]:
    """Generate transferable insights from conflict patterns."""
    insights = []
    
    if not conflicts:
        insights.append("样本中冲突机制不足，建议补充更多参考")
        return insights
    
    # Check for escalation patterns
    has_escalation = any('升级' in c.get('mechanism', '') or 'escalate' in c.get('mechanism', '').lower() 
                         for c in conflicts)
    if has_escalation:
        insights.append("参考作品善用冲突升级，每次解决引发新问题")
    
    # Check for cost patterns
    has_cost = any('代价' in c.get('mechanism', '') or 'cost' in c.get('mechanism', '').lower()
                   for c in conflicts)
    if has_cost:
        insights.append("参考作品重视行动代价，避免无成本解决")
    
    # Check for multi-threading
    has_threading = any('交织' in c.get('mechanism', '') or '并行' in c.get('mechanism', '')
                        for c in conflicts)
    if has_threading:
        insights.append("参考作品使用多线冲突交织，增强复杂度")
    
    if len(insights) == 0:
        insights.append("参考作品的冲突设计风格需要进一步审阅机制列表")
    
    return insights


def _generate_foreshadowing_insights(foreshadowing: List[Dict]) -> List[str]:
    """Generate transferable insights from foreshadowing patterns."""
    insights = []
    
    if not foreshadowing:
        insights.append("样本中伏笔机制不足")
        return insights
    
    insights.append("参考作品使用伏笔增强因果链，建议提前埋设关键信息")
    
    # Check layering
    if len(foreshadowing) >= 5:
        insights.append("参考作品伏笔密度较高，可能采用多层铺垫")
    
    return insights


def _generate_pacing_insights(pacing: List[Dict]) -> List[str]:
    """Generate transferable insights from pacing patterns."""
    insights = []
    
    if not pacing:
        insights.append("样本中节奏控制机制不足")
        return insights
    
    insights.append("参考作品注重节奏控制，建议平衡紧张与舒缓场景")
    
    return insights


def _generate_reversal_insights(reversals: List[Dict]) -> List[str]:
    """Generate transferable insights from reversal patterns."""
    insights = []
    
    if not reversals:
        insights.append("样本中反转机制不足")
        return insights
    
    insights.append("参考作品使用反转增强戏剧张力，需要前置误导性铺垫")
    
    if len(reversals) >= 3:
        insights.append("参考作品反转频率较高，注意避免过度使用导致读者疲劳")
    
    return insights
