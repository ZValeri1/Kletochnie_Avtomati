export function ExportPanel({
  onExport,
  disabled,
}: {
  onExport: () => void;
  disabled?: boolean;
}) {
  return (
    <section className="panel export-panel" data-testid="export-panel">
      <h2>Экспорт результатов</h2>
      <p className="muted">
        JSON выбранной симуляции предназначен для анализа и не содержит RNG и
        истории.
      </p>
      <button
        data-testid="export-journal"
        disabled={disabled}
        onClick={onExport}
      >
        Скачать журнал JSON
      </button>
    </section>
  );
}
