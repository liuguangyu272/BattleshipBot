import copy
from pathlib import Path
import random
import sys
import unittest

from battleship.core import Rules, Target, deploy
from battleship.protocol import SubprocessBot, validate_observation
from battleship.webui import Session


class ProtocolUITests(unittest.TestCase):
    def test_real_subprocess_game(self):
        root = Path(__file__).resolve().parents[1]
        bot = SubprocessBot({"argv": [sys.executable, "-m", "battleship", "protocol"], "cwd": str(root)})
        try:
            bot.reset(Rules().to_dict(), 617)
            from battleship.core import validate_fleet
            validate_fleet(bot.place())
            target = Target(deploy(random.Random(917)))
            while not target.done:
                target.fire(bot.act(target.observation()))
        finally:
            bot.close()
        self.assertIsNotNone(bot.process.poll())

    def test_hard_deadline_kills_child(self):
        bot = SubprocessBot({"argv": [sys.executable, "-c", "import time; time.sleep(10)"], "timeout_ms": 100, "setup_timeout_ms": 100})
        with self.assertRaises(TimeoutError):
            bot.reset(Rules().to_dict(), 1)
        self.assertIsNotNone(bot.process.poll())

    def test_observation_validator(self):
        obs = Target(deploy(random.Random(27))).observation()
        validate_observation(obs, Rules())
        for key, value in [("remaining", [5]), ("grid", [0]), ("done", True), ("legal_actions", [1])]:
            broken = copy.deepcopy(obs)
            broken[key] = value
            with self.assertRaises(ValueError):
                validate_observation(broken, Rules())

    def test_ui_full_demo_and_human(self):
        for mode in ("human", "demo"):
            session = Session(mode, seed=764)
            view = session.view()
            self.assertIsNone(view["enemy_fleet"])
            while session.game.winner is None:
                view = session.step(view["observation"]["legal_actions"][0] if mode == "human" else None)
                if view["observation"]["winner"] is None:
                    self.assertIsNone(view["enemy_fleet"])
            self.assertIsNotNone(view["enemy_fleet"])
            self.assertTrue(view["replay"])


if __name__ == "__main__":
    unittest.main()
