from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import os

import pytest

from backend.atomic_model.acceleration import ComputeBackend
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import EventEngine, RandomSource
from backend.atomic_model.topology import Topology


def initial(dimensions=(6, 6), method="monte_carlo"):
    engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    config = {"dimensions": list(dimensions), "seed_init": 41, "seed_sim": 42,
              "initialization_mode": "explicit_defective", "n_v": 5, "n_i": 5,
              "method": method}
    return engine.create_initial_state(config, RandomSource(42))


@pytest.fixture(scope="module")
def cuda():
    backend = ComputeBackend("cuda")
    status = backend.status()
    if status["backend"] != "cuda":
        if os.environ.get("GAMMA_REQUIRE_CUDA") == "1":
            pytest.fail(status["reason"])
        pytest.skip(status["reason"])
    return backend


def test_missing_cuda_dependency_is_optional(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr("backend.atomic_model.acceleration.importlib.import_module", missing)
    backend = ComputeBackend("auto")
    assert backend.status()["backend"] == "cpu"
    result = initial()
    expected = EventEngine(compute_backend=ComputeBackend("cpu")).probabilities(
        result.topology, result.state, 0, 82)
    actual = EventEngine(compute_backend=backend).probabilities(result.topology, result.state, 0, 82)
    assert actual == expected


def test_forced_cpu_never_imports_cuda(monkeypatch):
    def unexpected(name):
        pytest.fail("CPU mode must not import optional GPU dependencies")
    monkeypatch.setattr("backend.atomic_model.acceleration.importlib.import_module", unexpected)
    assert ComputeBackend("cpu").status()["backend"] == "cpu"


@pytest.mark.parametrize("dimensions", [(3, 4), (2, 3, 2)])
def test_local_shells_match_full_field_definition(dimensions):
    topology = Topology.create(dimensions)
    # Includes field boundaries, both sublattices and both radii.
    for source, origin in topology.sites.items():
        for radius in (1, 2):
            expected = frozenset(key for key, site in topology.sites.items()
                if key != source and max(abs(a-b) for a,b in zip(origin.half_units, site.half_units))
                == (2*radius if site.kind == origin.kind else 2*radius-1))
            assert topology.shell(source, radius) == expected


@pytest.mark.parametrize("dimensions", [(6, 6), (4, 4, 4)])
@pytest.mark.parametrize("method", ["monte_carlo", "cellular_automata"])
def test_gpu_and_cpu_have_identical_trajectories_and_rng(cuda, dimensions, method):
    result = initial(dimensions, method)
    cpu_engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    gpu_engine = SimulationEngine(compute_backend=cuda)
    a, b = result.state, result.state.working_copy()
    ra, rb = RandomSource(42), RandomSource(42)
    before = cuda.status()["cuda_batches"]
    for _ in range(150):
        left = cpu_engine.step(a.transition_copy(include_history=False), ra)
        right = gpu_engine.step(b.transition_copy(include_history=False), rb)
        assert left.state.to_dict() == right.state.to_dict()
        assert asdict(left.event) == asdict(right.event)
        assert ra.get_state() == rb.get_state()
        a, b = left.state, right.state
    assert cuda.status()["cuda_batches"] > before
    assert cuda.status()["backend"] == "cuda"


def test_gpu_preserves_all_probability_and_block_reason_fields(cuda):
    result = initial((4, 4))
    cpu = EventEngine(result.state.configuration, compute_backend=ComputeBackend("cpu"))
    gpu = EventEngine(result.state.configuration, compute_backend=cuda)
    for atom_id in result.state.atoms:
        for energy in (0, 20, 82):
            assert gpu.probabilities(result.topology, result.state, atom_id, energy) == \
                cpu.probabilities(result.topology, result.state, atom_id, energy)


def test_runtime_cuda_failure_recomputes_on_cpu_without_changing_rng(cuda, monkeypatch):
    failing = ComputeBackend("cuda")
    assert failing.status()["backend"] == "cuda"
    def failed(*args):
        raise RuntimeError("simulated device loss")
    monkeypatch.setattr(failing, "_validate_cuda", failed)
    a = initial().state
    b = a.working_copy()
    cpu = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    gpu = SimulationEngine(compute_backend=failing)
    ra, rb = RandomSource(42), RandomSource(42)
    for _ in range(30):
        a = cpu.step(a.transition_copy(include_history=False), ra).state
        b = gpu.step(b.transition_copy(include_history=False), rb).state
        assert a.to_dict() == b.to_dict()
        assert ra.get_state() == rb.get_state()
    assert failing.status()["backend"] == "cpu"
    assert failing.status()["fallbacks"] == 1


def test_concurrent_gpu_streams_keep_simulations_isolated(cuda):
    result = initial()
    def trajectory(seed, backend):
        engine = SimulationEngine(compute_backend=backend)
        state, rng = result.state.working_copy(), RandomSource(seed)
        for _ in range(80):
            state = engine.step(state.transition_copy(include_history=False), rng).state
        return state.to_dict(), rng.get_state()
    expected = [trajectory(seed, ComputeBackend("cpu")) for seed in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda seed: trajectory(seed, cuda), range(4)))
    assert actual == expected
    assert cuda.status()["backend"] == "cuda"
