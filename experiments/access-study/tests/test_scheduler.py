"""Deterministic scheduler unit proof. No CLI/model, freeze, claim or public case."""
import threading
import time
import unittest
from access_study.run_all import classify_transport, schedule_slots


def completed_slot():
    # A correct final hold is unsuccessful, but must not stop the cohort either.
    return {"transport": {"launched": True, "termination": "structured_finish", "errors": []},
            "outcome": {"success": False}}


def limit_slot(kind):
    messages = {"action_cap": "RuntimeError: Action cap without finish", "deadline": "session_timeout",
                "session_deadline": "RuntimeError: session_deadline",
                "deadline_during_preparation": "deadline_during_preparation: TimeoutError: deadline_during_preparation"}
    return {"transport": {"launched": kind != "deadline_during_preparation", "termination": kind,
                           "errors": [messages[kind]]}, "outcome": {"success": False}}


class SchedulerProof(unittest.TestCase):
    def execute(self, first, count=3):
        launched, events = [], []
        cells = [{"opaque_id": str(i)} for i in range(count)]
        def worker(cell):
            launched.append(cell["opaque_id"])
            return first if cell["opaque_id"] == "0" else completed_slot()
        result = schedule_slots(cells, {"workers": 1, "session_seconds": 180}, time.monotonic() + 1000,
                                worker, events.append)
        return result, launched, events

    def test_expected_caps_and_deadlines_continue_to_later_assignments(self):
        for kind in ("action_cap", "deadline", "session_deadline", "deadline_during_preparation"):
            with self.subTest(termination=kind):
                result, launched, events = self.execute(limit_slot(kind))
                self.assertEqual(launched, ["0", "1", "2"])
                self.assertEqual(result, {"attempted": 3, "unlaunched": 0, "stop_reason": None})
                returned = next(i for i, e in enumerate(events) if e["event"] == "session_returned" and e["id"] == "0")
                later = next(i for i, e in enumerate(events) if e["event"] == "launch_attempt" and e["cell"]["opaque_id"] == "1")
                self.assertLess(returned, later)
                decision = events[returned]["scheduling_decision"]
                self.assertEqual(decision["classification"], "expected_" + kind)
                self.assertEqual(decision["scope"], "slot")
                self.assertFalse(decision["stop"])
                self.assertEqual(events[returned]["errors"], limit_slot(kind)["transport"]["errors"])

    def test_two_workers_reuse_freed_slot_after_cap(self):
        released = threading.Event()
        events = []
        cells = [{"opaque_id": str(i)} for i in range(4)]
        def worker(cell):
            if cell["opaque_id"] == "0":
                return limit_slot("action_cap")
            if cell["opaque_id"] == "1":
                if not released.wait(timeout=2):
                    raise RuntimeError("Scheduler failed to launch the next slot after cap")
            if cell["opaque_id"] == "2":
                released.set()
            return completed_slot()
        result = schedule_slots(cells, {"workers": 2, "session_seconds": 180}, time.monotonic() + 1000,
                                worker, events.append)
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(result["attempted"], 4)
        cap_returned = next(i for i, e in enumerate(events) if e["event"] == "session_returned" and e["id"] == "0")
        next_started = next(i for i, e in enumerate(events) if e["event"] == "launch_attempt" and e["cell"]["opaque_id"] == "2")
        self.assertLess(cap_returned, next_started)

    def test_fatal_route_and_instrument_errors_stop_future_assignments(self):
        cases = [("transport_failure", "authentication failed"), ("transport_failure", "quota exhausted"),
                 ("transport_failure", "Unexpected native tool use"),
                 ("transport_failure", "Missing or changed observed model identity"),
                 ("instrument_error", "RuntimeError: instrument_error"),
                 ("check_infrastructure_or_timeout", "RuntimeError: check_infrastructure_or_timeout")]
        for termination, error in cases:
            with self.subTest(error=error):
                first = {"transport": {"launched": True, "termination": termination, "errors": [error]}}
                result, launched, events = self.execute(first)
                self.assertEqual(launched, ["0"])
                self.assertEqual(result["attempted"], 1)
                self.assertEqual(result["unlaunched"], 2)
                self.assertIsNotNone(result["stop_reason"])
                self.assertTrue(events[-1]["scheduling_decision"]["stop"])

    def test_limit_label_never_masks_additional_errors(self):
        for kind in ("action_cap", "deadline", "session_deadline", "deadline_during_preparation"):
            for other in ("CLI nonzero exit", "stdout reader did not terminate", "quota exhausted", "instrument_error"):
                with self.subTest(termination=kind, additional=other):
                    first = limit_slot(kind)
                    first["transport"]["errors"].append(other)
                    result, launched, events = self.execute(first)
                    self.assertEqual(launched, ["0"])
                    self.assertIsNotNone(result["stop_reason"])
                    self.assertEqual(events[-1]["errors"], first["transport"]["errors"])

    def test_missing_unknown_and_inconsistent_classification_is_fatal(self):
        for record in (None, {}, {"termination": "action_cap", "errors": []},
                       {"termination": "deadline", "errors": ["RuntimeError: Action cap without finish"]},
                       {"termination": "unknown", "errors": []},
                       {"termination": "action_cap", "errors": "session_timeout"}):
            with self.subTest(record=record):
                self.assertTrue(classify_transport(record)["stop"])

    def test_global_budget_still_stops_before_launch(self):
        called, events = [], []
        result = schedule_slots([{"opaque_id": "0"}], {"workers": 2, "session_seconds": 180},
                                time.monotonic() + 1, lambda cell: called.append(cell), events.append)
        self.assertEqual(called, [])
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["stop_reason"], "global_budget_prevents_full_next_session")

    def test_worker_exception_is_fatal_without_retry(self):
        called, events = [], []
        def worker(cell):
            called.append(cell["opaque_id"])
            raise RuntimeError("synthetic instrument failure")
        result = schedule_slots([{"opaque_id": "0"}, {"opaque_id": "1"}],
                                {"workers": 1, "session_seconds": 180}, time.monotonic() + 1000,
                                worker, events.append)
        self.assertEqual(called, ["0"])
        self.assertEqual(result["stop_reason"], "worker_exception")
        self.assertEqual(events[-1]["event"], "worker_exception")
