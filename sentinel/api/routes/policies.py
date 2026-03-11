# sentinel/api/routes/policies.py
from fastapi import APIRouter

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("/")
async def list_policies() -> dict:
    return {"message": "Policy registry not yet implemented"}
