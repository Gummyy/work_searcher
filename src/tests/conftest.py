import logging

import pytest


@pytest.fixture(autouse=True)
def silence_app_logger():
    """Strips app logger handlers during tests to avoid polluting log files."""
    logger = logging.getLogger("work_searcher")
    original_handlers = logger.handlers[:]
    logger.handlers = []
    yield
    logger.handlers = original_handlers
