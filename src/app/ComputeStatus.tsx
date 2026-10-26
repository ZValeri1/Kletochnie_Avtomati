import { useEffect, useState } from "react";

type Status = {
  backend: "cpu" | "cuda";
  device_name: string | null;
  reason: string | null;
};

export function ComputeStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch("/api/compute", { signal: controller.signal });
        if (!response.ok) throw new Error("Compute status unavailable");
        const value = await response.json();
        if (!["cpu", "cuda"].includes(value.backend)) throw new Error("Invalid compute status");
        if (!controller.signal.aborted) setStatus(value);
      } catch {
        if (!controller.signal.aborted) setStatus(null);
      } finally {
        pending = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);
  return (
    <span className="compute-status" data-testid="compute-status"
      title={status?.reason ?? "GPU проверяет допустимость переходов. CPU управляет симуляцией. При ошибке CUDA расчёт автоматически продолжается на CPU."}>
      {status?.backend === "cuda"
        ? `GPU · ${status.device_name ?? "NVIDIA CUDA"}`
        : status?.backend === "cpu" ? "CPU · резервный расчёт" : "Устройство расчёта: проверка…"}
    </span>
  );
}
