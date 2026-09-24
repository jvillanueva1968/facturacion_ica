import httpx
from typing import Dict, Any
from app.config import get_settings

settings = get_settings()


class SigmaClient:
    def __init__(self):
        self.base_url = settings.sigma_api_url.rstrip('/')
        self.token = settings.sigma_api_token
        self.client = httpx.AsyncClient(
            timeout=30,
            headers={"X-API-Token": self.token, "Content-Type": "application/json"}
        )

    async def registrar_factura(self, data: Dict[str, Any]) -> Dict[str, Any]:
        response = await self.client.post(
            f"{self.base_url}/facturas/registrar",
            json=data
        )
        response.raise_for_status()
        return response.json()

    async def consultar_factura(self, numero_referencia: str) -> Dict[str, Any]:
        response = await self.client.get(
            f"{self.base_url}/facturas/consultar",
            params={"numero_referencia": numero_referencia}
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()