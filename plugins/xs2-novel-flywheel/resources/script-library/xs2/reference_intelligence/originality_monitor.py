"""Real-time originality monitoring for draft content.

Monitors similarity during writing process to prevent unconscious copying.
"""
import json
import hashlib
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class SimilarityWarning:
    """Similarity warning during writing."""
    severity: str               # low/medium/high/critical
    similarity_score: float     # 0-1
    reference_source: str       # Which reference work
    similar_segment: str        # The similar segment in reference
    suggestion: str             # How to rewrite
    location: str              # Where in the draft


class OriginalityMonitor:
    """Real-time originality monitoring."""
    
    def __init__(self, load_fn=None):
        """Initialize monitor.
        
        Args:
            load_fn: Function to load JSON files
        """
        self.load = load_fn
        self.reference_texts = []
        self.reference_segments = {}
        self._load_references()
    
    def _load_references(self):
        """Load reference texts for comparison."""
        if not self.load:
            return
        
        try:
            # Load reference windows
            candidates = self.load("learning/candidates.json")
            
            for candidate in candidates.get("candidates", []):
                evidence = candidate.get("evidence", {})
                raw_text = evidence.get("raw_text", "")
                if raw_text:
                    self.reference_texts.append({
                        "source": candidates.get("source", {}).get("title", "参考作品"),
                        "text": raw_text,
                        "candidate_id": candidate.get("candidate_id", "")
                    })
            
            # Create n-gram index for fast lookup
            self._build_segment_index()
            
        except (OSError, ValueError, KeyError):
            pass
    
    def _build_segment_index(self):
        """Build n-gram index for fast similarity detection."""
        for ref in self.reference_texts:
            text = ref["text"]
            source = ref["source"]
            
            # Create 5-gram segments
            for i in range(len(text) - 5):
                segment = text[i:i+5]
                if segment not in self.reference_segments:
                    self.reference_segments[segment] = []
                self.reference_segments[segment].append({
                    "source": source,
                    "position": i,
                    "context": text[max(0, i-10):i+15]
                })
    
    def check_draft_segment(
        self,
        draft_text: str,
        threshold: float = 0.75
    ) -> List[SimilarityWarning]:
        """Check a draft segment for similarity.
        
        Args:
            draft_text: Draft text to check
            threshold: Similarity threshold (0-1)
            
        Returns:
            List of warnings
        """
        warnings = []
        
        # Quick check: if no references loaded
        if not self.reference_texts:
            return warnings
        
        # Check against each reference
        for ref in self.reference_texts:
            ref_text = ref["text"]
            ref_source = ref["source"]
            
            # Find similar segments
            similarity, similar_part = self._calculate_similarity(
                draft_text,
                ref_text
            )
            
            if similarity >= threshold:
                severity = self._determine_severity(similarity)
                suggestion = self._generate_rewrite_suggestion(
                    draft_text,
                    similar_part,
                    severity
                )
                
                warnings.append(SimilarityWarning(
                    severity=severity,
                    similarity_score=similarity,
                    reference_source=ref_source,
                    similar_segment=similar_part[:100] + "...",
                    suggestion=suggestion,
                    location="当前段落"
                ))
        
        return warnings
    
    def check_full_chapter(
        self,
        chapter_text: str,
        threshold: float = 0.75
    ) -> Dict[str, Any]:
        """Check full chapter for similarity.
        
        Args:
            chapter_text: Full chapter text
            threshold: Similarity threshold
            
        Returns:
            Detailed similarity report
        """
        # Split into paragraphs
        paragraphs = [p.strip() for p in chapter_text.split("\n\n") if p.strip()]
        
        all_warnings = []
        paragraph_scores = []
        
        for i, para in enumerate(paragraphs):
            warnings = self.check_draft_segment(para, threshold)
            
            max_score = max([w.similarity_score for w in warnings], default=0.0)
            paragraph_scores.append({
                "paragraph_index": i,
                "paragraph_preview": para[:50] + "...",
                "max_similarity": max_score,
                "warnings": len(warnings)
            })
            
            all_warnings.extend(warnings)
        
        # Overall assessment
        overall_score = sum(p["max_similarity"] for p in paragraph_scores) / len(paragraph_scores) if paragraph_scores else 0.0
        
        return {
            "overall_similarity": overall_score,
            "total_warnings": len(all_warnings),
            "critical_warnings": sum(1 for w in all_warnings if w.severity == "critical"),
            "high_warnings": sum(1 for w in all_warnings if w.severity == "high"),
            "paragraph_scores": paragraph_scores,
            "warnings": [
                {
                    "severity": w.severity,
                    "similarity_score": w.similarity_score,
                    "reference_source": w.reference_source,
                    "similar_segment": w.similar_segment,
                    "suggestion": w.suggestion,
                    "location": w.location
                }
                for w in all_warnings
            ],
            "recommendation": self._generate_overall_recommendation(overall_score, all_warnings)
        }
    
    def _calculate_similarity(
        self,
        text1: str,
        text2: str
    ) -> Tuple[float, str]:
        """Calculate similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Tuple of (similarity_score, most_similar_segment)
        """
        # Simple longest common substring approach
        # For production, use more sophisticated algorithms
        
        max_similarity = 0.0
        most_similar_segment = ""
        
        # Use sliding window
        window_size = min(50, len(text1), len(text2))
        
        for i in range(len(text1) - window_size + 1):
            segment1 = text1[i:i+window_size]
            
            for j in range(len(text2) - window_size + 1):
                segment2 = text2[j:j+window_size]
                
                # Calculate character-level similarity
                common_chars = sum(1 for c1, c2 in zip(segment1, segment2) if c1 == c2)
                similarity = common_chars / window_size
                
                if similarity > max_similarity:
                    max_similarity = similarity
                    most_similar_segment = segment2
        
        return max_similarity, most_similar_segment
    
    def _determine_severity(self, similarity: float) -> str:
        """Determine warning severity.
        
        Args:
            similarity: Similarity score
            
        Returns:
            Severity level
        """
        if similarity >= 0.95:
            return "critical"
        elif similarity >= 0.85:
            return "high"
        elif similarity >= 0.75:
            return "medium"
        else:
            return "low"
    
    def _generate_rewrite_suggestion(
        self,
        draft_text: str,
        similar_part: str,
        severity: str
    ) -> str:
        """Generate rewrite suggestion.
        
        Args:
            draft_text: Draft text
            similar_part: Similar segment from reference
            severity: Warning severity
            
        Returns:
            Rewrite suggestion
        """
        suggestions = {
            "critical": "⚠️ 极高相似度！必须完全重写此段落，改变：\n1. 句式结构\n2. 用词选择\n3. 表达角度\n4. 细节描写",
            "high": "⚠️ 高相似度。建议：\n1. 改变叙述视角\n2. 调整句子顺序\n3. 用不同的修辞手法\n4. 增加原创细节",
            "medium": "⚠️ 中等相似度。建议：\n1. 保留核心思路\n2. 改写具体表达\n3. 融入你的角色特点\n4. 添加个人风格",
            "low": "提示：有一定相似度，可以微调表达方式。"
        }
        
        return suggestions.get(severity, "建议审查并调整")
    
    def _generate_overall_recommendation(
        self,
        overall_score: float,
        warnings: List[SimilarityWarning]
    ) -> str:
        """Generate overall recommendation.
        
        Args:
            overall_score: Overall similarity score
            warnings: All warnings
            
        Returns:
            Recommendation text
        """
        if overall_score >= 0.9:
            return "🚫 整章相似度过高，强烈建议大幅改写"
        elif overall_score >= 0.8:
            return "⚠️ 章节相似度较高，建议重点修改标记段落"
        elif overall_score >= 0.7:
            return "⚠️ 章节有明显相似之处，建议调整部分段落"
        elif overall_score >= 0.5:
            return "✅ 章节整体原创性良好，个别地方可微调"
        else:
            return "✅ 章节原创性优秀，保持当前风格"
    
    def save_monitoring_report(
        self,
        report: Dict,
        output_path: str = "learning/originality_monitoring.json"
    ) -> None:
        """Save monitoring report.
        
        Args:
            report: Monitoring report
            output_path: Output file path
        """
        data = {
            "schema": "xs2.originality.monitoring.v1",
            "report": report,
            "timestamp": str(__import__("datetime").datetime.now())
        }
        
        from pathlib import Path
        Path(output_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def generate_markdown_report(
        self,
        report: Dict,
        chapter_num: int = None
    ) -> str:
        """Generate human-readable markdown report.
        
        Args:
            report: Monitoring report
            chapter_num: Chapter number
            
        Returns:
            Markdown formatted report
        """
        md = f"# 原创性检测报告\n\n"
        
        if chapter_num:
            md += f"**章节**：第 {chapter_num} 章\n"
        
        md += f"**整体相似度**：{report['overall_similarity']*100:.1f}%\n"
        md += f"**总警告数**：{report['total_warnings']}\n"
        md += f"  - 严重：{report['critical_warnings']}\n"
        md += f"  - 高风险：{report['high_warnings']}\n\n"
        
        md += f"## 总体评估\n\n{report['recommendation']}\n\n"
        
        # Critical and high warnings
        high_priority = [w for w in report['warnings'] if w['severity'] in ['critical', 'high']]
        
        if high_priority:
            md += f"## 需要立即处理的问题\n\n"
            for i, w in enumerate(high_priority, 1):
                md += f"### {i}. {w['severity'].upper()} - 相似度 {w['similarity_score']*100:.1f}%\n\n"
                md += f"**参考来源**：{w['reference_source']}\n\n"
                md += f"**相似片段**：\n```\n{w['similar_segment']}\n```\n\n"
                md += f"**建议**：\n{w['suggestion']}\n\n"
                md += "---\n\n"
        
        # Paragraph breakdown
        md += "## 段落详情\n\n"
        for para in report['paragraph_scores']:
            status = "🔴" if para['max_similarity'] >= 0.8 else ("🟡" if para['max_similarity'] >= 0.6 else "🟢")
            md += f"- {status} 段落 {para['paragraph_index']+1}：相似度 {para['max_similarity']*100:.1f}%\n"
            md += f"  > {para['paragraph_preview']}\n"
        
        return md
