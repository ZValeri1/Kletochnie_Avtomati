export function ExportPanel({
  onExport,
  onReport,
  onExportAll,
  emptySession,
  reporting,
  disabled,
}: {
  onExport: () => void;
  onReport: () => void;
  onExportAll: () => void;
  emptySession?: boolean;
  reporting?: boolean;
  disabled?: boolean;
}) {
  return (
    <section className="panel export-panel" data-testid="export-panel">
      <h2>Экспорт результатов</h2>
      <p className="muted">
        Отчёт об испытании: начальные параметры, все шесть графиков и данные
        CSV/JSON. Распакуйте ZIP и откройте report.html; графики также доступны
        в SVG.
      </p>
      <button
        data-testid="export-report"
        disabled={disabled || reporting}
        onClick={onReport}
      >
        {reporting
          ? "Формирование отчёта…"
          : "Скачать отчёт об испытании (ZIP)"}
      </button>
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
      <button
        data-testid="export-all-reports"
        disabled={emptySession || reporting}
        onClick={onExportAll}
      >
        Скачать все эксперименты сессии (ZIP)
      </button>
    </section>
  );
}
