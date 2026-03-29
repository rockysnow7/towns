from datetime import datetime, timezone, timedelta
from bson import ObjectId
from db import db
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from model import BedroomNode, Edge, FriendRequest, Friendship, Node, NormalEdge, User
from passlib.hash import argon2
from pydantic import BaseModel, Field
from typing import Annotated, Literal

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
    """Register a new user and create a new node for them to start on."""

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
    """Login a user and return a JWT token."""

    account = db["users"].find_one({"username": request.username})
    if not account:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not argon2.verify(request.password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return LoginResponse(
        token=create_token(str(account["_id"])),
        message="Login successful",
    )


class DeleteAccountRequest(BaseModel):
    password: str
    pass_ownership_to_user_with_username: str | None = None

class DeleteAccountResponse(BaseModel):
    message: str

@router.delete("/delete-account", status_code=200, response_model=DeleteAccountResponse)
def delete_account(
    request: DeleteAccountRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> DeleteAccountResponse:
    """Delete a user and all their data. Optionally pass ownership of their nodes and items to a friend."""

    user_id = get_current_user_id(credentials)
    user = db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not argon2.verify(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    if request.pass_ownership_to_user_with_username:
        target_user = db["users"].find_one({"username": request.pass_ownership_to_user_with_username})
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")

        target_user_id = str(target_user["_id"])
        db["nodes"].update_many({"owner_id": user_id}, {"$set": {"owner_id": target_user_id}})
        db["items"].update_many({"owner_id": user_id}, {"$set": {"owner_id": target_user_id}})

        db["users"].delete_one({"_id": ObjectId(user_id)})

        return DeleteAccountResponse(
            message=f"Account deleted successfully. Ownership passed to {request.pass_ownership_to_user_with_username}.",
        )

    db["users"].delete_one({"_id": ObjectId(user_id)})

    node_ids = db["nodes"].find({"owner_id": user_id}, {"_id": 1})
    node_ids = [node_id["_id"] for node_id in node_ids]
    node_oids = [ObjectId(node_id["_id"]) for node_id in node_ids]

    db["nodes"].delete_many({"_id": {"$in": node_oids}})
    db["edges"].delete_many({"$or": [{"source_node_id": {"$in": node_ids}}, {"destination_node_id": {"$in": node_ids}}]})
    db["items"].delete_many({"owner_id": user_id})

    return DeleteAccountResponse(message="Account deleted successfully. Goodbye.")


class CreateFriendRequestRequest(BaseModel):
    target_username: str
    connector_node_id: str

class CreateFriendRequestResponse(BaseModel):
    message: str

@router.post("/create-friend-request", status_code=200, response_model=CreateFriendRequestResponse)
def create_friend_request(
    request: CreateFriendRequestRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> CreateFriendRequestResponse:
    """Create a friend request to a user."""

    user_id = get_current_user_id(credentials)
    user = db["users"].find_one({"_id": ObjectId(user_id)})
    user = User.model_validate(user)

    target_user = db["users"].find_one({"username": request.target_username})
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    target_user = User.model_validate(target_user)

    # check if the target user is the same as the user
    if target_user._id == user_id:
        raise HTTPException(status_code=400, detail="You cannot send a friend request to yourself")

    # check if the target user is already friends with the user
    result = db["friendships"].find_one({"$or": [
        {"user_id_1": user_id, "user_id_2": target_user._id},
        {"user_id_1": target_user._id, "user_id_2": user_id},
    ]})
    if result:
        raise HTTPException(status_code=409, detail="You are already friends with this user")

    # check if the user has already sent a friend request to the target user
    if any(friend_request.sender_id == user_id for friend_request in target_user.received_friend_requests):
        raise HTTPException(status_code=409, detail="You have already sent a friend request to this user")

    # check if the target user has already sent a friend request to the user
    if any(friend_request.sender_id == target_user._id for friend_request in user.received_friend_requests):
        raise HTTPException(status_code=409, detail="This user has already sent you a friend request")

    connector_node = db["nodes"].find_one({"_id": ObjectId(request.connector_node_id)})
    if not connector_node:
        raise HTTPException(status_code=404, detail="Connector node not found")
    connector_node = Node.model_validate(connector_node)

    if connector_node.owner_id is not None and connector_node.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Connector node belongs to a different user")

    connector_node_name = utils.get_node_name(connector_node)

    # create the friend request
    friend_request = FriendRequest(
        sender_id=user_id,
        sender_username=user.username,
        connector_node_id=request.connector_node_id,
        connector_node_name=connector_node_name,
    )
    db["users"].update_one(
        {"_id": ObjectId(target_user._id)},
        {"$push": {"received_friend_requests": friend_request.model_dump(mode="json")}},
    )

    return CreateFriendRequestResponse(
        message=f"Friend request sent to {request.target_username}",
    )


class FriendRequestDecisionAccept(BaseModel):
    decision_type: Literal["accept"] = "accept"
    connector_node_id: str

class FriendRequestDecisionReject(BaseModel):
    decision_type: Literal["reject"] = "reject"

FriendRequestDecision = Annotated[
    FriendRequestDecisionAccept | FriendRequestDecisionReject,
    Field(discriminator="decision_type"),
]

class DecideFriendRequestRequest(BaseModel):
    friend_request_sender_id: str
    decision: FriendRequestDecision

class DecideFriendRequestResponse(BaseModel):
    message: str

@router.post("/decide-friend-request", status_code=200, response_model=DecideFriendRequestResponse)
def decide_friend_request(
    request: DecideFriendRequestRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> DecideFriendRequestResponse:
    """Decide whether to accept or reject a friend request."""

    user_id = get_current_user_id(credentials)
    user = db["users"].find_one({"_id": ObjectId(user_id)})
    user = User.model_validate(user)

    friend_request = next((friend_request for friend_request in user.received_friend_requests if friend_request.sender_id == request.friend_request_sender_id), None)
    if not friend_request:
        raise HTTPException(status_code=404, detail=f"Friend request from user with ID {request.friend_request_sender_id} not found")

    match request.decision:
        case FriendRequestDecisionReject():
            db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"received_friend_requests": {
                    "sender_id": request.friend_request_sender_id,
                }}},
            )
            return DecideFriendRequestResponse(
                message=f"Friend request from {friend_request.sender_username} rejected",
            )

        case FriendRequestDecisionAccept():
            # check that the connector node exists and is owned by the current user or null
            connector_node = db["nodes"].find_one({"_id": ObjectId(request.decision.connector_node_id)})
            if not connector_node:
                raise HTTPException(status_code=404, detail="Connector node not found")
            connector_node = Node.model_validate(connector_node)
            if connector_node.owner_id is not None and connector_node.owner_id != user_id:
                raise HTTPException(status_code=403, detail="Connector node belongs to a different user")

            # create the friendship
            friendship = Friendship(
                user_id_1=user_id,
                user_id_2=request.friend_request_sender_id,
            )
            db["friendships"].insert_one(friendship.model_dump(mode="json"))

            # delete the friend request
            db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"received_friend_requests": {
                    "sender_id": request.friend_request_sender_id,
                }}},
            )

            # and add edges between the two chosen connector nodes
            utils.create_edge(
                request.decision.connector_node_id,
                friend_request.connector_node_id,
                NormalEdge(),
            )
            utils.create_edge(
                friend_request.connector_node_id,
                request.decision.connector_node_id,
                NormalEdge(),
            )

            return DecideFriendRequestResponse(
                message=f"Friend request from {friend_request.sender_username} accepted",
            )
