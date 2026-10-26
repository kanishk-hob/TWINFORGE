import httpx

from app.config import SIMULATOR_TIMEOUT_SECONDS, SIMULATOR_URL


async def get_snapshot(
    base_url: str = SIMULATOR_URL,
    timeout_seconds: float = SIMULATOR_TIMEOUT_SECONDS,
):
    timeout = httpx.Timeout(timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/api/v1/snapshot"
        )

        response.raise_for_status()

        return response.json()
