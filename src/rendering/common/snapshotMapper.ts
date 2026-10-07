import {
  decodeSimulationSnapshot,
  type ProbabilityOverlay,
  type SimulationEvent,
  type SimulationSnapshot,
} from "../../contracts";

export type RenderAtom = {
  id: number;
  site_key: string;
  coordinate: number[];
  site_kind: "lattice" | "interstitial";
  metal_relation: "interior" | "boundary" | "outside";
  visual_state: string;
};

export type RenderFrame = {
  simulation_id: string;
  revision: number;
  mode: "2d" | "3d";
  dimensions: number[];
  field_dimensions: number[];
  metal_dimensions: number[];
  metal_origin: number[];
  metal_contour: [number, number][] | null;
  atoms: RenderAtom[];
  vacancies: number[][];
  event_highlight_revision: number | null;
  highlighted_atom_ids: number[];
  highlighted_site_ids: string[];
  diagnostic_targets: {
    site_key: string;
    coordinate: number[];
    selectable: boolean;
    block_code: string | null;
  }[];
  last_event: {
    operation: SimulationEvent["operation"];
    q_n: number | null;
    act_number: number;
  } | null;
};

const knownStates = new Set([
  "correct",
  "boundary",
  "interstitial",
  "external",
]);

export function mapSnapshotToRenderFrame(
  value: SimulationSnapshot | unknown,
  lastEvent?: SimulationEvent | null,
  overlay?: ProbabilityOverlay | null,
): RenderFrame {
  const snapshot = decodeSimulationSnapshot(value);
  const currentEvent = lastEvent?.simulation_id === snapshot.simulation_id &&
    lastEvent.revision === snapshot.revision ? lastEvent : null;
  const currentOverlay = overlay?.simulation_id === snapshot.simulation_id &&
    overlay.revision === snapshot.revision ? overlay : null;
  const metalOrigin = snapshot.configuration.field_dimensions.map(
    (fieldSize, axis) =>
      Math.floor((fieldSize - snapshot.configuration.dimensions[axis]) / 2),
  );
  return {
    simulation_id: snapshot.simulation_id,
    revision: snapshot.revision,
    mode: snapshot.dimensions.length === 2 ? "2d" : "3d",
    dimensions: [...snapshot.dimensions],
    field_dimensions: [...snapshot.configuration.field_dimensions],
    metal_dimensions: [...snapshot.configuration.dimensions],
    metal_origin: metalOrigin,
    metal_contour: snapshot.configuration.contour?.map((point) => [
      point[0] + metalOrigin[0],
      point[1] + metalOrigin[1],
    ]) ?? null,
    atoms: snapshot.atoms.map((atom) => ({
      id: atom.id,
      site_key: atom.site_key,
      coordinate: [...atom.coordinate],
      site_kind: atom.site_kind,
      metal_relation: atom.metal_relation,
      visual_state: knownStates.has(atom.visual_state) ? atom.visual_state : "unknown",
    })),
    vacancies: snapshot.vacancies.map((coordinate) => [...coordinate]),
    event_highlight_revision: currentEvent?.revision ?? null,
    highlighted_atom_ids: currentEvent ? [...currentEvent.affected_atom_ids] : [],
    highlighted_site_ids: currentEvent ? [...currentEvent.affected_site_ids] : [],
    diagnostic_targets: currentOverlay?.outcomes.map((outcome) => ({
      site_key: outcome.destination_site,
      coordinate: [...outcome.destination_coordinate],
      selectable: outcome.selectable,
      block_code: outcome.block_code,
    })) ?? [],
    last_event: currentEvent ? {
      operation: currentEvent.operation,
      q_n: currentEvent.q_n,
      act_number: currentEvent.act_number,
    } : null,
  };
}
