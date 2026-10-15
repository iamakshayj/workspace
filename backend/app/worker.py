import asyncio
from .config import get_settings
from .database import init_database, verify_database_revision
from .job_service import job_queue, job_worker
from .object_storage import object_storage
from .telemetry import configure_logging


async def run_worker() -> None:
    settings = get_settings()
    if settings.environment.strip().lower() == "production":
        await verify_database_revision()
    else:
        await init_database()
    await object_storage.start()
    await job_queue.start()
    try:
        await job_worker.run_forever()
    finally:
        job_worker.stop()
        await job_queue.stop()


def main() -> None:
    configure_logging(get_settings().environment)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
