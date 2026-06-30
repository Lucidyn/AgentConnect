"""Entry point: python -m backend.run"""

import uvicorn

from backend.config import settings


def main():
    uvicorn.run(
        "backend.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
