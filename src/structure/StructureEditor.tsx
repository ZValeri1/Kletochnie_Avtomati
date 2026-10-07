import { useEffect, useState } from "react";
import type { PreparationEditInput } from "../api/simulationApi";
import type {
  DestinationOption,
  PreparationEditPreview,
  SimulationEvent,
  SimulationSnapshot,
} from "../contracts";
import type { CommandAvailability } from "../simulations/capabilities";

const destinationBlockMessage = (code: string) => ({
  SITE_OCCUPIED: "Позиция уже занята",
  DISCONNECTED_ATOM: "Атом потеряет связь с металлом",
  EXTERNAL_REENTRY_FORBIDDEN: "Внешний атом нельзя вернуть в металл",
  POSITION_OUTSIDE_FIELD: "Позиция находится за пределами поля",
  UNKNOWN_SITE: "Позиция не существует",
  DIMENSION_MISMATCH: "Размерность позиции не совпадает с моделью",
}[code] ?? "Переход отклонён серверной проверкой");

export function StructureEditor({
  snapshot,
  availability,
  selectedAtomId,
  destinations,
  preview,
  previewPending = false,
  previewError = "",
  lastEdit,
  pending,
  error,
  onSelectAtom,
  onPreview,
  onEdit,
}: {
  snapshot: SimulationSnapshot;
  availability: CommandAvailability;
  selectedAtomId: number | null;
  destinations: DestinationOption[];
  preview?: PreparationEditPreview | null;
  previewPending?: boolean;
  previewError?: string;
  lastEdit?: SimulationEvent | null;
  pending: boolean;
  error: string;
  onSelectAtom: (atomId: number | null) => void;
  onPreview?: (edit: PreparationEditInput) => void;
  onEdit: (edit: PreparationEditInput) => void;
}) {
  const [destination, setDestination] = useState("");
  const [contourText, setContourText] = useState("");
  useEffect(() => {
    setContourText(
      snapshot.configuration.contour
        ?.map((point) => point.join(","))
        .join("; ") ?? "",
    );
  }, [snapshot.simulation_id, snapshot.configuration.contour]);
  useEffect(() => {
    setDestination("");
  }, [snapshot.simulation_id, snapshot.revision]);

  const contour = () => contourText.split(";").map((point) =>
    point.trim().split(",").map((value) => Number(value)) as [number, number]);
  const selected = snapshot.atoms.find((atom) => atom.id === selectedAtomId);
  const is2D = snapshot.configuration.dimensions.length === 2;
  const allowedDestinations = destinations.filter((item) => item.selectable);
  const blockedDestinations = destinations.filter((item) => !item.selectable);
  const confirmedEdit = lastEdit?.origin === "manual_edit" ? lastEdit : null;
  const atomsFromMetrics = (metrics: SimulationEvent["metrics_before"]) =>
    metrics.n_correct + metrics.n_i + metrics.n_as;
  return (
    <section className="panel structure-editor" data-testid="structure-editor" aria-busy={pending || previewPending}>
      <h2>Редактор структуры</h2>
      <p className="muted">Изменение отправляется на сервер. До подтверждённого snapshot атом остаётся на прежнем месте.</p>
      <div className="editor-summary"><span>Атомов: {snapshot.counts.n_atoms}</span><span>V: {snapshot.metrics.n_v}</span><span>I: {snapshot.metrics.n_i}</span><span>As: {snapshot.metrics.n_as}</span><span>D: {snapshot.metrics.d}</span><span>S: {snapshot.metrics.s.toFixed(4)}</span></div>
      <label>Атом<select value={selectedAtomId ?? ""} onChange={(event) => onSelectAtom(event.target.value === "" ? null : Number(event.target.value))}><option value="">Не выбран</option>{snapshot.atoms.map((atom) => <option key={atom.id} value={atom.id}>#{atom.id} · {atom.site_key}</option>)}</select></label>
      <label>Позиция назначения<input data-testid="editor-destination" list="allowed-destinations" placeholder="lattice:2,3 или interstitial:2.5,3.5" value={destination} onChange={(event) => setDestination(event.target.value)} /></label>
      <datalist id="allowed-destinations">{allowedDestinations.map((item) => <option key={item.key} value={item.key}>{item.kind} · {item.coordinate.join(", ")}</option>)}</datalist>
      {selected && <p className="muted">Допустимых назначений по серверу: {allowedDestinations.length}. Выберите вариант из списка или укажите позицию для получения серверной причины отказа.</p>}
      {selected && blockedDestinations.length > 0 && (
        <details className="blocked-destinations" data-testid="blocked-destinations">
          <summary>Недоступные позиции и причины: {blockedDestinations.length}</summary>
          <ul>
            {blockedDestinations.map((item) => (
              <li key={item.key}>{item.key} — {destinationBlockMessage(item.block_code ?? "UNKNOWN")} ({item.block_code ?? "UNKNOWN"})</li>
            ))}
          </ul>
        </details>
      )}
      <div className="row-actions">
        <button data-testid="add-atom" disabled={!availability.add || pending || !destination} onClick={() => onEdit({ action: "add", destination_key: destination })}>Добавить</button>
        <button data-testid="remove-atom" disabled={!availability.remove || pending || !selected} onClick={() => selected && onEdit({ action: "remove", atom_id: selected.id })}>Удалить</button>
        <button data-testid="move-atom" disabled={!availability.move || pending || !selected || !destination} onClick={() => selected && onEdit({ action: "move", atom_id: selected.id, destination_key: destination })}>Переместить</button>
      </div>
      <div className="row-actions preview-actions">
        <button data-testid="preview-add" disabled={!availability.add || pending || previewPending || !destination} onClick={() => onPreview?.({ action: "add", destination_key: destination })}>Предпросмотр добавления</button>
        <button data-testid="preview-remove" disabled={!availability.remove || pending || previewPending || !selected} onClick={() => selected && onPreview?.({ action: "remove", atom_id: selected.id })}>Предпросмотр удаления</button>
        <button data-testid="preview-move" disabled={!availability.move || pending || previewPending || !selected || !destination} onClick={() => selected && onPreview?.({ action: "move", atom_id: selected.id, destination_key: destination })}>Предпросмотр переноса</button>
      </div>
      {error && <p className="field-error" role="alert" aria-live="assertive">Сервер отклонил действие: {error}</p>}
      <label>Ортогональный контур 2D<textarea data-testid="boundary-contour" value={contourText} disabled={!is2D || !availability.boundary} placeholder="0,0; 4,0; 4,4; 0,4; 0,0" onChange={(event) => setContourText(event.target.value)} /></label>
      <div className="row-actions">
        <button disabled={!is2D || !availability.boundary || pending || !contourText} onClick={() => onEdit({ action: "boundary", contour: contour() })}>Применить контур</button>
        <button data-testid="preview-boundary" disabled={!is2D || !availability.boundary || pending || previewPending || !contourText} onClick={() => onPreview?.({ action: "boundary", contour: contour() })}>Предпросмотр контура</button>
      </div>
      {!is2D && <p className="blocked-reason" data-testid="boundary-blocked-3d">В 3D граница задаётся прямоугольным параллелепипедом в конфигурации.</p>}
      {is2D && !availability.boundary && <p className="blocked-reason">Граница зафиксирована после запуска.</p>}
      {!availability.add && <p className="blocked-reason">После запуска доступны только перемещения существующих атомов на паузе.</p>}
      {previewPending && <p className="pending" aria-live="polite">Сервер рассчитывает предварительные метрики…</p>}
      {previewError && <p className="field-error" role="alert">Предпросмотр недоступен: {previewError}</p>}
      {pending && <p className="pending" aria-live="polite">Ожидается серверное подтверждение…</p>}
      {preview && (
        <div className="manual-edit-comparison" data-testid="manual-edit-preview">
          <h3>Предварительный просмотр: {preview.action}</h3>
          <table>
            <thead><tr><th>Показатель</th><th>До</th><th>После</th></tr></thead>
            <tbody>
              <tr><th>N_atoms</th><td data-testid="preview-before-n-atoms">{preview.counts_before.n_atoms}</td><td>{preview.counts_after.n_atoms}</td></tr>
              <tr><th>N_V</th><td>{preview.counts_before.n_v}</td><td data-testid="preview-after-n-v">{preview.counts_after.n_v}</td></tr>
              <tr><th>N_I</th><td>{preview.counts_before.n_i}</td><td data-testid="preview-after-n-i">{preview.counts_after.n_i}</td></tr>
              <tr><th>N_As</th><td>{preview.counts_before.n_as}</td><td>{preview.counts_after.n_as}</td></tr>
              <tr><th>D</th><td>{preview.metrics_before.d}</td><td data-testid="preview-after-d">{preview.metrics_after.d}</td></tr>
              <tr><th>S</th><td>{preview.metrics_before.s.toFixed(4)}</td><td>{preview.metrics_after.s.toFixed(4)}</td></tr>
            </tbody>
          </table>
          <p className="muted">Это серверный расчёт без изменения revision, истории или RNG.</p>
        </div>
      )}
      {confirmedEdit && (
        <div className="manual-edit-comparison" data-testid="manual-edit-comparison">
          <h3>Последняя подтверждённая ручная операция</h3>
          <table>
            <thead><tr><th>Показатель</th><th>До</th><th>После</th></tr></thead>
            <tbody>
              <tr><th>N_atoms</th><td data-testid="manual-before-n-atoms">{atomsFromMetrics(confirmedEdit.metrics_before)}</td><td>{atomsFromMetrics(confirmedEdit.metrics_after)}</td></tr>
              <tr><th>N_V</th><td>{confirmedEdit.metrics_before.n_v}</td><td>{confirmedEdit.metrics_after.n_v}</td></tr>
              <tr><th>N_I</th><td data-testid="manual-before-n-i">{confirmedEdit.metrics_before.n_i}</td><td data-testid="manual-after-n-i">{confirmedEdit.metrics_after.n_i}</td></tr>
              <tr><th>N_As</th><td>{confirmedEdit.metrics_before.n_as}</td><td data-testid="manual-after-n-as">{confirmedEdit.metrics_after.n_as}</td></tr>
              <tr><th>D</th><td>{confirmedEdit.metrics_before.d}</td><td>{confirmedEdit.metrics_after.d}</td></tr>
              <tr><th>S</th><td>{confirmedEdit.metrics_before.s.toFixed(4)}</td><td>{confirmedEdit.metrics_after.s.toFixed(4)}</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
