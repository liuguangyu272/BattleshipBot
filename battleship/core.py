from __future__ import annotations

from dataclasses import dataclass, asdict
from functools import lru_cache
import hashlib
import json
import random
from pathlib import Path


@dataclass(frozen=True)
class Rules:
    size: int = 10
    fleet: tuple[int, ...] = (5, 4, 3, 3, 2)
    rule_id: str = "local-classic-touching-v1"

    def __post_init__(self):
        if type(self.size) is not int or not 2 <= self.size <= 20 or not self.fleet:
            raise ValueError("size must be 2..20, fleet must not be empty")
        if any(type(x) is not int or not 1 <= x <= self.size for x in self.fleet):
            raise ValueError("invalid ship length")
        if sum(self.fleet) > self.size ** 2:
            raise ValueError("fleet exceeds board")

    def to_dict(self):
        return {"size": self.size, "fleet": list(self.fleet), "rule_id": self.rule_id}

    @classmethod
    def from_dict(cls, value):
        if value.get("rule_id", cls.rule_id) != cls.rule_id:
            raise ValueError("unsupported rules: need an explicit adapter")
        return cls(value["size"], tuple(value["fleet"]))


def seed_for(seed, *labels):
    """Stable across Python processes; never disclose referee's seed to bots."""
    raw = json.dumps([seed, *labels], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def mask_of(cells):
    return sum(1 << c for c in set(cells))


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@lru_cache(maxsize=128)
def placements(size, length):
    result = []
    for r in range(size):
        for c in range(size):
            if c + length <= size:
                cells = tuple(r * size + c + k for k in range(length))
                result.append((mask_of(cells), cells))
            if length > 1 and r + length <= size:
                cells = tuple((r + k) * size + c for k in range(length))
                result.append((mask_of(cells), cells))
    return tuple(result)


def validate_fleet(fleet, rules=Rules()):
    if not isinstance(fleet, (list, tuple)) or len(fleet) != len(rules.fleet):
        raise ValueError("wrong number of ships")
    occupied = 0
    clean = []
    for ship, length in zip(fleet, rules.fleet):
        if not isinstance(ship, (list, tuple)) or len(ship) != length:
            raise ValueError("wrong ship length or order")
        if any(type(c) is not int or not 0 <= c < rules.size ** 2 for c in ship):
            raise ValueError("invalid cell")
        cells = tuple(sorted(ship))
        m = mask_of(cells)
        if m.bit_count() != length or m not in {p[0] for p in placements(rules.size, length)}:
            raise ValueError("ships must be straight contiguous unique cells")
        if occupied & m:
            raise ValueError("overlapping ships")
        occupied |= m
        clean.append(cells)
    return tuple(clean)


def deploy(rng, rules=Rules(), style="uniform"):
    """uniform = independent labeled placements with whole-fleet rejection.

    This is uniform over legal labeled fleets, unlike sequential rejection.
    Biased styles intentionally stress a uniform-prior attacker.
    """
    if style == "mixed":
        style = rng.choices(["uniform", "edge", "cluster", "spread"], [5, 2, 1, 2])[0]
    if style not in ("uniform", "edge", "cluster", "spread"):
        raise ValueError("unknown deployment style")
    pools = [placements(rules.size, n) for n in rules.fleet]
    if style == "uniform":
        for _ in range(20000):
            chosen = [rng.choice(p) for p in pools]
            union = 0
            for m, _ in chosen:
                if m & union:
                    break
                union |= m
            else:
                return tuple(p[1] for p in chosen)
        raise ValueError("could not sample fleet; board may be too dense")
    anchor = rng.randrange(rules.size ** 2)
    for _ in range(1000):
        chosen, occupied = [], 0
        for pool in pools:
            candidates = [(m, cells) for m, cells in pool if not occupied & m]
            if not candidates:
                break
            weights = []
            for _, cells in candidates:
                edge = sum(min(c // rules.size, c % rules.size,
                               rules.size - 1 - c // rules.size,
                               rules.size - 1 - c % rules.size) for c in cells) / len(cells)
                dist = sum(abs(c // rules.size - anchor // rules.size) +
                           abs(c % rules.size - anchor % rules.size) for c in cells) / len(cells)
                weights.append((1 / (1 + edge) ** 2) if style == "edge" else
                               (1 / (1 + dist) ** 3) if style == "cluster" else
                               (1 + dist) ** 2)
            m, cells = rng.choices(candidates, weights)[0]
            chosen.append(cells)
            occupied |= m
        else:
            return tuple(chosen)
    raise ValueError("could not deploy fleet")


class Target:
    """Referee-only hidden board. Bots receive observation(), never this object."""
    def __init__(self, fleet, rules=Rules()):
        self.rules = rules
        self.fleet = validate_fleet(fleet, rules)
        self.masks = tuple(mask_of(s) for s in self.fleet)
        self.occupied = 0
        for m in self.masks:
            self.occupied |= m
        self.shots = 0
        self.grid = [0] * (rules.size ** 2)  # 0 unknown, 1 miss, 2 hit, 3 sunk
        self.sunk = []

    def fire(self, cell):
        if type(cell) is not int or not 0 <= cell < self.rules.size ** 2:
            raise ValueError("shot out of bounds or not an integer")
        bit = 1 << cell
        if bit & self.shots:
            raise ValueError("duplicate shot")
        self.shots |= bit
        self.grid[cell] = 1
        result = {"cell": cell, "result": "miss"}
        if bit & self.occupied:
            self.grid[cell] = 2
            result["result"] = "hit"
            for ship, m in zip(self.fleet, self.masks):
                if bit & m and m & self.shots == m:
                    self.sunk.append(list(ship))
                    for c in ship:
                        self.grid[c] = 3
                    result.update(result="sunk", sunk=list(ship), length=len(ship))
                    break
        return result

    @property
    def done(self):
        return self.occupied & self.shots == self.occupied

    def observation(self):
        remaining = list(self.rules.fleet)
        for ship in self.sunk:
            remaining.remove(len(ship))
        return {"rules": self.rules.to_dict(), "grid": self.grid.copy(),
                "remaining": remaining, "sunk": [s.copy() for s in self.sunk],
                "legal_actions": [i for i, x in enumerate(self.grid) if x == 0],
                "shots_taken": self.shots.bit_count(), "done": self.done}


class Game:
    def __init__(self, fleets, rules=Rules(), first=0):
        if type(first) is not int or first not in (0, 1):
            raise ValueError("first must be 0 or 1")
        self.rules = rules
        self.boards = [Target(f, rules) for f in fleets]
        if len(self.boards) != 2:
            raise ValueError("need two fleets")
        self.first = self.turn = first
        self.winner = None
        self.events = []

    def observe(self, player):
        if player not in (0, 1):
            raise ValueError("invalid player")
        obs = self.boards[1 - player].observation()
        # Own board is legal information, but attack implementations deliberately ignore it.
        obs.update(player=player, to_move=self.turn, winner=self.winner,
                   own_fleet=[list(s) for s in self.boards[player].fleet],
                   incoming=self.boards[player].grid.copy())
        return obs

    def step(self, player, action):
        if type(player) is not int or player not in (0, 1):
            raise ValueError("invalid player")
        if self.winner is not None:
            raise ValueError("game is over")
        if player != self.turn:
            raise ValueError("wrong turn")
        result = self.boards[1 - player].fire(action)
        self.events.append({"ply": len(self.events), "player": player, **result})
        if self.boards[1 - player].done:
            self.winner = player
        else:
            self.turn = 1 - player
        return result

    def replay(self):
        return {"schema": 1, "visibility": "REFEREE_FULL_STATE_POSTGAME_ONLY",
                "rules": self.rules.to_dict(), "first": self.first,
                "fleets": [[list(s) for s in b.fleet] for b in self.boards],
                "events": self.events.copy(), "winner": self.winner}


def verify_replay(data):
    game = Game(data["fleets"], Rules.from_dict(data["rules"]), data["first"])
    for event in data["events"]:
        game.step(event["player"], event["cell"])
        if game.events[-1] != event:
            raise ValueError("replay feedback mismatch")
    if game.winner != data["winner"]:
        raise ValueError("replay winner mismatch")
    return game


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
