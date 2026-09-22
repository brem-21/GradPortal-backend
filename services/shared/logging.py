import logging

import structlog


def configure_logging(service_name: str, development: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if development else structlog.processors.JSONRenderer(),
        ]
    )
    structlog.get_logger(service_name).info("service_logging_configured", service=service_name)
