import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import "./styles.css";

type Site = { kind: string; coordinate: number[]; key: string };
type Atom = { id: number; site: Site; state: string };
type Metrics = { vacancies: number; interstitials: number; defects: number; entropy: number };
type Snapshot = { revision: number; dimensions: number[]; atoms: Atom[]; metrics: Metrics; act: number; can_undo: boolean; can_redo: boolean; history_index: number; history_length: number };
type Event = { act: number; revision: number; energy_ev: number; event_type: string; target_atom_id: number };
type Sample = { act: number; entropy: number; defects: number };

const palette: Record<string, string> = { correct: "#5b8def", surface: "#9a65c9", interstitial: "#ed8a34", surface_defect: "#b84d83" };

async function api<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!response.ok) throw new Error((await response.json()).detail ?? "Request failed");
  return response.json() as Promise<T>;
}

const sample = (snapshot: Snapshot): Sample => ({ act: snapshot.act, entropy: snapshot.metrics.entropy, defects: snapshot.metrics.defects });

function LineChart({ title, samples, field, color }: { title: string; samples: Sample[]; field: "entropy" | "defects"; color: string }) {
  const values = samples.map((item) => item[field]);
  const max = Math.max(1, ...values);
  const last = values.at(-1) ?? 0;
  const points = values.length < 2 ? "0,100 100,100" : values.map((value, index) => `${(index / (values.length - 1)) * 100},${100 - (value / max) * 92}`).join(" ");
  return <article className="chart"><div><small>{title}</small><strong>{last.toFixed(field === "entropy" ? 3 : 0)}</strong></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={title}><path d="M0 100H100M0 50H100M0 0H100" className="chart-grid" /><polyline points={points} fill="none" stroke={color} strokeWidth="2.5" vectorEffect="non-scaling-stroke" /></svg><footer>N = {samples.at(-1)?.act ?? 0}</footer></article>;
}

function Lattice2D({ snapshot, selectedAtomId }: { snapshot: Snapshot; selectedAtomId: number | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio, 2);
    canvas.width = bounds.width * ratio; canvas.height = bounds.height * ratio;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio); context.clearRect(0, 0, bounds.width, bounds.height);
    const [nx, ny] = snapshot.dimensions;
    const padding = 30; const step = Math.min((bounds.width - padding * 2) / Math.max(nx - 1, 1), (bounds.height - padding * 2) / Math.max(ny - 1, 1));
    const width = step * (nx - 1); const height = step * (ny - 1); const ox = (bounds.width - width) / 2; const oy = (bounds.height - height) / 2;
    context.strokeStyle = "#273348";
    for (let x = 0; x < nx; x += 1) { context.beginPath(); context.moveTo(ox + x * step, oy); context.lineTo(ox + x * step, oy + height); context.stroke(); }
    for (let y = 0; y < ny; y += 1) { context.beginPath(); context.moveTo(ox, oy + y * step); context.lineTo(ox + width, oy + y * step); context.stroke(); }
    for (const atom of snapshot.atoms) { const [x, y] = atom.site.coordinate; const px = ox + x * step; const py = oy + y * step; if (atom.id === selectedAtomId) { context.beginPath(); context.fillStyle = "#f7d654"; context.arc(px, py, Math.max(9, step * 0.34), 0, Math.PI * 2); context.fill(); } context.beginPath(); context.fillStyle = palette[atom.state] ?? palette.correct; context.arc(px, py, Math.max(3, Math.min(7, step * 0.22)), 0, Math.PI * 2); context.fill(); }
  }, [selectedAtomId, snapshot]);
  return <canvas className="scene scene-2d" ref={canvasRef} aria-label="Вид сверху на 2D кристаллическую решётку" />;
}

function Lattice3D({ snapshot, selectedAtomId }: { snapshot: Snapshot; selectedAtomId: number | null }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const container = host.current;
    if (!container) return;
    const scene = new THREE.Scene(); scene.background = new THREE.Color("#10151e");
    const renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.setSize(container.clientWidth, container.clientHeight); container.replaceChildren(renderer.domElement);
    const [nx, ny, nz] = snapshot.dimensions; const max = Math.max(nx, ny, nz); const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 400); camera.position.set(max * 1.25, max * 1.05, max * 1.35);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.minDistance = max * 0.6; controls.maxDistance = max * 4;
    scene.add(new THREE.AmbientLight(0xffffff, 1.5), new THREE.DirectionalLight(0xb7ccf0, 1.2), new THREE.GridHelper(max, max, 0x33445b, 0x263244));
    const geometry = new THREE.SphereGeometry(0.19, 16, 12);
    for (const atom of snapshot.atoms) { const [x, y, z] = atom.site.coordinate; const sphere = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: palette[atom.state] ?? palette.correct, roughness: 0.35, metalness: 0.25 })); sphere.position.set(x - (nx - 1) / 2, z - (nz - 1) / 2, y - (ny - 1) / 2); scene.add(sphere); if (atom.id === selectedAtomId) { const mark = new THREE.Mesh(new THREE.SphereGeometry(0.29, 16, 12), new THREE.MeshBasicMaterial({ color: "#f7d654", wireframe: true })); mark.position.copy(sphere.position); scene.add(mark); } }
    let frame = 0; const draw = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(draw); }; draw();
    const resize = () => { camera.aspect = container.clientWidth / container.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(container.clientWidth, container.clientHeight); };
    window.addEventListener("resize", resize);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", resize); controls.dispose(); geometry.dispose(); renderer.dispose(); };
  }, [selectedAtomId, snapshot]);
  return <div className="scene" ref={host} aria-label="Вращаемая 3D кристаллическая решётка" />;
}

function AxisInputs({ mode, dimensions, onChange }: { mode: "2d" | "3d"; dimensions: number[]; onChange: (axis: number, value: number) => void }) {
  return <div className="axis-inputs">{["X", "Y", "Z"].slice(0, mode === "2d" ? 2 : 3).map((axis, index) => <label key={axis}>{axis}<input aria-label={`Размер оси ${axis}`} type="number" min="2" max={mode === "2d" ? 200 : 30} value={dimensions[index]} onChange={(event) => onChange(index, Number(event.target.value))} /></label>)}</div>;
}

function App() {
  const [mode, setMode] = useState<"2d" | "3d">("2d"); const [dimensions, setDimensions] = useState([10, 10, 10]); const [moved, setMoved] = useState(0); const [seed, setSeed] = useState(42); const [snapshot, setSnapshot] = useState<Snapshot | null>(null); const [events, setEvents] = useState<Event[]>([]); const [samples, setSamples] = useState<Sample[]>([]); const [selectedAtomId, setSelectedAtomId] = useState<number | null>(null); const [error, setError] = useState(""); const [simulation, setSimulation] = useState<"paused" | "forward" | "reverse">("paused"); const [speed, setSpeed] = useState(260); const busy = useRef(false);
  const commitSnapshot = (next: Snapshot, branch = false) => { setSnapshot(next); setSamples((current) => branch ? [...current.slice(0, next.history_index), sample(next)] : current.length > next.history_index ? current : [...current, sample(next)]); };
  const create = async () => { try { setError(""); setEvents([]); setSelectedAtomId(null); setSimulation("paused"); const next = await api<Snapshot>("/api/model", { dimensions: dimensions.slice(0, mode === "2d" ? 2 : 3), moved_atoms: moved, seed_init: seed, seed_sim: seed + 1 }); setSnapshot(next); setSamples([sample(next)]); } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка создания модели"); } };
  const step = async () => { const event = await api<Event>("/api/model/step", {}); setEvents((items) => [event, ...items].slice(0, 80)); setSelectedAtomId(event.target_atom_id); commitSnapshot(await api<Snapshot>("/api/model/snapshot"), true); };
  const travel = async (direction: "undo" | "redo") => commitSnapshot(await api<Snapshot>(`/api/model/${direction}`, {}));
  const guarded = async (action: () => Promise<void>) => { if (busy.current) return; try { busy.current = true; setError(""); await action(); } catch (reason) { setSimulation("paused"); setError(reason instanceof Error ? reason.message : "Ошибка симуляции"); } finally { busy.current = false; } };
  useEffect(() => { void create(); }, []);
  useEffect(() => { if (simulation === "paused") return; const timer = window.setInterval(() => { void guarded(async () => { if (simulation === "forward") await step(); else if (snapshot?.can_undo) await travel("undo"); else setSimulation("paused"); }); }, speed); return () => window.clearInterval(timer); }, [simulation, snapshot, speed]);
  useEffect(() => { const listener = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); setSimulation("paused"); void guarded(() => travel("undo")); } }; window.addEventListener("keydown", listener); return () => window.removeEventListener("keydown", listener); }, [snapshot]);
  const selected = snapshot?.atoms.find((atom) => atom.id === selectedAtomId); const metrics = snapshot?.metrics; const visibleSamples = samples.slice(0, (snapshot?.history_index ?? 0) + 1); const axis = (index: number, value: number) => setDimensions((values) => values.map((current, key) => key === index ? Math.max(2, value || 2) : current));
  return <main><aside className="sidebar"><div className="brand"><span className="brand-mark">g</span><div><strong>Gamma Irradiation</strong><small>qualitative lattice model</small></div></div><section><h2>Новая модель</h2><label>Пространство<select value={mode} onChange={(event) => setMode(event.target.value as "2d" | "3d")}><option value="2d">2D решётка</option><option value="3d">3D решётка</option></select></label><label>Размеры решётки</label><AxisInputs mode={mode} dimensions={dimensions} onChange={axis} /><label>Перемещённые атомы<input type="number" min="0" value={moved} onChange={(event) => setMoved(Number(event.target.value))} /></label><label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><button className="primary" onClick={() => void create()}>Создать модель</button></section><section><h2>Симуляция</h2><label>Скорость: {speed} мс<input aria-label="Скорость симуляции" type="range" min="80" max="1200" step="20" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></label><div className="simulation-controls"><button onClick={() => void guarded(step)} disabled={!snapshot}>Шаг</button><button className={simulation === "forward" ? "active-control" : ""} onClick={() => setSimulation("forward")} disabled={!snapshot}>Пуск</button><button onClick={() => setSimulation("paused")} disabled={simulation === "paused"}>Пауза</button><button title="Ctrl+Z" onClick={() => void guarded(() => travel("undo"))} disabled={!snapshot?.can_undo}>Назад</button><button className={simulation === "reverse" ? "active-control" : ""} onClick={() => setSimulation("reverse")} disabled={!snapshot?.can_undo}>Обратно</button><button onClick={() => void guarded(() => travel("redo"))} disabled={!snapshot?.can_redo}>Вперёд</button></div></section><p className="notice">Модель качественная: параметры требуют анализа чувствительности и не предсказывают свойства материала.</p></aside><section className="workspace"><header><div><span className="eyebrow">AUTHORITATIVE PYTHON STATE · {simulation === "paused" ? "ПАУЗА" : simulation === "forward" ? "СИМУЛЯЦИЯ ВПЕРЁД" : "ИСТОРИЯ НАЗАД"}</span><h1>{mode === "2d" ? "2D: вид сверху" : "3D: перетаскивайте для вращения"}</h1></div><span className="revision">act {snapshot?.act ?? 0} · rev {snapshot?.revision ?? 0}</span></header>{error && <div className="error">{error}</div>}{snapshot && (mode === "2d" ? <Lattice2D snapshot={snapshot} selectedAtomId={selectedAtomId} /> : <Lattice3D snapshot={snapshot} selectedAtomId={selectedAtomId} />)}<div className="legend">{Object.entries(palette).map(([state]) => <span key={state}><i className={state} />{state}</span>)}{selected && <span className="selected-legend"><i />выбранный атом #{selected.id}</span>}</div><div className="metrics">{[["Акт", snapshot?.act ?? 0], ["История", `${(snapshot?.history_index ?? 0) + 1}/${snapshot?.history_length ?? 1}`], ["Вакансии", metrics?.vacancies ?? 0], ["Дефекты", metrics?.defects ?? 0], ["Энтропия", metrics?.entropy.toFixed(3) ?? "0.000"]].map(([label, value]) => <div key={String(label)}><small>{label}</small><strong>{value}</strong></div>)}</div><section className="charts"><LineChart title="Энтропия S(N)" samples={visibleSamples} field="entropy" color="#5b8def" /><LineChart title="Дефекты D(N)" samples={visibleSamples} field="defects" color="#ed8a34" /></section></section><aside className="diagnostics"><h2>Журнал актов</h2>{selected && <div className="selected-atom"><strong>Атом #{selected.id}</strong><span>{selected.state}</span><small>({selected.site.coordinate.join(", ")})</small></div>}<div className="journal-list">{events.length === 0 ? <p className="muted">Выполните первый акт облучения.</p> : events.map((event) => <button className={`event ${selectedAtomId === event.target_atom_id ? "active" : ""}`} key={event.revision} onClick={() => setSelectedAtomId(event.target_atom_id)}><strong>#{event.act} {event.event_type}</strong><span>Q = {event.energy_ev.toFixed(2)} eV</span><small>мишень: атом {event.target_atom_id}</small></button>)}</div></aside></main>;
}

createRoot(document.getElementById("root")!).render(<App />);
