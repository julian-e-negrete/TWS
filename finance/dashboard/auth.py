"""
JWT authentication for dashboard — Tarea 11.3
Provides: token creation, verification, role-based access decorator.
Integrates with finance.config.settings for secret key.
"""
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from finance.config.settings import settings
from finance.utils.logger import logger

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"

# In-memory user store (replace with DB in production)
_USERS: dict[str, dict] = {
    "admin": {"hashed_password": _pwd.hash("admin123"), "role": ROLE_ADMIN},
    "viewer": {"hashed_password": _pwd.hash("viewer123"), "role": ROLE_VIEWER},
}


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def create_token(username: str, role: str, expires_hours: Optional[int] = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        hours=expires_hours or settings.jwt_expiration_hours
    )
    payload = {"sub": username, "role": role, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Returns payload dict or raises JWTError."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def authenticate(username: str, password: str) -> Optional[str]:
    """Returns JWT token if credentials valid, else None."""
    user = _USERS.get(username)
    if not user or not _pwd.verify(password, user["hashed_password"]):
        logger.warning("Failed login attempt for user={username}", username=username)
        return None
    token = create_token(username, user["role"])
    logger.info("User {username} authenticated (role={role})", username=username, role=user["role"])
    return token


# ---------------------------------------------------------------------------
# Flask/Dash route decorator
# ---------------------------------------------------------------------------

def require_role(*roles: str):
    """
    Decorator for Flask/Dash server routes.
    Checks Authorization: Bearer <token> header.
    Usage:
        @app.server.route("/admin")
        @require_role("admin")
        def admin_page(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from flask import request, jsonify
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Missing token"}), 401
            token = auth.split(" ", 1)[1]
            try:
                payload = decode_token(token)
                if payload.get("role") not in roles:
                    return jsonify({"error": "Insufficient permissions"}), 403
            except JWTError as e:
                logger.warning("Invalid token: {e}", e=e)
                return jsonify({"error": "Invalid or expired token"}), 401
            return f(*args, **kwargs)
        return wrapper
    return decorator
