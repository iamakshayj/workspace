import re
from datetime import datetime, timezone
from hashlib import sha256

from .database import User


AVATAR_COLORS = ["#6D5CE8", "#258A71", "#C45C7A", "#337FBC", "#B06B24", "#7453A6"]


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def avatar_color(user_id: str) -> str:
    index = int(sha256(user_id.encode("utf-8")).hexdigest()[:8], 16) % len(AVATAR_COLORS)
    return AVATAR_COLORS[index]


def user_handle(user: User) -> str:
    local_part = user.email.split("@", 1)[0].lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", local_part).strip("-._") or "member"
    return f"{slug}-{user.id[:4].lower()}"


def user_summary(user: User) -> dict[str, str]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "handle": user_handle(user),
        "color": avatar_color(user.id),
    }
