"""Schema only for future aggregate context; never used to infer personal traits."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AggregateContext:
    source: str
    dataset_date: str
    geographic_scope: str
    population_definition: str
    limitations: str
    metrics: dict

    def to_dict(self):
        return asdict(self)


def validate_context(data: dict) -> AggregateContext:
    required = ("source", "dataset_date", "geographic_scope", "population_definition", "limitations", "metrics")
    if not isinstance(data, dict) or any(not data.get(key) for key in required) or not isinstance(data["metrics"], dict):
        raise ValueError("Aggregate context requires attribution, date, scope, population, limitations, and metrics")
    return AggregateContext(**{key: data[key] for key in required})
