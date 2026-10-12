import argparse
import json
import os
import signal
from threading import Event

import psycopg

from .demo_graph_seed import seed_graph_demo
from .demo_seed import SeedConflict, seed_demo
from .logging import EventLogger, configure_runtime_logging
from .persistence.database import Database
from .persistence.db_roles import RoleProvisionError, provision_roles, validate_passwords
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
    commands.add_parser("install-graph-schema", help="Explicit admin-only Neo4j constraint setup")
    rebuild = commands.add_parser(
        "rebuild-graph", help="Explicit admin-only verified Graph rebuild"
    )
    rebuild.add_argument(
        "--recover", action="store_true", help="Explicitly recover an abandoned Rebuild flag"
    )
    projection = commands.add_parser(
        "project-graph", help="Run the normal Outbox Projection worker"
    )
    projection.add_argument("--once", action="store_true")
    commands.add_parser(
        "seed-demo-graph", help="Explicitly bootstrap the initial Graph demo fixture"
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
                projection_password = os.environ.get("LINESCOPE_PROJECTION_PASSWORD", "")
                validate_passwords(query_password, runtime_password, projection_password)
                applied = database.migrate()
                provision_roles(
                    database,
                    query_password=query_password,
                    runtime_password=runtime_password,
                    projection_password=projection_password,
                )
            except (RoleProvisionError, psycopg.Error):
                parser.exit(
                    1, "Database role provisioning failed; use the administrative procedure.\n"
                )
        else:
            applied = database.migrate()
        print(json.dumps({"applied": applied}))
    elif args.command in {"seed-demo", "seed-demo-graph"}:
        try:
            print(
                json.dumps(
                    (seed_demo if args.command == "seed-demo" else seed_graph_demo)(
                        Database(settings)
                    )
                )
            )
        except SeedConflict as error:
            parser.exit(1, f"{args.command}: {error}\n")
        except psycopg.Error:
            parser.exit(1, "Demo bootstrap failed; check migrations and administrative access.\n")
    elif args.command in {"install-graph-schema", "rebuild-graph"}:
        from neo4j import GraphDatabase

        from .graph.administration import GraphAdministration

        if settings.neo4j_uri is None:
            parser.exit(1, "Graph administration requires configured Neo4j.\n")
        events = EventLogger(settings.log_level)
        configure_runtime_logging(events)
        try:
            with GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                connection_timeout=settings.connect_seconds,
                connection_acquisition_timeout=5,
                max_transaction_retry_time=0,
            ) as driver:
                administration = GraphAdministration(
                    Database(settings),
                    driver,
                    graph_database=settings.neo4j_database,
                    logger=events,
                )
                if args.command == "install-graph-schema":
                    administration.install_schema()
                    print(json.dumps({"schema_installed": True}))
                else:
                    verified = administration.rebuild(recover=args.recover)
                    print(
                        json.dumps(
                            {
                                "generation": verified.generation,
                                "snapshot_hash": verified.snapshot_hash,
                                "node_count": verified.node_count,
                                "aggregate_count": verified.aggregate_count,
                            }
                        )
                    )
        except Exception as error:
            events.emit(
                "runtime.diagnostic",
                component="rebuild",
                outcome="failure",
                result_code="INTERNAL_ERROR",
                level="ERROR",
                error=error,
            )
            parser.exit(1, "Graph administration failed; inspect Graph state before retrying.\n")
    elif args.command == "project-graph":
        from neo4j import GraphDatabase

        from .graph.neo4j_projection import Neo4jProjection
        from .graph.projection_runtime import projection_step, run_projection_loop
        from .graph.projection_worker import ProjectionWorker

        if settings.neo4j_uri is None:
            parser.exit(1, "Graph Projection requires configured Neo4j.\n")
        events = EventLogger(settings.log_level)
        configure_runtime_logging(events)
        stop = Event()
        previous = {}
        failed = False
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, lambda *_: stop.set())
            events.emit(
                "service.started", component="projection", outcome="success", result_code="OK"
            )
            with GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                connection_timeout=settings.connect_seconds,
                connection_acquisition_timeout=5,
                max_transaction_retry_time=0,
            ) as driver:
                database = Database(settings)
                worker = ProjectionWorker(
                    database,
                    Neo4jProjection(driver, database=settings.neo4j_database),
                    logger=events,
                )
                if args.once:
                    print(json.dumps({"status": projection_step(database, worker)}))
                else:
                    run_projection_loop(database, worker, stop)
        except Exception as error:
            failed = True
            events.emit(
                "runtime.diagnostic",
                component="projection",
                outcome="failure",
                result_code="INTERNAL_ERROR",
                level="ERROR",
                error=error,
            )
            parser.exit(1, "Graph Projection stopped; inspect Graph state and operational logs.\n")
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            events.emit(
                "service.stopped",
                component="projection",
                outcome="failure" if failed else "success",
                result_code="INTERNAL_ERROR" if failed else "OK",
            )
    else:
        import uvicorn

        from .interfaces.api import create_app

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
