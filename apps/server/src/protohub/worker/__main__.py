import logging
import signal

from protohub.domain.settings import Settings
from protohub.persistence.database import create_session_factory
from protohub.persistence.jobs import SqlJobStore
from protohub.runtime import make_runtime
from protohub.worker import Worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    worker = Worker(
        SqlJobStore(create_session_factory(settings.database_url), settings),
        make_runtime(settings),
        settings,
    )
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    worker.run()


if __name__ == "__main__":
    main()
