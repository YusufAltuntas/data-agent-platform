"""The Celery application (K10). The API publishes runs by task name; the worker runs them."""

from celery import Celery

from dap.settings import Settings

RUN_TASK = "dap.run"  # the only argument is the run id (str)


def create_celery_app(settings: Settings) -> Celery:
    """RabbitMQ is the broker; there is no result backend, run state lives in Postgres."""
    app = Celery("dap", broker=settings.rabbitmq_url())
    app.conf.update(
        # A message is acknowledged only when the task finishes. A worker process that dies mid-task
        # (OOM) gets it redelivered (`task_reject_on_worker_lost`); a run killed by the hard time
        # limit gets it redelivered only because `task_acks_on_timeout` is off.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_acks_on_timeout=False,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=120,
        task_time_limit=150,
    )
    return app
