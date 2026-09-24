"""Entrypoint: python -m app (fixed port 19003; reads HOST; graceful shutdown)."""

import uvicorn

from .config import load_dotenv, load_settings


def main() -> None:
    load_dotenv()
    settings = load_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
