"""``python -m src.web`` で API を起動するためのエントリポイント。

Railway / Heroku 等で ``$PORT`` をシェル展開せずに直接受け取れるよう、
uvicorn を programmatic に呼び出す。
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
