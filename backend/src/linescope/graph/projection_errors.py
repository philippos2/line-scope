"""Known Projection failures; None means stop without inventing DEAD."""

import psycopg
from neo4j.exceptions import DriverError, Neo4jError

from .neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from .projection_payload import ProjectionPayloadError

TRANSIENT_POSTGRES = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.LockNotAvailable,
    psycopg.errors.QueryCanceled,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
)


def classify_projection_failure(error):
    if isinstance(error, (ProjectionPayloadError, ProjectionIntegrityError)):
        return True
    if isinstance(error, (GraphGenerationUnavailable, *TRANSIENT_POSTGRES)):
        return False
    if isinstance(error, (Neo4jError, DriverError)) and error.is_retryable():
        return False
    return None
