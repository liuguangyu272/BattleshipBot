"""Experimental public-feedback spatial mixture for the hunt phase.

This is an approximate model: ship placements are independent before observed
miss/sunk exclusions. The posterior is deliberately tempered, and must not be
described as an exact posterior over nonoverlapping complete fleets.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import math
from pathlib import Path

from .bots import Policy, PosteriorBot
from .core import placements, mask_of, save_json


@dataclass(frozen=True)
class ContextConfig:
    version: int = 1
    mix: float = 1.0
    temperature: float = .65
    length_power: float = 2.0
    uniform_floor: float = .10
    edge_prior: float = .20
    cluster_prior: float = .20
    spread_prior: float = .10
    cluster_power: float = 3.0

    def validate(self):
        if self.version != 1:
            raise ValueError("unsupported context version")
        for name in ("mix", "temperature", "uniform_floor", "edge_prior", "cluster_prior", "spread_prior"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid context parameter: " + name)
        for name in ("length_power", "cluster_power"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 6:
                raise ValueError("invalid context parameter: " + name)
        if self.edge_prior + self.cluster_prior + self.spread_prior >= 1:
            raise ValueError("spatial priors must leave positive uniform mass")
        return self


@lru_cache(maxsize=16)
def _templates(size, lengths, cluster_power):
    # Fixed quadrature over hidden anchor locations; never an actual board seed.
    coordinates = sorted(set(range(0, size, 2)) | {size - 1})
    anchors = [(r, c) for r in coordinates for c in coordinates]
    descriptors = [("uniform", None), ("edge", None)]
    descriptors += [(style, anchor) for style in ("cluster", "spread") for anchor in anchors]
    pools = {length: placements(size, length) for length in lengths}
    indices = {length: {mask: i for i, (mask, _) in enumerate(pool)} for length, pool in pools.items()}
    models = []
    for style, anchor in descriptors:
        priors = {}
        for length, pool in pools.items():
            weights = []
            for _, cells in pool:
                if style == "uniform":
                    weight = 1.0
                elif style == "edge":
                    edge = sum(min(c // size, c % size, size - 1 - c // size,
                                   size - 1 - c % size) for c in cells) / length
                    weight = (1 + edge) ** -2
                else:
                    distance = sum(abs(c // size - anchor[0]) + abs(c % size - anchor[1])
                                   for c in cells) / length
                    weight = (1 + distance) ** (-cluster_power if style == "cluster" else 2)
                weights.append(weight)
            total = sum(weights)
            priors[length] = tuple(w / total for w in weights)
        models.append((style, priors))
    return pools, indices, tuple(models), len(anchors)


class ContextBot(PosteriorBot):
    """Retain Champion pursuit; adapt hunt using public misses and sunk ships."""
    def __init__(self, policy=None, context=None):
        if policy is None:
            policy = Policy.load(Path(__file__).resolve().parents[1] / "policies" / "champion.json")
        super().__init__(policy)
        self.context = (context or ContextConfig()).validate()

    def reset(self, rules, seed):
        super().reset(rules, seed)
        self._models = _templates(self.rules.size, tuple(sorted(set(self.rules.fleet))), self.context.cluster_power)
        self.last_model_weights = {}

    def save(self, path):
        save_json(path, {"kind": "context", "policy": asdict(self.policy), "context": asdict(self.context)})

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("kind") != "context":
            raise ValueError("not a context strategy")
        return cls(Policy(**value["policy"]), ContextConfig(**value["context"]))

    def contextual_scores(self, obs):
        """Integrate latent edge/anchor models against the public observation.

        At a hunt state every successful shot belongs to a publicly sunk ship.
        Each model's evidence is the probability of these exact sunk placements
        times the mass of placements avoiding all observed cells for each
        remaining ship. Adaptive action selection adds no likelihood factor.
        Mutual exclusion among still-hidden ships is approximated, hence the
        tempered update and uniform floor.
        """
        config = self.context
        pools, indices, models, anchor_count = self._models
        blocked = mask_of(c for c, value in enumerate(obs["grid"]) if value != 0)
        counts = {length: obs["remaining"].count(length) for length in set(obs["remaining"])}
        allowed = {length: [i for i, (mask, _) in enumerate(pools[length]) if not mask & blocked]
                   for length in counts}
        if any(not values for values in allowed.values()):
            return None
        sunk = [(len(ship), indices[len(ship)][mask_of(ship)]) for ship in obs["sunk"]]
        prior_mass = {"uniform": 1 - config.edge_prior - config.cluster_prior - config.spread_prior,
                      "edge": config.edge_prior, "cluster": config.cluster_prior / anchor_count,
                      "spread": config.spread_prior / anchor_count}
        logs, free_masses = [], []
        for style, priors in models:
            free = {length: sum(priors[length][i] for i in allowed[length]) for length in counts}
            evidence = sum(math.log(priors[length][i]) for length, i in sunk)
            evidence += sum(counts[length] * math.log(free[length]) for length in counts)
            logs.append(math.log(max(1e-300, prior_mass[style])) + config.temperature * evidence)
            free_masses.append(free)
        maximum = max(logs)
        weights = [math.exp(value - maximum) for value in logs]
        total = sum(weights)
        weights = [(1 - config.uniform_floor) * weight / total for weight in weights]
        weights[0] += config.uniform_floor
        self.last_model_weights = {style: sum(weight for weight, (name, _) in zip(weights, models) if name == style)
                                   for style in ("uniform", "edge", "cluster", "spread")}
        scores = [0.0] * len(obs["grid"])
        for length, count in counts.items():
            contribution = count / length ** config.length_power
            for i in allowed[length]:
                probability = sum(weight * priors[length][i] / free[length]
                                  for weight, (_, priors), free in zip(weights, models, free_masses))
                for cell in pools[length][i][1]:
                    scores[cell] += contribution * probability
        return scores

    def choose(self, obs, scores):
        if not self.context.mix or any(v == 2 for v in obs["grid"]):
            return super().choose(obs, scores)
        contextual = self.contextual_scores(obs)
        if contextual is None:
            return super().choose(obs, scores)
        legal, size = obs["legal_actions"], self.rules.size
        if not legal or obs["done"]:
            raise ValueError("no action in terminal observation")
        baseline = list(scores)
        for cell in legal:
            row, col = divmod(cell, size)
            edge = min(row, col, size - 1 - row, size - 1 - col)
            baseline[cell] *= math.exp(-self.policy.edge_bias * edge)
            baseline[cell] *= 1 + self.policy.parity_bonus * ((row + col) % min(obs["remaining"]) == 0)
        context_max, baseline_max = max(contextual) or 1, max(baseline) or 1
        scores = [(1 - self.context.mix) * base / baseline_max + self.context.mix * value / context_max
                  for base, value in zip(baseline, contextual)]
        best = max(scores[c] for c in legal)
        self.last_scores = scores
        self.diagnostics = {"method": "context_hunt", "weights": self.last_model_weights.copy()}
        return self.rng.choice([c for c in legal if scores[c] >= best - 1e-10])
