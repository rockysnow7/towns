from datetime import datetime, timezone, timedelta
from bson import ObjectId
from db import db
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from model import BedroomNode, Node, NodeData, User
from passlib.hash import argon2
from pydantic import BaseModel

import jwt
import os
import utils


load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


router = APIRouter(prefix="/users")


def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> str:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
        return user_id
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class RegisterRequest(BaseModel):
    username: str
    password: str

class RegisterResponse(BaseModel):
    token: str
    message: str

@router.post("/register", status_code=201, response_model=RegisterResponse)
def register(request: RegisterRequest) -> RegisterResponse:
    if db["users"].find_one({"username": request.username}):
        raise HTTPException(status_code=409, detail="That username is already taken")

    password_hash = argon2.hash(request.password)
    user = User(
        username=request.username,
        password_hash=password_hash,
    )
    result = db["users"].insert_one(user.model_dump(mode="json"))
    user_id = str(result.inserted_id)

    token = create_token(user_id)

    # create a new node for the user to start on
    node_id = utils.create_node(user_id, BedroomNode())
    db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"current_node_id": node_id}},
    )

    return RegisterResponse(
        token=token,
        message="Account created successfully",
    )


class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    message: str

@router.post("/login", status_code=200, response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    account = db["users"].find_one({"username": request.username})
    if not account:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not argon2.verify(request.password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return LoginResponse(
        token=create_token(str(account["_id"])),
        message="Login successful",
    )
