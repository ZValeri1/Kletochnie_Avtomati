import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import "./styles.css";

type Site = { kind: string; coordinate: number[]; key: string };
type Atom = { id: number; site: Site; state: string };
type Metrics = { vacancies: number; interstitials: number; defects: number; entropy: number };
type Snapshot = { revision: number; dimensions: number[]; mode: "2d" | "3d"; atoms: Atom[]; vacancies: Site[]; metrics: Metrics; act: number };
type Event = { act: number; revision: number; energy_ev: number; event_type: string; target_atom_id: number };

const palette: Record<string, string> = { correct: "#5b8def", surface: "#9a65c9", interstitial: "#ed8a34", surface_defect: "#b84d83" };

async function api<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!response.ok) throw new Error((await response.json()).detail ?? "Request failed");
  return response.json() as Promise<T>;
}

function LatticeScene({ snapshot, view3d }: { snapshot: Snapshot; view3d: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const atoms = useMemo(() => snapshot.atoms, [snapshot.atoms]);
  useEffect(() => {
    const container = host.current;
    if (!container) return;
    const scene = new THREE.Scene(); scene.background = new THREE.Color("#10151e");
    const renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.setSize(container.clientWidth, container.clientHeight); container.replaceChildren(renderer.domElement);
    const max = Math.max(...snapshot.dimensions);
    const camera = view3d ? new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 200) : new THREE.OrthographicCamera(-max, max, max, -max, 0.1, 200);
    camera.position.set(max * 1.3, max * 1.05, view3d ? max * 1.4 : 50); camera.lookAt((snapshot.dimensions[0] - 1) / 2, (snapshot.dimensions[1] - 1) / 2, view3d ? (snapshot.dimensions[2] - 1) / 2 : 0); scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    const geometry = new THREE.SphereGeometry(view3d ? 0.19 : 0.14, 16, 12);
    for (const atom of atoms) { const [x, y, z = 0] = atom.site.coordinate; const sphere = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: palette[atom.state] ?? palette.correct, roughness: 0.35, metalness: 0.25 })); sphere.position.set(x - (snapshot.dimensions[0] - 1) / 2, z - (snapshot.dimensions.length === 3 ? snapshot.dimensions[2] - 1 : 0) / 2, y - (snapshot.dimensions[1] - 1) / 2); scene.add(sphere); }
    const render = () => renderer.render(scene, camera); render();
    const resize = () => { if (camera instanceof THREE.PerspectiveCamera) camera.aspect = container.clientWidth / container.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(container.clientWidth, container.clientHeight); render(); }; window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); geometry.dispose(); renderer.dispose(); };
  }, [atoms, snapshot, view3d]);
  return <div className="scene" ref={host} aria-label="Визуализация кристаллической решётки" />;
}

function App() {
  const [mode, setMode] = useState<"2d" | "3d">("2d"); const [size, setSize] = useState(30); const [moved, setMoved] = useState(0); const [seed, setSeed] = useState(42); const [snapshot, setSnapshot] = useState<Snapshot | null>(null); const [events, setEvents] = useState<Event[]>([]); const [error, setError] = useState("");
  const create = async () => { try { setError(""); setEvents([]); const s = mode === "2d" ? size : Math.min(size, 30); setSnapshot(await api<Snapshot>("/api/model", { dimensions: mode === "2d" ? [s, s] : [s, s, s], moved_atoms: moved, seed_init: seed, seed_sim: seed + 1 })); } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка создания модели"); } };
  const step = async () => { try { const event = await api<Event>("/api/model/step", {}); setEvents((items) => [event, ...items].slice(0, 8)); setSnapshot(await api<Snapshot>("/api/model/snapshot")); } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка шага"); } };
  useEffect(() => { void create(); }, []);
  const metrics = snapshot?.metrics;
  return <main><aside className="sidebar"><div className="brand"><span className="brand-mark">g</span><div><strong>Gamma Irradiation</strong><small>qualitative lattice model</small></div></div><section><h2>Новая модель</h2><label>Пространство<select value={mode} onChange={(event) => setMode(event.target.value as "2d" | "3d")}><option value="2d">2D решётка</option><option value="3d">3D решётка</option></select></label><label>Размер оси<input type="number" min="2" max={mode === "2d" ? 200 : 30} value={size} onChange={(event) => setSize(Number(event.target.value))} /></label><label>Перемещённые атомы<input type="number" min="0" value={moved} onChange={(event) => setMoved(Number(event.target.value))} /></label><label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><button className="primary" onClick={() => void create()}>Создать модель</button></section><section><h2>Управление</h2><div className="button-row"><button title="Выполнить один акт облучения" onClick={() => void step()} disabled={!snapshot}>Один шаг</button><button title="Создать новую модель" onClick={() => void create()}>Сброс</button></div></section><p className="notice">Модель качественная: параметры требуют анализа чувствительности и не предсказывают свойства материала.</p></aside><section className="workspace"><header><div><span className="eyebrow">AUTHORITATIVE PYTHON STATE</span><h1>{mode === "2d" ? "Квадратная решётка" : "Кубическая решётка"}</h1></div><span className="revision">rev {snapshot?.revision ?? 0}</span></header>{error && <div className="error">{error}</div>}{snapshot && <LatticeScene snapshot={snapshot} view3d={mode === "3d"} />}<div className="legend">{Object.entries(palette).map(([state]) => <span key={state}><i className={state} />{state}</span>)}</div><div className="metrics">{[["Акт", snapshot?.act ?? 0], ["Вакансии", metrics?.vacancies ?? 0], ["Межузельные", metrics?.interstitials ?? 0], ["Дефекты", metrics?.defects ?? 0], ["Энтропия", metrics?.entropy.toFixed(3) ?? "0.000"]].map(([label, value]) => <div key={String(label)}><small>{label}</small><strong>{value}</strong></div>)}</div></section><aside className="diagnostics"><h2>Журнал актов</h2>{events.length === 0 ? <p className="muted">Выполните первый акт облучения.</p> : events.map((event) => <article key={event.revision}><strong>#{event.act} {event.event_type}</strong><span>Q = {event.energy_ev.toFixed(2)} eV</span><small>мишень: атом {event.target_atom_id}</small></article>)}</aside></main>;
}
createRoot(document.getElementById("root")!).render(<App />);
