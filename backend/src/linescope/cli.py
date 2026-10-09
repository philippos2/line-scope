import argparse
import json

from .database import Database
from .demo_seed import SeedConflict, seed_demo
from .logging import EventLogger, configure_runtime_logging
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(prog="linescope")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser(
        "seed-demo", help="Explicitly bootstrap read-demo equipment after migrations"
    )
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings.env()
    if args.command == "migrate":
        print(json.dumps({"applied": Database(settings).migrate()}))
    elif args.command == "seed-demo":
        try:
            print(json.dumps(seed_demo(Database(settings))))
        except SeedConflict as error:
            parser.exit(1, f"seed-demo: {error}\n")
    else:
        import uvicorn

        from .api import create_app

        events = EventLogger(settings.log_level)
        configure_runtime_logging(events)
        uvicorn.run(
            create_app(settings, event_logger=events),
            host=args.host,
            port=args.port,
            log_config=None,
            access_log=False,
        )


if __name__ == "__main__":
    main()
