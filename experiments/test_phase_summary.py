"""Regression tests for the derived, phase-separated reproduction ledger."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("reproduction_ledger", ROOT / "reproduce_offline.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PhaseSummaryTests(unittest.TestCase):
    def setUp(self):
        self.pilot = {"assigned": 28, "launched": 28, "complete_structured": 28, "by_arm": {"fixture": 1}}
        self.expansion = {"assigned": 280, "launched": 280, "complete_structured": 280,
                          "by_arm": {"fixture": 2}, "action_exposed": 280,
                          "per_family_arm": [{"fixture": "controlled test"}],
                          "deterministic_reference": {"is_model": False}}
        self.summary = {"phases_are_not_pooled": True, "pilot": copy.deepcopy(self.pilot),
                        "expansion": copy.deepcopy(self.expansion)}

    def check(self):
        MODULE.validate_phase_summary(self.summary, self.pilot, self.expansion)

    def test_current_summary_passes(self):
        self.check()

    def test_stale_zero_expansion_is_rejected(self):
        self.summary["expansion"]["assigned"] = 0
        with self.assertRaisesRegex(RuntimeError, "expansion.assigned"):
            self.check()

    def test_stale_arm_metrics_are_rejected(self):
        self.summary["expansion"]["by_arm"] = {}
        with self.assertRaisesRegex(RuntimeError, "expansion.by_arm"):
            self.check()

    def test_stale_reference_is_rejected(self):
        self.summary["expansion"]["deterministic_reference"] = {"is_model": True}
        with self.assertRaisesRegex(RuntimeError, "expansion.deterministic_reference"):
            self.check()

    def test_pooled_summary_is_rejected(self):
        self.summary["phases_are_not_pooled"] = False
        with self.assertRaisesRegex(RuntimeError, "phase separation"):
            self.check()


if __name__ == "__main__":
    unittest.main(verbosity=2)
