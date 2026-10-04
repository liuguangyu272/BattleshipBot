from dataclasses import replace
import itertools
from pathlib import Path
import random
import tempfile
import unittest

from battleship.arena import play, attack_trial
from battleship.bots import Policy, make_bot, PosteriorBot
from battleship.core import Rules, Target, placements, mask_of, deploy


class BotTests(unittest.TestCase):
    def test_all_bots_complete_games(self):
        for name in ["random", "hunt", "density", "admiral", "joint"]:
            for seed in range(3):
                with self.subTest(name=name, seed=seed):
                    record, replay = play((name, "density"), seed, first=seed % 2)
                    self.assertFalse(record["faults"])
                    self.assertIn(record["winner"], (0, 1))
                    self.assertLessEqual(record["plies"], 199)
                    from battleship.core import verify_replay
                    verify_replay(replay)

    def test_save_reload_reproduces_entire_trajectory(self):
        p = Policy(hunt_power=.5, samples=32)
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            path = Path(temp)/"policy.json"
            p.save(path)
            self.assertEqual(Policy.load(path), p)
            a = make_bot("admiral", p)
            b = make_bot(str(path))
            for bot in (a, b):
                bot.reset(Rules().to_dict(), 1234)
            target = Target(deploy(random.Random(5830)))
            while not target.done:
                obs = target.observation()
                aa, bb = a.act(obs), b.act(obs)
                self.assertEqual(aa, bb)
                target.fire(aa)

    def test_independent_brute_force_posterior(self):
        rules = Rules(4, (3, 2))
        target = Target([[0, 1, 2], [7, 11]], rules)
        target.fire(1)
        target.fire(15)
        obs = target.observation()
        p = Policy(sink_bonus=0, exact_limit=1000000)
        bot = PosteriorBot(p)
        bot.reset(rules.to_dict(), 191)
        hits, pools = bot.candidates(obs)
        scores = bot.posterior(obs, hits, pools)
        totals, count = [0]*16, 0
        for left, right in itertools.product(placements(4, 3), placements(4, 2)):
            if left[0] & right[0]:
                continue
            union = left[0] | right[0]
            if not union & (1 << 1) or union & (1 << 15):
                continue
            count += 1
            for c in obs["legal_actions"]:
                totals[c] += bool(union & (1 << c))
        for c in obs["legal_actions"]:
            self.assertAlmostEqual(scores[c], totals[c]/count)
        bot = PosteriorBot(replace(p, exact_limit=0, samples=10000))
        bot.reset(rules.to_dict(), 191)
        sampled = bot.posterior(obs, hits, pools)
        for c in obs["legal_actions"]:
            self.assertAlmostEqual(sampled[c], scores[c], delta=.035)

    def test_adjacent_ships_ambiguous_hits(self):
        rules = Rules(5, (3, 2))
        target = Target([[0, 1, 2], [6, 11]], rules)
        for c in (1, 6):
            target.fire(c)
        bot = PosteriorBot()
        bot.reset(rules.to_dict(), 91)
        while not target.done:
            before = target.observation()
            action = bot.act(before)
            self.assertIn(action, before["legal_actions"])
            target.fire(action)

    def test_bot_does_not_mutate_observation(self):
        import copy
        target = Target(deploy(random.Random(837)))
        obs = target.observation()
        before = copy.deepcopy(obs)
        bot = make_bot("admiral")
        bot.reset(Rules().to_dict(), 8)
        bot.act(obs)
        self.assertEqual(obs, before)

    def test_policy_rejects_nonfinite(self):
        for p in [Policy(samples=-1), Policy(sink_bonus=float("nan")), Policy(joint_mix=2), Policy(mode="cheat")]:
            with self.assertRaises(ValueError):
                p.validate()

    def test_bellman_exact_two_endpoints(self):
        rules = Rules(4, (2,))
        target = Target([[4, 5]], rules)
        for c in [5, 1, 9]:
            target.fire(c)
        bot = make_bot("density", Policy(mode="density", endgame_limit=10))
        bot.reset(rules.to_dict(), 72)
        action = bot.act(target.observation())
        self.assertIn(action, (4, 6))
        self.assertEqual(bot.diagnostics["method"], "bellman_endgame")
        self.assertAlmostEqual(bot.diagnostics["expected_shots"], 1.5)

    def test_defensive_placement_valid_and_reproducible(self):
        p = Policy(defense_candidates=3)
        a, b = make_bot("admiral", p), make_bot("admiral", p)
        for bot in (a, b):
            bot.reset(Rules().to_dict(), 333)
        self.assertEqual(a.place(), b.place())

    def test_faults_forfeit_and_cleanup(self):
        from unittest.mock import patch
        from battleship.bots import RandomBot
        class Bad(RandomBot):
            closed = False
            def act(self, obs):
                return -1
            def close(self):
                self.closed = True
        bad = Bad()
        with patch("battleship.arena.make_bot", side_effect=[bad, RandomBot()]):
            result, _ = play()
        self.assertEqual(result["winner"], 1)
        self.assertEqual(result["faults"][0]["type"], "ValueError")
        self.assertTrue(bad.closed)


if __name__ == "__main__":
    unittest.main()
