from fastapi import APIRouter

from app.services.user_service import get_user_profile

router = APIRouter()


@router.get("/users/{user_id}")
def read_user(user_id: int):
    return get_user_profile(user_id)