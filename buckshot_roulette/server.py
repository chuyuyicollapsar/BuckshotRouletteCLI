from __future__ import annotations

import argparse
import sys

import uvicorn


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Buckshot Roulette backend server")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址，默认 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="监听端口，默认 8000",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用 uvicorn reload，开发时使用",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    uvicorn.run(
        "buckshot_roulette.backend.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
