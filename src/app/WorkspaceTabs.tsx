import { useState, type ReactNode } from "react";

export type WorkspaceTab = {
  id: string;
  label: string;
  content: ReactNode;
};

export function WorkspaceTabs({ tabs }: { tabs: WorkspaceTab[] }) {
  const [activeId, setActiveId] = useState(tabs[0]?.id ?? "");
  const active = tabs.find((tab) => tab.id === activeId) ?? tabs[0];

  if (!active) return null;

  return (
    <section className="workspace-tools">
      <div
        className="workspace-tabs"
        role="tablist"
        aria-label="Инструменты симуляции"
        data-testid="workspace-tabs"
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`workspace-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={tab.id === active.id}
            aria-controls={`workspace-panel-${tab.id}`}
            tabIndex={tab.id === active.id ? 0 : -1}
            onClick={() => setActiveId(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        id={`workspace-panel-${active.id}`}
        className="workspace-tab-panel"
        role="tabpanel"
        aria-labelledby={`workspace-tab-${active.id}`}
      >
        {active.content}
      </div>
    </section>
  );
}
