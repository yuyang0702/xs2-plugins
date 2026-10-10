"""Genre-aware technique adaptation engine.

Filters and adapts techniques based on novel genre and characteristics.
"""
import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


# Genre classification
GENRE_CATEGORIES = {
    "都市": ["都市", "现代", "重生", "系统"],
    "玄幻": ["玄幻", "修仙", "网游", "异界"],
    "历史": ["历史", "民国", "古代"],
    "悬疑": ["悬疑", "推理", "恐怖"],
    "言情": ["言情", "爱情", "婚恋"],
    "科幻": ["科幻", "未来", "末世"],
}

# Genre characteristics
GENRE_TRAITS = {
    "都市": {
        "setting": "现代城市",
        "systems": ["技能系统", "金手指"],
        "conflicts": ["职场", "感情", "家族"],
        "pacing": "快速",
        "duration": "中篇到长篇"
    },
    "玄幻": {
        "setting": "虚拟世界",
        "systems": ["修为系统", "功法", "宝物"],
        "conflicts": ["宗派", "天劫", "证道"],
        "pacing": "缓慢到快速",
        "duration": "长篇"
    },
    "悬疑": {
        "setting": "现实或虚拟",
        "systems": ["线索", "谜团"],
        "conflicts": ["解谜", "对抗"],
        "pacing": "快速",
        "duration": "中篇"
    },
}

# Compatibility mapping
TECHNIQUE_COMPATIBILITY = {
    "伏笔": {
        "都市": 0.9,      # 高兼容
        "玄幻": 0.95,     # 非常高
        "悬疑": 1.0,      # 完美兼容
    },
    "冲突升级": {
        "都市": 0.9,
        "玄幻": 0.85,
        "悬疑": 0.95,
    },
    "角色弧光": {
        "都市": 0.95,
        "玄幻": 0.8,
        "悬疑": 0.9,
    },
    "修为系统": {
        "都市": 0.3,      # 低兼容，需要改写
        "玄幻": 1.0,
        "悬疑": 0.1,
    },
    "证道大战": {
        "都市": 0.1,
        "玄幻": 0.95,
        "悬疑": 0.2,
    },
}


@dataclass
class AdaptedTechnique:
    """A technique adapted for specific genre."""
    original_id: str
    original_name: str
    category: str
    compatibility_score: float      # 0-1
    adaptation_status: str          # direct/adapt/risky/incompatible
    adapted_guidance: str           # 改写后的应用建议
    adaptation_notes: List[str]     # 改写说明
    example_for_genre: str          # 该类型的具体例子
    warnings: List[str]             # 使用警告


class GenreAdapter:
    """Genre-aware technique adaptation engine."""
    
    def __init__(self, load_fn=None):
        """Initialize adapter."""
        self.load = load_fn
    
    def identify_genre(self, novel_info: Dict) -> str:
        """Identify novel genre from info.
        
        Args:
            novel_info: Novel information including tags/keywords
            
        Returns:
            Identified genre string
        """
        keywords = novel_info.get("keywords", [])
        tags = novel_info.get("tags", [])
        description = novel_info.get("description", "").lower()
        
        # Combine all text sources
        all_text = " ".join(keywords + tags + [description])
        
        # Match against genre categories
        best_match = "未知"
        max_matches = 0
        
        for genre, patterns in GENRE_CATEGORIES.items():
            matches = sum(1 for pattern in patterns if pattern in all_text)
            if matches > max_matches:
                max_matches = matches
                best_match = genre
        
        return best_match
    
    def adapt_techniques(
        self,
        my_genre: str,
        reference_genre: str,
        techniques: List[Dict]
    ) -> List[AdaptedTechnique]:
        """Adapt techniques to target genre.
        
        Args:
            my_genre: Target novel genre
            reference_genre: Reference work genre
            techniques: Techniques to adapt
            
        Returns:
            List of adapted techniques
        """
        adapted = []
        
        for tech in techniques:
            name = tech.get("mechanism", "")
            tech_id = tech.get("candidate_id", tech.get("id", ""))
            category = tech.get("layer", tech.get("category", ""))
            
            # Determine adaptation status and score
            compat_score, status = self._calculate_compatibility(
                name, my_genre
            )
            
            # Generate adaptation guidance
            adaptation_notes = self._generate_adaptation_notes(
                name, my_genre, reference_genre, compat_score
            )
            
            adapted_guidance = self._adapt_guidance(
                tech.get("transfer_guidance", ""),
                my_genre,
                status
            )
            
            example = self._generate_example(name, my_genre)
            warnings = self._generate_warnings(name, my_genre, compat_score)
            
            adapted.append(AdaptedTechnique(
                original_id=tech_id,
                original_name=name,
                category=category,
                compatibility_score=compat_score,
                adaptation_status=status,
                adapted_guidance=adapted_guidance,
                adaptation_notes=adaptation_notes,
                example_for_genre=example,
                warnings=warnings
            ))
        
        # Filter by compatibility and sort
        result = [a for a in adapted if a.compatibility_score >= 0.3]
        result.sort(key=lambda a: a.compatibility_score, reverse=True)
        
        return result
    
    def _calculate_compatibility(
        self,
        technique_name: str,
        target_genre: str
    ) -> Tuple[float, str]:
        """Calculate compatibility score and status.
        
        Args:
            technique_name: Name of the technique
            target_genre: Target genre
            
        Returns:
            Tuple of (compatibility_score, status)
        """
        # Check explicit mapping
        for tech_type, compat_map in TECHNIQUE_COMPATIBILITY.items():
            if tech_type.lower() in technique_name.lower():
                score = compat_map.get(target_genre, 0.5)
                
                if score >= 0.9:
                    status = "direct"
                elif score >= 0.7:
                    status = "adapt"
                elif score >= 0.4:
                    status = "risky"
                else:
                    status = "incompatible"
                
                return score, status
        
        # Default: medium compatibility
        return 0.6, "adapt"
    
    def _generate_adaptation_notes(
        self,
        technique_name: str,
        target_genre: str,
        ref_genre: str,
        compat_score: float
    ) -> List[str]:
        """Generate specific adaptation notes.
        
        Args:
            technique_name: Technique name
            target_genre: Target genre
            ref_genre: Reference genre
            compat_score: Compatibility score
            
        Returns:
            List of adaptation notes
        """
        notes = []
        
        if compat_score >= 0.9:
            notes.append("可直接使用，无需改写")
        elif compat_score >= 0.7:
            notes.append(f"兼容性良好，可略微调整后使用")
            
            # Genre-specific adjustments
            if target_genre == "都市" and ref_genre == "玄幻":
                notes.append("将修仙系统替换为现代设定（技能、金手指等）")
            elif target_genre == "玄幻" and ref_genre == "都市":
                notes.append("将现代设定扩展到虚拟世界/异界背景")
            elif target_genre == "悬疑" and ref_genre == "都市":
                notes.append("加强线索的隐蔽性和谜团的复杂度")
        elif compat_score >= 0.4:
            notes.append("兼容性一般，需要较多改写")
            notes.append(f"建议参考本类型的其他参考作品")
        else:
            notes.append("基本不兼容，不建议使用")
            notes.append("如果坚持使用，需要完全重新设计")
        
        return notes
    
    def _adapt_guidance(
        self,
        original_guidance: str,
        target_genre: str,
        status: str
    ) -> str:
        """Adapt the transfer guidance for target genre.
        
        Args:
            original_guidance: Original transfer guidance
            target_genre: Target genre
            status: Adaptation status
            
        Returns:
            Adapted guidance
        """
        if status == "direct":
            return original_guidance
        elif status == "adapt":
            return f"【{target_genre}版本】{original_guidance}\n\n针对{target_genre}的调整：请根据本类型的特点修改具体表现形式，保留核心机制。"
        elif status == "risky":
            return f"【需要深度改写】{original_guidance}\n\n重要提示：此技巧与{target_genre}类型的融合度不高，使用前需要进行大量创意改写，确保符合本类型读者的期待。"
        else:
            return f"【不推荐】该技巧与{target_genre}类型不兼容。"
    
    def _generate_example(
        self,
        technique_name: str,
        target_genre: str
    ) -> str:
        """Generate a specific example for the target genre.
        
        Args:
            technique_name: Technique name
            target_genre: Target genre
            
        Returns:
            Example text
        """
        examples = {
            ("伏笔", "都市"): "在第一章提到主角有个神秘的过去，直到第50章才揭露真相",
            ("伏笔", "玄幻"): "第一章出现的普通石头，在修仙路上成为关键宝物",
            ("伏笔", "悬疑"): "第一个线索看似无关，到最后发现是破案的关键",
            ("冲突升级", "都市"): "职场竞争→股权争夺→黑势力介入→人性考验",
            ("冲突升级", "玄幻"): "同门师兄妹→宗派对立→天劫考验→证道之争",
            ("冲突升级", "悬疑"): "发现第一具尸体→谜团越来越复杂→真凶难以预测",
            ("角色弧光", "都市"): "从被动接受安排的继承人→主动掌控人生的企业家",
            ("角色弧光", "玄幻"): "从凡人少年→飞升仙人→面对真我",
            ("角色弧光", "悬疑"): "从天真警探→经历黑暗→坚守信念",
        }
        
        key = (technique_name.split("：")[-1] if "：" in technique_name else technique_name[:4], target_genre)
        return examples.get(key, f"请根据{target_genre}的特点自行设计{technique_name}的具体表现")
    
    def _generate_warnings(
        self,
        technique_name: str,
        target_genre: str,
        compat_score: float
    ) -> List[str]:
        """Generate usage warnings.
        
        Args:
            technique_name: Technique name
            target_genre: Target genre
            compat_score: Compatibility score
            
        Returns:
            List of warnings
        """
        warnings = []
        
        if compat_score < 0.5:
            warnings.append(f"⚠️ 高风险：该技巧与{target_genre}的兼容性较低")
            warnings.append("使用前建议征求编辑意见")
        
        if compat_score < 0.3:
            warnings.append("🚫 极不推荐：该技巧几乎不适用于本类型")
        
        if "系统" in technique_name or "体系" in technique_name:
            if target_genre not in ["玄幻", "网游", "科幻"]:
                warnings.append("提示：系统类技巧主要适用于有明确规则体系的类型")
        
        if target_genre == "都市" and any(kw in technique_name for kw in ["修仙", "证道", "渡劫"]):
            warnings.append("提示：该技巧是玄幻类型特有，需要改造为都市背景")
        
        return warnings
    
    def save_adapted_techniques(
        self,
        adapted: List[AdaptedTechnique],
        target_genre: str,
        output_path: str = None
    ) -> None:
        """Save adapted techniques to file.
        
        Args:
            adapted: List of adapted techniques
            target_genre: Target genre
            output_path: Output file path
        """
        if output_path is None:
            output_path = f"learning/adapted_techniques_{target_genre}.json"
        
        data = {
            "schema": "xs2.technique.adapted.v1",
            "target_genre": target_genre,
            "adapted_techniques": [
                {
                    "original_id": t.original_id,
                    "original_name": t.original_name,
                    "category": t.category,
                    "compatibility_score": t.compatibility_score,
                    "adaptation_status": t.adaptation_status,
                    "adapted_guidance": t.adapted_guidance,
                    "adaptation_notes": t.adaptation_notes,
                    "example_for_genre": t.example_for_genre,
                    "warnings": t.warnings
                }
                for t in adapted
            ],
            "summary": {
                "total": len(adapted),
                "direct": sum(1 for t in adapted if t.adaptation_status == "direct"),
                "adapt": sum(1 for t in adapted if t.adaptation_status == "adapt"),
                "risky": sum(1 for t in adapted if t.adaptation_status == "risky"),
                "incompatible": sum(1 for t in adapted if t.adaptation_status == "incompatible"),
            }
        }
        
        import json
        from pathlib import Path
        Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
