import math

import pytest

from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import EventEngine, RandomSource


class ScriptedRandom:
    def __init__(self, *, atom_id: int, beta: float, point: float = 0.0):
        self.atom_id = atom_id
        self.beta = beta
        self.point = point
        self.choice_calls = 0
        self.beta_calls = 0
        self.random_calls = 0
        self.calls = []

    def get_state(self):
        return (self.choice_calls, self.beta_calls, self.random_calls)

    def set_state(self, state):
        self.choice_calls, self.beta_calls, self.random_calls = state

    def choice(self, values):
        self.choice_calls += 1
        self.calls.append("choice")
        assert self.atom_id in values
        return self.atom_id

    def betavariate(self, alpha, beta):
        self.beta_calls += 1
        self.calls.append("beta")
        assert (alpha, beta) == (1, 4)
        return self.beta

    def random(self):
        self.random_calls += 1
        self.calls.append("random")
        return self.point


def test_below_threshold_draws_one_energy_and_records_no_change():
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(12),
    )
    atom_id = min(initial.state.atoms)
    random_source = ScriptedRandom(atom_id=atom_id, beta=0.25)
    before_atoms = dict(initial.state.atoms)

    result = engine.step(initial.state, random_source)

    assert random_source.choice_calls == 1
    assert random_source.beta_calls == 1
    assert random_source.random_calls == 0
    assert random_source.calls == ["choice", "beta"]
    assert result.state.atoms == before_atoms
    assert result.state.act_number == 1
    assert result.state.revision == 1
    assert result.event.operation == "no_change"
    assert result.event.q_n == 10
    assert result.event.q_thr == 20
    assert result.event.result_reason == "BELOW_THRESHOLD"


def test_manual_destinations_report_selectable_and_blocked_positions():
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
        },
        RandomSource(12),
    )
    source_id = next(
        atom_id
        for atom_id, key in initial.state.atoms.items()
        if initial.topology.sites[key].metal_relation == "interior"
    )
    destinations = engine.destinations(initial.state, source_id)
    occupied = next(
        key for key, atom_id in initial.state.occupied.items()
        if atom_id != source_id
    )
    disconnected = next(
        key for key, site in initial.topology.sites.items()
        if key not in initial.state.occupied
        and site.metal_relation == "outside"
        and not initial.topology.contact_neighbors(key) & initial.state.occupied.keys()
    )
    by_key = {item["key"]: item for item in destinations}

    assert any(item["selectable"] for item in destinations)
    assert by_key[occupied]["block_code"] == "SITE_OCCUPIED"
    assert by_key[disconnected]["block_code"] == "DISCONNECTED_ATOM"


def test_activated_act_selects_at_most_one_outcome_and_records_full_event():
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(12),
    )
    topology = initial.topology
    atom_id = next(
        atom_id
        for atom_id, key in initial.state.atoms.items()
        if topology.sites[key].metal_relation == "interior"
    )
    random_source = ScriptedRandom(atom_id=atom_id, beta=1.0, point=0.0)

    result = engine.step(initial.state, random_source)

    assert random_source.calls == ["choice", "beta", "random"]
    assert result.event.operation == "lattice_interstitial"
    assert result.event.result_reason == "APPLIED"
    assert result.event.source_coordinate == topology.sites[
        result.event.source_site
    ].coordinate
    assert result.event.destination_coordinate == topology.sites[
        result.event.destination_site
    ].coordinate
    assert result.event.affected_atom_ids == (atom_id,)
    assert result.event.metrics_before["d"] == 0
    assert result.event.metrics_after["d"] == 2
    assert result.state.events[-1]["q_n"] == 40


@pytest.mark.parametrize(
    "configuration",
    [
        {"weights": {"external_metal": 1.01}},
        {"weights": {"vacancy": 0.7, "interstitial": 0.2}},
        {"weights": {"shell_r1": 0.7, "shell_r2": 0.2}},
        {
            "weights": {
                "from_lattice_vacancy": 0.7,
                "from_lattice_interstitial": 0.2,
            }
        },
        {
            "weights": {
                "from_interstitial_shell_r1": 0.7,
                "from_interstitial_shell_r2": 0.2,
            }
        },
        {
            "weights": {
                "from_lattice_inside": 0.8,
                "from_lattice_outside": 0.1,
            }
        },
    ],
)
def test_invalid_probability_configuration_is_rejected(configuration):
    engine = SimulationEngine()
    with pytest.raises(ValueError):
        engine.create_initial_state(
            {
                "dimensions": [4, 4],
                "seed_init": 11,
                "seed_sim": 12,
                **configuration,
            },
            RandomSource(12),
        )


def test_a_saved_source_outside_probability_derives_its_inside_complement():
    effective = EventEngine.effective_source_probabilities(
        {"from_interstitial_outside": 0.2}
    )

    assert effective["from_interstitial_inside"] == 0.8
    assert effective["from_interstitial_outside"] == 0.2


def test_steps_reuse_the_immutable_topology_for_the_same_configuration():
    engine = SimulationEngine()
    random_source = RandomSource(32)
    initial = engine.create_initial_state(
        {
            "dimensions": [5, 5],
            "seed_init": 31,
            "seed_sim": 32,
            "q_max_ev": 0,
        },
        random_source,
    )

    stepped = engine.step(initial.state, random_source)

    assert stepped.topology is initial.topology


def test_physical_step_does_not_copy_immutable_historical_payloads():
    class ImmutableHistoricalPayload(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("historical payload must not be copied by a physical step")

    engine = SimulationEngine()
    random_source = RandomSource(32)
    initial = engine.create_initial_state(
        {
            "dimensions": [5, 5],
            "seed_init": 31,
            "seed_sim": 32,
            "q_max_ev": 0,
        },
        random_source,
    )
    initial.state.events.append(ImmutableHistoricalPayload())
    initial.state.metrics_points.append(ImmutableHistoricalPayload())

    stepped = engine.step(initial.state, random_source)

    assert stepped.state.events[0] is initial.state.events[0]
    assert stepped.state.metrics_points[-2] is initial.state.metrics_points[-1]
    assert len(stepped.state.events) == len(initial.state.events) + 1
    assert len(stepped.state.metrics_points) == len(initial.state.metrics_points) + 1


def test_each_available_position_uses_its_group_probability_divided_by_n():
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(12),
    )
    topology = initial.topology
    source_key = next(
        key
        for key in sorted(topology.metal_domain.lattice_keys)
        if topology.sites[key].metal_relation == "interior"
    )
    atom_id = initial.state.occupied[source_key]

    outcomes = engine.probabilities(initial.state, atom_id=atom_id, q_test=30)
    selectable = [outcome for outcome in outcomes if outcome.selectable]

    assert selectable
    assert sum(outcome.probability for outcome in selectable) <= 1.0
    for outcome in selectable:
        assert outcome.operation_weight == {
            "lattice": 0.80,
            "interstitial": 0.20,
        }[outcome.destination_kind]
        assert outcome.shell_weight == {1: 0.75, 2: 0.25}[outcome.shell]
        assert outcome.position_weight == (
            0.05 if outcome.destination_relation == "outside" else 0.95
        )
        group = [
            candidate
            for candidate in selectable
            if candidate.destination_kind == outcome.destination_kind
            and candidate.shell == outcome.shell
            and (candidate.destination_relation == "outside")
            == (outcome.destination_relation == "outside")
        ]
        assert math.isclose(
            outcome.probability,
            outcome.operation_weight
            * outcome.shell_weight
            * outcome.position_weight
            / len(group),
        )


def test_lattice_and_interstitial_sources_use_independent_probability_groups():
    from backend.atomic_model.event_executor import EventExecutor
    from backend.atomic_model.events import EventCandidate

    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [5, 5],
            "seed_init": 31,
            "seed_sim": 32,
            "q_max_ev": 40,
            "q_thr_ev": 20,
            "weights": {
                "from_lattice_vacancy": 0.60,
                "from_lattice_interstitial": 0.40,
                "from_lattice_shell_r1": 0.55,
                "from_lattice_shell_r2": 0.45,
                "from_lattice_inside": 0.90,
                "from_lattice_outside": 0.10,
                "from_interstitial_vacancy": 0.30,
                "from_interstitial_interstitial": 0.70,
                "from_interstitial_shell_r1": 0.25,
                "from_interstitial_shell_r2": 0.75,
                "from_interstitial_inside": 0.80,
                "from_interstitial_outside": 0.20,
            },
        },
        RandomSource(32),
    )
    topology = initial.topology
    lattice_atom_id = next(
        atom_id
        for atom_id, key in initial.state.atoms.items()
        if topology.sites[key].metal_relation == "interior"
    )
    lattice_outcomes = engine.probabilities(initial.state, lattice_atom_id, 30)

    for outcome in lattice_outcomes:
        assert outcome.operation_weight == {
            "lattice": 0.60,
            "interstitial": 0.40,
        }[outcome.destination_kind]
        assert outcome.shell_weight == {1: 0.55, 2: 0.45}[outcome.shell]
        assert outcome.position_weight == (
            0.10 if outcome.destination_relation == "outside" else 0.90
        )

    frenkel = next(
        outcome
        for outcome in lattice_outcomes
        if outcome.selectable and outcome.operation == "lattice_interstitial"
    )
    interstitial_state = EventExecutor().execute(
        topology,
        initial.state,
        EventCandidate(
            frenkel.operation,
            lattice_atom_id,
            frenkel.source_site,
            frenkel.destination_site,
            frenkel.shell,
            frenkel.operation_weight,
            frenkel.shell_weight,
            frenkel.position_weight,
            frenkel.total_weight,
            frenkel.probability,
        ),
    ).state
    interstitial_outcomes = engine.probabilities(
        interstitial_state, lattice_atom_id, 30
    )

    assert interstitial_outcomes
    assert all(outcome.source_kind == "interstitial" for outcome in interstitial_outcomes)
    for outcome in interstitial_outcomes:
        assert outcome.operation_weight == {
            "lattice": 0.30,
            "interstitial": 0.70,
        }[outcome.destination_kind]
        assert outcome.shell_weight == {1: 0.25, 2: 0.75}[outcome.shell]
        assert outcome.position_weight == (
            0.20 if outcome.destination_relation == "outside" else 0.80
        )


def test_second_shell_transition_only_requires_the_destination_to_be_free():
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [5, 5],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(12),
    )
    topology = initial.topology
    state = initial.state
    atom_id = next(
        atom_id
        for atom_id, key in state.atoms.items()
        if topology.sites[key].metal_relation == "interior"
    )
    outcome = next(
        outcome
        for outcome in engine.probabilities(state, atom_id, 30)
        if outcome.operation == "lattice_interstitial"
        and outcome.shell == 2
        and outcome.selectable
    )
    paths = topology.all_shortest_paths(state.atoms[atom_id], outcome.destination_site)
    assert any(key in state.occupied for path in paths for key in path[1:-1])
    assert outcome.block_code is None


def test_second_shell_recombination_applies_its_operation_and_shell_once():
    from backend.atomic_model.event_executor import EventExecutor
    from backend.atomic_model.events import EventCandidate

    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [5, 5],
            "seed_init": 21,
            "seed_sim": 22,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(22),
    )
    topology = initial.topology
    state = initial.state
    atom_id = next(
        atom_id
        for atom_id, key in state.atoms.items()
        if topology.sites[key].metal_relation == "interior"
    )
    frenkel = next(
        outcome
        for outcome in engine.probabilities(state, atom_id, 30)
        if outcome.selectable and outcome.operation == "lattice_interstitial"
    )
    state = EventExecutor().execute(
        topology,
        state,
        EventCandidate(
            frenkel.operation,
            atom_id,
            frenkel.source_site,
            frenkel.destination_site,
            frenkel.shell,
            frenkel.operation_weight,
            frenkel.shell_weight,
            frenkel.position_weight,
            frenkel.total_weight,
            frenkel.probability,
        ),
    ).state
    source_key = state.atoms[atom_id]
    destination = next(
        key
        for key in sorted(topology.shell(source_key, 2))
        if key in topology.metal_domain.lattice_keys
        and key != frenkel.source_site
    )
    paths = topology.all_shortest_paths(source_key, destination)
    cleared = state.working_copy()
    for key in {destination, *(key for path in paths for key in path[1:-1])}:
        if key in cleared.occupied and cleared.occupied[key] != atom_id:
            removed_atom_id = cleared.occupied.pop(key)
            del cleared.atoms[removed_atom_id]
    cleared.validate(topology)

    outcome = next(
        outcome
        for outcome in engine.probabilities(cleared, atom_id, 30)
        if outcome.destination_site == destination
    )

    assert outcome.operation == "interstitial_vacancy"
    assert outcome.shell == 2
    assert outcome.selectable
    assert outcome.operation_weight == 0.80
    assert outcome.shell_weight == 0.25
    assert outcome.position_weight == 0.95
    assert outcome.total_weight == 0.19


def test_external_metal_defaults_to_zero_but_can_be_enabled():
    from backend.atomic_model.event_executor import EventExecutor
    from backend.atomic_model.events import EventCandidate

    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(12),
    )
    topology = initial.topology
    state = initial.state
    atom_id = next(
        atom_id
        for atom_id, key in state.atoms.items()
        if topology.sites[key].metal_relation == "boundary"
    )
    exit_outcome = next(
        outcome
        for outcome in engine.probabilities(state, atom_id, 30)
        if outcome.selectable and outcome.operation == "boundary_external"
    )
    candidate = EventCandidate(
        exit_outcome.operation,
        atom_id,
        exit_outcome.source_site,
        exit_outcome.destination_site,
        exit_outcome.shell,
        exit_outcome.operation_weight,
        exit_outcome.shell_weight,
        exit_outcome.position_weight,
        exit_outcome.total_weight,
        exit_outcome.probability,
    )
    external = EventExecutor().execute(topology, state, candidate).state

    outcomes = engine.probabilities(external, atom_id, 30)
    reverse = next(
        outcome
        for outcome in outcomes
        if outcome.operation == "external_metal"
        and outcome.destination_site == exit_outcome.source_site
    )

    assert reverse.operation_weight == 0.8
    assert reverse.position_weight == 0
    assert reverse.total_weight == 0
    assert reverse.probability == 0
    assert not reverse.selectable
    assert reverse.block_code == "ZERO_PROBABILITY"

    enabled = external.working_copy()
    enabled.configuration["weights"] = {
        **enabled.configuration.get("weights", {}),
        "external_metal": 0.2,
    }
    enabled_reverse = next(
        outcome
        for outcome in engine.probabilities(enabled, atom_id, 30)
        if outcome.destination_site == exit_outcome.source_site
    )
    assert enabled_reverse.selectable
    assert enabled_reverse.position_weight == 0.2
    assert enabled_reverse.probability > 0


def test_probability_diagnostics_do_not_mutate_state_or_rng():
    engine = SimulationEngine()
    random_source = RandomSource(13)
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 11,
            "seed_sim": 13,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        random_source,
    )
    atom_id = min(initial.state.atoms)
    before = initial.state.to_dict()
    rng_before = random_source.get_state()

    engine.probabilities(initial.state, atom_id, q_test=30)

    assert initial.state.to_dict() == before
    assert random_source.get_state() == rng_before


def test_primary_target_selection_is_uniform_with_seeded_rng():
    engine = SimulationEngine()
    random_source = RandomSource(41)
    initial = engine.create_initial_state(
        {
            "dimensions": [2, 2],
            "seed_init": 40,
            "seed_sim": 41,
            "q_max_ev": 0,
            "q_thr_ev": 20,
        },
        random_source,
    )
    counts = {atom_id: 0 for atom_id in initial.state.atoms}
    state = initial.state
    for _ in range(800):
        result = engine.step(state, random_source)
        counts[result.event.source_atom_id] += 1
        state = result.state

    assert all(160 <= count <= 240 for count in counts.values())


def test_same_configuration_and_seed_produce_the_same_journal():
    engine = SimulationEngine()
    configuration = {
        "dimensions": [4, 4],
        "seed_init": 51,
        "seed_sim": 52,
        "q_max_ev": 40,
        "q_thr_ev": 20,
    }

    def journal():
        random_source = RandomSource(52)
        state = engine.create_initial_state(configuration, random_source).state
        for _ in range(20):
            state = engine.step(state, random_source).state
        return state.events

    assert journal() == journal()
