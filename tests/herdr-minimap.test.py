#!/usr/bin/python3
"""tools/herdr-minimap/minimap.py: the fan's shape, the states it shows, and which agents count as at work."""
import importlib.util
import json
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location("minimap", os.path.join(HERE, "..", "herdr-minimap", "minimap.py"))
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)
mm.COLOR = False


def crewmate(task, state="working", agents=(), name="🌸 Robin"):
    return {"task": task, "name": name, "kind": "ship", "state": state, "agents": list(agents), "project": "webapp",
            "model": "opus", "effort": "high", "age": 600, "prs": ["#1234"],
            "events": [(1794412758, "paused", "both PRs green")]}


class Chart(unittest.TestCase):
    def draw(self, *crew, width=64):
        return mm.frame_lines({"root": "👒 Luffy", "root_state": "working", "crew": list(crew)}, width)

    def test_the_root_sits_on_top_and_fans_down_to_each_crewmate(self):
        lines = self.draw(crewmate("a"), crewmate("b", name="🐟 Jinbe"), crewmate("c", name="🤖 Franky"))
        self.assertIn("👒 Luffy", lines[0])
        bar = next(l for l in lines if "╭" in l)
        self.assertEqual((bar.count("╭"), bar.count("┼"), bar.count("╮")), (1, 1, 1), bar)
        stem = lines[lines.index(bar) - 1]
        self.assertEqual(stem.index("│"), bar.index("┼"), "the root's stem meets the bar")
        names = lines[lines.index(bar) + 2]
        self.assertLess(names.index("Robin"), names.index("Jinbe"))
        self.assertLess(names.index("Jinbe"), names.index("Franky"))

    def test_two_crewmates_meet_the_stem_between_them(self):
        bar = next(l for l in self.draw(crewmate("a"), crewmate("b")) if "╭" in l)
        self.assertIn("┴", bar)

    def test_each_column_says_what_the_crewmate_is_doing_and_where(self):
        text = "\n".join(self.draw(crewmate("ci-tidy", agents=[("GitHub lane", True, 1), ("Slack", False, 1)])))
        for want in ("◐ working", "ci-tidy", "webapp · opus high", "⏱ 10m", "#1234", "● GitHub lane", "○ Slack"):
            self.assertIn(want, text)

    def test_a_crewmate_waiting_on_the_captain_is_counted_at_the_top(self):
        lines = self.draw(crewmate("a", state="decision"))
        self.assertIn("1 need you", lines[2])
        self.assertIn("◆ needs you", "\n".join(lines))

    def test_the_deck_log_lists_the_latest_events(self):
        text = "\n".join(self.draw(crewmate("a")))
        self.assertIn("deck log", text)
        self.assertIn("paused both PRs green", text)

    def test_no_crew_is_calm(self):
        self.assertIn("calm seas", " ".join(self.draw()))

    def test_lines_fit_the_width(self):
        long = crewmate("a-very-long-task-name-that-will-not-fit", agents=[("a description far too long " * 3, True, 2)])
        for width in (30, 40, 64):
            for line in self.draw(long, crewmate("b"), crewmate("c"), crewmate("d"), width=width):
                self.assertLessEqual(mm.cells(line), width, line)


class States(unittest.TestCase):
    def test_a_decision_beats_working_and_a_lost_pane_is_adrift(self):
        self.assertEqual(mm.state_of({"agent_status": "working"}, "decision"), "decision")
        self.assertEqual(mm.state_of({"agent_status": "blocked"}, ""), "decision")
        self.assertEqual(mm.state_of(None, ""), "adrift")
        self.assertEqual(mm.state_of({"agent_status": "idle"}, "paused"), "paused")
        self.assertEqual(mm.state_of({"agent_status": "idle"}, ""), "idle")

    def test_the_status_log_waits_until_its_decision_is_resolved(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "state"))
            path = os.path.join(home, "state", "t.status")
            old, mm.FM_HOME = mm.FM_HOME, home
            try:
                open(path, "w").write("working: setup\nneeds-decision [key=k]: which\nnote: x\n")
                self.assertEqual(mm.task_wait("t"), "decision")
                open(path, "a").write("resolved [key=k]: answered\n")
                self.assertEqual(mm.task_wait("t"), "")
                open(path, "a").write("paused: waiting on checks\n")
                self.assertEqual(mm.task_wait("t"), "paused")
            finally:
                mm.FM_HOME = old

    def test_the_tab_bar_line_names_each_crewmate_with_its_agents_at_work(self):
        line = mm.line_text({"crew": [crewmate("a", agents=[("x", True, 1), ("y", True, 1), ("z", False, 1)]),
                                      crewmate("b", state="decision")]})
        self.assertEqual(line, "⛵⇉ 🌸◐² 🌸◆")
        self.assertEqual(mm.line_text({"crew": []}), "", "no crew hides the entry")


class Agents(unittest.TestCase):
    def test_recent_transcripts_are_at_work_and_old_ones_drop_off(self):
        with tempfile.TemporaryDirectory() as home:
            folder = os.path.join(home, ".claude", "projects", "p", "sid", "subagents")
            os.makedirs(folder)
            now = time.time()
            for name, age in (("busy", 10), ("finished", 300), ("stale", 5000)):
                json.dump({"description": name, "spawnDepth": 1}, open(os.path.join(folder, f"agent-{name}.meta.json"), "w"))
                transcript = os.path.join(folder, f"agent-{name}.jsonl")
                open(transcript, "w").close()
                os.utime(transcript, (now - age, now - age))
            old = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                self.assertEqual(mm.subagents("sid", now), [("busy", True, 1), ("finished", False, 1)])
                self.assertEqual(mm.subagents("", now), [])
            finally:
                os.environ["HOME"] = old


if __name__ == "__main__":
    unittest.main()
