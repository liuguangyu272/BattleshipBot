from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from pathlib import Path
from functools import lru_cache
import math
import random
from typing import Protocol

from .core import Rules, Target, bits, mask_of, placements, deploy, save_json


class Bot(Protocol):
    def reset(self, rules: dict, seed: int) -> None: ...
    def place(self) -> list[list[int]]: ...
    def act(self, observation: dict) -> int: ...


class RandomBot:
    def reset(self, rules, seed):
        self.rules = Rules.from_dict(rules)
        self.rng = random.Random(seed)

    def place(self):
        return deploy(self.rng, self.rules)

    def act(self, obs):
        return self.rng.choice(obs["legal_actions"])


class HuntBot(RandomBot):
    """Parity hunt, adjacency pursuit with aligned double-hit preference."""
    def act(self, obs):
        grid, n = obs["grid"], self.rules.size
        legal = obs["legal_actions"]
        targets = {}
        for c, v in enumerate(grid):
            if v != 2:
                continue
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                r, col = divmod(c, n)
                nr, nc = r + dr, col + dc
                if 0 <= nr < n and 0 <= nc < n and grid[nr*n+nc] == 0:
                    behind_r, behind_c = r-dr, col-dc
                    aligned = (0 <= behind_r < n and 0 <= behind_c < n and
                               grid[behind_r*n+behind_c] == 2)
                    t = nr*n+nc
                    targets[t] = targets.get(t, 0) + (8 if aligned else 1)
        if targets:
            best = max(targets.values())
            return self.rng.choice([c for c, v in targets.items() if v == best])
        parity = [c for c in legal if (c // n + c % n) % 2 == 0]
        return self.rng.choice(parity or legal)


@dataclass
class Policy:
    version: int = 1
    mode: str = "hybrid"
    samples: int = 128
    hunt_power: float = 0.0
    length_power: float = 0.0
    target_power: float = 3.0
    sink_bonus: float = 0.15
    info_bonus: float = 0.0
    parity_bonus: float = 0.0
    edge_bias: float = 0.0
    target_bonus: float = 0.0
    joint_mix: float = 1.0
    exact_limit: int = 20000
    endgame_limit: int = 0
    defense_candidates: int = 0
    deployment: str = "mixed"

    def validate(self):
        if self.version != 1 or self.mode not in ("density", "hybrid", "joint", "constraint", "adaptive"):
            raise ValueError("unsupported policy")
        if type(self.samples) is not int or not 1 <= self.samples <= 10000:
            raise ValueError("samples must be 1..10000")
        if type(self.exact_limit) is not int or not 0 <= self.exact_limit <= 1000000:
            raise ValueError("invalid exact_limit")
        if type(self.endgame_limit) is not int or not 0 <= self.endgame_limit <= 20:
            raise ValueError("endgame_limit must be 0..20")
        if type(self.defense_candidates) is not int or not 0 <= self.defense_candidates <= 64:
            raise ValueError("defense_candidates must be 0..64")
        for key in ("hunt_power", "length_power", "target_power", "sink_bonus", "info_bonus", "parity_bonus", "edge_bias", "target_bonus", "joint_mix"):
            v = getattr(self, key)
            if not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 10:
                raise ValueError("invalid policy parameter: " + key)
        if not 0 <= self.joint_mix <= 1:
            raise ValueError("joint_mix must be 0..1")
        if self.deployment not in ("uniform", "mixed", "edge", "cluster", "spread"):
            raise ValueError("invalid deployment")
        return self

    def save(self, path):
        self.validate()
        save_json(path, asdict(self))

    @classmethod
    def load(cls, path):
        import json
        return cls(**json.loads(Path(path).read_text(encoding="utf-8"))).validate()


class DensityBot(RandomBot):
    """Placement heatmap baseline; all arithmetic uses public observation."""
    def __init__(self, policy=None):
        self.policy = (policy or Policy(mode="density", deployment="uniform")).validate()
        self.diagnostics = {}

    def place(self):
        if self.policy.defense_candidates:
            return self.defensive_place()
        return deploy(self.rng, self.rules, self.policy.deployment)

    def defensive_place(self):
        """Private randomized best response against multiple simulated attackers.

        Only our own candidate boards are inspected. The simulations are part of
        deployment, do not have access to the actual opponent's hidden state.
        """
        candidates = []
        for i in range(self.policy.defense_candidates):
            fleet = deploy(self.rng, self.rules, self.policy.deployment)
            costs = []
            for kind in ("hunt", "density", "density"):
                attacker = HuntBot() if kind == "hunt" else DensityBot(Policy(mode="density", hunt_power=(i % 2)))
                attacker.reset(self.rules.to_dict(), self.rng.getrandbits(64))
                target = Target(fleet, self.rules)
                while not target.done:
                    target.fire(attacker.act(target.observation()))
                costs.append(target.shots.bit_count())
            # Focus on probability attackers, retain a hunt term for diversity.
            score = .2 * costs[0] + .4 * costs[1] + .4 * costs[2]
            candidates.append((score, fleet))
        candidates.sort(key=lambda item: item[0], reverse=True)
        # Stochastic top-two selection avoids turning placement into a fixed pattern.
        return self.rng.choice(candidates[:min(2, len(candidates))])[1]

    def candidates(self, obs):
        blocked = mask_of(i for i, v in enumerate(obs["grid"]) if v in (1, 3))
        hits = mask_of(i for i, v in enumerate(obs["grid"]) if v == 2)
        pools = [[(m, c) for m, c in placements(self.rules.size, length)
                  if not m & blocked and m & hits != m] for length in obs["remaining"]]
        if len(pools) == 1 and hits:
            pools[0] = [p for p in pools[0] if p[0] & hits == hits]
        return hits, pools

    def density(self, obs, hits, pools):
        scores = [0.0] * len(obs["grid"])
        hunt = [0.0] * len(scores)
        for length, pool in zip(obs["remaining"], pools):
            norm = max(1, len(pool)) ** self.policy.hunt_power * length ** self.policy.length_power
            for m, cells in pool:
                h = (m & hits).bit_count()
                weight = h ** self.policy.target_power if h else 0
                if h == len(cells) - 1:
                    weight *= 1 + self.policy.sink_bonus
                for c in cells:
                    if obs["grid"][c] == 0:
                        hunt[c] += 1 / norm
                        scores[c] += weight
        return scores if hits and max(scores) > 0 else hunt

    def choose(self, obs, scores):
        legal, n = obs["legal_actions"], self.rules.size
        if not legal or obs["done"]:
            raise ValueError("no action in terminal observation")
        for c in legal:
            r, col = divmod(c, n)
            edge = min(r, col, n-1-r, n-1-col)
            scores[c] *= math.exp(-self.policy.edge_bias * edge)
            if not any(v == 2 for v in obs["grid"]):
                scores[c] *= 1 + self.policy.parity_bonus * ((r + col) % min(obs["remaining"]) == 0)
        best = max(scores[c] for c in legal)
        choice = self.rng.choice([c for c in legal if scores[c] >= best - 1e-10])
        self.last_scores = scores
        return choice

    def act(self, obs):
        hits, pools = self.candidates(obs)
        if self.policy.endgame_limit and len(pools) == 1 and len(pools[0]) <= self.policy.endgame_limit:
            action = self.solve_endgame(obs, hits, pools[0])
            if action is not None:
                return action
        self.diagnostics = {"method": "density"}
        return self.choose(obs, self.density(obs, hits, pools))

    def solve_endgame(self, obs, hits, pool):
        """Exact expected remaining shots for one uniformly distributed ship.

        A belief state is (consistent hypotheses, already-hit cells); misses are
        absent from every remaining hypothesis. All hit and miss branches are
        integrated. State budget fallback discards the incomplete search.
        """
        if not pool:
            return None
        masks = tuple(p[0] for p in pool)
        length = len(pool[0][1])
        initial = (1 << len(masks)) - 1
        calls = 0

        @lru_cache(maxsize=None)
        def solve(hypotheses, hitmask):
            nonlocal calls
            calls += 1
            if calls > 15000:
                raise OverflowError("endgame state cap")
            if hitmask.bit_count() == length:
                return 0.0, ()
            indices = tuple(bits(hypotheses))
            union = 0
            for i in indices:
                union |= masks[i]
            legal = union & ~hitmask
            best, choices = float("inf"), []
            # Equal partitions have equal action value; memoization shares futures.
            for cell in bits(legal):
                bit = 1 << cell
                yes = sum(1 << i for i in indices if masks[i] & bit)
                no = hypotheses ^ yes
                value = 1.0
                if yes:
                    value += yes.bit_count() / len(indices) * solve(yes, hitmask | bit)[0]
                if no:
                    value += no.bit_count() / len(indices) * solve(no, hitmask)[0]
                if value < best - 1e-9:
                    best, choices = value, [cell]
                elif abs(value-best) < 1e-9:
                    choices.append(cell)
            return best, tuple(choices)

        try:
            cost, choices = solve(initial, hits)
        except OverflowError:
            return None
        self.diagnostics = {"method": "bellman_endgame", "states": calls, "expected_shots": cost}
        return self.rng.choice(choices) if choices else None


class PosteriorBot(DensityBot):
    """Joint legal-fleet importance sampling + exact small endgame enumeration.

    At each step a deterministic uncovered hit chooses the next ship to place.
    Sampling a uniform feasible branch gives q=1/branch_count. Multiplying branch
    counts gives the importance weight 1/q. Complete no-hit ships in fixed index
    order. Failed proposals contribute zero, not a repaired biased configuration.
    """
    def __init__(self, policy=None):
        super().__init__(policy or Policy())

    def posterior(self, obs, hits, pools):
        scores = [0.0] * len(obs["grid"])
        sinks = [0.0] * len(scores)
        target_scores = [0.0] * len(scores)
        total = sumsq = 0.0
        accepted = 0
        unknown = mask_of(obs["legal_actions"])

        def record(chosen, weight):
            nonlocal total, sumsq, accepted
            accepted += 1
            total += weight
            sumsq += weight * weight
            for m, cells in chosen:
                un = m & unknown
                if un.bit_count() == 1:
                    sinks[un.bit_length() - 1] += weight
                for c in cells:
                    if obs["grid"][c] == 0:
                        scores[c] += weight
                        if m & hits:
                            target_scores[c] += weight

        combos = math.prod(len(pool) for pool in pools)
        if combos <= self.policy.exact_limit:
            def visit(i, occupied, chosen):
                if i == len(pools):
                    if hits & occupied == hits:
                        record(chosen, 1.0)
                    return
                for p in pools[i]:
                    if not p[0] & occupied:
                        visit(i+1, occupied | p[0], chosen + [p])
            visit(0, 0, [])
            method = "exact"
        else:
            # Preindex hit-covering placements. Duplicate lengths remain labeled.
            cover = {h: [(i, p) for i, pool in enumerate(pools) for p in pool if p[0] & (1 << h)]
                     for h in bits(hits)}
            for _ in range(self.policy.samples):
                unused = set(range(len(pools)))
                occupied, uncovered, weight, chosen = 0, hits, 1.0, []
                failed = False
                while uncovered:
                    branches = None
                    for h in bits(uncovered):
                        valid = [(i, p) for i, p in cover[h] if i in unused and not p[0] & occupied]
                        if branches is None or len(valid) < len(branches):
                            branches = valid
                        if not valid:
                            break
                    if not branches:
                        failed = True
                        break
                    weight *= len(branches)
                    i, p = self.rng.choice(branches)
                    chosen.append(p)
                    unused.remove(i)
                    occupied |= p[0]
                    uncovered &= ~p[0]
                if failed:
                    continue
                for i in sorted(unused):
                    valid = [p for p in pools[i] if not p[0] & occupied]
                    if not valid:
                        failed = True
                        break
                    weight *= len(valid)
                    p = self.rng.choice(valid)
                    chosen.append(p)
                    occupied |= p[0]
                if not failed:
                    record(chosen, weight)
            method = "importance"
        self.diagnostics = {"method": method, "accepted": accepted,
                            "ess": total * total / sumsq if sumsq else 0}
        if not total:
            return None
        for c in obs["legal_actions"]:
            p = scores[c] / total
            scores[c] = (p + self.policy.sink_bonus * sinks[c] / total + self.policy.info_bonus * p * (1-p)
                         + self.policy.target_bonus * target_scores[c] / total)
        return scores

    def act(self, obs):
        hits, pools = self.candidates(obs)
        if self.policy.endgame_limit and len(pools) == 1 and len(pools[0]) <= self.policy.endgame_limit:
            action = self.solve_endgame(obs, hits, pools[0])
            if action is not None:
                return action
        density = self.density(obs, hits, pools)
        use_joint = self.policy.mode == "joint" or (self.policy.mode == "hybrid" and (hits or len(pools) <= 2))
        scores = None
        hit_cells = tuple(bits(hits))
        ambiguous = (len(hit_cells) >= 2 and
                     len({c // self.rules.size for c in hit_cells}) > 1 and
                     len({c % self.rules.size for c in hit_cells}) > 1)
        if self.policy.mode == "adaptive" and ambiguous:
            scores = self.constrained_targets(obs, hits, pools)
        elif self.policy.mode == "constraint" and hits:
            scores = self.constrained_targets(obs, hits, pools)
        elif self.policy.mode == "constraint" and len(pools) <= 2:
            scores = self.posterior(obs, hits, pools)
        elif use_joint:
            scores = self.posterior(obs, hits, pools)
        if scores is None:
            self.diagnostics = {"method": "density" if not use_joint else "fallback"}
            scores = density
        elif self.policy.joint_mix < 1:
            ds = max(density) or 1
            ps = max(scores) or 1
            scores = [self.policy.joint_mix * p/ps + (1-self.policy.joint_mix) * d/ds
                      for p, d in zip(scores, density)]
        return self.choose(obs, scores)

    def constrained_targets(self, obs, hits, pools):
        """Deterministic enumeration of damaged-ship assignments.

        Integrate free ships using product of valid-placement counts. This drops
        mutual exclusions BETWEEN undamaged ships only, and is explicitly an
        approximation, not an exact full-fleet posterior. It removes Monte Carlo
        variance from the high-value pursuit decision. A node cap bounds work.
        """
        scores = [0.0] * len(obs["grid"])
        total, nodes, leaves = 0.0, 0, 0
        unknown = mask_of(obs["legal_actions"])
        cover = {h: [(i, p) for i, pool in enumerate(pools) for p in pool if p[0] & (1 << h)]
                 for h in bits(hits)}

        def visit(unused, occupied, uncovered, chosen):
            nonlocal total, nodes, leaves
            nodes += 1
            if nodes > 20000:
                raise OverflowError("target enumeration node cap")
            if not uncovered:
                counts = [sum(not p[0] & occupied for p in pools[i]) for i in unused]
                weight = math.prod(counts)
                if not weight:
                    return
                total += weight
                leaves += 1
                for m, cells in chosen:
                    sink = (m & unknown).bit_count() == 1
                    h = (m & hits).bit_count()
                    bonus = h ** self.policy.target_bonus
                    for c in cells:
                        if obs["grid"][c] == 0:
                            scores[c] += weight * bonus * (1 + self.policy.sink_bonus * sink)
                return
            branches = None
            for h in bits(uncovered):
                valid = [(i, p) for i, p in cover[h] if i in unused and not p[0] & occupied]
                if branches is None or len(valid) < len(branches):
                    branches = valid
                if not valid:
                    return
            for i, p in branches:
                visit(unused - {i}, occupied | p[0], uncovered & ~p[0], chosen + [p])

        try:
            visit(set(range(len(pools))), 0, hits, [])
        except OverflowError:
            # Discard truncated enumeration to avoid traversal-order bias.
            return self.posterior(obs, hits, pools)
        self.diagnostics = {"method": "constraint_approx", "nodes": nodes, "assignments": leaves}
        return [s/total for s in scores] if total else None


def make_bot(name="admiral", policy=None):
    if name == "champion":
        path = Path(__file__).resolve().parent.parent / "policies" / "champion.json"
        p = policy or Policy.load(path)
        return DensityBot(p) if p.mode == "density" else PosteriorBot(p)
    if name.startswith("exec:"):
        from .protocol import SubprocessBot
        return SubprocessBot(name[5:])
    if name == "random":
        return RandomBot()
    if name == "hunt":
        return HuntBot()
    if name == "density":
        return DensityBot(policy)
    if name in ("admiral", "joint"):
        return PosteriorBot(policy or Policy(mode="joint" if name == "joint" else "hybrid"))
    if Path(name).is_file():
        p = Policy.load(name)
        return DensityBot(p) if p.mode == "density" else PosteriorBot(p)
    raise ValueError("unknown bot: " + name)
