import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import autonomous_agent
from core.brain_router import classify_task


class AutonomousAgentTests(unittest.TestCase):
    def test_planner_accepts_valid_json(self):
        agent = autonomous_agent.AutonomousAgent("test goal")
        agent.plan(lambda *a, **k: {"content": '[{"description":"write file","tool":"file_controller","params":{"action":"create_file"}}]'})
        self.assertEqual(len(agent.steps), 1)
        self.assertEqual(agent.steps[0]["status"], autonomous_agent.STATUS_PENDING)

    def test_planner_rejects_unknown_tool(self):
        agent = autonomous_agent.AutonomousAgent("test goal")
        with self.assertRaises(ValueError):
            agent.plan(lambda *a, **k: {"content": '[{"description":"bad","tool":"shell","params":{}}]'})

    def test_load_rejects_path_traversal_id(self):
        with self.assertRaises(ValueError):
            autonomous_agent.AutonomousAgent.load("../escape")

    def test_run_retries_then_completes(self):
        agent = autonomous_agent.AutonomousAgent("test")
        agent.steps = [{"description":"x","tool":"file_controller","params":{},"status":"pending","result":"","retries":0}]
        calls = {"n": 0}
        def execute(step):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("temporary")
            return "ok"
        with tempfile.TemporaryDirectory() as td, patch.object(autonomous_agent, "TASKS_DIR", Path(td)):
            agent.run(execute)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(agent.steps[0]["status"], autonomous_agent.STATUS_DONE)


class BrainRouterTests(unittest.TestCase):
    def test_simple_command(self):
        self.assertEqual(classify_task("what time is it"), "simple")

    def test_complex_command(self):
        self.assertEqual(classify_task("debug this Python function"), "complex")


if __name__ == "__main__":
    unittest.main()
