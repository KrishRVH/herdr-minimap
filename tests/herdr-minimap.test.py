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
        for width in (30, 40, 64, 90):
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


SNAP = {"focused_workspace_id": "w1", "focused_pane_id": "w1:p1", "focused_tab_id": "w1:t1",
        "workspaces": [{"workspace_id": "w1", "number": 1, "label": "first mate", "agent_status": "working"},
                       {"workspace_id": "w2", "number": 2, "label": "└ ci-tidy · p:6uAob5", "agent_status": "done"},
                       {"workspace_id": "w3", "number": 3, "label": "⚓ captain's deck", "agent_status": "unknown"},
                       {"workspace_id": "w4", "number": 4, "label": "notes", "agent_status": "idle"}],
        "agents": [{"pane_id": "w1:p1", "display_agent": "👒 Luffy", "agent_status": "working", "workspace_id": "w1",
                    "terminal_title_stripped": "CI rework"},
                   {"pane_id": "w2:p2", "display_agent": "🌸 Robin", "agent_status": "blocked", "workspace_id": "w2"}],
        "layouts": [{"tab_id": "w1:t1", "workspace_id": "w1", "zoomed": False, "area": {"width": 200},
                     "panes": [{"pane_id": "w1:p1", "rect": {"x": 0, "y": 0, "width": 120, "height": 60}},
                               {"pane_id": "w1:p3", "rect": {"x": 120, "y": 0, "width": 80, "height": 20}},
                               {"pane_id": "w1:p4", "rect": {"x": 120, "y": 20, "width": 80, "height": 40}}]},
                    {"tab_id": "w2:t1", "workspace_id": "w2", "zoomed": False, "panes": []},
                    {"tab_id": "w3:t1", "workspace_id": "w3", "zoomed": False, "panes": []},
                    {"tab_id": "w4:t1", "workspace_id": "w4", "zoomed": True, "panes": []}]}


class Nav(unittest.TestCase):
    def data(self):
        crew = [dict(crewmate("ci-tidy"), space="w2", pane="w2:p2")]
        data = {"root": "👒 Luffy", "root_pane": "w1:p1", "root_state": "working", "crew": crew}
        data.update(mm.places(SNAP, crew))
        return data

    def test_spaces_name_the_crewmate_and_mark_crew_and_deck_spaces(self):
        spaces = self.data()["spaces"]
        self.assertEqual([s["label"] for s in spaces], ["first mate", "🌸 Robin · ci-tidy", "⚓ captain's deck", "notes"])
        self.assertEqual([(s["crew"], s["deck"], s["here"]) for s in spaces],
                         [(False, False, True), (True, False, False), (False, True, False), (False, False, False)])
        self.assertEqual(mm.space_label({"label": "└ grt · p:xyz", "number": 5}, []), "grt")

    def test_crew_spaces_and_their_agents_hang_under_the_first_mate(self):
        snap = {"workspaces": [{"workspace_id": "w1", "number": 1, "label": "first mate"},
                               {"workspace_id": "w3", "number": 2, "label": "⚓ captain's deck"},
                               {"workspace_id": "w2", "number": 3, "label": "└ ci-tidy · p:a"},
                               {"workspace_id": "w5", "number": 4, "label": "2ndmate-ops"},
                               {"workspace_id": "w6", "number": 5, "label": "└ sweep · p:b"},
                               {"workspace_id": "w7", "number": 6, "label": "└ grt · p:c"}],
                "panes": [{"pane_id": "w1:p1", "workspace_id": "w1"}],
                "agents": [{"pane_id": "w6:p1", "workspace_id": "w6"}, {"pane_id": "w2:p2", "workspace_id": "w2"},
                           {"pane_id": "w1:p1", "workspace_id": "w1"}, {"pane_id": "w5:p1", "workspace_id": "w5"}]}
        crew = [dict(crewmate("ci-tidy"), space="w2")]
        out = mm.places(snap, crew, "w1:p1")
        self.assertEqual([(s["id"], s["depth"], s["last"]) for s in out["spaces"]],
                         [("w1", 0, False), ("w2", 1, True), ("w3", 0, False), ("w5", 0, False), ("w6", 1, False),
                          ("w7", 1, True)], "this home's crew under the first mate; other └ spaces under their owner")
        self.assertEqual({a["pane"]: a["depth"] for a in out["agents"]},
                         {"w1:p1": 0, "w2:p2": 1, "w5:p1": 0, "w6:p1": 1})
        order = [a["pane"] for a in out["agents"]]
        self.assertEqual(order[order.index("w1:p1") + 1], "w2:p2", "Robin's agent right under the first mate's")
        self.assertEqual(order[order.index("w5:p1") + 1], "w6:p1")

    def test_agents_carry_herdr_state_and_their_space_number(self):
        agents = self.data()["agents"]
        self.assertEqual([(a["name"], a["state"], a["n"]) for a in agents],
                         [("👒 Luffy", "working", 1), ("🌸 Robin", "decision", 2)])

    def test_every_listed_place_is_pickable_and_clickable(self):
        hits = []
        lines, items = mm.nav_lines(self.data(), 60, cursor=1, hits=hits)
        self.assertEqual(items, [("space", "w1"), ("space", "w2"), ("space", "w3"), ("space", "w4"),
                                 ("agent", "w1:p1"), ("agent", "w2:p2")])
        for place in items:
            line = next(l for l, _, _, p in hits if p == place)
            self.assertTrue(lines[line].strip(), place)
        self.assertIn("▸", lines[2], "the cursor marks the second space")
        chart = next(i for i, l in enumerate(lines) if "fleet" in l)
        robin = [l for l, _, _, p in hits if p == ("agent", "w2:p2") and l > chart]
        self.assertTrue(any("Robin" in lines[l] for l in robin), "a crewmate's column in the chart is clickable too")
        self.assertEqual(mm.hit_at(hits, 5, next(l for l, _, _, p in hits if p == ("space", "w3"))), ("space", "w3"))
        self.assertIsNone(mm.hit_at(hits, 5, 0), "the section rule is not a place")

    def test_the_column_goes_into_every_tab_but_a_zoomed_one(self):
        snap = dict(SNAP, layouts=[dict(l, panes=l["panes"] or [{"pane_id": "x", "rect": {}}]) for l in SNAP["layouts"]])
        for tab in ("w1:t1", "w2:t1", "w3:t1"):
            self.assertTrue(mm.hostable(snap, tab)[0], tab)
        self.assertFalse(mm.hostable(snap, "w4:t1")[0], "zoomed")
        self.assertFalse(mm.hostable(snap, "nope")[0])

    def test_following_moves_the_column_only_when_focus_is_in_another_tab(self):
        moves = []
        old = mm.herdr
        mm.herdr = lambda *a, **k: moves.append(a) or {"move_result": {"pane": {"pane_id": "w1:p9", "tab_id": "w1:t1"}}}
        try:
            self.assertEqual(mm.follow(SNAP, {"pane_id": "w1:p3", "tab_id": "w1:t1"})["pane_id"], "w1:p3")
            self.assertEqual(moves, [], "already in the focused tab")
            self.assertEqual(mm.follow(SNAP, {"pane_id": "w2:p5", "tab_id": "w2:t1"})["pane_id"], "w1:p9")
            self.assertEqual(moves[0][:7], ("pane", "move", "w2:p5", "--tab", "w1:t1", "--target-pane", "w1:p4"))
            zoomed = dict(SNAP, focused_tab_id="w4:t1")
            self.assertEqual(mm.follow(zoomed, {"pane_id": "w2:p5", "tab_id": "w2:t1"})["pane_id"], "w2:p5")
            self.assertEqual(len(moves), 1, "a zoomed tab keeps the column out")
        finally:
            mm.herdr = old

    def test_the_column_splits_off_the_tallest_pane_on_the_right_edge(self):
        layout = SNAP["layouts"][0]
        self.assertEqual(mm.right_edge(layout)["pane_id"], "w1:p4")
        self.assertAlmostEqual(mm.ratio_for(200), 1 - mm.WIDTH / 200)
        self.assertEqual(mm.ratio_for(80), 0.5, "a narrow pane keeps at least half")

    def test_keys_clicks_and_the_wheel(self):
        self.assertEqual(mm.keys_of(b"\x1b[A\x1b[Bj\r\x1b"), [("up",), ("down",), ("char", "j"), ("enter",), ("esc",)])
        self.assertEqual(mm.keys_of(b"\x1b[<0;12;4M\x1b[<0;12;4m"), [("click", 11, 3)])
        self.assertEqual(mm.keys_of(b"\x1b[<64;1;1M\x1b[<65;1;1M"), [("wheel", -1), ("wheel", 1)])
        self.assertEqual(mm.keys_of(b"\x1b[I2"), [("char", "2")], "a focus report is skipped")
        self.assertEqual(mm.keys_of("é".encode()), [], "a wider character is no key, not an empty q")


if __name__ == "__main__":
    unittest.main()
