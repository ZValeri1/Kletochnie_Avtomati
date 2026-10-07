"""Deterministic construction of the four initial lattice modes."""

from __future__ import annotations

import math
import random
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from backend.atomic_model.errors import InitializationError, StateInvariantError
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology

InitializationMode = Literal[
    "ordered", "random_defective", "explicit_defective", "symmetric_defective"
]


@dataclass(frozen=True)
class InitializationCounts:
    n0: int
    n_atoms: int
    n_v: int
    n_i: int
    n_as: int

    @classmethod
    def from_state(cls, topology: Topology, state: SimulationState) -> InitializationCounts:
        n0 = len(topology.metal_domain.lattice_keys)
        n_v = n0 - len(topology.metal_domain.lattice_keys & state.occupied.keys())
        n_i = sum(
            topology.sites[key].kind == "interstitial"
            and topology.sites[key].metal_relation == "interior"
            for key in state.atoms.values()
        )
        n_as = sum(
            topology.sites[key].metal_relation == "outside"
            for key in state.atoms.values()
        )
        return cls(n0, len(state.atoms), n_v, n_i, n_as)


@dataclass(frozen=True)
class InitializationSpec:
    mode: InitializationMode
    n_v: int
    n_i: int
    n_as: int
    seed_init: int | None

    @classmethod
    def from_configuration(
        cls, topology: Topology, configuration: dict, rng: random.Random
    ) -> InitializationSpec:
        mode = configuration.get("initialization_mode", "ordered")
        seed_init = configuration.get("seed_init")
        if seed_init is not None and type(seed_init) is not int:
            raise InitializationError("INVALID_INITIALIZATION_MODE")
        if mode not in (
            "ordered", "random_defective", "explicit_defective", "symmetric_defective"
        ):
            raise InitializationError("INVALID_INITIALIZATION_MODE")
        n0 = len(topology.metal_domain.lattice_keys)
        if mode == "random_defective":
            parameters = configuration.get("random_parameters") or {}
            if not isinstance(parameters, dict):
                raise InitializationError("INVALID_DEFECT_COUNT")
            if set(parameters) - {"vacancies", "interstitials", "adatoms"}:
                raise InitializationError("INVALID_DEFECT_COUNT")
            capacities = {
                "vacancies": n0,
                "interstitials": sum(
                    site.kind == "interstitial" and site.metal_relation == "interior"
                    for site in topology.sites.values()
                ),
                "adatoms": sum(
                    site.metal_relation == "outside" for site in topology.sites.values()
                ),
            }
            defaults = {
                "vacancies": (0.05 * n0, 0.02 * n0),
                "interstitials": (0.05 * n0, 0.02 * n0),
                "adatoms": (0.01 * n0, 0.01 * n0),
            }
            values = {}
            category_rngs = {
                category: random.Random(rng.getrandbits(64))
                for category in ("vacancies", "interstitials", "adatoms")
            }
            for category in ("vacancies", "interstitials", "adatoms"):
                item = parameters.get(category, {})
                if not isinstance(item, dict):
                    raise InitializationError("INVALID_DEFECT_COUNT")
                mean = item.get("mu", defaults[category][0])
                sigma = item.get("sigma", defaults[category][1])
                if not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in (mean, sigma)
                ) or sigma < 0:
                    raise InitializationError("INVALID_DEFECT_COUNT")
                values[category] = _truncated_normal_integer(
                    category_rngs[category], float(mean), float(sigma), capacities[category]
                )
            n_v, n_i, n_as = (
                values["vacancies"], values["interstitials"], values["adatoms"]
            )
        else:
            n_v = configuration.get("n_v", 0)
            n_i = configuration.get("n_i", 0)
            n_as = configuration.get("n_as", 0)
            if any(type(value) is not int or value < 0 for value in (n_v, n_i, n_as)):
                raise InitializationError("INVALID_DEFECT_COUNT")
            if mode == "ordered" and (n_v, n_i, n_as) != (0, 0, 0):
                raise InitializationError("INVALID_DEFECT_COUNT")
        if n_v > n0 or (mode == "symmetric_defective" and n_i + n_as != n_v):
            raise InitializationError("INVALID_DEFECT_COUNT")
        return cls(mode, n_v, n_i, n_as, seed_init)


def _truncated_normal_integer(
    rng: random.Random, mean: float, sigma: float, upper: int
) -> int:
    if upper < 0:
        raise InitializationError("INITIAL_CONFIGURATION_INFEASIBLE")
    for _ in range(1000):
        value = round(rng.gauss(mean, sigma)) if sigma else round(mean)
        if 0 <= value <= upper:
            return value
    raise InitializationError("INITIAL_CONFIGURATION_INFEASIBLE")


class Initializer:
    MAX_PLACEMENT_ATTEMPTS = 64

    def build(self, topology: Topology, configuration: dict) -> SimulationState:
        rng = random.Random(configuration.get("seed_init"))
        spec = InitializationSpec.from_configuration(topology, configuration, rng)
        if spec.mode == "ordered":
            state = SimulationState.create_ideal(topology, configuration)
            state.validate(topology)
            return state

        interior = sorted(
            key for key, site in topology.sites.items()
            if site.kind == "interstitial" and site.metal_relation == "interior"
        )
        external = frozenset(
            key for key, site in topology.sites.items()
            if site.metal_relation == "outside"
        )
        if spec.n_i > len(interior) or spec.n_as > len(external):
            raise InitializationError("INITIAL_CONFIGURATION_INFEASIBLE")

        metal = sorted(topology.metal_domain.lattice_keys)
        for _ in range(self.MAX_PLACEMENT_ATTEMPTS):
            vacant = set(rng.sample(metal, spec.n_v))
            positions = {
                atom_id: key for atom_id, key in enumerate(metal)
                if key not in vacant
            }
            # Build one vacancy sample per attempt; atom identifiers stay stable.
            state = SimulationState.from_positions(
                topology, positions, configuration=deepcopy(configuration)
            )
            next_atom_id = len(metal)
            interior_pool = [
                key for key in interior
                if topology.contact_neighbors(key) & state.occupied.keys()
            ]
            if len(interior_pool) < spec.n_i:
                continue
            for key in rng.sample(interior_pool, spec.n_i):
                state.atoms[next_atom_id] = key
                state.occupied[key] = next_atom_id
                next_atom_id += 1

            frontier = {
                neighbor
                for occupied_key in state.occupied
                for neighbor in topology.contact_neighbors(occupied_key)
                if neighbor in external and neighbor not in state.occupied
            }
            for _ in range(spec.n_as):
                if not frontier:
                    break
                key = rng.choice(sorted(frontier))
                frontier.remove(key)
                state.atoms[next_atom_id] = key
                state.occupied[key] = next_atom_id
                next_atom_id += 1
                frontier.update(
                    neighbor for neighbor in topology.contact_neighbors(key)
                    if neighbor in external and neighbor not in state.occupied
                )
            if next_atom_id != len(metal) + spec.n_i + spec.n_as:
                continue
            try:
                state.validate(topology)
            except StateInvariantError:
                continue
            counts = InitializationCounts.from_state(topology, state)
            if (counts.n_v, counts.n_i, counts.n_as) == (
                spec.n_v, spec.n_i, spec.n_as
            ):
                return state
        raise InitializationError("INITIAL_CONFIGURATION_INFEASIBLE")
