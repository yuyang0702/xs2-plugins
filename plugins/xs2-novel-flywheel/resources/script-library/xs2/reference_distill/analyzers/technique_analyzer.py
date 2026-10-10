"""Writing technique analysis module for reference novels.

Extracts dialogue techniques, scene construction, and descriptive patterns.
"""
import json
from typing import Dict, List, Any


def analyze_writing_techniques(candidates: List[Dict], source_metadata: Dict,
                               dna_profile: Dict = None) -> Dict[str, Any]:
    """Extract writing technique patterns from candidates and DNA profile.
    
    Args:
        candidates: List of candidate mechanisms from candidates.json
        source_metadata: Metadata from learning/dna/metadata.json
        dna_profile: Optional DNA profile with language and style analysis
        
    Returns:
        Dictionary with technique analysis organized by dimensions
    """
    
    # Extract dialogue techniques
    dialogue_techniques = [c for c in candidates
                          if c.get('layer') == 'dialogue'
                          or '对话' in c.get('mechanism', '')
                          or 'dialogue' in c.get('mechanism', '').lower()]
    
    # Extract scene construction techniques
    scene_techniques = [c for c in candidates
                       if any(kw in c.get('mechanism', '')
                             for kw in ['场景', '环境', '氛围'])
                       or any(kw in c.get('mechanism', '').lower()
                             for kw in ['scene', 'setting', 'atmosphere'])]
    
    # Extract descriptive techniques
    descriptive_techniques = [c for c in candidates
                             if c.get('layer') == 'imagery'
                             or any(kw in c.get('mechanism', '')
                                   for kw in ['描写', '细节', '感官'])
                             or any(kw in c.get('mechanism', '').lower()
                                   for kw in ['description', 'detail', 'sensory', 'imagery'])]
    
    # Extract pacing techniques
    pacing_techniques = [c for c in candidates
                        if any(kw in c.get('mechanism', '')
                              for kw in ['节奏', '推进', '张弛'])
                        or 'pacing' in c.get('mechanism', '').lower()]
    
    # Extract language patterns from DNA profile
    language_analysis = {}
    if dna_profile:
        language_analysis = _extract_language_patterns(dna_profile)
    
    # Analyze dialogue construction
    dialogue_analysis = _analyze_dialogue_construction(dialogue_techniques)
    
    # Analyze scene setting
    scene_analysis = _analyze_scene_construction(scene_techniques)
    
    # Analyze descriptive style
    descriptive_analysis = _analyze_descriptive_style(descriptive_techniques, language_analysis)
    
    result = {
        "schema": "xs2.reference.technique_analysis.v1",
        "source": source_metadata.get("source", {}),
        "technique_dimensions": {
            "dialogue_craft": {
                "patterns": [_extract_pattern(d) for d in dialogue_techniques[:12]],
                "count": len(dialogue_techniques),
                "construction_analysis": dialogue_analysis,
                "transferable_insights": _generate_dialogue_insights(dialogue_techniques)
            },
            "scene_construction": {
                "patterns": [_extract_pattern(s) for s in scene_techniques[:10]],
                "count": len(scene_techniques),
                "construction_analysis": scene_analysis,
                "transferable_insights": _generate_scene_insights(scene_techniques)
            },
            "descriptive_technique": {
                "patterns": [_extract_pattern(d) for d in descriptive_techniques[:10]],
                "count": len(descriptive_techniques),
                "style_analysis": descriptive_analysis,
                "transferable_insights": _generate_descriptive_insights(descriptive_techniques)
            },
            "pacing_control": {
                "patterns": [_extract_pattern(p) for p in pacing_techniques[:8]],
                "count": len(pacing_techniques),
                "transferable_insights": _generate_pacing_insights(pacing_techniques)
            },
            "language_patterns": language_analysis
        },
        "application_notes": [
            "写作技法分析提取的是技巧模式，不是具体句子",
            "应用时必须用本书独特的语言表达，禁止复制参考作品原句",
            "对话技巧需要适配本书人物性格和场景",
            "场景描写需要服务本书情节，不要为了技巧而技巧"
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
        "confidence": candidate.get("confidence", "medium")
    }


def _extract_language_patterns(dna_profile: Dict) -> Dict:
    """Extract language patterns from DNA profile."""
    stats = dna_profile.get('statistics', {})
    docs = dna_profile.get('documents', {})
    
    # Extract key statistics
    sentence_stats = {
        "mean_length": stats.get('mean_sentence_chars', 0),
        "short_ratio": stats.get('short_sentence_ratio', 0),
        "long_ratio": stats.get('long_sentence_ratio', 0)
    }
    
    # Extract punctuation patterns
    punct_counts = stats.get('punctuation_counts', {})
    
    # Check for specific language document
    language_doc = docs.get('语言DNA.md', '')
    
    patterns = {
        "sentence_structure": sentence_stats,
        "punctuation_usage": punct_counts,
        "has_language_analysis": bool(language_doc),
        "notes": "语言模式来自统计分析和DNA文档"
    }
    
    return patterns


def _analyze_dialogue_construction(techniques: List[Dict]) -> Dict:
    """Analyze dialogue construction patterns."""
    if not techniques:
        return {"type": "insufficient_data", "notes": "对话技法样本不足"}
    
    features = []
    
    # Check for subtext
    has_subtext = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['潜台词', '言外之意', '暗示'])
    if has_subtext:
        features.append("使用对话潜台词")
    
    # Check for interruption/overlap
    has_interruption = any(kw in t.get('mechanism', '')
                          for t in techniques
                          for kw in ['打断', '抢话', '重叠'])
    if has_interruption:
        features.append("使用对话打断/重叠")
    
    # Check for action beats
    has_beats = any(kw in t.get('mechanism', '')
                   for t in techniques
                   for kw in ['动作', '表情', '行为'])
    if has_beats:
        features.append("对话配合动作描写")
    
    # Check for silence/pause
    has_silence = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['沉默', '停顿', '无言'])
    if has_silence:
        features.append("使用沉默/停顿")
    
    # Check for voice differentiation
    has_voice = any(kw in t.get('mechanism', '')
                   for t in techniques
                   for kw in ['声线', '语气', '说话方式'])
    if has_voice:
        features.append("角色声线差异化")
    
    return {
        "detected_features": features if features else ["对话特征需要进一步审阅"],
        "pattern_count": len(techniques)
    }


def _analyze_scene_construction(techniques: List[Dict]) -> Dict:
    """Analyze scene construction patterns."""
    if not techniques:
        return {"type": "insufficient_data", "notes": "场景技法样本不足"}
    
    features = []
    
    # Check for sensory details
    has_sensory = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['视觉', '听觉', '嗅觉', '触觉', '味觉', '感官'])
    if has_sensory:
        features.append("多感官细节构建")
    
    # Check for atmosphere
    has_atmosphere = any(kw in t.get('mechanism', '')
                        for t in techniques
                        for kw in ['氛围', '气氛', '意境'])
    if has_atmosphere:
        features.append("注重氛围营造")
    
    # Check for setting as character
    has_active_setting = any(kw in t.get('mechanism', '')
                            for t in techniques
                            for kw in ['环境影响', '场景作用', '空间塑造'])
    if has_active_setting:
        features.append("环境主动影响情节")
    
    # Check for selective detail
    has_selective = any(kw in t.get('mechanism', '')
                       for t in techniques
                       for kw in ['选择性', '关键', '聚焦'])
    if has_selective:
        features.append("选择性细节描写")
    
    return {
        "detected_features": features if features else ["场景特征需要进一步审阅"],
        "pattern_count": len(techniques)
    }


def _analyze_descriptive_style(techniques: List[Dict], 
                               language_analysis: Dict) -> Dict:
    """Analyze descriptive style patterns."""
    if not techniques:
        return {"type": "insufficient_data", "notes": "描写技法样本不足"}
    
    features = []
    
    # Check for show vs tell
    has_show = any(kw in t.get('mechanism', '')
                  for t in techniques
                  for kw in ['展示', '呈现', 'show'])
    if has_show:
        features.append("倾向展示而非告知")
    
    # Check for metaphor/simile
    has_figurative = any(kw in t.get('mechanism', '')
                        for t in techniques
                        for kw in ['比喻', '隐喻', '象征', 'metaphor', 'simile'])
    if has_figurative:
        features.append("使用比喻/象征")
    
    # Check for concrete imagery
    has_concrete = any(kw in t.get('mechanism', '')
                      for t in techniques
                      for kw in ['具体', '实体', '意象'])
    if has_concrete:
        features.append("使用具体意象")
    
    # Check for economy
    has_economy = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['精简', '凝练', '简洁'])
    if has_economy:
        features.append("描写简洁凝练")
    
    # Incorporate language stats if available
    if language_analysis and language_analysis.get('sentence_structure'):
        sent_stats = language_analysis['sentence_structure']
        if sent_stats['short_ratio'] > 0.4:
            features.append("偏好短句")
        elif sent_stats['long_ratio'] > 0.3:
            features.append("使用较多长句")
    
    return {
        "detected_features": features if features else ["描写特征需要进一步审阅"],
        "pattern_count": len(techniques)
    }


def _generate_dialogue_insights(techniques: List[Dict]) -> List[str]:
    """Generate transferable insights from dialogue techniques."""
    insights = []
    
    if not techniques:
        insights.append("对话技法样本不足")
        return insights
    
    insights.append("参考作品注重对话功能性，建议对话推进情节或揭示人物")
    
    # Check for naturalness
    has_natural = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['自然', '真实', '生活化'])
    if has_natural:
        insights.append("参考作品追求对话自然感，避免过度书面化")
    
    # Check for conflict in dialogue
    has_conflict = any(kw in t.get('mechanism', '')
                      for t in techniques
                      for kw in ['冲突', '对立', '张力'])
    if has_conflict:
        insights.append("参考作品在对话中制造张力")
    
    return insights


def _generate_scene_insights(techniques: List[Dict]) -> List[str]:
    """Generate transferable insights from scene techniques."""
    insights = []
    
    if not techniques:
        insights.append("场景技法样本不足")
        return insights
    
    insights.append("参考作品注重场景构建，建议通过环境传递情绪")
    
    # Check for purposeful setting
    has_purpose = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['服务', '支撑', '衬托'])
    if has_purpose:
        insights.append("参考作品场景服务情节，不做无关描写")
    
    return insights


def _generate_descriptive_insights(techniques: List[Dict]) -> List[str]:
    """Generate transferable insights from descriptive techniques."""
    insights = []
    
    if not techniques:
        insights.append("描写技法样本不足")
        return insights
    
    insights.append("参考作品注重描写经济性，建议选择关键细节")
    
    # Check for sensory focus
    has_sensory = any(kw in t.get('mechanism', '')
                     for t in techniques
                     for kw in ['感官', '五感'])
    if has_sensory:
        insights.append("参考作品调动多种感官，增强代入感")
    
    return insights


def _generate_pacing_insights(techniques: List[Dict]) -> List[str]:
    """Generate transferable insights from pacing techniques."""
    insights = []
    
    if not techniques:
        insights.append("节奏控制样本不足")
        return insights
    
    insights.append("参考作品注重节奏变化，建议交替紧张与舒缓")
    
    # Check for acceleration
    has_acceleration = any(kw in t.get('mechanism', '')
                          for t in techniques
                          for kw in ['加速', '紧凑', '急促'])
    if has_acceleration:
        insights.append("参考作品在关键时刻加速叙事节奏")
    
    # Check for deceleration
    has_deceleration = any(kw in t.get('mechanism', '')
                          for t in techniques
                          for kw in ['放缓', '舒展', '延展'])
    if has_deceleration:
        insights.append("参考作品在情感时刻放缓节奏")
    
    return insights
