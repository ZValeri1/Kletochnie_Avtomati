from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class AggregateResult:
    mean: dict[str, float]
    minimum: dict[str, float]
    maximum: dict[str, float]
    percentiles: dict[str, dict[str, float]]
    confidence_interval: dict[str, tuple[float, float]]
    schema_version: int = 1


@dataclass(frozen=True)
class MetricAggregate:
    count: int
    mean: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    confidence_interval: tuple[float, float]
    ci_informative: bool


@dataclass(frozen=True)
class ResearchAggregate:
    final: dict[str, MetricAggregate]
    by_act: dict[int, dict[str, MetricAggregate]]
    bootstrap_seed: int
    schema_version: int = 1


class StatisticsCalculator:
    EXCLUDED_FIELDS = {"act_number", "revision", "origin"}

    def aggregate(
        self,
        series: list[dict[str, float]],
        bootstrap_seed: int,
        bootstrap_samples: int = 2_000,
    ) -> AggregateResult:
        if not series:
            raise ValueError("At least one metric row is required")
        keys = tuple(series[0])
        random_source = random.Random(bootstrap_seed)
        means = {
            key: sum(float(item[key]) for item in series) / len(series) for key in keys
        }
        minimum = {key: min(float(item[key]) for item in series) for key in keys}
        maximum = {key: max(float(item[key]) for item in series) for key in keys}
        percentiles = {
            key: {
                "p50": self._percentile([float(item[key]) for item in series], 0.5),
                "p95": self._percentile([float(item[key]) for item in series], 0.95),
            }
            for key in keys
        }
        intervals = {}
        for key in keys:
            values = [float(item[key]) for item in series]
            bootstrap_means = sorted(
                sum(random_source.choice(values) for _ in values) / len(values)
                for _ in range(bootstrap_samples)
            )
            intervals[key] = (
                self._percentile(bootstrap_means, 0.025),
                self._percentile(bootstrap_means, 0.975),
            )
        return AggregateResult(means, minimum, maximum, percentiles, intervals)

    def aggregate_trajectories(
        self,
        trajectories: list[list[dict]],
        bootstrap_seed: int,
        bootstrap_samples: int = 2_000,
    ) -> ResearchAggregate:
        completed = [trajectory for trajectory in trajectories if trajectory]
        if not completed:
            raise ValueError("At least one completed trajectory is required")
        random_source = random.Random(bootstrap_seed)
        final = self._aggregate_rows(
            [trajectory[-1] for trajectory in completed],
            random_source,
            bootstrap_samples,
        )
        rows_by_act: dict[int, list[dict]] = {}
        for trajectory in completed:
            for point in trajectory:
                act_number = point.get("act_number")
                if isinstance(act_number, int) and act_number >= 0:
                    rows_by_act.setdefault(act_number, []).append(point)
        by_act = {
            act_number: self._aggregate_rows(rows, random_source, bootstrap_samples)
            for act_number, rows in sorted(rows_by_act.items())
        }
        return ResearchAggregate(final=final, by_act=by_act, bootstrap_seed=bootstrap_seed)

    def _aggregate_rows(
        self,
        rows: list[dict],
        random_source: random.Random,
        bootstrap_samples: int,
    ) -> dict[str, MetricAggregate]:
        keys = sorted(
            set.intersection(
                *[
                    {
                        key
                        for key, value in row.items()
                        if key not in self.EXCLUDED_FIELDS
                        and isinstance(value, (int, float))
                    }
                    for row in rows
                ]
            )
        )
        result = {}
        for key in keys:
            values = [float(row[key]) for row in rows]
            count = len(values)
            mean = sum(values) / count
            if count == 1:
                interval = (values[0], values[0])
            else:
                bootstrap_means = sorted(
                    sum(random_source.choice(values) for _ in values) / count
                    for _ in range(bootstrap_samples)
                )
                interval = (
                    self._percentile(bootstrap_means, 0.025),
                    self._percentile(bootstrap_means, 0.975),
                )
            result[key] = MetricAggregate(
                count=count,
                mean=mean,
                minimum=min(values),
                maximum=max(values),
                p50=self._percentile(values, 0.5),
                p95=self._percentile(values, 0.95),
                confidence_interval=interval,
                ci_informative=count > 1,
            )
        return result

    @staticmethod
    def _percentile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * probability
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
