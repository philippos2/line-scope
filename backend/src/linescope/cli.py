import argparse
import json
import os

import psycopg

from .database import Database
from .db_roles import RoleProvisionError, provision_roles, validate_passwords
from .demo_seed import SeedConflict, seed_demo
from .logging import EventLogger, configure_runtime_logging
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(prog="linescope")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser(
        "migrate-and-provision", help="Admin-only migration and fixed DB role grants"
    )
    commands.add_parser(
        "seed-demo", help="Explicitly bootstrap read-demo equipment after migrations"
    )
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings.env()
    if args.command in {"migrate", "migrate-and-provision"}:
        database = Database(settings)
        if args.command == "migrate-and-provision":
            try:
                # Validate secrets before committing migrations. Provisioning
                # failure still prevents Compose from starting the API.
                query_password = os.environ.get("LINESCOPE_QUERY_PASSWORD", "")
                runtime_password = os.environ.get("LINESCOPE_RUNTIME_PASSWORD", "")
                validate_passwords(query_password, runtime_password)
                applied = database.migrate()
                provision_roles(
                    database, query_password=query_password, runtime_password=runtime_password
                )
            except (RoleProvisionError, psycopg.Error):
                parser.exit(
                    1, "Database role provisioning failed; use the administrative procedure.\n"
                )
        else:
            applied = database.migrate()
        print(json.dumps({"applied": applied}))
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
