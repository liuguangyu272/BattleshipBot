import copy
from dataclasses import replace
from pathlib import Path
import random
import tempfile
import unittest

from battleship.bots import Policy, PosteriorBot
from battleship.context_bot import ContextBot, ContextConfig
from battleship.core import Game, Rules, Target, deploy


class ContextTests(unittest.TestCase):
    def test_save_reload_same_complete_trajectory(self):
        rules = Rules(5, (3, 2))
        a = ContextBot(Policy(samples=32, endgame_limit=6), ContextConfig(mix=.75))
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            path = Path(temp) / "context.json"
            a.save(path)
            b = ContextBot.load(path)
            for bot in (a, b):
                bot.reset(rules.to_dict(), 483)
            target = Target([[0, 1, 2], [14, 19]], rules)
            while not target.done:
                observation = target.observation()
                before = copy.deepcopy(observation)
                action = a.act(observation)
                self.assertEqual(action, b.act(observation))
                self.assertEqual(observation, before)
                self.assertIn(action, observation["legal_actions"])
                target.fire(action)

    def test_publicly_indistinguishable_states(self):
        rules = Rules(5, (3, 2))
        a = Game([[[0, 1, 2], [5, 6]], [[0, 1, 2], [8, 9]]], rules)
        b = Game([[[0, 1, 2], [5, 6]], [[0, 1, 2], [18, 19]]], rules)
        for game in (a, b):
            for cell in (0, 1, 2, 24):
                game.boards[1].fire(cell)
        left, right = ContextBot(), ContextBot()
        for bot in (left, right):
            bot.reset(rules.to_dict(), 87)
        self.assertEqual(a.observe(0), b.observe(0))
        self.assertEqual(left.act(a.observe(0)), right.act(b.observe(0)))
        self.assertEqual(left.last_model_weights, right.last_model_weights)

    def test_disabled_context_reproduces_champion(self):
        a = ContextBot(context=ContextConfig(mix=0))
        b = PosteriorBot(replace(a.policy))
        for bot in (a, b):
            bot.reset(Rules().to_dict(), 212)
        target = Target(deploy(random.Random(131)))
        while not target.done:
            observation = target.observation()
            action = a.act(observation)
            self.assertEqual(action, b.act(observation))
            target.fire(action)

    def test_misses_and_sunk_update_finite_normalized_weights(self):
        rules = Rules(5, (3, 2))
        target = Target([[0, 1, 2], [8, 9]], rules)
        bot = ContextBot()
        bot.reset(rules.to_dict(), 87)
        bot.contextual_scores(target.observation())
        initial = dict(bot.last_model_weights)
        for cell in (0, 1, 2, 24):
            target.fire(cell)
        scores = bot.contextual_scores(target.observation())
        self.assertNotEqual(initial, bot.last_model_weights)
        self.assertAlmostEqual(sum(bot.last_model_weights.values()), 1)
        self.assertGreaterEqual(bot.last_model_weights["uniform"], bot.context.uniform_floor)
        for cell, value in enumerate(target.grid):
            if value:
                self.assertEqual(scores[cell], 0)

    def test_config_rejects_invalid_values(self):
        for config in (ContextConfig(mix=2), ContextConfig(temperature=float("nan")),
                       ContextConfig(cluster_prior=.9, edge_prior=.8)):
            with self.assertRaises(ValueError):
                config.validate()


if __name__ == "__main__":
    unittest.main()
