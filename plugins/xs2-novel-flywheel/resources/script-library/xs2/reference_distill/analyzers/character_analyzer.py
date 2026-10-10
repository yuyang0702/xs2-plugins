"""Character analysis module for reference novels.

Extracts character arc patterns, relationship dynamics, and character voice.
"""
import json
from typing import Dict, List, Any
import re


def analyze_character_patterns(candidates: List[Dict], source_metadata: Dict, 
                               dna_profile: Dict = None) -> Dict[str, Any]:
    """Extract character-level patterns from candidates and DNA profile.
    
    Args:
        candidates: List of candidate mechanisms from candidates.json
        source_metadata: Metadata from learning/dna/metadata.json
        dna_profile: Optional DNA profile with character analysis
        
    Returns:
        Dictionary with character analysis organized by dimensions
    """
    
    # Extract character-related mechanisms
    character_mechanisms = [c for c in candidates 
                           if c.get('layer') == 'character' 
                           or '人物' in c.get('mechanism', '')
                           or '角色' in c.get('mechanism', '')
                           or 'character' in c.get('mechanism', '').lower()]
    
    # Extract dialogue patterns
    dialogue_patterns = [c for c in candidates 
                        if c.get('layer') == 'dialogue'
                        or '对话' in c.get('mechanism', '')
                        or 'dialogue' in c.get('mechanism', '').lower()]
    
    # Extract relationship patterns
    relationship_patterns = [c for c in candidates
                            if '关系' in c.get('mechanism', '')
                            or '互动' in c.get('mechanism', '')
                            or 'relationship' in c.get('mechanism', '').lower()]
    
    # Analyze character arcs
    arc_analysis = _analyze_character_arcs(character_mechanisms)
    
    # Analyze motivations and conflicts
    motivation_analysis = _analyze_motivations(character_mechanisms)
    
    # Analyze voice distinctiveness
    voice_analysis = _analyze_character_voices(dialogue_patterns, dna_profile)
    
    result = {
        "schema": "xs2.reference.character_analysis.v1",
        "source": source_metadata.get("source", {}),
        "character_dimensions": {
            "character_arcs": {
                "patterns": [_extract_pattern(c) for c in character_mechanisms[:12]],
                "count": len(character_mechanisms),
                "arc_structure": arc_analysis,
                "transferable_insights": _generate_arc_insights(character_mechanisms)
            },
            "motivations_and_goals": {
                "patterns": motivation_analysis["patterns"][:10],
                "internal_external_balance": motivation_analysis["balance"],
                "transferable_insights": motivation_analysis["insights"]
            },
            "relationships": {
                "patterns": [_extract_pattern(r) for r in relationship_patterns[:10]],
                "count": len(relationship_patterns),
                "dynamics": _analyze_relationship_dynamics(relationship_patterns),
                "transferable_insights": _generate_relationship_insights(relationship_patterns)
            },
            "character_voice": {
                "dialogue_patterns": [_extract_pattern(d) for d in dialogue_patterns[:10]],
                "count": len(dialogue_patterns),
                "voice_distinctiveness": voice_analysis,
                "transferable_insights": _generate_voice_insights(dialogue_patterns)
            }
        },
        "application_notes": [
            "角色分析提取的是人物塑造技巧，不是具体人物",
            "应用时必须创建本书独特的角色，禁止复制参考作品人物",
            "人物弧光需要根据本书篇幅和情节重新设计",
            "对话风格可借鉴技巧，但台词必须符合本书人物性格"
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


def _analyze_character_arcs(mechanisms: List[Dict]) -> Dict:
    """Analyze character arc patterns."""
    if not mechanisms:
        return {"type": "insufficient_data", "notes": "人物机制样本不足"}
    
    # Detect transformation patterns
    has_transformation = any(kw in m.get('mechanism', '') 
                            for m in mechanisms 
                            for kw in ['成长', '转变', '蜕变', 'transformation', 'growth'])
    
    # Detect internal conflict
    has_internal_conflict = any(kw in m.get('mechanism', '')
                               for m in mechanisms
                               for kw in ['内心', '矛盾', '挣扎', 'internal', 'conflict'])
    
    # Detect choice and consequence
    has_choices = any(kw in m.get('mechanism', '')
                     for m in mechanisms
                     for kw in ['选择', '决策', '代价', 'choice', 'decision', 'consequence'])
    
    arc_features = []
    if has_transformation:
        arc_features.append("包含人物转变弧光")
    if has_internal_conflict:
        arc_features.append("强调内心冲突")
    if has_choices:
        arc_features.append("重视选择与后果")
    
    return {
        "detected_features": arc_features if arc_features else ["未检测到明显弧光特征"],
        "mechanism_count": len(mechanisms)
    }


def _analyze_motivations(mechanisms: List[Dict]) -> Dict:
    """Analyze character motivation patterns."""
    if not mechanisms:
        return {
            "patterns": [],
            "balance": {"internal": 0, "external": 0},
            "insights": ["人物动机样本不足"]
        }
    
    # Classify motivations
    internal_keywords = ['欲望', '恐惧', '信念', '价值观', 'desire', 'fear', 'belief']
    external_keywords = ['目标', '障碍', '对抗', 'goal', 'obstacle', 'opposition']
    
    internal_count = sum(1 for m in mechanisms 
                        if any(kw in m.get('mechanism', '') for kw in internal_keywords))
    external_count = sum(1 for m in mechanisms
                        if any(kw in m.get('mechanism', '') for kw in external_keywords))
    
    patterns = []
    for m in mechanisms[:10]:
        mech = m.get('mechanism', '')
        if any(kw in mech for kw in internal_keywords):
            motivation_type = "internal"
        elif any(kw in mech for kw in external_keywords):
            motivation_type = "external"
        else:
            motivation_type = "mixed"
        
        patterns.append({
            "mechanism": mech,
            "type": motivation_type,
            "transfer_guidance": m.get('transfer_guidance', '')
        })
    
    insights = []
    if internal_count > external_count:
        insights.append("参考作品重视内在动机，建议深挖角色心理")
    elif external_count > internal_count:
        insights.append("参考作品重视外在目标，建议设计清晰的行动线")
    else:
        insights.append("参考作品平衡内外动机")
    
    return {
        "patterns": patterns,
        "balance": {
            "internal": internal_count,
            "external": external_count
        },
        "insights": insights
    }


def _analyze_relationship_dynamics(patterns: List[Dict]) -> Dict:
    """Analyze relationship dynamic patterns."""
    if not patterns:
        return {"type": "insufficient_data", "notes": "关系样本不足"}
    
    # Detect relationship change patterns
    has_evolution = any(kw in p.get('mechanism', '')
                       for p in patterns
                       for kw in ['变化', '发展', '转折', 'evolution', 'shift'])
    
    # Detect conflict patterns
    has_conflict = any(kw in p.get('mechanism', '')
                      for p in patterns
                      for kw in ['冲突', '对立', '矛盾', 'conflict', 'tension'])
    
    # Detect support patterns
    has_support = any(kw in p.get('mechanism', '')
                     for p in patterns
                     for kw in ['合作', '支持', '联盟', 'cooperation', 'support', 'alliance'])
    
    dynamics = []
    if has_evolution:
        dynamics.append("关系随情节发展而变化")
    if has_conflict:
        dynamics.append("人物间存在冲突张力")
    if has_support:
        dynamics.append("包含合作与支持关系")
    
    return {
        "detected_dynamics": dynamics if dynamics else ["关系动态特征不明显"],
        "pattern_count": len(patterns)
    }


def _analyze_character_voices(dialogue_patterns: List[Dict], 
                              dna_profile: Dict = None) -> Dict:
    """Analyze character voice distinctiveness."""
    if not dialogue_patterns and not dna_profile:
        return {"distinctiveness": "insufficient_data", "notes": "对话样本不足"}
    
    # Extract voice features from dialogue patterns
    voice_features = []
    
    for d in dialogue_patterns:
        mech = d.get('mechanism', '')
        if '声线' in mech or 'voice' in mech.lower():
            voice_features.append("注重角色声线差异")
            break
    
    for d in dialogue_patterns:
        mech = d.get('mechanism', '')
        if '语气' in mech or 'tone' in mech.lower():
            voice_features.append("通过语气塑造性格")
            break
    
    for d in dialogue_patterns:
        mech = d.get('mechanism', '')
        if '潜台词' in mech or 'subtext' in mech.lower():
            voice_features.append("善用对话潜台词")
            break
    
    # Check DNA profile if available
    if dna_profile:
        docs = dna_profile.get('documents', {})
        char_doc = docs.get('人物写法.md', '')
        if '对话' in char_doc or '声线' in char_doc:
            voice_features.append("DNA分析包含对话风格观察")
    
    return {
        "detected_features": voice_features if voice_features else ["对话特征需要进一步审阅"],
        "pattern_count": len(dialogue_patterns)
    }


def _generate_arc_insights(mechanisms: List[Dict]) -> List[str]:
    """Generate transferable insights from character arc patterns."""
    insights = []
    
    if not mechanisms:
        insights.append("人物弧光样本不足")
        return insights
    
    # Check for growth patterns
    has_growth = any(kw in m.get('mechanism', '')
                    for m in mechanisms
                    for kw in ['成长', '转变', '蜕变'])
    if has_growth:
        insights.append("参考作品重视人物成长弧光，建议设计角色转变")
    
    # Check for internal consistency
    has_consistency = any('一致' in m.get('mechanism', '') or 'consistent' in m.get('mechanism', '').lower()
                         for m in mechanisms)
    if has_consistency:
        insights.append("参考作品保持人物行为一致性")
    
    # Check for agency
    has_agency = any(kw in m.get('mechanism', '')
                    for m in mechanisms
                    for kw in ['主动', '选择', '决策', 'agency', 'choice'])
    if has_agency:
        insights.append("参考作品赋予角色主动性，避免被动推进")
    
    if len(insights) == 0:
        insights.append("人物弧光特征需要进一步审阅机制列表")
    
    return insights


def _generate_relationship_insights(patterns: List[Dict]) -> List[str]:
    """Generate transferable insights from relationship patterns."""
    insights = []
    
    if not patterns:
        insights.append("关系样本不足")
        return insights
    
    insights.append("参考作品注重人物关系塑造，建议设计动态关系变化")
    
    # Check for complexity
    if len(patterns) >= 5:
        insights.append("参考作品关系网络较复杂，可能使用多层次互动")
    
    return insights


def _generate_voice_insights(dialogue_patterns: List[Dict]) -> List[str]:
    """Generate transferable insights from dialogue voice patterns."""
    insights = []
    
    if not dialogue_patterns:
        insights.append("对话样本不足")
        return insights
    
    insights.append("参考作品注重对话塑造，建议为每个角色设计独特声线")
    
    # Check for subtext
    has_subtext = any('潜台词' in d.get('mechanism', '') or 'subtext' in d.get('mechanism', '').lower()
                     for d in dialogue_patterns)
    if has_subtext:
        insights.append("参考作品善用对话潜台词，增强戏剧张力")
    
    return insights
