"""Consolidated, evidence-backed final editorial and render review.

This module summarizes existing diagnostics. It never edits a timeline, modifies
rendered media, or grants publication approval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class FinalReviewItem:
    category: str
    severity: str
    title: str
    evidence: tuple[str, ...]
    recommendation: str


@dataclass(frozen=True)
class FinalReviewReport:
    project_name: str
    status: str
    ready_for_human_approval: bool
    user_approved: bool
    items: tuple[FinalReviewItem, ...]
    error_count: int
    warning_count: int
    advisory_count: int
    render_verified: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        lines = [
            "# ZENITH Desktop — Final Review",
            "",
            f"- Project: {self.project_name or 'Untitled project'}",
            f"- Status: {self.status}",
            f"- Ready for human approval: {'Yes' if self.ready_for_human_approval else 'No'}",
            "- User approval: NOT GRANTED",
            f"- Render structurally verified: {'Yes' if self.render_verified else 'No'}",
            f"- Findings: {self.error_count} errors, {self.warning_count} warnings, {self.advisory_count} advisories",
            "",
            "## Findings",
        ]
        if not self.items:
            lines.append("No findings were supplied to this report.")
        for item in self.items:
            lines.extend([
                f"### [{item.severity.upper()}] {item.title}",
                f"- Category: {item.category}",
            ])
            lines.extend(f"- Evidence: {value}" for value in item.evidence)
            lines.append(f"- Recommendation: {item.recommendation}")
            lines.append("")
        if self.notes:
            lines.extend(["## Notes", ""])
            lines.extend(f"- {note}" for note in self.notes)
        lines.extend([
            "",
            "> This report is an aid to human review. It does not certify artistic quality,",
            "> semantic scene understanding, speech-to-picture lip-sync, or publication approval.",
            "",
        ])
        return "\n".join(lines)


def _read(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _sequence(value: Any) -> tuple:
    if value is None:
        return ()
    return tuple(value)


def build_final_review_report(
    project_name: str,
    *,
    director_report: Any = None,
    render_report: Any = None,
) -> FinalReviewReport:
    """Combine current director findings and post-render diagnostics.

    A render is considered structurally verified only when the supplied render
    report explicitly has valid=True and decode_succeeded=True. A director
    report with technical errors blocks readiness. Warnings/advisories remain
    visible for a human to resolve or consciously accept.
    """
    if not isinstance(project_name, str):
        raise TypeError("project_name must be a string")

    items: list[FinalReviewItem] = []
    notes: list[str] = []
    director_errors = 0
    if director_report is not None:
        for finding in _sequence(_read(director_report, "findings", ())):
            severity = str(_read(finding, "severity", "advisory")).lower()
            if severity not in {"error", "warning", "advisory"}:
                severity = "advisory"
            if severity == "error":
                director_errors += 1
            items.append(FinalReviewItem(
                category=str(_read(finding, "category", "editorial")),
                severity=severity,
                title=str(_read(finding, "title", "Untitled finding")),
                evidence=tuple(str(x) for x in _sequence(_read(finding, "evidence", ()))),
                recommendation=str(_read(finding, "recommendation", "Review manually.")),
            ))
    else:
        notes.append("Director review was not supplied; editorial checks may be incomplete.")

    render_verified = bool(
        render_report is not None
        and _read(render_report, "valid", False) is True
        and _read(render_report, "decode_succeeded", False) is True
    )
    if render_report is None:
        notes.append("No post-render verification report was supplied.")
    else:
        if not render_verified:
            items.append(FinalReviewItem(
                "render", "error", "Rendered file has not passed structural verification",
                ("The render report is missing a valid decode/verification result.",),
                "Resolve the render issue and run post-render verification again.",
            ))
        visual = _read(render_report, "visual_quality")
        if visual is not None:
            for interval in _sequence(_read(visual, "black_intervals", ())):
                items.append(FinalReviewItem(
                    "visual_quality", "advisory", "Possible sustained black interval",
                    (str(interval),),
                    "Inspect this interval in the exported video; black may be intentional.",
                ))
            for interval in _sequence(_read(visual, "freeze_intervals", ())):
                items.append(FinalReviewItem(
                    "visual_quality", "advisory", "Possible frozen-frame interval",
                    (str(interval),),
                    "Inspect motion and source footage around this interval.",
                ))
        if _read(render_report, "visual_scan_error"):
            notes.append(str(_read(render_report, "visual_scan_error")))
        audio = _read(render_report, "audio_quality")
        if audio is not None:
            transient_count = _read(audio, "transient_candidate_count", None)
            clipping_count = _read(audio, "clipping_interval_count", None)
            if transient_count:
                items.append(FinalReviewItem(
                    "audio_quality", "advisory", "Possible abrupt audio transients",
                    (f"{transient_count} candidate(s) detected; not confirmed audible clicks.",),
                    "Listen to the flagged sections using headphones.",
                ))
            if clipping_count:
                items.append(FinalReviewItem(
                    "audio_quality", "warning", "Possible audio clipping",
                    (f"{clipping_count} interval(s) detected near full scale.",),
                    "Listen and inspect peak levels; reduce gain if distortion is audible.",
                ))
            if _read(audio, "duration_mismatch", False):
                items.append(FinalReviewItem(
                    "audio_quality", "warning", "Audio duration differs from video duration",
                    ("Decoded audio duration is outside the configured tolerance.",),
                    "Check timeline alignment and listen to the beginning and end.",
                ))
            if _read(audio, "duration_scan_complete", True) is False:
                notes.append("Audio diagnostics reached their scan limit; the full soundtrack was not inspected.")
        if _read(render_report, "audio_scan_error"):
            notes.append(str(_read(render_report, "audio_scan_error")))

    error_count = sum(item.severity == "error" for item in items)
    warning_count = sum(item.severity == "warning" for item in items)
    advisory_count = sum(item.severity == "advisory" for item in items)
    ready = render_verified and error_count == 0
    status = "ready_for_human_approval" if ready else "blocked" if error_count else "review_required"
    notes.append("Speech-to-picture lip-sync is not verified by duration comparison alone.")
    notes.append("No finding has been automatically fixed and no publication approval has been granted.")

    return FinalReviewReport(
        project_name=project_name.strip(),
        status=status,
        ready_for_human_approval=ready,
        user_approved=False,
        items=tuple(items),
        error_count=error_count,
        warning_count=warning_count,
        advisory_count=advisory_count,
        render_verified=render_verified,
        notes=tuple(notes),
    )
