"""Explicit administrative Graph setup; never an Agent Tool or normal worker."""

from .graph_leadership import graph_leadership
from .graph_locks import acquire_graph_mutation_lock
from .neo4j_generation import Neo4jGeneration
from .neo4j_projection import Neo4jProjection, install_projection_schema
from .rebuild_controller import RebuildController


class GraphAdministration:
    def __init__(self, database, driver, *, graph_database="neo4j", logger=None):
        self.database, self.driver = database, driver
        self.graph_database, self.logger = graph_database, logger

    def install_schema(self):
        with graph_leadership(self.database) as leader:
            with self.database.transaction() as connection:
                acquire_graph_mutation_lock(connection, shared=False)
                leader.require()
                install_projection_schema(self.driver, database=self.graph_database)
                leader.require()

    def rebuild(self, *, recover=False):
        if type(recover) is not bool:
            raise ValueError("Recovery must be an explicit boolean")
        controller = RebuildController(
            self.database,
            Neo4jProjection(self.driver, database=self.graph_database),
            Neo4jGeneration(self.driver, database=self.graph_database),
            logger=self.logger,
        )
        with graph_leadership(self.database) as leader:
            return controller.recover(leader) if recover else controller.run(leader)
