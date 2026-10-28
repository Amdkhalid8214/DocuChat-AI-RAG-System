import os
import secrets
import hashlib
import hmac
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    hasher = PasswordHasher()
except ImportError:
    hasher = None

from backend.config import settings
from backend.db.session import get_db, AsyncSessionLocal
from backend.db.models import UserModel, UserSessionModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hashes a password using Argon2id if available, otherwise PBKDF2-HMAC-SHA256."""
    if hasher:
        try:
            argon_hash = hasher.hash(password)
            return argon_hash, "argon2id"
        except Exception:
            pass
            
    if not salt or salt == "argon2id":
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    ).hex()
    return pwd_hash, salt

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verifies password using Argon2id or legacy PBKDF2."""
    if stored_hash.startswith("$argon2"):
        if hasher:
            try:
                return hasher.verify(stored_hash, password)
            except Exception:
                return False
    # Fallback to PBKDF2
    new_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(new_hash, stored_hash)

from datetime import datetime, timedelta, timezone

def create_jwt_token(user_id: str, username: str, role: str) -> str:
    """Creates a signed, expiring JWT token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
        "iat": now
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodes and validates a JWT token."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except Exception:
        return None

async def create_user_session(user_id: str, db: AsyncSession, username: str = "", role: str = "user") -> str:
    token = create_jwt_token(user_id, username, role)
    session_obj = UserSessionModel(
        token=token,
        user_id=user_id,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(session_obj)
    await db.commit()
    return token

async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> Optional[UserModel]:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_auth_token:
        token = x_auth_token.strip()

    if not token:
        return None

    # First attempt JWT decoding
    payload = decode_jwt_token(token)
    user_id = payload.get("sub") if payload else None

    if user_id:
        user_res = await db.execute(select(UserModel).where(UserModel.id == user_id))
        user = user_res.scalar_one_or_none()
        if user:
            return user

    # Fallback to DB session lookup
    stmt = select(UserSessionModel).where(UserSessionModel.token == token)
    res = await db.execute(stmt)
    session_record = res.scalar_one_or_none()
    if not session_record:
        return None

    user_stmt = select(UserModel).where(UserModel.id == session_record.user_id)
    user_res = await db.execute(user_stmt)
    return user_res.scalar_one_or_none()

async def get_current_user(
    user: Optional[UserModel] = Depends(get_current_user_optional)
) -> UserModel:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in.")
    return user

async def seed_default_users():
    """Seeds default demo users if the user table is empty."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(UserModel))
            existing = result.scalars().first()
            if not existing:
                logger.info("Seeding default demo users (admin / demo)...")
                # Admin user
                adm_hash, adm_salt = hash_password("admin123")
                admin = UserModel(
                    username="admin",
                    email="admin@enterprise.ai",
                    password_hash=adm_hash,
                    salt=adm_salt,
                    role="admin"
                )
                # Demo user
                demo_hash, demo_salt = hash_password("demo123")
                demo = UserModel(
                    username="demo",
                    email="demo@enterprise.ai",
                    password_hash=demo_hash,
                    salt=demo_salt,
                    role="user"
                )
                session.add(admin)
                session.add(demo)
                await session.commit()
                logger.info("Default users 'admin' and 'demo' seeded successfully.")
        except Exception as e:
            logger.warning(f"Could not seed default users: {e}")

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    clean_username = req.username.strip().lower()
    if not clean_username:
        raise HTTPException(status_code=400, detail="Username cannot be blank")

    # Check if username exists
    existing = await db.execute(select(UserModel).where(UserModel.username == clean_username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists. Please choose another or log in.")

    pwd_hash, salt = hash_password(req.password)
    new_user = UserModel(
        username=clean_username,
        email=req.email.strip() if req.email else None,
        password_hash=pwd_hash,
        salt=salt,
        role="user"
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    token = await create_user_session(new_user.id, db, username=new_user.username, role=new_user.role)
    return {
        "message": "User registered successfully",
        "token": token,
        "user": new_user.to_dict()
    }

@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    clean_username = req.username.strip().lower()
    stmt = select(UserModel).where(UserModel.username == clean_username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash, user.salt):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = await create_user_session(user.id, db, username=user.username, role=user.role)
    return {
        "message": "Login successful",
        "token": token,
        "user": user.to_dict()
    }

@router.get("/me")
async def get_me(user: UserModel = Depends(get_current_user)):
    return {
        "user": user.to_dict()
    }

@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_auth_token:
        token = x_auth_token.strip()

    if token:
        await db.execute(delete(UserSessionModel).where(UserSessionModel.token == token))
        await db.commit()

    return {"message": "Logged out successfully"}

