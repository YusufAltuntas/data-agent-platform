"""The worker's Celery app, configured from the environment: `celery -A dap.worker.app worker`.

Importing it opens no connection; the worker process creates them on its first task. Nor does
it serve metrics: only the `celery worker` command does, from its parent process.
"""

import time
from typing import Any

from celery.signals import celeryd_init, setup_logging, worker_process_shutdown, worker_shutdown

from dap.celery_app import create_celery_app
from dap.observability import metrics
from dap.observability.logging import configure_logging
from dap.settings import get_settings
from dap.worker.runner import WorkerContext
from dap.worker.tasks import register_tasks

# The worker's metrics live only as long as its pod: after a shutdown, keep serving them for one
# more Prometheus scrape (every 15 s, deploy/values/prometheus.yaml).
LAST_SCRAPE_WAIT_S = 20

settings = get_settings()
app = create_celery_app(settings)
register_tasks(app, WorkerContext(settings))


@setup_logging.connect
def _json_logging(**kwargs: Any) -> None:
    """With a receiver connected, Celery leaves the root logger to us: JSON logs (design §9)."""
    configure_logging()


@celeryd_init.connect
def _serve_metrics(**kwargs: Any) -> None:
    """In the worker's parent process, before the pool starts: the metrics endpoint (design §9).

    Under the prefork pool it serves what the children wrote to `PROMETHEUS_MULTIPROC_DIR`.
    """
    metrics.start_worker_metrics_server(settings.worker_metrics_port)
    worker_shutdown.connect(_wait_for_last_scrape, weak=False)


def _wait_for_last_scrape(**kwargs: Any) -> None:
    """After the warm shutdown (no task is consumed any more), before the process exits."""
    time.sleep(LAST_SCRAPE_WAIT_S)


@worker_process_shutdown.connect
def _pool_child_exited(pid: int, **kwargs: Any) -> None:
    metrics.mark_process_dead(pid)
