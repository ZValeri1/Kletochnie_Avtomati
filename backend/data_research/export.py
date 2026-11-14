from __future__ import annotations

class JournalExporter:
    """Build a browser download without creating a user-visible server path."""

    @staticmethod
    def build(*, simulation_id, revision, configuration, events, metrics, final_snapshot, name=None):
        return {
            "schema_version": 1,
            "simulation_id": simulation_id,
            "name": name,
            "revision": revision,
            "configuration": configuration,
            "events": events,
            "metrics": metrics,
            "formulas": {
                "d": "D = N_V + N_I + N_As",
                "s": "S = -k * [N * (c*ln(c)+(1-c)*ln(1-c)) + N_prime * (c_prime*ln(c_prime)+(1-c_prime)*ln(1-c_prime))]; k=1.380649e-23 J/K; c=n_v/N; c_prime=(n_i+n_as)/N_prime; 0*ln(0)=0",
                "s_legacy": "S_legacy = -sum(n_j * ln(n_j / sum(n_j))); j = {n_correct, n_v, n_i, n_outside}; n_outside=n_as+n_lost; 0*ln(0)=0",
            },
            "units": {"q_n": "eV", "q_thr": "eV", "d": "count", "s": "J/K", "s_legacy": "dimensionless"},
            "final_snapshot": final_snapshot,
        }
