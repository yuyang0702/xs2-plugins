"""Multi-dimensional analysis coordinator and originality detection.

Orchestrates analysis across all dimensions and provides plagiarism prevention.
"""
import json
import hashlib
from typing import Dict, List, Any, Tuple
from pathlib import Path

try:
    from analyzers.plot_analyzer import analyze_plot_structure
    from analyzers.character_analyzer import analyze_character_patterns
    from analyzers.conflict_analyzer import analyze_conflict_mechanics
    from analyzers.technique_analyzer import analyze_writing_techniques
except ImportError:
    import sys
    analyzers_path = str(Path(__file__).parent / "analyzers")
    if analyzers_path not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent))
    from analyzers.plot_analyzer import analyze_plot_structure
    from analyzers.character_analyzer import analyze_character_patterns
    from analyzers.conflict_analyzer import analyze_conflict_mechanics
    from analyzers.technique_analyzer import analyze_writing_techniques


class ReferenceAnalysisUpgrade:
    """Upgrade existing candidates.json with multi-dimensional analysis."""
    
    def __init__(self, load_fn, save_fn, digest_fn):
        """Initialize with project functions.
        
        Args:
            load_fn: Function to load JSON files
            save_fn: Function to save JSON files
            digest_fn: Function to compute SHA256 hash
        """
        self.load = load_fn
        self.save = save_fn
        self.digest = digest_fn
    
    def perform_analysis(self) -> Dict[str, Any]:
        """Execute full multi-dimensional analysis.
        
        Returns:
            Dictionary with all analysis results
        """
        # Load prerequisites
        try:
            candidates = self.load("learning/candidates.json").get("candidates", [])
        except (OSError, ValueError):
            candidates = []
        
        try:
            source_metadata = self.load("learning/dna/metadata.json")
        except (OSError, ValueError):
            source_metadata = {}
        
        try:
            dna_profile = self.load("learning/dna/profile.json")
        except (OSError, ValueError):
            dna_profile = {}
        
        # Perform dimensional analyses
        plot_analysis = analyze_plot_structure(candidates, source_metadata)
        character_analysis = analyze_character_patterns(candidates, source_metadata, dna_profile)
        conflict_analysis = analyze_conflict_mechanics(candidates, source_metadata, dna_profile)
        technique_analysis = analyze_writing_techniques(candidates, source_metadata, dna_profile)
        
        # Combine all analyses
        combined_analysis = {
            "schema": "xs2.reference.multi_dimensional_analysis.v1",
            "created_at": self._timestamp(),
            "source": source_metadata.get("source", {}),
            "analyses": {
                "plot": plot_analysis,
                "character": character_analysis,
                "conflict": conflict_analysis,
                "technique": technique_analysis
            },
            "summary": self._generate_summary(
                plot_analysis, character_analysis, conflict_analysis, technique_analysis
            )
        }
        
        combined_analysis["analysis_sha256"] = self.digest(combined_analysis)
        
        return combined_analysis
    
    def enhance_candidates(self, combined_analysis: Dict) -> None:
        """Enhance existing candidates.json with analysis data.
        
        This function adds a non-breaking _analysis field to the existing
        candidates.json, maintaining full backward compatibility.
        
        Args:
            combined_analysis: Results from perform_analysis()
        """
        try:
            candidates_data = self.load("learning/candidates.json")
        except (OSError, ValueError):
            candidates_data = {"source": {}, "candidates": [], "candidates_sha256": ""}
        
        # Add analysis field (non-breaking, prefixed with underscore)
        candidates_data["_analysis"] = {
            "schema": "xs2.reference.candidates_analysis.v1",
            "analysis_sha256": combined_analysis["analysis_sha256"],
            "plot_summary": combined_analysis["summary"].get("plot", ""),
            "character_summary": combined_analysis["summary"].get("character", ""),
            "conflict_summary": combined_analysis["summary"].get("conflict", ""),
            "technique_summary": combined_analysis["summary"].get("technique", ""),
            "source": combined_analysis["source"]
        }
        
        self.save("learning/candidates.json", candidates_data)
    
    def save_analyses(self, combined_analysis: Dict) -> None:
        """Save individual analysis files for selective loading.
        
        Args:
            combined_analysis: Results from perform_analysis()
        """
        analysis_dir = Path("learning/analysis")
        analysis_dir.mkdir(exist_ok=True)
        
        # Save combined analysis
        self.save("learning/reference_analysis.json", combined_analysis)
        
        # Save individual dimension analyses
        analyses = combined_analysis["analyses"]
        self.save(str(analysis_dir / "plot_analysis.json"), analyses["plot"])
        self.save(str(analysis_dir / "character_analysis.json"), analyses["character"])
        self.save(str(analysis_dir / "conflict_analysis.json"), analyses["conflict"])
        self.save(str(analysis_dir / "technique_analysis.json"), analyses["technique"])
        
        # Save summary for quick reference
        summary = {
            "schema": "xs2.reference.analysis_summary.v1",
            "created_at": combined_analysis.get("created_at"),
            "source": combined_analysis.get("source", {}),
            "summaries": combined_analysis.get("summary", {})
        }
        self.save("learning/analysis_summary.json", summary)
    
    def _timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
    
    def _generate_summary(self, plot: Dict, character: Dict, 
                         conflict: Dict, technique: Dict) -> Dict[str, str]:
        """Generate high-level summaries for each dimension."""
        return {
            "plot": self._summarize_plot(plot),
            "character": self._summarize_character(character),
            "conflict": self._summarize_conflict(conflict),
            "technique": self._summarize_technique(technique)
        }
    
    def _summarize_plot(self, analysis: Dict) -> str:
        """Summarize plot analysis."""
        dims = analysis.get("plot_dimensions", {})
        
        lines = ["# 剧情设计分析", ""]
        
        conflict = dims.get("conflict_escalation", {})
        if conflict.get("count"):
            lines.append(f"冲突升级模式：{conflict['count']}个样本")
            insights = conflict.get("transferable_insights", [])
            if insights:
                lines.append("- " + insights[0])
        
        foreshadow = dims.get("foreshadowing", {})
        if foreshadow.get("count"):
            lines.append(f"伏笔铺垫模式：{foreshadow['count']}个样本")
            insights = foreshadow.get("transferable_insights", [])
            if insights:
                lines.append("- " + insights[0])
        
        reversals = dims.get("reversals", {})
        if reversals.get("count"):
            lines.append(f"反转机制：{reversals['count']}个样本")
        
        return "\n".join(lines) if len(lines) > 2 else "剧情分析数据不足"
    
    def _summarize_character(self, analysis: Dict) -> str:
        """Summarize character analysis."""
        dims = analysis.get("character_dimensions", {})
        
        lines = ["# 角色塑造分析", ""]
        
        arcs = dims.get("character_arcs", {})
        if arcs.get("count"):
            lines.append(f"人物弧光模式：{arcs['count']}个样本")
            insights = arcs.get("transferable_insights", [])
            if insights:
                lines.append("- " + insights[0])
        
        voice = dims.get("character_voice", {})
        if voice.get("count"):
            lines.append(f"角色声线模式：{voice['count']}个样本")
        
        relationships = dims.get("relationships", {})
        if relationships.get("count"):
            lines.append(f"关系动态模式：{relationships['count']}个样本")
        
        return "\n".join(lines) if len(lines) > 2 else "角色分析数据不足"
    
    def _summarize_conflict(self, analysis: Dict) -> str:
        """Summarize conflict analysis."""
        dims = analysis.get("conflict_dimensions", {})
        
        lines = ["# 冲突设计分析", ""]
        
        escalation = dims.get("escalation_paths", {})
        if escalation.get("count"):
            lines.append(f"升级路径模式：{escalation['count']}个样本")
            insights = escalation.get("transferable_insights", [])
            if insights:
                lines.append("- " + insights[0])
        
        resolution = dims.get("resolution_mechanics", {})
        if resolution.get("count"):
            lines.append(f"解决机制：{resolution['count']}个样本")
        
        chains = dims.get("conflict_chains", {})
        if chains.get("count"):
            lines.append(f"冲突链范例：{chains['count']}条")
        
        return "\n".join(lines) if len(lines) > 2 else "冲突分析数据不足"
    
    def _summarize_technique(self, analysis: Dict) -> str:
        """Summarize technique analysis."""
        dims = analysis.get("technique_dimensions", {})
        
        lines = ["# 写作技法分析", ""]
        
        dialogue = dims.get("dialogue_craft", {})
        if dialogue.get("count"):
            lines.append(f"对话技法：{dialogue['count']}个样本")
        
        scene = dims.get("scene_construction", {})
        if scene.get("count"):
            lines.append(f"场景构建：{scene['count']}个样本")
        
        descriptive = dims.get("descriptive_technique", {})
        if descriptive.get("count"):
            lines.append(f"描写技巧：{descriptive['count']}个样本")
        
        language = dims.get("language_patterns", {})
        if language.get("sentence_structure"):
            lines.append(f"语言特征：平均句长 {language['sentence_structure']['mean_length']} 字")
        
        return "\n".join(lines) if len(lines) > 2 else "技法分析数据不足"


class OriginalityDetector:
    """Detect and prevent plagiarism during writing."""
    
    def __init__(self, load_fn, save_fn):
        """Initialize detector.
        
        Args:
            load_fn: Function to load JSON files
            save_fn: Function to save JSON files
        """
        self.load = load_fn
        self.save = save_fn
    
    def check_originality(self, writing_text: str, 
                         threshold: float = 0.75) -> Dict[str, Any]:
        """Check writing against reference for originality.
        
        Args:
            writing_text: Text to check
            threshold: Similarity threshold (0-1) for flagging
            
        Returns:
            Dictionary with originality assessment
        """
        # Load reference texts
        try:
            references = self.load("learning/dna/metadata.json")
            source_units = references.get("source_units", [])
        except (OSError, ValueError):
            return {
                "status": "unable_to_check",
                "reason": "参考文本不可用"
            }
        
        # Perform similarity checks
        flags = []
        similarities = []
        
        for unit in source_units[:5]:  # Check up to 5 units
            title = unit.get("title", "")
            similarity = self._calculate_similarity(writing_text, unit, references)
            similarities.append({
                "unit": title,
                "similarity": similarity
            })
            
            if similarity >= threshold:
                flags.append({
                    "severity": "high",
                    "unit": title,
                    "similarity": similarity,
                    "recommendation": "相似度过高，建议重新审视表达方式和具体情节"
                })
            elif similarity >= 0.6:
                flags.append({
                    "severity": "medium",
                    "unit": title,
                    "similarity": similarity,
                    "recommendation": "存在相似之处，建议审核是否过度依赖参考"
                })
        
        return {
            "status": "checked",
            "original": len(flags) == 0,
            "max_similarity": max([s["similarity"] for s in similarities]) if similarities else 0,
            "flags": flags,
            "similarities": similarities,
            "notes": [
                "检测结果仅供参考，最终判断由创作者确定",
                "相似度指标基于内容分析，不代表剽窃判定",
                "应结合人工审阅进行最终确认"
            ]
        }
    
    def _calculate_similarity(self, text: str, unit: Dict, 
                             metadata: Dict) -> float:
        """Calculate similarity between text and reference unit.
        
        This is a placeholder implementation. Real implementation would
        use more sophisticated similarity metrics.
        
        Args:
            text: Text to check
            unit: Reference unit
            metadata: Source metadata
            
        Returns:
            Similarity score (0-1)
        """
        # Simple heuristic: check for key phrase overlap
        # This is a placeholder - real implementation would be more sophisticated
        
        # Extract key terms from writing
        writing_terms = self._extract_terms(text)
        
        # For now, return conservative estimate
        if not writing_terms:
            return 0.0
        
        # This would be replaced with proper similarity algorithm
        # such as Jaccard similarity, cosine similarity, or embedding-based comparison
        return 0.0
    
    def _extract_terms(self, text: str) -> set:
        """Extract key terms from text."""
        import re
        # Extract 2-character terms
        terms = set()
        for match in re.finditer(r'[\u4e00-\u9fff]{2,}', text):
            terms.add(match.group())
        return terms
    
    def generate_report(self, check_result: Dict) -> str:
        """Generate human-readable originality report."""
        lines = ["# 原创性检测报告", ""]
        
        if check_result.get("status") == "unable_to_check":
            lines.append(f"无法进行检测：{check_result.get('reason')}")
            return "\n".join(lines)
        
        is_original = check_result.get("original")
        max_sim = check_result.get("max_similarity", 0)
        
        if is_original:
            lines.append(f"✓ 检测通过。最高相似度：{max_sim:.1%}")
            lines.append("")
            lines.append("你的写作保持了独特性。继续按照自己的风格创作。")
        else:
            lines.append(f"⚠ 检测存在问题。最高相似度：{max_sim:.1%}")
            lines.append("")
            lines.append("发现的问题：")
            for flag in check_result.get("flags", []):
                severity = "【高】" if flag["severity"] == "high" else "【中】"
                lines.append(f"- {severity} {flag['unit']}: {flag['similarity']:.1%}")
                lines.append(f"  建议：{flag['recommendation']}")
        
        lines.extend(["", "# 详细相似度分析"])
        for sim in check_result.get("similarities", []):
            lines.append(f"- {sim['unit']}: {sim['similarity']:.1%}")
        
        lines.extend(["", "# 注意事项"])
        lines.extend(["- " + note for note in check_result.get("notes", [])])
        
        return "\n".join(lines)
