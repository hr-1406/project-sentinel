"""Quick script to test PostgreSQL connection and create sentinel_db if needed."""
import sys

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# Connection settings — adjust if your PostgreSQL uses different credentials
PG_HOST = "localhost"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASS = "raphael1111"
DB_NAME = "sentinel_db"

def main():
    # Step 1: Connect to default 'postgres' database
    print(f"Connecting to PostgreSQL at {PG_HOST}:{PG_PORT} as '{PG_USER}'...")
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT,
            user=PG_USER, password=PG_PASS,
            dbname="postgres"
        )
    except psycopg2.OperationalError as e:
        print(f"\nERROR: Could not connect to PostgreSQL.\n{e}")
        print("\nPlease ensure:")
        print("  1. PostgreSQL is installed (download from https://www.postgresql.org/download/windows/)")
        print("  2. The PostgreSQL service is running")
        print("  3. Credentials are correct (default: postgres/postgres)")
        sys.exit(1)

    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Step 2: Check if database exists
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    exists = cur.fetchone()

    if exists:
        print(f"Database '{DB_NAME}' already exists. Skipping creation.")
    else:
        print(f"Creating database '{DB_NAME}'...")
        cur.execute(f'CREATE DATABASE "{DB_NAME}"')
        print(f"Database '{DB_NAME}' created successfully!")

    cur.close()
    conn.close()
    print("Done. PostgreSQL is ready.")

if __name__ == "__main__":
    main()
