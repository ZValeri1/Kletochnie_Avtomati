import { useRef, useState } from "react";

export function SimulationName({
  name,
  onRename,
}: {
  name: string;
  onRename: (name: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const cancelled = useRef(false);
  const begin = () => {
    cancelled.current = false;
    setDraft(name);
    setError("");
    setEditing(true);
  };
  const save = async () => {
    if (cancelled.current || pending.current) return;
    const value = draft.trim();
    if (!value) {
      setError("Введите название эксперимента.");
      return;
    }
    if (value === name) {
      setEditing(false);
      return;
    }
    pending.current = true;
    setSaving(true);
    setError("");
    try {
      await onRename(value);
      setEditing(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить название.",
      );
    } finally {
      pending.current = false;
      setSaving(false);
    }
  };
  return editing ? (
    <div
      className="simulation-name-editor"
      onClick={(event) => event.stopPropagation()}
    >
      <input
        aria-label="Название эксперимента"
        data-testid="simulation-name-input"
        autoFocus
        maxLength={120}
        value={draft}
        disabled={saving}
        aria-invalid={Boolean(error)}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void save()}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void save();
          } else if (event.key === "Escape") {
            event.preventDefault();
            cancelled.current = true;
            setEditing(false);
          }
        }}
      />
      {saving && <small>Сохранение…</small>}
      {error && <small role="alert">{error}</small>}
    </div>
  ) : (
    <strong
      data-testid="simulation-name"
      className="simulation-name"
      role="button"
      tabIndex={0}
      title="Двойной щелчок или F2 — изменить название"
      onDoubleClick={(event) => {
        event.stopPropagation();
        begin();
      }}
      onKeyDown={(event) => {
        if (["Enter", "F2"].includes(event.key)) {
          event.preventDefault();
          begin();
        }
      }}
    >
      {name}
    </strong>
  );
}
