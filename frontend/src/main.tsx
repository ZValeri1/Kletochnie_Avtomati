import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import "./styles.css";

type Site = { coordinate: number[]; key: string; kind?: string };
type Atom = { id: number; site: Site; state: string };
type Metrics = { vacancies: number; defects: number; entropy: number };
type Config = {
  profile: string;
  q_max_ev: number;
  frenkel_threshold_ev: number;
  recombine_threshold_ev: number;
  thresholds: Record<string, number>;
  weights: Record<string, number>;
};
type Snapshot = {
  revision: number;
  dimensions: number[];
  atoms: Atom[];
  metrics: Metrics;
  act: number;
  can_undo: boolean;
  can_redo: boolean;
  history_index: number;
  history_length: number;
  config: Config;
};
type Event = {
  act: number;
  revision: number;
  energy_ev: number;
  event_type: string;
  target_atom_id: number;
  cascade?: CascadeBranch[];
};
type CascadeBranch = {
  sequence: number;
  parent_sequence: number | null;
  status: "committed" | "conflict_cancelled" | "dissipated";
  atom_id?: number;
  source_site: Site;
  destination_site?: Site;
  energy_ev: number;
  child_energy_ev?: number;
};
type Sample = { act: number; entropy: number; defects: number };
type Outcome = {
  event_type: string;
  probability: number;
  destinations: string[];
  active?: boolean;
  threshold_ev?: number;
};
type Destination = { key: string; kind: string; coordinate: number[] };

const palette: Record<string, string> = {
  correct: "#5b8def",
  surface: "#9a65c9",
  interstitial: "#ed8a34",
  surface_defect: "#b84d83",
};
const defaults: Config = {
  profile: "fe_co60_physical",
  q_max_ev: 82,
  frenkel_threshold_ev: 40,
  recombine_threshold_ev: 4,
  thresholds: {
    shift: 12,
    swap: 25,
    frenkel_create: 40,
    knock: 50,
    surface_shift: 9,
    surface_swap: 20,
    surface_frenkel_create: 30,
    surface_knock: 37.5,
    surface_out: 60,
    recombine_d1: 4,
    fill_d2: 4,
    interstitial_hop: 6,
    to_surface: 12,
    interstitial_swap: 15,
    replacement_knock: 45,
    surface_hop: 3,
    surface_return_d1: 6,
    surface_fill_d2: 8,
    surface_push: 10,
    to_interstitial: 18,
    replacement_return: 20,
  },
  weights: {
    shift: 0.7,
    frenkel_create: 0.2,
    knock: 0.08,
    swap: 0.02,
    surface_shift: 0.65,
    surface_frenkel_create: 0.2,
    surface_knock: 0.1,
    surface_swap: 0.03,
    surface_out: 0.02,
    recombine_d1: 0.9,
    fill_d2: 0.3,
    interstitial_hop: 1,
    to_surface: 0.01,
    interstitial_swap: 0.05,
    replacement_knock: 0.05,
    surface_hop: 1,
    surface_return_d1: 0.4,
    surface_fill_d2: 0.2,
    surface_push: 0.1,
    to_interstitial: 0.2,
    replacement_return: 0.05,
  },
};
const thresholdGroups = [
  {
    title: "Внутренний атом",
    keys: ["shift", "swap", "frenkel_create", "knock"],
  },
  {
    title: "Поверхностный атом",
    keys: [
      "surface_shift",
      "surface_swap",
      "surface_frenkel_create",
      "surface_knock",
      "surface_out",
    ],
  },
  {
    title: "Межузельный атом",
    keys: [
      "recombine_d1",
      "fill_d2",
      "interstitial_hop",
      "to_surface",
      "interstitial_swap",
      "replacement_knock",
    ],
  },
  {
    title: "Поверхностный дефект",
    keys: [
      "surface_hop",
      "surface_return_d1",
      "surface_fill_d2",
      "surface_push",
      "to_interstitial",
      "replacement_return",
    ],
  },
];
const thresholdLabels: Record<string, string> = {
  shift: "Смещение",
  swap: "Обмен",
  frenkel_create: "Пара Френкеля",
  knock: "Выбивание",
  surface_shift: "Смещение",
  surface_swap: "Обмен",
  surface_frenkel_create: "Пара Френкеля",
  surface_knock: "Выбивание",
  surface_out: "Выход на поверхность",
  recombine_d1: "Рекомбинация d=1",
  fill_d2: "Заполнение d=2",
  interstitial_hop: "Межузельный переход",
  to_surface: "Переход к поверхности",
  interstitial_swap: "Обмен с узлом",
  replacement_knock: "Замещающее выбивание",
  surface_hop: "Поверхностный переход",
  surface_return_d1: "Возврат d=1",
  surface_fill_d2: "Заполнение d=2",
  surface_push: "Поверхностный сдвиг",
  to_interstitial: "Переход в межузлие",
  replacement_return: "Замещающий возврат",
};
const sample = (snapshot: Snapshot): Sample => ({
  act: snapshot.act,
  entropy: snapshot.metrics.entropy,
  defects: snapshot.metrics.defects,
});
const duration = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(Math.floor((ms % 1000) / 10)).padStart(2, "0")}`;
async function api<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const payload = await res.text();
    try {
      const parsed = JSON.parse(payload) as { detail?: string };
      throw new Error(parsed.detail ?? "Request failed");
    } catch (error) {
      if (error instanceof SyntaxError)
        throw new Error(payload || "Request failed");
      throw error;
    }
  }
  return res.json() as Promise<T>;
}

function Chart({
  title,
  data,
  field,
  color,
}: {
  title: string;
  data: Sample[];
  field: "entropy" | "defects";
  color: string;
}) {
  const values = data.map((x) => x[field]);
  const max =
    field === "defects"
      ? Math.max(2, Math.ceil(Math.max(...values)))
      : Math.max(1, ...values);
  const mid = Math.floor((data.length - 1) / 2);
  const p = (v: number, i: number) =>
    `${15 + (i / Math.max(1, values.length - 1)) * 103},${88 - (v / max) * 72}`;
  const label = (v: number) =>
    field === "entropy" ? v.toFixed(2) : Number.isInteger(v) ? String(v) : v.toFixed(1);
  return (
    <article className="chart">
      <div className="chart-title">
        <small>{title}</small>
        <strong>
          {field === "entropy"
            ? (values.at(-1) ?? 0).toFixed(3)
            : (values.at(-1) ?? 0)}
        </strong>
      </div>
      <div className="chart-plot">
        <svg viewBox="0 0 120 108" preserveAspectRatio="none" aria-hidden="true">
          <path d="M15 16H118M15 52H118M15 88H118" className="chart-grid" />
          <polyline
            points={values.length < 2 ? "15,88 118,88" : values.map(p).join(" ")}
            fill="none"
            stroke={color}
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <span className="chart-y chart-y-max">{label(max)}</span>
        <span className="chart-y chart-y-mid">{label(max / 2)}</span>
        <span className="chart-y chart-y-zero">0</span>
        <div className="chart-x">
          {data.length < 2 ? (
            <span className="chart-x-single">N={data[0]?.act ?? 0}</span>
          ) : (
            <>
              <span>N={data[0]?.act ?? 0}</span>
              <span>N={data[mid]?.act ?? 0}</span>
              <span>N={data.at(-1)?.act ?? 0}</span>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

function Lattice2D({
  snapshot,
  selected,
  choose,
  editMode,
  moveAtom,
  cascade,
}: {
  snapshot: Snapshot;
  selected: number | null;
  choose: (id: number) => void;
  editMode: boolean;
  moveAtom: (atomId: number, coordinate: number[]) => void;
  cascade?: CascadeBranch[];
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ atomId: number; x: number; y: number } | null>(null);
  const project = () => {
    const canvas = ref.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const [nx, ny] = snapshot.dimensions;
    const step = Math.min(
      (rect.width - 60) / Math.max(1, nx - 1),
      (rect.height - 60) / Math.max(1, ny - 1),
    );
    return {
      rect,
      nx,
      ny,
      step,
      ox: (rect.width - step * (nx - 1)) / 2,
      oy: (rect.height - step * (ny - 1)) / 2,
    };
  };
  useEffect(() => {
    const canvas = ref.current;
    const view = project();
    if (!canvas || !view) return;
    const ratio = Math.min(devicePixelRatio, 2);
    canvas.width = view.rect.width * ratio;
    canvas.height = view.rect.height * ratio;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, view.rect.width, view.rect.height);
    ctx.strokeStyle = "#273348";
    for (let x = 0; x < view.nx; x += 1) {
      ctx.beginPath();
      ctx.moveTo(view.ox + x * view.step, view.oy);
      ctx.lineTo(view.ox + x * view.step, view.oy + view.step * (view.ny - 1));
      ctx.stroke();
    }
    for (let y = 0; y < view.ny; y += 1) {
      ctx.beginPath();
      ctx.moveTo(view.ox, view.oy + y * view.step);
      ctx.lineTo(view.ox + view.step * (view.nx - 1), view.oy + y * view.step);
      ctx.stroke();
    }
    for (const atom of snapshot.atoms) {
      const [x, y] = atom.site.coordinate;
      const px = view.ox + x * view.step;
      const py = view.oy + y * view.step;
      if (selected === atom.id) {
        ctx.fillStyle = "#f7d654";
        ctx.beginPath();
        ctx.arc(px, py, Math.max(9, view.step * 0.34), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = palette[atom.state] ?? palette.correct;
      ctx.beginPath();
      ctx.arc(
        px,
        py,
        Math.max(3, Math.min(7, view.step * 0.22)),
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }
    for (const branch of cascade ?? []) {
      const [sx, sy] = branch.source_site.coordinate;
      const sourceX = view.ox + sx * view.step;
      const sourceY = view.oy + sy * view.step;
      const color =
        branch.status === "committed"
          ? "#f7d654"
          : branch.status === "conflict_cancelled"
            ? "#e45d74"
            : "#a5b4c9";
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2.5;
      if (branch.destination_site) {
        const [dx, dy] = branch.destination_site.coordinate;
        const destinationX = view.ox + dx * view.step;
        const destinationY = view.oy + dy * view.step;
        const angle = Math.atan2(destinationY - sourceY, destinationX - sourceX);
        ctx.beginPath();
        ctx.moveTo(sourceX, sourceY);
        ctx.lineTo(destinationX, destinationY);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(destinationX, destinationY);
        ctx.lineTo(
          destinationX - 8 * Math.cos(angle - Math.PI / 6),
          destinationY - 8 * Math.sin(angle - Math.PI / 6),
        );
        ctx.lineTo(
          destinationX - 8 * Math.cos(angle + Math.PI / 6),
          destinationY - 8 * Math.sin(angle + Math.PI / 6),
        );
        ctx.closePath();
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.arc(sourceX, sourceY, 7, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }, [snapshot, selected, cascade]);
  const hitAtom = (event: ReactMouseEvent<HTMLCanvasElement>) => {
    const view = project();
    if (!view) return null;
    const x = event.clientX - view.rect.left;
    const y = event.clientY - view.rect.top;
    const hit = snapshot.atoms.reduce<{ id: number; d: number } | null>(
      (best, atom) => {
        const d = Math.hypot(
          x - (view.ox + atom.site.coordinate[0] * view.step),
          y - (view.oy + atom.site.coordinate[1] * view.step),
        );
        return !best || d < best.d ? { id: atom.id, d } : best;
      },
      null,
    );
    return hit && hit.d < Math.max(14, view.step * 0.45) ? hit : null;
  };
  const click = (event: ReactMouseEvent<HTMLCanvasElement>) => {
    const hit = hitAtom(event);
    if (hit) choose(hit.id);
  };
  const startDrag = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!editMode) return;
    const hit = hitAtom(event);
    if (!hit) return;
    drag.current = { atomId: hit.id, x: event.clientX, y: event.clientY };
    choose(hit.id);
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const endDrag = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!editMode || !drag.current) return;
    const started = drag.current;
    drag.current = null;
    const view = project();
    if (
      !view ||
      Math.hypot(event.clientX - started.x, event.clientY - started.y) < 4
    )
      return;
    moveAtom(started.atomId, [
      (event.clientX - view.rect.left - view.ox) / view.step,
      (event.clientY - view.rect.top - view.oy) / view.step,
    ]);
  };
  return (
    <canvas
      className={`scene scene-2d ${editMode ? "scene-editing" : ""}`}
      ref={ref}
      onClick={editMode ? undefined : click}
      onPointerDown={startDrag}
      onPointerUp={endDrag}
      aria-label="Вид сверху на 2D решётку"
    />
  );
}

function Lattice3D({
  snapshot,
  selected,
  choose,
}: {
  snapshot: Snapshot;
  selected: number | null;
  choose: (id: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#10151e");
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(element.clientWidth, element.clientHeight);
    element.replaceChildren(renderer.domElement);
    const [nx, ny, nz] = snapshot.dimensions;
    const max = Math.max(nx, ny, nz);
    const camera = new THREE.PerspectiveCamera(
      45,
      element.clientWidth / element.clientHeight,
      0.1,
      400,
    );
    camera.position.set(max * 1.25, max, max * 1.35);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = max * 0.6;
    controls.maxDistance = max * 4;
    scene.add(
      new THREE.AmbientLight(0xffffff, 1.5),
      new THREE.DirectionalLight(0xb7ccf0, 1.2),
      new THREE.GridHelper(max, max, 0x33445b, 0x263244),
    );
    const geometry = new THREE.SphereGeometry(0.19, 16, 12);
    const meshes: THREE.Object3D[] = [];
    for (const atom of snapshot.atoms) {
      const [x, y, z] = atom.site.coordinate;
      const mesh = new THREE.Mesh(
        geometry,
        new THREE.MeshStandardMaterial({
          color: palette[atom.state] ?? palette.correct,
          roughness: 0.35,
          metalness: 0.25,
        }),
      );
      mesh.userData.atom = atom.id;
      mesh.position.set(x - (nx - 1) / 2, z - (nz - 1) / 2, y - (ny - 1) / 2);
      meshes.push(mesh);
      scene.add(mesh);
      if (atom.id === selected) {
        const ring = new THREE.Mesh(
          new THREE.SphereGeometry(0.29, 16, 12),
          new THREE.MeshBasicMaterial({ color: "#f7d654", wireframe: true }),
        );
        ring.position.copy(mesh.position);
        scene.add(ring);
      }
    }
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const pick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        (-(event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(meshes, false)[0];
      if (hit) choose(hit.object.userData.atom as number);
    };
    renderer.domElement.addEventListener("click", pick);
    let id = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      id = requestAnimationFrame(render);
    };
    render();
    const resize = () => {
      camera.aspect = element.clientWidth / element.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(element.clientWidth, element.clientHeight);
    };
    addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(id);
      renderer.domElement.removeEventListener("click", pick);
      removeEventListener("resize", resize);
      controls.dispose();
      geometry.dispose();
      renderer.dispose();
    };
  }, [snapshot, selected, choose]);
  return <div className="scene" ref={host} aria-label="Вращаемая 3D решётка" />;
}

function AxisInputs({
  mode,
  values,
  change,
}: {
  mode: "2d" | "3d";
  values: number[];
  change: (index: number, value: number) => void;
}) {
  return (
    <div className="axis-inputs">
      {["X", "Y", "Z"].slice(0, mode === "2d" ? 2 : 3).map((axis, i) => (
        <label key={axis}>
          {axis}
          <input
            type="number"
            min="2"
            value={values[i]}
            onChange={(e) => change(i, Number(e.target.value))}
          />
        </label>
      ))}
    </div>
  );
}

function App() {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [size, setSize] = useState([30, 30, 12]);
  const [moved, setMoved] = useState(0);
  const [surfaceMoved, setSurfaceMoved] = useState(0);
  const [concentration, setConcentration] = useState<number | "">("");
  const [seed, setSeed] = useState(42);
  const [config, setConfig] = useState<Config>(defaults);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [cascadeEvent, setCascadeEvent] = useState<Event | null>(null);
  const [history, setHistory] = useState<Sample[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [mouseMode, setMouseMode] = useState<"view" | "probability" | "edit">(
    "view",
  );
  const [energy, setEnergy] = useState(40);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [simulation, setSimulation] = useState<
    "paused" | "forward" | "reverse"
  >("paused");
  const [speed, setSpeed] = useState(80);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const commit = (next: Snapshot, branch = false) => {
    setSnapshot(next);
    setConfig(next.config);
    setHistory((old) =>
      branch
        ? [...old.slice(0, next.history_index), sample(next)]
        : old.length > next.history_index
          ? old
          : [...old, sample(next)],
    );
  };
  const guard = async (work: () => Promise<void>) => {
    if (busy.current) return;
    try {
      busy.current = true;
      setError("");
      await work();
    } catch (reason) {
      setSimulation("paused");
      setError(reason instanceof Error ? reason.message : "Ошибка");
    } finally {
      busy.current = false;
    }
  };
  const create = async () => {
    try {
      setSimulation("paused");
      setElapsed(0);
      setEvents([]);
      setCascadeEvent(null);
      setSelected(null);
      const next = await api<Snapshot>("/api/model", {
        ...config,
        dimensions: size.slice(0, mode === "2d" ? 2 : 3),
        moved_atoms: moved,
        moved_surface_atoms: surfaceMoved,
        defect_concentration: concentration === "" ? null : concentration,
        seed_init: seed,
        seed_sim: seed + 1,
      });
      setSnapshot(next);
      setConfig(next.config);
      setHistory([sample(next)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка создания");
    }
  };
  const step = async () => {
    const event = await api<Event>("/api/model/step", {});
    setEvents((old) => [event, ...old].slice(0, 200));
    if (event.cascade?.length) setCascadeEvent(event);
    setSelected(event.target_atom_id);
    commit(await api<Snapshot>("/api/model/snapshot"), true);
  };
  const travel = async (dir: "undo" | "redo") =>
    commit(await api<Snapshot>(`/api/model/${dir}`, {}));
  const choose = (id: number) => {
    setSimulation("paused");
    setSelected(id);
  };
  useEffect(() => {
    void create();
  }, []);
  useEffect(() => {
    if (selected === null || simulation !== "paused") {
      setOutcomes([]);
      setDestinations([]);
      return;
    }
    void guard(async () => {
      if (mouseMode === "probability") {
        const result = await api<{ outcomes: Outcome[] }>(
          "/api/model/probabilities",
          { atom_id: selected, energy_ev: energy },
        );
        setOutcomes(result.outcomes);
        setDestinations([]);
      } else if (mouseMode === "edit") {
        const result = await api<{ destinations: Destination[] }>(
          `/api/model/atoms/${selected}/destinations`,
        );
        setDestinations(result.destinations);
        setOutcomes([]);
      } else {
        setOutcomes([]);
        setDestinations([]);
      }
    });
  }, [selected, mouseMode, energy, simulation]);
  useEffect(() => {
    if (simulation === "paused") return;
    const timer = setInterval(() => {
      void guard(async () => {
        if (simulation === "forward") await step();
        else if (snapshot?.can_undo) await travel("undo");
        else setSimulation("paused");
      });
    }, speed);
    return () => clearInterval(timer);
  }, [simulation, snapshot, speed]);
  useEffect(() => {
    if (simulation === "paused") return;
    const timer = setInterval(() => setElapsed((x) => x + 100), 100);
    return () => clearInterval(timer);
  }, [simulation]);
  const updateConfig = (
    name:
      | "profile"
      | "q_max_ev"
      | "frenkel_threshold_ev"
      | "recombine_threshold_ev",
    value: string | number,
  ) => setConfig((current) => ({ ...current, [name]: value }));
  const axis = (i: number, value: number) =>
    setSize((old) =>
      old.map((x, key) => (key === i ? Math.max(2, value || 2) : x)),
    );
  const selectedAtom = snapshot?.atoms.find((x) => x.id === selected);
  const move = (destination: Destination) =>
    void guard(async () => {
      if (selected === null) return;
      const event = await api<Event>("/api/model/move", {
        atom_id: selected,
        destination_key: destination.key,
      });
      setEvents((old) => [event, ...old].slice(0, 200));
      commit(await api<Snapshot>("/api/model/snapshot"), true);
      setDestinations([]);
    });
  const moveFromDrop = (atomId: number, coordinate: number[]) =>
    void guard(async () => {
      const result = await api<{ destinations: Destination[] }>(
        `/api/model/atoms/${atomId}/destinations`,
      );
      const destination = result.destinations.reduce<Destination | null>(
        (closest, candidate) => {
          const distance = Math.hypot(
            coordinate[0] - candidate.coordinate[0],
            coordinate[1] - candidate.coordinate[1],
          );
          return !closest ||
            distance <
              Math.hypot(
                coordinate[0] - closest.coordinate[0],
                coordinate[1] - closest.coordinate[1],
              )
            ? candidate
            : closest;
        },
        null,
      );
      if (!destination) throw new Error("Нет допустимого места для переноса");
      const event = await api<Event>("/api/model/move", {
        atom_id: atomId,
        destination_key: destination.key,
      });
      setSelected(atomId);
      setEvents((old) => [event, ...old].slice(0, 200));
      commit(await api<Snapshot>("/api/model/snapshot"), true);
      setDestinations([]);
    });
  const visible = history.slice(0, (snapshot?.history_index ?? 0) + 1);
  return (
    <main>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">g</span>
          <div>
            <strong>Gamma Irradiation</strong>
            <small>qualitative lattice model</small>
          </div>
        </div>
        <section className="panel">
          <h2>Новая модель</h2>
          <label>
            Пространство
            <select
              value={mode}
              onChange={(e) => {
                const next = e.target.value as "2d" | "3d";
                setMode(next);
                setSize(next === "2d" ? [30, 30, 12] : [12, 12, 12]);
              }}
            >
              <option value="2d">2D решётка</option>
              <option value="3d">3D решётка</option>
            </select>
          </label>
          <label>Размеры решётки</label>
          <AxisInputs mode={mode} values={size} change={axis} />
          <label>
            Внутренние дефекты
            <input
              type="number"
              min="0"
              value={moved}
              onChange={(e) => setMoved(Number(e.target.value))}
            />
          </label>
          <label>
            Поверхностные дефекты
            <input
              type="number"
              min="0"
              value={surfaceMoved}
              onChange={(e) => setSurfaceMoved(Number(e.target.value))}
            />
          </label>
          <label>
            Концентрация c
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={concentration}
              onChange={(e) =>
                setConcentration(
                  e.target.value === "" ? "" : Number(e.target.value),
                )
              }
            />
          </label>
          <label>
            Seed
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
          <button className="primary" onClick={() => void create()}>
            Создать модель
          </button>
        </section>
        <section className="panel">
          <h2>Симуляция</h2>
          <div className="timer">
            <small>Время симуляции</small>
            <strong>{duration(elapsed)}</strong>
          </div>
          <label>
            Скорость: {speed} мс
            <input
              type="range"
              min="40"
              max="1200"
              step="20"
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
          </label>
          <div className="simulation-controls">
            <button onClick={() => void guard(step)}>Шаг</button>
            <button
              className={simulation === "forward" ? "active-control" : ""}
              onClick={() => setSimulation("forward")}
            >
              Пуск
            </button>
            <button onClick={() => setSimulation("paused")}>Пауза</button>
            <button
              onClick={() => void guard(() => travel("undo"))}
              disabled={!snapshot?.can_undo}
            >
              Назад
            </button>
            <button
              className={simulation === "reverse" ? "active-control" : ""}
              onClick={() => setSimulation("reverse")}
              disabled={!snapshot?.can_undo}
            >
              Обратно
            </button>
            <button
              onClick={() => void guard(() => travel("redo"))}
              disabled={!snapshot?.can_redo}
            >
              Вперёд
            </button>
          </div>
        </section>
        <section className="panel system-parameters">
          <h2>Параметры системы</h2>
          <label>
            Энергетический профиль
            <select
              value={config.profile}
              onChange={(e) => updateConfig("profile", e.target.value)}
            >
              <option value="fe_co60_physical">Fe / Co-60</option>
              <option value="cascade_test">Cascade test</option>
            </select>
          </label>
          <div className="parameter-grid">
            <label>
              Qmax, эВ
              <input
                type="number"
                min="0"
                value={config.q_max_ev}
                onChange={(e) =>
                  updateConfig("q_max_ev", Number(e.target.value))
                }
              />
            </label>
            <label>
              Порог Френкеля, эВ
              <input
                type="number"
                min="0"
                value={config.frenkel_threshold_ev}
                onChange={(e) =>
                  updateConfig("frenkel_threshold_ev", Number(e.target.value))
                }
              />
            </label>
            <label>
              Порог рекомбинации, эВ
              <input
                type="number"
                min="0"
                value={config.recombine_threshold_ev}
                onChange={(e) =>
                  updateConfig("recombine_threshold_ev", Number(e.target.value))
                }
              />
            </label>
          </div>
          <details>
            <summary>Пороги событий</summary>
            <div className="threshold-groups">
              {thresholdGroups.map((group) => (
                <section className="threshold-group" key={group.title}>
                  <h3>{group.title}</h3>
                  {group.keys.map((name) => (
                    <label key={name}>
                      <span>{thresholdLabels[name]}</span>
                      <input
                        type="number"
                        min="0"
                        value={config.thresholds[name] ?? 0}
                        onChange={(e) =>
                          setConfig((old) => ({
                            ...old,
                            thresholds: {
                              ...old.thresholds,
                              [name]: Number(e.target.value),
                            },
                          }))
                        }
                      />
                      <em>эВ</em>
                    </label>
                  ))}
                </section>
              ))}
            </div>
          </details>
          <details>
            <summary>Вероятности переходов</summary>
            <p className="weight-note">
              Относительные веса: доступные события нормируются до 100%.
            </p>
            <div className="threshold-groups">
              {thresholdGroups.map((group) => (
                <section
                  className="threshold-group"
                  key={`weight-${group.title}`}
                >
                  <h3>{group.title}</h3>
                  {group.keys.map((name) => (
                    <label key={name}>
                      <span>{thresholdLabels[name]}</span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={
                          config.weights[name] ??
                          config.weights[name.replace(/^surface_/, "")] ??
                          1
                        }
                        onChange={(e) =>
                          setConfig((old) => ({
                            ...old,
                            weights: {
                              ...old.weights,
                              [name]: Number(e.target.value),
                            },
                          }))
                        }
                      />
                      <em>вес</em>
                    </label>
                  ))}
                </section>
              ))}
            </div>
          </details>
        </section>
      </aside>
      <section className="workspace">
        <header>
          <div>
            <span className="eyebrow">
              AUTHORITATIVE PYTHON STATE ·{" "}
              {simulation === "paused"
                ? "ПАУЗА"
                : simulation === "forward"
                  ? "СИМУЛЯЦИЯ ВПЕРЁД"
                  : "ИСТОРИЯ НАЗАД"}
            </span>
            <h1>
              {mode === "2d"
                ? "2D: вид сверху"
                : "3D: перетаскивайте для вращения"}
            </h1>
          </div>
          <span className="revision">
            act {snapshot?.act ?? 0} · rev {snapshot?.revision ?? 0}
          </span>
        </header>
        {error && <div className="error">{error}</div>}
        {snapshot &&
          (mode === "2d" ? (
            <Lattice2D
              snapshot={snapshot}
              selected={selected}
              choose={choose}
              editMode={mouseMode === "edit"}
              moveAtom={moveFromDrop}
              cascade={cascadeEvent?.cascade}
            />
          ) : (
            <Lattice3D
              snapshot={snapshot}
              selected={selected}
              choose={choose}
            />
          ))}
        <div className="legend">
          {Object.entries(palette).map(([state]) => (
            <span key={state}>
              <i className={state} />
              {state}
            </span>
          ))}
        </div>
        <div className="metrics">
          {[
            ["Акт", snapshot?.act ?? 0],
            [
              "История",
              `${(snapshot?.history_index ?? 0) + 1}/${snapshot?.history_length ?? 1}`,
            ],
            ["Вакансии", snapshot?.metrics.vacancies ?? 0],
            ["Дефекты", snapshot?.metrics.defects ?? 0],
            ["Энтропия", snapshot?.metrics.entropy.toFixed(3) ?? "0.000"],
          ].map(([name, value]) => (
            <div key={String(name)}>
              <small>{name}</small>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <section className="charts">
          <Chart
            title="Энтропия S(N)"
            data={visible}
            field="entropy"
            color="#5b8def"
          />
          <Chart
            title="Дефекты D(N)"
            data={visible}
            field="defects"
            color="#ed8a34"
          />
        </section>
      </section>
      <aside className="diagnostics">
        <h2>Диагностика атома</h2>
        <div className="mode-controls">
          <button
            className={mouseMode === "view" ? "active-control" : ""}
            onClick={() => setMouseMode("view")}
          >
            Просмотр
          </button>
          <button
            className={mouseMode === "probability" ? "active-control" : ""}
            onClick={() => {
              setSimulation("paused");
              setMouseMode("probability");
            }}
          >
            Вероятности
          </button>
          <button
            className={mouseMode === "edit" ? "active-control" : ""}
            onClick={() => {
              setSimulation("paused");
              setMouseMode("edit");
            }}
          >
            Редактирование
          </button>
        </div>
        {selectedAtom && (
          <div className="selected-atom">
            <strong>Атом #{selectedAtom.id}</strong>
            <span>{selectedAtom.state}</span>
            <small>({selectedAtom.site.coordinate.join(", ")})</small>
          </div>
        )}
        {mouseMode === "probability" && (
          <div className="diagnostic-list">
            <label>
              Q test, эВ
              <input
                type="number"
                value={energy}
                onChange={(e) => setEnergy(Number(e.target.value))}
              />
            </label>
            {outcomes.map((x, i) => (
              <div
                key={`${x.event_type}-${i}`}
                className={x.active === false ? "inactive-outcome" : ""}
              >
                <strong>{thresholdLabels[x.event_type] ?? x.event_type}</strong>
                <span>{(x.probability * 100).toFixed(1)}%</span>
                {x.active === false && <small>Порог: {x.threshold_ev} эВ</small>}
                <small>{x.destinations.join(" → ")}</small>
              </div>
            ))}
          </div>
        )}
        {mouseMode === "edit" && (
          <div className="diagnostic-list">
            {destinations.slice(0, 40).map((x) => (
              <button key={x.key} onClick={() => move(x)}>
                {x.kind} ({x.coordinate.join(", ")})
              </button>
            ))}
          </div>
        )}
        {cascadeEvent && (
          <section className="cascade-trace" aria-live="polite">
            <h2>Каскад акта #{cascadeEvent.act}</h2>
            <p>
              {cascadeEvent.cascade?.filter((branch) => branch.status === "committed").length ?? 0}
              {" "}ветвей применено
            </p>
            <div>
              {cascadeEvent.cascade?.map((branch) => (
                <article key={branch.sequence} className={`cascade-${branch.status}`}>
                  <strong>#{branch.sequence} · {branch.status}</strong>
                  <small>Q {branch.energy_ev.toFixed(1)} eV</small>
                  {branch.destination_site && (
                    <small>
                      {branch.source_site.key} → {branch.destination_site.key}
                    </small>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}
        <h2>Журнал актов</h2>
        <div className="journal-list">
          {events.length ? (
            events.map((event) => (
              <button
                className={`event ${selected === event.target_atom_id ? "active" : ""}`}
                key={event.revision}
                onClick={() => {
                  if (event.cascade?.length) setCascadeEvent(event);
                  choose(event.target_atom_id);
                }}
              >
                <strong>
                  #{event.act} {event.event_type}
                </strong>
                <span>Q = {event.energy_ev.toFixed(2)} eV</span>
                <small>мишень: атом {event.target_atom_id}</small>
              </button>
            ))
          ) : (
            <p className="muted">Выполните первый акт облучения.</p>
          )}
        </div>
      </aside>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
