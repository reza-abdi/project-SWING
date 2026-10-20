"""Run the Digital Twin API from any working directory."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
import uvicorn  # noqa: E402

from modules.config import runtime_settings  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    settings = runtime_settings()
    uvicorn.run("modules.physics_engine.api:app", host=settings.twin_bind_host, port=settings.twin_port)


if __name__ == "__main__":
    main()
