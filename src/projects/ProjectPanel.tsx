import { useEffect, useState } from "react";
import type { ProjectStatus } from "../contracts";

export function ProjectPanel({
  name,
  onName,
  onSave,
  onLoad,
  onDelete,
  projects,
  simulations,
}: {
  name: string;
  onName: (name: string) => void;
  onSave: (simulationIds: string[]) => void;
  onLoad: () => void;
  onDelete: () => void;
  projects: ProjectStatus[];
  simulations: { id: string; label: string }[];
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const simulationKey = simulations.map((item) => item.id).join("|");
  useEffect(() => {
    setSelected((current) => {
      const available = new Set(simulations.map((item) => item.id));
      const retained = current.filter((id) => available.has(id));
      const added = simulations
        .map((item) => item.id)
        .filter((id) => !current.includes(id));
      return [...retained, ...added];
    });
  }, [simulationKey]);
  return (
    <section className="panel projects" data-testid="project-panel">
      <h2>Проекты</h2>
      <p className="muted">
        Продолжимый проект хранит состояние, RNG, журнал, метрики и доступную
        историю.
      </p>
      <input
        data-testid="project-name"
        value={name}
        onChange={(event) => onName(event.target.value)}
      />
      <fieldset className="project-simulations">
        <legend>Симуляции проекта</legend>
        {simulations.map((simulation) => (
          <label key={simulation.id}>
            <input
              type="checkbox"
              checked={selected.includes(simulation.id)}
              onChange={(event) =>
                setSelected((current) =>
                  event.target.checked
                    ? [...current, simulation.id]
                    : current.filter((id) => id !== simulation.id),
                )
              }
            />
            {simulation.label}
          </label>
        ))}
      </fieldset>
      <div className="row-actions">
        <button
          data-testid="save-project"
          disabled={!selected.length}
          onClick={() => onSave(selected)}
        >
          Сохранить
        </button>
        <button data-testid="load-project" onClick={onLoad}>
          Открыть
        </button>
        <button onClick={onDelete}>Удалить</button>
      </div>
      <ul className="project-list">
        {projects.map((project) => (
          <li key={project.project_id}>
            <button
              className="link-button"
              onClick={() => onName(project.project_id)}
            >
              {project.project_id}
            </button>
            <span>{project.simulation_count} сим.</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
