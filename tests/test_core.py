import copy
import json
import random
import unittest

from battleship.core import Rules, Game, Target, deploy, placements, validate_fleet, verify_replay
from battleship.protocol import validate_observation


class RulesTests(unittest.TestCase):
    def test_fleet_geometry(self):
        r = Rules(5, (3, 2))
        self.assertEqual(validate_fleet([[0, 1, 2], [5, 6]], r), ((0, 1, 2), (5, 6)))
        for fleet in ([[0, 1, 5], [6, 7]], [[0, 1, 2], [2, 3]], [[0, 0, 1], [5, 6]],
                      [[3, 4, 5], [6, 7]], [[0, 1, 2], [24, 25]], [[True, 1, 2], [5, 6]]):
            with self.assertRaises(ValueError):
                validate_fleet(fleet, r)

    def test_feedback_remaining_touching_and_terminal(self):
        target = Target([[0, 1, 2], [5, 6, 7], [3, 4]], Rules(5, (3, 3, 2)))
        self.assertEqual(target.fire(0), {"cell": 0, "result": "hit"})
        target.fire(1)
        self.assertEqual(target.fire(2)["sunk"], [0, 1, 2])
        self.assertEqual(target.observation()["remaining"], [3, 2])
        self.assertEqual(target.grid[3], 0)  # touching is allowed, no auto-water
        self.assertEqual(target.fire(24)["result"], "miss")
        for c in [3, 4, 5, 6, 7]:
            target.fire(c)
        self.assertTrue(target.done)
        validate_observation(target.observation(), target.rules)

    def test_illegal_is_atomic(self):
        g = Game([[[0, 1]], [[2, 3]]], Rules(4, (2,)))
        for player, action in [(1, 4), (0, -1), (0, 16), (0, True), (0, 1.0)]:
            before = g.replay()
            with self.assertRaises(ValueError):
                g.step(player, action)
            self.assertEqual(before, g.replay())
        g.step(0, 2)
        self.assertEqual(g.turn, 1)  # no extra turn on hit
        g.step(1, 15)
        with self.assertRaises(ValueError):
            g.step(0, 2)
        g.step(0, 3)
        self.assertEqual(g.winner, 0)
        with self.assertRaises(ValueError):
            g.step(1, 0)

    def test_observation_isolation(self):
        rules = Rules(4, (2,))
        a = Game([[[0, 1]], [[2, 3]]], rules)
        b = Game([[[0, 1]], [[6, 7]]], rules)
        self.assertEqual(a.observe(0), b.observe(0))
        observation = a.observe(0)
        self.assertFalse(any(k in observation for k in ("seed", "fleets", "enemy_fleet", "occupied")))
        observation["grid"][0] = 2
        observation["own_fleet"][0][0] = 15
        observation["rules"]["fleet"][0] = 4
        self.assertEqual(a.observe(0), b.observe(0))

    def test_seeded_deploy_valid_diverse(self):
        for style in ["uniform", "mixed", "edge", "cluster", "spread"]:
            for seed in range(50):
                f = deploy(random.Random(seed), style=style)
                validate_fleet(f)
                self.assertEqual(f, deploy(random.Random(seed), style=style))
        self.assertNotEqual(deploy(random.Random(1)), deploy(random.Random(2)))

    def test_replay_rejects_tampering(self):
        g = Game([[[0, 1]], [[2, 3]]], Rules(4, (2,)))
        g.step(0, 2)
        g.step(1, 0)
        g.step(0, 3)
        self.assertEqual(verify_replay(g.replay()).winner, 0)
        data = copy.deepcopy(g.replay())
        data["events"][0]["result"] = "miss"
        with self.assertRaises(ValueError):
            verify_replay(data)


if __name__ == "__main__":
    unittest.main()
