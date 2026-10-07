import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.support import symbol


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "module_name,class_name,filename",
    [
        ("backend.contracts.simulation", "SimulationSnapshot", "simulation_snapshot.json"),
        ("backend.contracts.simulation", "SimulationEvent", "simulation_event.json"),
        ("backend.contracts.simulation", "ProbabilityOverlay", "probability_overlay.json"),
        ("backend.contracts.simulation", "MetricsSeries", "metrics_series.json"),
        ("backend.contracts.simulation", "SliceAtlas", "slice_atlas.json"),
        ("backend.contracts.simulation", "PreparationEditPreview", "preparation_edit_preview.json"),
        ("backend.contracts.projects", "ProjectStatus", "project_status.json"),
        ("backend.contracts.experiments", "ExperimentStatus", "experiment_status.json"),
        ("backend.contracts.errors", "ApplicationError", "application_error.json"),
    ],
)
def test_shared_fixture_is_accepted_and_round_trips(module_name, class_name, filename):
    contract = symbol(module_name, class_name)
    payload = fixture(filename)

    decoded = contract.model_validate(payload)

    assert decoded.model_dump(mode="json") == payload


def test_atom_snapshot_topology_fields_are_typed_and_round_trip():
    contract = symbol("backend.contracts.simulation", "AtomSnapshot")
    payload = fixture("simulation_snapshot.json")["atoms"][0]

    decoded = contract.model_validate(payload)

    assert decoded.site_key == "lattice:0,0"
    assert decoded.site_kind == "lattice"
    assert decoded.metal_relation == "boundary"
    assert decoded.model_dump(mode="json") == payload


def test_destination_option_requires_a_reason_when_it_is_not_selectable():
    contract = symbol("backend.contracts.simulation", "DestinationOption")

    allowed = contract.model_validate({
        "key": "lattice:1,1",
        "kind": "lattice",
        "coordinate": [1, 1],
        "selectable": True,
        "block_code": None,
    })

    assert allowed.selectable
    with pytest.raises(ValidationError):
        contract.model_validate({
            "key": "lattice:2,2",
            "kind": "lattice",
            "coordinate": [2, 2],
            "selectable": False,
            "block_code": None,
        })


@pytest.mark.parametrize(
    "field,removed_value",
    [("site_kind", "bridge"), ("metal_relation", "hollow")],
)
def test_atom_snapshot_rejects_removed_topology_classifications(
    field, removed_value
):
    contract = symbol("backend.contracts.simulation", "AtomSnapshot")
    payload = fixture("simulation_snapshot.json")["atoms"][0]
    payload[field] = removed_value

    with pytest.raises(ValidationError):
        contract.model_validate(payload)


@pytest.mark.parametrize("field", ["site_key", "site_kind", "metal_relation"])
def test_atom_snapshot_rejects_a_missing_physical_field(field):
    contract = symbol("backend.contracts.simulation", "AtomSnapshot")
    payload = fixture("simulation_snapshot.json")["atoms"][0]
    payload.pop(field)

    with pytest.raises(ValidationError):
        contract.model_validate(payload)


@pytest.mark.parametrize(
    "class_name,filename,required_field",
    [
        ("SimulationSnapshot", "simulation_snapshot.json", "revision"),
        ("SimulationEvent", "simulation_event.json", "event_id"),
    ],
)
def test_simulation_contract_rejects_a_missing_required_field(
    class_name, filename, required_field
):
    contract = symbol("backend.contracts.simulation", class_name)
    payload = fixture(filename)
    payload.pop(required_field)

    with pytest.raises(ValidationError):
        contract.model_validate(payload)


def test_contracts_reject_unknown_schema_versions():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload["schema_version"] = 999

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


def test_snapshot_rejects_coordinate_with_wrong_dimension():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload["atoms"][0]["coordinate"] = [0.0, 0.0, 0.0]

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


def test_snapshot_rejects_non_finite_coordinates():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload["atoms"][0]["coordinate"][0] = float("inf")

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


def test_snapshot_rejects_unknown_runtime_status():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload["status"] = "BROKEN"

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


def test_snapshot_requires_a_complete_normalized_configuration():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload.pop("configuration")

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


def test_snapshot_configuration_rejects_a_missing_effective_weight():
    snapshot = symbol("backend.contracts.simulation", "SimulationSnapshot")
    payload = fixture("simulation_snapshot.json")
    payload["configuration"]["weights"].pop("boundary_external")

    with pytest.raises(ValidationError):
        snapshot.model_validate(payload)


@pytest.mark.parametrize("field", ["q_n", "q_thr", "operation_weight"])
def test_event_rejects_a_missing_physical_field(field):
    event = symbol("backend.contracts.simulation", "SimulationEvent")
    payload = fixture("simulation_event.json")
    payload.pop(field)

    with pytest.raises(ValidationError):
        event.model_validate(payload)


def test_contract_accepts_an_unknown_optional_field_for_forward_compatibility():
    event = symbol("backend.contracts.simulation", "SimulationEvent")
    payload = fixture("simulation_event.json")
    payload["future_optional_field"] = {"enabled": True}

    decoded = event.model_validate(payload)

    assert decoded.event_id == "event-3"


def test_probability_overlay_preserves_blocked_outcomes():
    contract = symbol("backend.contracts.simulation", "ProbabilityOverlay")

    decoded = contract.model_validate(fixture("probability_overlay.json"))

    assert decoded.outcomes[0].selectable is True
    assert decoded.outcomes[1].selectable is False
    assert decoded.outcomes[1].block_code == "PATH_BLOCKED"


def test_probability_overlay_rejects_removed_operation_names():
    contract = symbol("backend.contracts.simulation", "ProbabilityOverlay")
    payload = fixture("probability_overlay.json")
    payload["outcomes"][0]["operation"] = "swap"

    with pytest.raises(ValidationError):
        contract.model_validate(payload)


def test_metrics_series_preserves_point_revision_and_origin():
    contract = symbol("backend.contracts.simulation", "MetricsSeries")

    decoded = contract.model_validate(fixture("metrics_series.json"))

    assert decoded.points[0].origin == "initialization"
    assert decoded.points[1].revision == 3


def test_slice_atlas_preserves_site_classification_and_occupancy():
    contract = symbol("backend.contracts.simulation", "SliceAtlas")

    decoded = contract.model_validate(fixture("slice_atlas.json"))

    site = decoded.slices[0].sites[0]
    assert site.site_kind == "lattice"
    assert site.metal_relation == "boundary"
    assert site.atom_id == 0


def test_project_status_does_not_expose_a_server_path():
    contract = symbol("backend.contracts.projects", "ProjectStatus")

    decoded = contract.model_validate(fixture("project_status.json"))

    assert decoded.project_id == "project-a"
    assert "path" not in decoded.model_dump(mode="json")


def test_experiment_status_has_explicit_progress_fields():
    contract = symbol("backend.contracts.experiments", "ExperimentStatus")

    decoded = contract.model_validate(fixture("experiment_status.json"))

    assert decoded.completed_steps == 4
    assert decoded.total_steps == 12


def test_application_error_requires_recovery_classification():
    contract = symbol("backend.contracts.errors", "ApplicationError")
    payload = fixture("application_error.json")
    payload.pop("recoverable")

    with pytest.raises(ValidationError):
        contract.model_validate(payload)
