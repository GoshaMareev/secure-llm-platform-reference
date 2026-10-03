"""Small dependency-free Prometheus registry for the pinned native images."""

from __future__ import annotations

import threading
from collections import defaultdict
from contextvars import ContextVar

REQUEST_CONTEXT = ContextVar("reference_request_context", default=None)
MODEL_ALIAS = ContextVar("model_alias", default="reference-rag")
_LOCK = threading.Lock()
_REGISTRY = []
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)


class Metric:
    def __init__(self, name, help_, labels, histogram=False):
        self.name, self.help, self.names, self.histogram = name, help_, labels, histogram
        self.values = defaultdict(lambda: [0.0, 0, [0] * len(BUCKETS)])
        _REGISTRY.append(self)

    def labels(self, **labels):
        if set(labels) != set(self.names):
            raise ValueError("Invalid metric labels")
        return Point(self, tuple(str(labels[n]) for n in self.names))


class Point:
    def __init__(self, metric, labels):
        self.metric, self.key = metric, labels

    def inc(self, amount=1):
        with _LOCK:
            self.metric.values[self.key][0] += amount

    def observe(self, value):
        with _LOCK:
            row = self.metric.values[self.key]
            row[0] += value
            row[1] += 1
            for i, bucket in enumerate(BUCKETS):
                row[2][i] += int(value <= bucket)


def render():
    lines = []
    with _LOCK:
        for metric in _REGISTRY:
            lines.extend(
                [
                    f"# HELP {metric.name} {metric.help}",
                    f"# TYPE {metric.name} {'histogram' if metric.histogram else 'counter'}",
                ]
            )
            for values, row in metric.values.items():
                labels = ",".join(f'{key}="{value}"' for key, value in zip(metric.names, values, strict=True))
                if metric.histogram:
                    lines.extend(
                        f'{metric.name}_bucket{{{labels},le="{bucket}"}} {count}'
                        for bucket, count in zip(BUCKETS, row[2], strict=True)
                    )
                    lines += [
                        f'{metric.name}_bucket{{{labels},le="+Inf"}} {row[1]}',
                        f"{metric.name}_sum{{{labels}}} {row[0]}",
                        f"{metric.name}_count{{{labels}}} {row[1]}",
                    ]
                else:
                    lines.append(f"{metric.name}{{{labels}}} {row[0]}")
    return ("\n".join(lines) + "\n").encode()


LOG_ERRORS = Metric("reference_operational_log_errors_total", "Operational logging failures", ["component"])
AUDIT_ERRORS = Metric("reference_audit_errors_total", "Durable audit failures", ["component"])
STAGE_SECONDS = Metric(
    "reference_stage_seconds", "Time in pipeline stage", ["stage", "model_alias", "verdict"], True
)
