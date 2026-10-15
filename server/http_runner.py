import copy
import sys
from logging import Filter, LogRecord

import uvicorn

from server.config import ConfigError, load_settings
from server.http_app import build_http_app


class SuppressUsageCurrentAccessLog(Filter):
    """Hide routine access-log entries for an unsupported polling endpoint."""

    def filter(self, record: LogRecord) -> bool:
        return "/v1/usage/current" not in record.getMessage()


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    app = build_http_app(settings)

    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["filters"] = {
        **log_config.get("filters", {}),
        "suppress_usage_current": {
            "()": SuppressUsageCurrentAccessLog,
        },
    }
    log_config["handlers"]["access"]["filters"] = ["suppress_usage_current"]

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
