"""Conflict analysis module for reference novels.

Extracts conflict escalation patterns, tension management, and resolution mechanics.
"""
import json
from typing import Dict, List, Any


def analyze_conflict_mechanics(candidates: List[Dict], source_metadata: Dict,
                               dna_profile: Dict = None) -> Dict[str, Any]:
    """Extract conflict-level patterns from candidates and DNA profile.
    
    Args:
        candidates: List of candidate mechanisms from candidates.json
        source_metadata: Metadata from learning/dna/metadata.json
        dna_profile: Optional DNA profile with conflict patterns
        
    Returns:
        Dictionary with conflict analysis organized by dimensions
    """
    
    # Extract conflict-related mechanisms
    conflict_mechanisms = [c for c in candidates
                          if 'conflict' in c.get('mechanism', '').lower()
                          or '冲突' in c.get('mechanism', '')]
    
    # Extract escalation patterns
    escalation_patterns = [c for c in candidates
                          if any(kw in c.get('mechanism', '')
                                for kw in ['升级', '加剧', '恶化', '激化'])
                          or 'escalat' in c.get('mechanism', '').lower()]
    
    # Extract resolution patterns
    resolution_patterns = [c for c in candidates
                          if any(kw in c.get('mechanism', '')
                                for kw in ['解决', '化解', '收束', '回收'])
                          or 'resolut' in c.get('mechanism', '').lower()]
    
    # Extract cost/consequence patterns
    cost_patterns = [c for c in candidates
                    if any(kw in c.get('mechanism', '')
                          for kw in ['代价', '后果', '牺牲', '损失'])
                    or any(kw in c.get('mechanism', '').lower()
                          for kw in ['cost', 'consequence', 'sacrifice'])]
    
    # Analyze conflict structure from DNA profile
    conflict_chains = []
    if dna_profile:
        conflict_chains = dna_profile.get('conflict_patterns', [])
    
    # Analyze escalation ladder
    escalation_analysis = _analyze_escalation_ladder(escalation_patterns, conflict_chains)
    
    # Analyze resolution mechanics
    resolution_analysis = _analyze_resolution_mechanics(resolution_patterns, conflict_chains)
    
    # Analyze cost integration
    cost_analysis = _analyze_cost_integration(cost_patterns)
    
    result = {
        "schema": "xs2.reference.conflict_analysis.v1",
        "source": source_metadata.get("source", {}),
        "conflict_dimensions": {
            "escalation_paths": {
                "patterns": [_extract_pattern(e) for e in escalation_patterns[:12]],
                "count": len(escalation_patterns),
                "escalation_ladder": escalation_analysis,
                "transferable_insights": _generate_escalation_insights(escalation_patterns)
            },
            "resolution_mechanics": {
                "patterns": [_extract_pattern(r) for r in resolution_patterns[:10]],
                "count": len(resolution_patterns),
                "resolution_structure": resolution_analysis,
                "transferable_insights": _generate_resolution_insights(resolution_patterns)
            },
            "cost_and_stakes": {
                "patterns": [_extract_pattern(c) for c in cost_patterns[:10]],
                "count": len(cost_patterns),
                "cost_integration": cost_analysis,
                "transferable_insights": _generate_cost_insights(cost_patterns)
            },
            "conflict_chains": {
                "chains": [_extract_conflict_chain(chain) for chain in conflict_chains[:8]],
                "count": len(conflict_chains),
                "transferable_insights": _generate_chain_insights(conflict_chains)
            }
        },
        "application_notes": [
            "冲突分析提取的是冲突推进机制，不是具体冲突内容",
            "应用时必须根据本书世界观和人物重新设计冲突",
            "升级路径需要匹配本书篇幅，不要盲目加速",
            "代价必须在故事中真实体现，不能流于口头"
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


def _extract_conflict_chain(chain: Dict) -> Dict:
    """Extract transferable pattern from a conflict chain."""
    return {
        "name": chain.get("name", ""),
        "goal": chain.get("goal", ""),
        "foreshadowing": chain.get("foreshadowing", ""),
        "obstacle": chain.get("obstacle", ""),
        "cost": chain.get("cost", ""),
        "causal_link": chain.get("causal_link", ""),
        "payoff": chain.get("payoff", ""),
        "application_scope": chain.get("application_scope", "general"),
        "confidence": chain.get("confidence", "medium")
    }


def _analyze_escalation_ladder(patterns: List[Dict], chains: List[Dict]) -> Dict:
    """Analyze conflict escalation structure."""
    if not patterns and not chains:
        return {"type": "insufficient_data", "notes": "冲突升级样本不足"}
    
    # Analyze escalation stages
    stages = []
    
    # Check for progressive escalation
    has_progressive = any(kw in p.get('mechanism', '')
                         for p in patterns
                         for kw in ['逐步', '渐进', '层层', 'progressive', 'gradual'])
    if has_progressive:
        stages.append("渐进式升级")
    
    # Check for sudden escalation
    has_sudden = any(kw in p.get('mechanism', '')
                    for p in patterns
                    for kw in ['突然', '骤然', '急转', 'sudden', 'abrupt'])
    if has_sudden:
        stages.append("突发式升级")
    
    # Check for multi-threading
    has_threading = any(kw in p.get('mechanism', '')
                       for p in patterns
                       for kw in ['多线', '并行', '交织', 'multi-thread', 'parallel'])
    if has_threading:
        stages.append("多线交织升级")
    
    # Analyze chain escalation if available
    chain_escalation = []
    for chain in chains[:3]:
        if chain.get('next_obstacle'):
            chain_escalation.append({
                "name": chain.get('name', ''),
                "has_next_obstacle": True,
                "causal_link": chain.get('causal_link', '')
            })
    
    return {
        "detected_stages": stages if stages else ["升级特征需要进一步审阅"],
        "pattern_count": len(patterns),
        "chain_escalation_examples": chain_escalation[:3]
    }


def _analyze_resolution_mechanics(patterns: List[Dict], chains: List[Dict]) -> Dict:
    """Analyze conflict resolution structure."""
    if not patterns and not chains:
        return {"type": "insufficient_data", "notes": "冲突解决样本不足"}
    
    mechanics = []
    
    # Check for earned resolution
    has_earned = any(kw in p.get('mechanism', '')
                    for p in patterns
                    for kw in ['铺垫', '积累', '准备', 'earned', 'setup'])
    if has_earned:
        mechanics.append("解决需要前置铺垫")
    
    # Check for incomplete resolution
    has_incomplete = any(kw in p.get('mechanism', '')
                        for p in patterns
                        for kw in ['遗留', '未完', '新问题', 'incomplete', 'new problem'])
    if has_incomplete:
        mechanics.append("解决引发新问题")
    
    # Check for collaborative resolution
    has_collaborative = any(kw in p.get('mechanism', '')
                           for p in patterns
                           for kw in ['合作', '协同', '联手', 'collaborative', 'teamwork'])
    if has_collaborative:
        mechanics.append("多人协作解决")
    
    # Analyze payoff from chains
    chain_payoffs = []
    for chain in chains[:3]:
        if chain.get('payoff'):
            chain_payoffs.append({
                "name": chain.get('name', ''),
                "payoff": chain.get('payoff', ''),
                "cost": chain.get('cost', '')
            })
    
    return {
        "detected_mechanics": mechanics if mechanics else ["解决机制需要进一步审阅"],
        "pattern_count": len(patterns),
        "chain_payoff_examples": chain_payoffs[:3]
    }


def _analyze_cost_integration(patterns: List[Dict]) -> Dict:
    """Analyze how costs and stakes are integrated."""
    if not patterns:
        return {"integration": "insufficient_data", "notes": "代价样本不足"}
    
    integration_features = []
    
    # Check for emotional cost
    has_emotional = any(kw in p.get('mechanism', '')
                       for p in patterns
                       for kw in ['情感', '心理', '关系', 'emotional', 'psychological', 'relationship'])
    if has_emotional:
        integration_features.append("包含情感/关系代价")
    
    # Check for physical cost
    has_physical = any(kw in p.get('mechanism', '')
                      for p in patterns
                      for kw in ['受伤', '损失', '牺牲', 'injury', 'loss', 'physical'])
    if has_physical:
        integration_features.append("包含实体损失")
    
    # Check for opportunity cost
    has_opportunity = any(kw in p.get('mechanism', '')
                         for p in patterns
                         for kw in ['放弃', '错过', '选择', 'give up', 'miss', 'trade-off'])
    if has_opportunity:
        integration_features.append("包含机会成本")
    
    # Check for irreversible consequences
    has_irreversible = any(kw in p.get('mechanism', '')
                          for p in patterns
                          for kw in ['不可逆', '永久', '无法挽回', 'irreversible', 'permanent'])
    if has_irreversible:
        integration_features.append("包含不可逆后果")
    
    return {
        "detected_features": integration_features if integration_features else ["代价类型需要进一步审阅"],
        "pattern_count": len(patterns)
    }


def _generate_escalation_insights(patterns: List[Dict]) -> List[str]:
    """Generate transferable insights from escalation patterns."""
    insights = []
    
    if not patterns:
        insights.append("冲突升级样本不足")
        return insights
    
    insights.append("参考作品注重冲突升级，建议每次解决引发新挑战")
    
    # Check for stakes escalation
    has_stakes = any('赌注' in p.get('mechanism', '') or 'stake' in p.get('mechanism', '').lower()
                    for p in patterns)
    if has_stakes:
        insights.append("参考作品提升赌注，增强读者投入")
    
    # Check for multi-front escalation
    has_multifront = any(kw in p.get('mechanism', '')
                        for p in patterns
                        for kw in ['多方', '多条', '多重'])
    if has_multifront:
        insights.append("参考作品使用多线并发升级，增强压迫感")
    
    return insights


def _generate_resolution_insights(patterns: List[Dict]) -> List[str]:
    """Generate transferable insights from resolution patterns."""
    insights = []
    
    if not patterns:
        insights.append("冲突解决样本不足")
        return insights
    
    insights.append("参考作品注重解决的因果链，避免突兀化解")
    
    # Check for cost in resolution
    has_cost = any('代价' in p.get('mechanism', '') or 'cost' in p.get('mechanism', '').lower()
                  for p in patterns)
    if has_cost:
        insights.append("参考作品解决伴随代价，避免无成本胜利")
    
    return insights


def _generate_cost_insights(patterns: List[Dict]) -> List[str]:
    """Generate transferable insights from cost patterns."""
    insights = []
    
    if not patterns:
        insights.append("代价样本不足")
        return insights
    
    insights.append("参考作品重视行动代价，建议明确展示后果")
    
    # Check for lasting impact
    has_lasting = any(kw in p.get('mechanism', '')
                     for p in patterns
                     for kw in ['持续', '影响', '改变'])
    if has_lasting:
        insights.append("参考作品代价具有持续影响，不是一次性事件")
    
    return insights


def _generate_chain_insights(chains: List[Dict]) -> List[str]:
    """Generate transferable insights from conflict chains."""
    insights = []
    
    if not chains:
        insights.append("冲突链样本不足")
        return insights
    
    # Check for causal links
    has_causal = any(chain.get('causal_link') for chain in chains)
    if has_causal:
        insights.append("参考作品冲突链具有因果联系，避免断裂")
    
    # Check for foreshadowing
    has_foreshadowing = any(chain.get('foreshadowing') for chain in chains)
    if has_foreshadowing:
        insights.append("参考作品提前埋设冲突伏笔")
    
    # Check for payoff
    has_payoff = any(chain.get('payoff') for chain in chains)
    if has_payoff:
        insights.append("参考作品冲突得到明确回收")
    
    if len(insights) == 0:
        insights.append("冲突链特征需要进一步审阅")
    
    return insights
