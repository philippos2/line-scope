"""Fixed failure metadata shared by normal and Rebuild queues."""


def projection_failure(attempt, max_attempts, *, permanent):
    if type(permanent) is not bool or type(attempt) is not int or attempt < 1:
        raise ValueError("Invalid Projection failure metadata")
    dead = permanent or attempt >= max_attempts
    code = (
        "PROJECTION_PERMANENT_FAILURE"
        if permanent
        else "PROJECTION_ATTEMPTS_EXHAUSTED"
        if dead
        else "PROJECTION_TRANSIENT_FAILURE"
    )
    delay = min(2 ** min(attempt - 1, 6), 60)
    return dead, code, delay
