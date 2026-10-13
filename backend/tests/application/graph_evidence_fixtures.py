"""Module-local real stores for read-only alternative/SPOF Evidence cases.

Mutation, concurrency and recovery suites retain their function-local stores.
Each importing module owns a separate PG schema and rebuilt Graph generation.
"""

from dataclasses import replace

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from linescope.demo_graph_seed import seed_graph_demo
from linescope.graph.administration import GraphAdministration
from linescope.graph.analysis_reader import GraphAnalysisReader
from linescope.persistence.database import Database


@pytest.fixture(scope="module")
def evidence_world(database_factory, graph_driver):
    with graph_driver.session() as session:
        before = {
            row["g"]
            for row in session.run("MATCH (g:LineScopeGeneration) RETURN g.generation AS g")
        }
    with database_factory() as writable:
        try:
            writable.migrate()
            seed_graph_demo(writable)
            generation = GraphAdministration(writable, graph_driver).rebuild().generation
            options = conninfo_to_dict(writable.settings.dsn)["options"]
            readonly = Database(
                replace(
                    writable.settings,
                    dsn=make_conninfo(
                        writable.settings.dsn,
                        options=options + " -c default_transaction_read_only=on",
                    ),
                )
            )
            yield readonly, (GraphAnalysisReader(readonly, graph_driver), generation)
        finally:
            # Suites sharing the disposable Graph run sequentially. Remove only
            # generations created during this module, including failed rebuilds.
            with graph_driver.session() as session:
                after = {
                    row["g"]
                    for row in session.run("MATCH (g:LineScopeGeneration) RETURN g.generation AS g")
                }
                for generation in after - before:
                    session.run("MATCH (n {generation:$g}) DETACH DELETE n", g=generation).consume()


@pytest.fixture(scope="module")
def db(evidence_world):
    return evidence_world[0]


@pytest.fixture(scope="module")
def reader_world(evidence_world):
    return evidence_world[1]
