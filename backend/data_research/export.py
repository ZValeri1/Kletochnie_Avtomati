from __future__ import annotations

class JournalExporter:
    """Build a browser download without creating a user-visible server path."""

    @staticmethod
    def build(*, simulation_id, revision, configuration, events, metrics, final_snapshot):
        return {
            "schema_version": 1,
            "simulation_id": simulation_id,
            "revision": revision,
            "configuration": configuration,
            "events": events,
            "metrics": metrics,
            "formulas": {
                "d": "D = N_V + N_I + N_As",
                "s": "S = -sum_i(n_i / n * ln(n_i / n))",
            },
            "units": {"q_n": "eV", "q_thr": "eV", "d": "count", "s": "1"},
            "final_snapshot": final_snapshot,
        }
