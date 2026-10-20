import json
import logging
from io import StringIO

from modules.logging_config import configure_logging, request_context


def test_service_logs_have_correlation_severity_redaction_and_bounds():
    services = ("digital_twin.api", "ai_agent.api")
    prior = {
        name: (logging.getLogger(name.split(".", 1)[0]).handlers[:], logging.getLogger(name.split(".", 1)[0]).level,
               logging.getLogger(name.split(".", 1)[0]).propagate)
        for name in services
    }
    stream = StringIO()
    try:
        configure_logging("DEBUG", stream=stream)
        with request_context("request-42"):
            for name in services:
                logger = logging.getLogger(name)
                logger.debug("Authorization: Bearer bearer-secret")
                logger.info("api_key=key-secret password=password-secret %s", "x" * 2500)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert [record["service"] for record in records] == ["digital_twin", "digital_twin", "ai_agent", "ai_agent"]
        assert all(record["request_id"] == "request-42" for record in records)
        assert [record["level"] for record in records] == ["DEBUG", "INFO", "DEBUG", "INFO"]
        assert "bearer-secret" not in stream.getvalue()
        assert "key-secret" not in stream.getvalue()
        assert "password-secret" not in stream.getvalue()
        for record in records:
            assert len(record["message"]) <= 2000
        assert records[1]["message"].endswith("[truncated]")
    finally:
        for name, (handlers, level, propagate) in prior.items():
            logger = logging.getLogger(name.split(".", 1)[0])
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate
