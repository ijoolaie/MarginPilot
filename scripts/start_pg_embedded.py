"""Start embedded PostgreSQL and keep it running (cleanup_mode=None).

Prints the psycopg DSN for the smoke/integration scripts.
Sandbox-only verification tool — NOT a product dependency.
"""

import pgserver

PGDATA = "/tmp/mp-pgdata"


def main() -> str:
    server = pgserver.get_server(PGDATA, cleanup_mode=None)
    dsn = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    print(dsn)
    return dsn


if __name__ == "__main__":
    main()
