"""Tests for consolidated final editorial/render review reporting."""
import json
import unittest
from types import SimpleNamespace

from final_review_report import build_final_review_report


class FinalReviewReportTests(unittest.TestCase):
    def test_verified_render_and_director_findings_are_summarized(self):
        director = SimpleNamespace(findings=(
            SimpleNamespace(
                category="continuity", severity="warning", title="Small gap",
                evidence=("12 empty frames",), recommendation="Inspect the gap.",
            ),
            SimpleNamespace(
                category="pacing", severity="advisory", title="Long shot",
                evidence=("12 seconds",), recommendation="Check the pacing.",
            ),
        ))
        audio = SimpleNamespace(
            transient_candidates=(object(),), clipped_intervals_seconds=(),
            duration_matches_video=True, duration_scan_complete=True,
        )
        visual = SimpleNamespace(black_intervals=(), freeze_intervals=())
        render = SimpleNamespace(
            valid=True, decode_succeeded=True, visual_quality=visual,
            visual_scan_error=None, audio_quality=audio, audio_scan_error=None,
        )
        report = build_final_review_report("Demo", director_report=director, render_report=render)
        self.assertTrue(report.ready_for_human_approval)
        self.assertFalse(report.user_approved)
        self.assertEqual(report.status, "ready_for_human_approval")
        self.assertEqual((report.error_count, report.warning_count, report.advisory_count), (0, 1, 2))
        self.assertTrue(any("transient" in item.title.lower() for item in report.items))
        self.assertIn("NOT GRANTED", report.to_markdown())
        self.assertEqual(json.loads(report.to_json())["project_name"], "Demo")

    def test_invalid_render_blocks_human_approval(self):
        render = SimpleNamespace(valid=False, decode_succeeded=False)
        report = build_final_review_report("Broken", render_report=render)
        self.assertFalse(report.ready_for_human_approval)
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.error_count, 1)

    def test_director_error_blocks_readiness_even_when_render_is_valid(self):
        director = SimpleNamespace(findings=(
            SimpleNamespace(
                category="technical", severity="error", title="Missing source",
                evidence=("Source file unavailable",), recommendation="Relink media.",
            ),
        ))
        render = SimpleNamespace(valid=True, decode_succeeded=True)
        report = build_final_review_report("Project", director_report=director, render_report=render)
        self.assertFalse(report.ready_for_human_approval)
        self.assertEqual(report.status, "blocked")

    def test_missing_render_requires_review_not_approval(self):
        report = build_final_review_report("Unrendered", director_report=SimpleNamespace(findings=()))
        self.assertFalse(report.ready_for_human_approval)
        self.assertFalse(report.user_approved)
        self.assertEqual(report.status, "review_required")

    def test_audio_scan_limit_is_disclosed(self):
        audio = SimpleNamespace(
            transient_candidates=(), clipped_intervals_seconds=(),
            duration_matches_video=True, duration_scan_complete=False,
        )
        render = SimpleNamespace(
            valid=True, decode_succeeded=True, audio_quality=audio,
        )
        report = build_final_review_report("Long", render_report=render)
        self.assertTrue(any("scan limit" in note.lower() for note in report.notes))

    def test_project_name_must_be_text(self):
        with self.assertRaises(TypeError):
            build_final_review_report(None)


if __name__ == "__main__":
    unittest.main()
