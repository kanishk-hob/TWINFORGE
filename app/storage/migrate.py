"""Run explicitly before starting the service: python -m app.storage.migrate."""
import asyncio
from app.config import DATABASE_URL, DATABASE_TIMEOUT_SECONDS
from app.storage.postgres import PostgresStore, PersistenceError


async def main():
    if not DATABASE_URL:
        raise SystemExit("Set TWINFORGE_DATABASE_URL before migrating")
    store = PostgresStore(DATABASE_URL, DATABASE_TIMEOUT_SECONDS)
    try:
        await store.migrate()
        print("Database migrations applied")
    except PersistenceError as error:
        raise SystemExit(str(error)) from None
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
