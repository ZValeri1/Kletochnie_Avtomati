import math

from hypothesis import given, settings, strategies as st

from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource


dimensions = st.one_of(
    st.tuples(st.integers(2, 5), st.integers(2, 5)),
    st.tuples(st.integers(2, 4), st.integers(2, 4), st.integers(2, 4)),
)


@settings(max_examples=60, deadline=None)
@given(
    dimensions=dimensions,
    seed=st.integers(min_value=0, max_value=2**31 - 1),
    steps=st.integers(min_value=1, max_value=6),
)
def test_generated_step_sequences_preserve_critical_invariants(
    dimensions, seed, steps
):
    engine = SimulationEngine()
    random_source = RandomSource(seed)
    initial = engine.create_initial_state(
        {"dimensions": list(dimensions), "seed_init": seed, "q_max_ev": 82},
        random_source,
    )
    state = initial.state
    atom_count = len(state.atoms)

    for _ in range(steps):
        result = engine.step(state, random_source)
        state = result.state
        state.validate(result.topology)
        assert len(state.atoms) == atom_count
        assert len(state.occupied) == atom_count
        assert len(set(state.atoms.values())) == atom_count
        assert all(
            math.isfinite(float(value))
            for value in result.metrics.model_dump().values()
        )
