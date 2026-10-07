from pathlib import Path

from tests.support import call, symbol, value


def test_mass_experiment_is_reproducible_and_exports_all_runs(tmp_path):
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    service_class = symbol(
        "backend.data_research.experiments", "ExperimentService"
    )
    exporter_class = symbol("backend.data_research.export", "ResultExporter")

    def execute():
        manager = manager_class(max_parallel_simulations=4)
        service = service_class(manager=manager)
        return call(
            service.run,
            configurations=[{"dimensions": [6, 6], "q_max_ev": 30}] * 20,
            steps=100,
            master_seed=303,
        )

    first = execute()
    second = execute()
    exported = exporter_class(root=tmp_path).export(
        value(first, "project_export"), export_id="mass-result"
    )

    assert value(first, "aggregate") == value(second, "aggregate")
    assert len(value(first, "successful_runs")) == 20
    assert (Path(value(exported, "path")) / "manifest.json").is_file()
