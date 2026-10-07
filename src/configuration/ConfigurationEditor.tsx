import { useEffect, useState } from "react";
import type {
  ConfigurationPatchInput,
  InitializationMode,
  OperationWeightsInput,
  SimulationCreateInput,
} from "../api/simulationApi";
import type { SimulationSnapshot } from "../contracts";

const number = (value: string) => Number(value);
const defaultWeights = {
  lattice_vacancy: 0.7,
  lattice_interstitial: 0.2,
  interstitial_vacancy_r1: 0.9,
  interstitial_vacancy_r2: 0.3,
  interstitial_interstitial: 1,
  boundary_external: 0.02,
  external_external: 1,
  external_interstitial: 0.2,
  interstitial_external: 1,
  external_metal: 0,
  shell_r1: 0.75,
  shell_r2: 0.25,
  vacancy: 0.8,
  interstitial: 0.2,
  external: 0.05,
} satisfies Required<OperationWeightsInput>;
type WeightKey = keyof typeof defaultWeights;

const probabilityLabels = new Map<WeightKey, string>([
  ["vacancy", "В свободный узел (вакансию)"],
  ["interstitial", "В свободное межузлие"],
  ["shell_r1", "Первый контур"],
  ["shell_r2", "Второй контур"],
  ["external", "Снаружи металла для внутреннего атома"],
  ["external_metal", "Внутрь металла для внешнего атома"],
]);
const defaultRandom = {
  vacancies: { mu: 1, sigma: 0.5 },
  interstitials: { mu: 1, sigma: 0.5 },
  adatoms: { mu: 0, sigma: 0.25 },
};

const defectCountLabels = {
  n_v: "Начальные вакансии",
  n_i: "Начальные межузельные атомы",
  n_as: "Начальные атомы за контуром",
} as const;

const randomDistributionLabels = {
  vacancies: "Вакансии",
  interstitials: "Межузельные атомы",
  adatoms: "Атомы за контуром",
} as const;

const formValues = (snapshot?: SimulationSnapshot | null) => {
  const configuration = snapshot?.configuration;
  return {
    mode: configuration?.dimensions.length === 3 ? "3d" as const : "2d" as const,
    dimensions: configuration ? [
      configuration.dimensions[0],
      configuration.dimensions[1],
      configuration.dimensions[2] ?? 4,
    ] : [5, 5, 4],
    initializationMode: configuration?.initialization_mode ?? "ordered",
    counts: configuration ? {
      n_v: configuration.n_v,
      n_i: configuration.n_i,
      n_as: configuration.n_as,
    } : { n_v: 0, n_i: 0, n_as: 0 },
    seeds: configuration ? {
      seed_init: configuration.seed_init,
      seed_sim: configuration.seed_sim,
    } : { seed_init: 41, seed_sim: 42 },
    qMax: configuration?.q_max_ev ?? 82,
    qThr: configuration?.q_thr_ev ?? 20,
    weights: { ...defaultWeights, ...configuration?.weights },
    random: { ...defaultRandom, ...configuration?.random_parameters },
  };
};

export function ConfigurationEditor({
  onCreate,
  onConfigure,
  currentSnapshot,
  pending = false,
  serverError = "",
}: {
  onCreate: (configuration: SimulationCreateInput) => void;
  onConfigure?: (configuration: ConfigurationPatchInput) => void;
  currentSnapshot?: SimulationSnapshot | null;
  pending?: boolean;
  serverError?: string;
}) {
  const initial = formValues(currentSnapshot);
  const [mode, setMode] = useState<"2d" | "3d">(initial.mode);
  const [dimensions, setDimensions] = useState(initial.dimensions);
  const [initializationMode, setInitializationMode] = useState<InitializationMode>(initial.initializationMode);
  const [counts, setCounts] = useState(initial.counts);
  const [seeds, setSeeds] = useState(initial.seeds);
  const [qMax, setQMax] = useState(initial.qMax);
  const [qThr, setQThr] = useState(initial.qThr);
  const [weights, setWeights] = useState(initial.weights);
  const [error, setError] = useState("");
  const [random, setRandom] = useState(initial.random);
  const configurationKey = currentSnapshot ? JSON.stringify(currentSnapshot.configuration) : "";

  useEffect(() => {
    if (!currentSnapshot) return;
    const next = formValues(currentSnapshot);
    setMode(next.mode);
    setDimensions(next.dimensions);
    setInitializationMode(next.initializationMode);
    setCounts(next.counts);
    setSeeds(next.seeds);
    setQMax(next.qMax);
    setQThr(next.qThr);
    setWeights(next.weights);
    setRandom(next.random);
  }, [currentSnapshot?.simulation_id, configurationKey]);

  const setDimension = (index: number, value: number) =>
    setDimensions((current) => current.map((item, i) => i === index ? value : item));

  const buildPayload = (): SimulationCreateInput | null => {
    const selectedDimensions = dimensions.slice(0, mode === "2d" ? 2 : 3);
    if (selectedDimensions.some((value) => !Number.isInteger(value) || value < 2)) {
      setError("Размеры должны быть целыми числами не меньше 2.");
      return null;
    }
    if ([counts.n_v, counts.n_i, counts.n_as].some((value) => !Number.isInteger(value) || value < 0)) {
      setError("Количество дефектов должно быть целым неотрицательным числом.");
      return null;
    }
    if (!Number.isFinite(qMax) || !Number.isFinite(qThr) || qMax < 0 || qThr < 0) {
      setError("Q_max и Q_thr должны быть неотрицательными числами.");
      return null;
    }
    if (Object.values(weights).some((value) => !Number.isFinite(value) || value < 0 || value > 1)) {
      setError("Все вероятности должны быть числами от 0 до 1.");
      return null;
    }
    if (Math.abs(weights.vacancy + weights.interstitial - 1) > 1e-9) {
      setError("Вероятности перехода в вакансию и межузлие должны давать 1.");
      return null;
    }
    if (Math.abs(weights.shell_r1 + weights.shell_r2 - 1) > 1e-9) {
      setError("Вероятности первого и второго контуров должны давать 1.");
      return null;
    }
    setError("");
    return {
      dimensions: selectedDimensions,
      initialization_mode: initializationMode,
      ...counts,
      random_parameters: initializationMode === "random_defective" ? random : undefined,
      ...seeds,
      q_max_ev: qMax,
      q_thr_ev: qThr,
      weights,
    };
  };

  const submit = (target: "create" | "configure") => {
    const configuration = buildPayload();
    if (!configuration) return;
    if (target === "create") onCreate(configuration);
    else onConfigure?.(configuration);
  };

  const locked = currentSnapshot?.config_locked ? currentSnapshot.configuration : null;
  const canConfigure = currentSnapshot?.status === "PREPARATION" && !currentSnapshot.config_locked;
  return (
    <section className="panel configuration">
      <h2>{canConfigure ? "Конфигурация выбранной симуляции" : "Новая конфигурация"}</h2>
      <div className="form-grid">
        <label>Размерность модели<select data-testid="dimension-mode" value={mode} onChange={(event) => setMode(event.target.value as "2d" | "3d")}><option value="2d">Двумерная (2D)</option><option value="3d">Трёхмерная (3D)</option></select></label>
        {dimensions.slice(0, mode === "2d" ? 2 : 3).map((value, index) => (
          <label key={index}>Размер металла по оси {"XYZ"[index]}, узлов<input data-testid={`dimension-${"xyz"[index]}`} type="number" min={2} value={value} onChange={(event) => setDimension(index, number(event.target.value))} /></label>
        ))}
        <label className="wide-field">Способ формирования начальной структуры<select data-testid="initialization-mode" value={initializationMode} onChange={(event) => setInitializationMode(event.target.value as InitializationMode)}><option value="ordered">Упорядоченная — без начальных дефектов</option><option value="random_defective">Случайное распределение дефектов</option><option value="explicit_defective">Заданное количество дефектов</option><option value="symmetric_defective">Симметричное распределение дефектов</option></select></label>
        {initializationMode !== "ordered" && initializationMode !== "random_defective" && (["n_v", "n_i", "n_as"] as const).map((key) => (
          <label key={key}>{defectCountLabels[key]}<input data-testid={key === "n_v" ? "initial-vacancies" : `initial-${key}`} type="number" min={0} value={counts[key]} onChange={(event) => setCounts({ ...counts, [key]: number(event.target.value) })} /></label>
        ))}
        {initializationMode === "random_defective" && (Object.keys(random) as (keyof typeof random)[]).map((key) => (
          <div className="distribution" key={key}><span>{randomDistributionLabels[key]}</span><label>Среднее количество (μ)<input type="number" value={random[key].mu} onChange={(event) => setRandom({ ...random, [key]: { ...random[key], mu: number(event.target.value) } })} /></label><label>Разброс значений (σ)<input type="number" min={0} value={random[key].sigma} onChange={(event) => setRandom({ ...random, [key]: { ...random[key], sigma: number(event.target.value) } })} /></label></div>
        ))}
        <label>Зерно генератора начальной структуры<input data-testid="seed-init" type="number" value={seeds.seed_init} onChange={(event) => setSeeds({ ...seeds, seed_init: number(event.target.value) })} /></label>
        <label>Зерно генератора хода симуляции<input data-testid="seed-sim" type="number" value={seeds.seed_sim} onChange={(event) => setSeeds({ ...seeds, seed_sim: number(event.target.value) })} /></label>
        <label>Максимальная переданная энергия, эВ<input type="number" min={0} value={qMax} onChange={(event) => setQMax(number(event.target.value))} /></label>
        <label>Порог активации перехода, эВ<input data-testid="q-threshold" type="number" min={0} value={qThr} onChange={(event) => setQThr(number(event.target.value))} /></label>
      </div>
      <details className="weights-editor">
        <summary>Вероятности переходов</summary>
        <div className="weights-intro">
          <strong>Вероятность конкретной свободной позиции</strong>
          <p>
            Три вероятности перемножаются и делятся на число доступных позиций
            с той же комбинацией типа, контура и положения относительно металла.
          </p>
          <code>Pᵢ = P(тип) × P(контур) × P(положение) / N</code>
        </div>
        <section className="weight-section" aria-labelledby="transition-weights-title">
          <div className="weight-section-heading">
            <span>1</span>
            <div>
              <h3 id="transition-weights-title">Тип свободной позиции</h3>
              <p>Эти две вероятности в сумме должны давать 1.</p>
            </div>
          </div>
          <div className="weight-rows">
            {(["vacancy", "interstitial"] as const).map((key) => (
              <label className="weight-row" key={key}>
                <span className="weight-route"><strong>{probabilityLabels.get(key)}</strong></span>
                <span className="weight-input-wrap"><span>P</span><input aria-label={probabilityLabels.get(key)} data-testid={`weight-${key}`} type="number" min={0} max={1} step={0.01} value={weights[key]} onChange={(event) => setWeights({ ...weights, [key]: number(event.target.value) })} /></span>
              </label>
            ))}
          </div>
        </section>
        <section className="weight-section" aria-labelledby="multiplier-weights-title">
          <div className="weight-section-heading">
            <span>2</span>
            <div>
              <h3 id="multiplier-weights-title">Контур</h3>
              <p>Первый и второй контуры в сумме должны давать 1.</p>
            </div>
          </div>
          <div className="weight-rows">
            {(["shell_r1", "shell_r2"] as const).map((key) => (
              <label className="weight-row" key={key}>
                <span className="weight-route"><strong>{probabilityLabels.get(key)}</strong></span>
                <span className="weight-input-wrap"><span>P</span><input aria-label={probabilityLabels.get(key)} data-testid={`weight-${key.replaceAll("_", "-")}`} type="number" min={0} max={1} step={0.01} value={weights[key]} onChange={(event) => setWeights({ ...weights, [key]: number(event.target.value) })} /></span>
              </label>
            ))}
          </div>
        </section>
        <section className="weight-section" aria-labelledby="position-probabilities-title">
          <div className="weight-section-heading"><span>3</span><div><h3 id="position-probabilities-title">Положение относительно металла</h3><p>Граничные позиции считаются внутренними.</p></div></div>
          <div className="weight-groups multiplier-groups">
            <div className="weight-group"><div className="weight-group-heading"><h4>Атом находится внутри металла</h4></div><div className="weight-rows">
              <label className="weight-row"><span className="weight-route"><strong>Внутри металла</strong></span><span className="weight-input-wrap"><span>P</span><input aria-label="Внутри металла для внутреннего атома" data-testid="probability-inside" type="number" min={0} max={1} step={0.01} value={1 - weights.external} onChange={(event) => setWeights({ ...weights, external: 1 - number(event.target.value) })} /></span></label>
              <label className="weight-row"><span className="weight-route"><strong>Снаружи металла</strong></span><span className="weight-input-wrap"><span>P</span><input aria-label={probabilityLabels.get("external")} data-testid="weight-external" type="number" min={0} max={1} step={0.01} value={weights.external} onChange={(event) => setWeights({ ...weights, external: number(event.target.value) })} /></span></label>
            </div></div>
            <div className="weight-group"><div className="weight-group-heading"><h4>Атом находится снаружи металла</h4><p>Вероятность входа по умолчанию равна 0, но её можно изменить.</p></div><div className="weight-rows">
              <label className="weight-row"><span className="weight-route"><strong>Внутрь металла</strong></span><span className="weight-input-wrap"><span>P</span><input aria-label={probabilityLabels.get("external_metal")} data-testid="weight-external-metal" type="number" min={0} max={1} step={0.01} value={weights.external_metal} onChange={(event) => setWeights({ ...weights, external_metal: number(event.target.value), external_external: 1 - number(event.target.value) })} /></span></label>
              <label className="weight-row"><span className="weight-route"><strong>Снаружи металла</strong></span><span className="weight-input-wrap"><span>P</span><input aria-label="Снаружи металла для внешнего атома" data-testid="probability-external-outside" type="number" min={0} max={1} step={0.01} value={1 - weights.external_metal} onChange={(event) => setWeights({ ...weights, external_metal: 1 - number(event.target.value), external_external: number(event.target.value) })} /></span></label>
            </div></div>
          </div>
        </section>
      </details>
      {(error || serverError) && <p className="field-error">{error || serverError}</p>}
      <div className="row-actions">
        <button data-testid="create-simulation" disabled={pending} onClick={() => submit("create")}>Создать новую</button>
        {canConfigure && <button data-testid="update-configuration" disabled={pending} onClick={() => submit("configure")}>Применить к выбранной</button>}
      </div>
      {pending && <p className="pending">Ожидается серверное подтверждение…</p>}
      {locked && (
        <details className="locked-configuration" open>
          <summary>Зафиксированные параметры выбранной симуляции</summary>
          <dl>
            <div><dt>Размеры металла</dt><dd>{locked.dimensions.join(" × ")}</dd></div>
            <div><dt>Размеры поля</dt><dd data-testid="locked-field-dimensions">{locked.field_dimensions.join(" × ")}</dd></div>
            <div><dt>Контур</dt><dd>{locked.contour ? locked.contour.map((point) => `(${point.join(", ")})`).join(" → ") : "Стандартный прямоугольник"}</dd></div>
            <div><dt>Профиль</dt><dd data-testid="locked-profile">{locked.profile}</dd></div>
            <div><dt>Режим инициализации</dt><dd>{locked.initialization_mode}</dd></div>
            <div><dt>Начальные вакансии</dt><dd data-testid="locked-count-n-v">{locked.n_v}</dd></div>
            <div><dt>Начальные межузельные атомы</dt><dd data-testid="locked-count-n-i">{locked.n_i}</dd></div>
            <div><dt>Начальные атомы за контуром</dt><dd data-testid="locked-count-n-as">{locked.n_as}</dd></div>
            {Object.keys(locked.random_parameters).length === 0 ? (
              <div><dt>Случайные распределения</dt><dd>Не используются</dd></div>
            ) : Object.entries(locked.random_parameters).map(([key, parameters]) => (
              <div key={key}>
                <dt>Распределение {key}</dt>
                <dd data-testid={`locked-random-${key}`}>μ={parameters.mu}; σ={parameters.sigma}</dd>
              </div>
            ))}
            <div><dt>Зерно структуры / зерно симуляции</dt><dd>{locked.seed_init} / {locked.seed_sim}</dd></div>
            <div><dt>Максимальная энергия / порог активации</dt><dd>{locked.q_max_ev} / {locked.q_thr_ev} эВ</dd></div>
            {(Object.entries(locked.weights) as [WeightKey, number][]).filter(([key]) => probabilityLabels.has(key)).map(([key, value]) => (
              <div key={key}>
                <dt>{probabilityLabels.get(key) ?? `Вероятность ${key}`}</dt>
                <dd data-testid={`locked-weight-${key.replaceAll("_", "-")}`}>{value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}
