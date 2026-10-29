"""Standalone mock-authority service (runs as its own container in docker-compose).

    uvicorn app.mock_authority.main:app --port 8100
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.mock_authority.service import router, set_outage, outage_enabled

app = FastAPI(title="Simulated Issuing Authorities", version="1.0.0")
app.include_router(router)


class OutageToggle(BaseModel):
    enabled: bool


@app.post("/mock-authority/admin/outage")
def toggle_outage(body: OutageToggle):
    set_outage(body.enabled)
    return {"outage": outage_enabled()}
