import { ApplicationRequestError } from "../api/simulationApi";
import { decodeApplicationError } from "../contracts";

export async function downloadReport(
  kind: "simulations" | "experiments",
  id: string,
) {
  await download(
    `/api/${kind}/${encodeURIComponent(id)}/report.zip`,
    `${kind}-${id}-report.zip`,
  );
}

export async function downloadSessionReport(simulationIds: string[]) {
  await download("/api/simulations/report.zip", "session-report.zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schema_version: 1, simulation_ids: simulationIds }),
  });
}

async function download(path: string, filename: string, options?: RequestInit) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    if (payload?.schema_version === 1) {
      throw new ApplicationRequestError(
        decodeApplicationError(payload),
        response.status,
      );
    }
    if (response.status === 404) {
      throw new Error(
        "Отчёт недоступен. Обновите страницу и убедитесь, что запущена новая версия сервера.",
      );
    }
    throw new Error("Не удалось сформировать отчёт. Попробуйте ещё раз.");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
