from __future__ import annotations

import unittest

from profiling import Profiler, format_snapshot, resource_snapshot


class ProfilingTests(unittest.TestCase):
    def test_resource_snapshot_never_raises_and_returns_dict(self) -> None:
        snap = resource_snapshot()
        self.assertIsInstance(snap, dict)

    def test_format_snapshot_is_string(self) -> None:
        self.assertIsInstance(format_snapshot(resource_snapshot()), str)
        self.assertEqual(format_snapshot({}), "n/a")

    def test_profiler_records_stages_meta_and_summarizes(self) -> None:
        prof = Profiler("test")
        prof.record("extract", 0.012)
        prof.record("redact", 0.034)
        prof.mark(messages=4, engine="deterministic")

        self.assertEqual([name for name, _ in prof.stages], ["extract", "redact"])
        self.assertEqual(prof.meta["messages"], 4)
        self.assertGreaterEqual(prof.elapsed(), 0.0)
        prof.summary()  # must not raise

    def test_stage_context_manager_records_duration(self) -> None:
        prof = Profiler("test")
        with prof.stage("chart"):
            pass
        self.assertEqual(prof.stages[-1][0], "chart")
        self.assertGreaterEqual(prof.stages[-1][1], 0.0)


if __name__ == "__main__":
    unittest.main()
