#!/usr/bin/env python3
"""Validate critic handoff, or publish a complete polisher body to chapter.md.

This validates the model's review contract and source citations. It does not
infer literary quality or authorship from syntax, words, or statistics.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def normalize_critique(data: object, chapter: str) -> dict:
    """Keep uncertain claims visible while distinguishing grounded repairs.

    Legacy issues remain readable. Optional evidence/impact fields establish a
    reviewable source basis for material repairs; matching a quote alone cannot
    establish that the model's interpretation is correct.
    """
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("critique must be an object with an issues array")
    if not isinstance(data.get("feels_human"), bool):
        raise ValueError("critique.feels_human must be a boolean")
    if not isinstance(chapter, str) or not chapter.strip():
        raise ValueError("source chapter must contain text")

    result = copy.deepcopy(data)
    warnings = []
    blocking = []
    uncertain = False
    material = False
    severity_aliases = {"major": "high", "moderate": "medium", "minor": "low"}
    source = re.sub(r"\s+", " ", chapter).strip()

    for index, issue in enumerate(result["issues"]):
        if not isinstance(issue, dict):
            raise ValueError(f"issues[{index}] must be an object")
        for field in ("dimension", "description"):
            if not isinstance(issue.get(field), str) or not issue[field].strip():
                raise ValueError(f"issues[{index}].{field} must contain text")
        severity = issue.get("severity")
        if isinstance(severity, str):
            severity = severity.strip().lower()
            severity = severity_aliases.get(severity, severity)
            issue["severity"] = severity

        evidence = issue.get("evidence", [])
        excerpts = [evidence] if isinstance(evidence, str) else evidence
        has_excerpts = (
            isinstance(excerpts, list)
            and bool(excerpts)
            and all(isinstance(quote, str) and quote.strip() for quote in excerpts)
        )
        matches, repairs = [], []
        if has_excerpts:
            pairs = {"“": "”", "‘": "’", '"': '"', "'": "'"}
            for quote_index, quote in enumerate(excerpts):
                exact = re.sub(r"\s+", " ", quote).strip()
                matched = exact in source
                if not matched and len(exact) > 2 and pairs.get(exact[0]) == exact[-1]:
                    inner = exact[1:-1].strip()
                    if inner and inner in source:
                        matched = True
                        repairs.append({"index": quote_index, "repair": "paired_outer_quote"})
                matches.append(matched)
        grounded = has_excerpts and all(matches)
        if repairs:
            issue["evidence_repairs"] = repairs
        else:
            issue.pop("evidence_repairs", None)
        has_impact = isinstance(issue.get("impact"), str) and bool(issue["impact"].strip())
        issue["evidence_status"] = "verified" if grounded and has_impact else "unverified"

        if severity not in {"high", "medium", "low"}:
            uncertain = True
            warnings.append(f"issues[{index}]: unknown severity; retain this claim for review")
        elif severity in {"high", "medium"}:
            material = True
            if grounded and has_impact:
                blocking.append(index)
            else:
                uncertain = True
                reason = "missing or unmatched source excerpts" if not grounded else "missing explicit scene impact"
                warnings.append(f"issues[{index}]: {reason}; do not rewrite from this claim without checking the scene")

    if not data["feels_human"] and not material and not uncertain:
        assessment = data.get("scene_assessment")
        has_assessment = bool(assessment.strip()) if isinstance(assessment, str) else bool(assessment)
        if not result["issues"]:
            uncertain = True
            warnings.append("feels_human=false has no supporting issues; retain this assessment for review")
        elif has_assessment:
            # Free text cannot be classified reliably here. Preserve the
            # model's explicit negative summary instead of guessing sentiment
            # or treating low notes as evidence for a chapter-level failure.
            uncertain = True
            warnings.append("scene_assessment accompanies feels_human=false without material issue evidence; retain it for review")

    # Minor notes do not establish a chapter-level failure. Unverified material
    # claims retain a non-clean summary, without becoming confirmed blockers.
    result["feels_human"] = not (material or uncertain)
    result["blocking_issues"] = blocking
    result["review_warnings"] = warnings
    result["review_status"] = (
        "revise" if blocking else "needs_review" if uncertain
        else "pass_with_notes" if result["issues"] else "pass"
    )
    return result


def focused_commit_check(output, expected_sha, guard_path, guard_sha):
    """Refuse focused publication after any bound manuscript/feedback edit."""
    root = Path.cwd().resolve()
    def safe(relative):
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("focused commit path escapes workspace")
        return candidate
    if not expected_sha and not guard_path and not guard_sha:
        return
    if not all([expected_sha, guard_path, guard_sha]):
        raise ValueError("focused commit is missing expected input fingerprints")
    file = safe(guard_path)
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != guard_sha:
        raise ValueError("focused commit receipt changed; chapter unchanged")
    guard = json.loads(file.read_text(encoding="utf-8"))
    if guard.get("body_sha256") != expected_sha or safe(guard["body_path"]) != output.resolve():
        raise ValueError("focused commit manuscript receipt mismatch")
    for relative, digest in guard["files"].items():
        path = safe(relative)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("focused manuscript or author feedback changed; chapter unchanged")
    state = json.loads(safe(".novel-project.json").read_text(encoding="utf-8-sig"))
    current = {"chapter_number": str(state.get("values", {}).get("chapter_number", "0001")).zfill(4),
               "author_feedback_file": str(state.get("values", {}).get("author_feedback_file") or "").strip(),
               "receipt": state.get("lengthRepairFeedback") or {}}
    if "narrative_pov" in guard["state_binding"]:
        current["narrative_pov"] = state.get("values", {}).get("narrative_pov", "third_person")
    if 'book_contract_sha256' in guard['state_binding']:
        import importlib.util
        spec=importlib.util.spec_from_file_location('polish_book_contract',Path(__file__).resolve().parents[2]/'xs2/prose_policy/book_contract.py')
        book=importlib.util.module_from_spec(spec);spec.loader.exec_module(book)
        current['book_contract_sha256']=book.digest(book.resolve(root))
    if current != guard["state_binding"]:
        raise ValueError("focused author feedback selection changed; chapter unchanged")


def _write_text(path: Path, text: str, check=None) -> None:
    """Replace only after validation and a complete write have succeeded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
        if check is not None:
            check()
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main():
    parser = argparse.ArgumentParser(description="Validate critic notes or publish PP JSON")
    parser.add_argument("--body-json", help="PP body.json")
    parser.add_argument("--output", help="chapter.md output")
    parser.add_argument("--normalize-critique", help="Critic JSON to normalize in place")
    parser.add_argument("--source-chapter", help="Chapter reviewed by the critic")
    parser.add_argument("--expected-body-sha", default="")
    parser.add_argument("--focused-guard", default="")
    parser.add_argument("--focused-guard-sha", default="")
    args = parser.parse_args()

    if args.normalize_critique:
        if not args.source_chapter or args.body_json or args.output:
            parser.error("--normalize-critique requires --source-chapter and cannot publish a body")
        review_path = Path(args.normalize_critique)
        data = json.loads(review_path.read_text(encoding="utf-8"))
        review = normalize_critique(data, Path(args.source_chapter).read_text(encoding="utf-8"))
        _write_text(review_path, json.dumps(review, ensure_ascii=False, indent=2) + "\n")
        print(f"[OK] review={review['review_status']}; grounded repairs={len(review['blocking_issues'])}")
    else:
        if not args.body_json or not args.output or args.source_chapter:
            parser.error("publishing requires --body-json and --output")
        data = json.loads(Path(args.body_json).read_text(encoding="utf-8"))
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, str) or not body.strip():
            raise ValueError("polisher output must contain a nonempty body string; chapter unchanged")
        check = lambda: focused_commit_check(Path(args.output), args.expected_body_sha, args.focused_guard, args.focused_guard_sha)
        check()
        _write_text(Path(args.output), body, check=check)
        print(f"[OK] chapter written ({len(body)} chars)")


if __name__ == "__main__":
    main()
