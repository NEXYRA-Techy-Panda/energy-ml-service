"""Runtime settings read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

CONTRACT_VERSION = "1.0.1"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int


def load_dotenv(path: Path = Path(".env")) -> None:
    """Loads KEY=VALUE lines from a local .env without overriding real environment variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_settings() -> Settings:
    host = os.environ.get("HOST") or "127.0.0.1"
    raw_port = os.environ.get("PORT") or "8000"
    if not raw_port.isdigit() or not 0 <= int(raw_port) <= 65535:
        raise ValueError(f'PORT must be an integer in [0, 65535]; got "{raw_port}"')
    return Settings(host=host, port=int(raw_port))
