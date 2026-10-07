import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { RenderFrame } from "../common/snapshotMapper";

const colourFor = (atom: RenderFrame["atoms"][number]) => {
  if (atom.metal_relation === "outside") return "#ef4444";
  if (atom.metal_relation === "boundary") return "#15803d";
  if (atom.site_kind === "interstitial") return "#fb923c";
  return "#22c55e";
};

export function Lattice2DRenderer({
  frame,
  highlightDurationMs = 800,
  selectedAtomId,
  onSelectAtom,
  onMove,
}: {
  frame: RenderFrame;
  highlightDurationMs?: number;
  selectedAtomId?: number | null;
  onSelectAtom?: (atomId: number | null) => void;
  onMove?: (atomId: number, destinationKey: string) => void;
}) {
  const reference = useRef<HTMLCanvasElement>(null);
  const dragAtom = useRef<number | null>(null);
  const panDrag = useRef<{ x: number; y: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [showPositions, setShowPositions] = useState(true);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const [highlighted, setHighlighted] = useState<Set<number>>(new Set());
  const geometry = useMemo(() => {
    const width = 900;
    const height = 560;
    const base = Math.min((width - 80) / Math.max(1, frame.field_dimensions[0] - 1), (height - 80) / Math.max(1, frame.field_dimensions[1] - 1));
    return { width, height, scale: base * zoom, ox: 40 + pan.x, oy: 40 + pan.y };
  }, [frame.field_dimensions, pan, zoom]);

  useEffect(() => {
    const canvas = reference.current;
    if (!canvas) return;
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      setZoom((value) =>
        Math.min(3, Math.max(0.5, value * (event.deltaY > 0 ? 0.9 : 1.1))),
      );
    };
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, []);

  useEffect(() => {
    if (frame.event_highlight_revision === null) {
      setHighlighted(new Set());
      return;
    }
    setHighlighted(new Set(frame.highlighted_atom_ids));
    const timer = window.setTimeout(() => setHighlighted(new Set()), highlightDurationMs);
    return () => window.clearTimeout(timer);
  }, [frame.event_highlight_revision]);

  useEffect(() => {
    const canvas = reference.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const { scale, ox, oy } = geometry;
    const latticeRadius = Math.max(2.5, scale * 0.2);
    const interstitialRadius = Math.max(2.2, scale * 0.17);
    const vacancyHalfSize = Math.max(2.4, scale * 0.14);
    const diagnosticRadius = Math.max(3.5, scale * 0.25);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#07111f";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#64748b";
    context.lineWidth = 1;
    if (showPositions) {
      for (let x = 0; x < frame.field_dimensions[0]; x += 1) {
        for (let y = 0; y < frame.field_dimensions[1]; y += 1) {
          context.beginPath();
          context.arc(ox + x * scale, oy + y * scale, 1.5, 0, Math.PI * 2);
          context.fill();
        }
      }
      context.fillStyle = "#475569";
      for (let x = 0; x < frame.field_dimensions[0] - 1; x += 1) {
        for (let y = 0; y < frame.field_dimensions[1] - 1; y += 1) {
          context.beginPath();
          context.arc(ox + (x + 0.5) * scale, oy + (y + 0.5) * scale, 1.2, 0, Math.PI * 2);
          context.fill();
        }
      }
    }
    context.strokeStyle = "#334155";
    context.strokeRect(ox, oy, (frame.field_dimensions[0] - 1) * scale, (frame.field_dimensions[1] - 1) * scale);
    context.strokeStyle = "#94a3b8";
    context.setLineDash([5, 5]);
    if (frame.metal_contour?.length) {
      context.beginPath();
      frame.metal_contour.forEach(([x, y], index) => index ? context.lineTo(ox + x * scale, oy + y * scale) : context.moveTo(ox + x * scale, oy + y * scale));
      context.stroke();
    } else {
      context.strokeRect(
        ox + frame.metal_origin[0] * scale,
        oy + frame.metal_origin[1] * scale,
        (frame.metal_dimensions[0] - 1) * scale,
        (frame.metal_dimensions[1] - 1) * scale,
      );
    }
    context.setLineDash([]);
    for (const vacancy of frame.vacancies) {
      context.strokeStyle = "#f8fafc";
      context.lineWidth = Math.max(1, scale * 0.045);
      context.strokeRect(
        ox + vacancy[0] * scale - vacancyHalfSize,
        oy + vacancy[1] * scale - vacancyHalfSize,
        vacancyHalfSize * 2,
        vacancyHalfSize * 2,
      );
    }
    for (const target of frame.diagnostic_targets) {
      context.beginPath();
      context.arc(ox + target.coordinate[0] * scale, oy + target.coordinate[1] * scale, diagnosticRadius, 0, Math.PI * 2);
      context.strokeStyle = target.selectable ? "#38bdf8" : "#f59e0b";
      context.setLineDash(target.selectable ? [] : [3, 3]);
      context.lineWidth = 2;
      context.stroke();
    }
    context.setLineDash([]);
    for (const atom of frame.atoms) {
      const radius = atom.site_kind === "interstitial"
        ? interstitialRadius
        : latticeRadius;
      context.beginPath();
      context.arc(ox + atom.coordinate[0] * scale, oy + atom.coordinate[1] * scale, radius, 0, Math.PI * 2);
      context.fillStyle = highlighted.has(atom.id) ? "#fde047" : colourFor(atom);
      context.fill();
      context.strokeStyle = atom.id === selectedAtomId ? "#ffffff" : atom.site_kind === "interstitial" ? "#0f172a" : "#cbd5e1";
      context.lineWidth = atom.id === selectedAtomId ? Math.max(2, scale * 0.075) : Math.max(1, scale * 0.025);
      context.stroke();
      if (atom.metal_relation === "boundary") {
        const boundaryHalfSize = radius * 1.28;
        context.strokeRect(
          ox + atom.coordinate[0] * scale - boundaryHalfSize,
          oy + atom.coordinate[1] * scale - boundaryHalfSize,
          boundaryHalfSize * 2,
          boundaryHalfSize * 2,
        );
      } else if (atom.metal_relation === "outside") {
        const x = ox + atom.coordinate[0] * scale;
        const y = oy + atom.coordinate[1] * scale;
        const diamondRadius = radius * 1.45;
        context.beginPath();
        context.moveTo(x, y - diamondRadius);
        context.lineTo(x + diamondRadius, y);
        context.lineTo(x, y + diamondRadius);
        context.lineTo(x - diamondRadius, y);
        context.closePath();
        context.stroke();
      }
      if (atom.site_kind === "interstitial") {
        const x = ox + atom.coordinate[0] * scale;
        const y = oy + atom.coordinate[1] * scale;
        const markerRadius = radius * 0.58;
        context.beginPath();
        context.moveTo(x - markerRadius, y);
        context.lineTo(x + markerRadius, y);
        context.moveTo(x, y - markerRadius);
        context.lineTo(x, y + markerRadius);
        context.stroke();
      }
    }
  }, [frame, geometry, highlighted, selectedAtomId, showPositions]);

  const canvasPoint = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: (event.clientX - rect.left) * event.currentTarget.width / rect.width, y: (event.clientY - rect.top) * event.currentTarget.height / rect.height };
  };
  const nearestAtom = (x: number, y: number) => {
    const hitRadius = Math.max(8, geometry.scale * 0.25);
    return frame.atoms.find((atom) => Math.hypot(geometry.ox + atom.coordinate[0] * geometry.scale - x, geometry.oy + atom.coordinate[1] * geometry.scale - y) <= hitRadius);
  };
  const destinationKey = (x: number, y: number) => {
    const gx = Math.round(((x - geometry.ox) / geometry.scale) * 2) / 2;
    const gy = Math.round(((y - geometry.oy) / geometry.scale) * 2) / 2;
    const kind = Number.isInteger(gx) && Number.isInteger(gy) ? "lattice" : "interstitial";
    return `${kind}:${gx},${gy}`;
  };

  const pointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (event.button === 2) {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      panDrag.current = { x: event.clientX, y: event.clientY };
      dragAtom.current = null;
      setIsPanning(true);
      setTooltip(null);
      return;
    }
    const point = canvasPoint(event);
    const atom = nearestAtom(point.x, point.y);
    dragAtom.current = atom?.id ?? null;
    onSelectAtom?.(atom?.id ?? null);
  };

  const pointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (panDrag.current) {
      const rect = event.currentTarget.getBoundingClientRect();
      const dx = (event.clientX - panDrag.current.x) * event.currentTarget.width / rect.width;
      const dy = (event.clientY - panDrag.current.y) * event.currentTarget.height / rect.height;
      panDrag.current = { x: event.clientX, y: event.clientY };
      setPan((value) => ({ x: value.x + dx, y: value.y + dy }));
      return;
    }
    const point = canvasPoint(event);
    const atom = nearestAtom(point.x, point.y);
    const eventText = atom && highlighted.has(atom.id) && frame.last_event
      ? ` · акт ${frame.last_event.act_number}: ${frame.last_event.operation}, Q=${frame.last_event.q_n ?? "—"}`
      : "";
    setTooltip(atom
      ? {
          x: event.nativeEvent.offsetX,
          y: event.nativeEvent.offsetY,
          text: `#${atom.id} · ${atom.site_key} · ${atom.site_kind} · ${atom.metal_relation}${eventText}`,
        }
      : null);
    if (event.shiftKey && event.buttons === 1 && dragAtom.current === null) {
      setPan((value) => ({
        x: value.x + event.movementX,
        y: value.y + event.movementY,
      }));
    }
  };

  const pointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (panDrag.current || event.button === 2) {
      panDrag.current = null;
      setIsPanning(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      return;
    }
    const point = canvasPoint(event);
    if (dragAtom.current !== null && onMove) {
      onMove(dragAtom.current, destinationKey(point.x, point.y));
    }
    dragAtom.current = null;
  };

  const cancelPointer = () => {
    panDrag.current = null;
    dragAtom.current = null;
    setIsPanning(false);
  };

  return <div className="renderer-wrap"><div className="renderer-toolbar"><button data-testid="toggle-sites" aria-pressed={showPositions} onClick={() => setShowPositions((value) => !value)}>{showPositions ? "Скрыть позиции" : "Показать позиции"}</button></div><canvas ref={reference} width={900} height={560} data-testid="renderer-2d" className={`renderer-canvas${isPanning ? " is-panning" : ""}`} onContextMenu={(event) => event.preventDefault()} onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerMove={pointerMove} onPointerCancel={cancelPointer} />{tooltip && <div className="canvas-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>{tooltip.text}</div>}<div className="legend"><span><i className="ordered" />атом в узле</span><span><i className="boundary" />граничный атом □</span><span><i className="orange" />межузельный атом</span><span><i className="red" />за контуром ◇</span><span><i className="yellow" />попадание</span><span><i className="diagnostic" />диагностическая цель</span><span><i className="vacancy" />вакансия</span></div><p className="muted">Колесо — масштаб; правая кнопка мыши — перемещение поля; перетаскивание атома левой кнопкой — команда редактора.</p></div>;
}
