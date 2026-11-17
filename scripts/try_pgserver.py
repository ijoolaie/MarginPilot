"""Spin up a real embedded PostgreSQL (no root) and print its TCP/socket DSN.

Sandbox-only verification tool — NOT a product dependency.
"""

import sys

import pgserver

PGDATA = "/tmp/mp-pgdata"


def main() -> None:
    server = pgserver.get_server(PGDATA, cleanup_mode="stop")
    uri = server.get_uri()
    print("pgserver URI:", uri.replace("://", "+psycopg://", 1))
    # Real version probe through a real query.
    import sqlalchemy

    engine = sqlalchemy.create_engine(uri.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as conn:
        version = conn.execute(sqlalchemy.text("SELECT version()")).scalar_one()
    print("REAL PG:", version)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
