"""Runtime host setting; the service listener port is fixed at 19003."""

import os
from dataclasses import dataclass
from pathlib import Path

CONTRACT_VERSION = "1.0.1"
FIXED_PORT = 19003


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
    """Return runtime settings; the production HTTP port is intentionally fixed."""
    host = os.environ.get("HOST") or "127.0.0.1"
    return Settings(host=host, port=FIXED_PORT)
