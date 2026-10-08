import argparse
import json

from .database import Database
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(prog="linescope")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings.env()
    if args.command == "migrate":
        print(json.dumps({"applied": Database(settings).migrate()}))
    else:
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
