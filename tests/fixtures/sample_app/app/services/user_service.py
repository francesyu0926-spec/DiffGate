from app.utils.formatter import format_name


def get_user_profile(user_id: int) -> dict:
    name = format_name(f"user_{user_id}")
    return {"id": user_id, "name": name}