from bson import ObjectId
from db import db
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from model import Action, ActionCreateNode, Edge, Item, ItemData, ItemLocationUserInventory, ListedOption, Node, NormalEdge, User, ActionCreateNodeGeneric, ActionGoToNode
from pydantic import BaseModel
from rich import print
from routes.users import get_current_user_id

import utils


router = APIRouter(prefix="/game")


def validate_user_can_create_node_from_current(user_id: str, current_node_id: str) -> None:
    """Raise HTTPException if the user may not create a new node attached from their current node."""

    current_raw = db["nodes"].find_one({"_id": ObjectId(current_node_id)})
    if not current_raw:
        raise HTTPException(status_code=404, detail="Current node not found")
    current_node = Node.model_validate(current_raw)
    if current_node.owner_id is not None and current_node.owner_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot add a node to a node that you do not own",
        )


def validate_edge_creation(user_id: str, source_node_id: str, destination_node_id: str) -> None:
    """Raise HTTPException if the user may not create an edge from source to destination."""

    if source_node_id == destination_node_id:
        raise HTTPException(status_code=400, detail="You cannot connect a node to itself")

    source_raw = db["nodes"].find_one({"_id": ObjectId(source_node_id)})
    destination_raw = db["nodes"].find_one({"_id": ObjectId(destination_node_id)})
    if not source_raw:
        raise HTTPException(status_code=404, detail="Source node not found")
    if not destination_raw:
        raise HTTPException(status_code=404, detail="Destination node not found")

    source_node = Node.model_validate(source_raw)
    destination_node = Node.model_validate(destination_raw)

    if source_node.owner_id is not None and source_node.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Source node belongs to a different user")
    if destination_node.owner_id is not None and destination_node.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Destination node belongs to a different user")

    if db["edges"].find_one({
        "source_node_id": source_node_id,
        "destination_node_id": destination_node_id,
    }):
        raise HTTPException(status_code=409, detail="Edge already exists")


class CreateItemRequest(BaseModel):
    item_data: ItemData

class CreateItemResponse(BaseModel):
    message: str

@router.post("/create-item", status_code=201, response_model=CreateItemResponse)
def create_item(
    request: CreateItemRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> CreateItemResponse:
    """Create a new item for the current user."""

    user_id = get_current_user_id(credentials)

    item = Item(
        owner_id=user_id,
        location=ItemLocationUserInventory(user_id=user_id),
        item_data=request.item_data,
    )
    db["items"].insert_one(item.model_dump(mode="json"))
    return CreateItemResponse(message="Item created successfully")


def user_has_key_for_door(user_id: str, required_edge_id: str) -> bool:
    """Check if the user has a key for the given door."""

    return db["items"].find_one({
        "owner_id": user_id,
        "item_data.item_type": "key",
        "item_data.edge_id": required_edge_id,
    }) is not None


class GetStateResponse(BaseModel):
    current_node_name: str
    current_node_description: str
    options: list[ListedOption]

def get_node_name(node: Node) -> str:
    """Get the name of the given node."""

    if node.name is not None:
        return f"[green]{node.name}[/green]"

    owner = db["users"].find_one({"_id": ObjectId(node.owner_id)})
    owner = User.model_validate(owner)

    return f"[green]{owner.username}'s {node.node_data.node_type}[/green]"

def get_node_name_from_id(node_id: str) -> str:
    """Get the name of the node with the given ID."""

    node = db["nodes"].find_one({"_id": ObjectId(node_id)})
    node = Node.model_validate(node)
    return get_node_name(node)

def get_node_description(node: Node) -> str:
    """Get a description of the given node."""

    sentences: list[str] = []
    sentences.append(f"It is a {node.node_data.node_type}.")

    # add adjectives
    if node.adjectives:
        if len(node.adjectives) == 1:
            adjectives = node.adjectives[0]
        elif len(node.adjectives) == 2:
            adjectives = f"{node.adjectives[0]} and {node.adjectives[1]}"
        else:
            adjectives = f"{', '.join(node.adjectives[:-1])}, and {node.adjectives[-1]}"
        sentences.append(f"It is {adjectives}.")

    # TODO: add items

    # replace the first "It" with the node name (hacky but whatevs)
    node_name = get_node_name(node)
    sentences[0] = node_name + sentences[0][2:]

    return " ".join(sentences)

@router.get("/state", status_code=200, response_model=GetStateResponse)
def get_state(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> GetStateResponse:
    """Get the current state of the game for the current user (current node name, description, and options)."""

    user_id = get_current_user_id(credentials)

    user = db["users"].find_one({"_id": ObjectId(user_id)})
    user = User.model_validate(user)

    current_node = db["nodes"].find_one({"_id": ObjectId(user.current_node_id)})
    current_node = Node.model_validate(current_node)
    current_node_name = get_node_name(current_node)
    current_node_description = get_node_description(current_node)

    options = []

    # add create node option
    can_create_node = current_node.owner_id is None or current_node.owner_id == user_id
    options.append(ListedOption(
        action=ActionCreateNodeGeneric(),
        available=can_create_node,
    ))

    # add movement options
    edges_from_current_node = db["edges"].find({"source_node_id": user.current_node_id})
    edges_from_current_node = [Edge.model_validate(edge) for edge in edges_from_current_node]
    for edge in edges_from_current_node:
        match edge.edge_data.edge_type:
            case "normal":
                options.append(ListedOption(
                    action=ActionGoToNode(
                        node_id=edge.destination_node_id,
                        node_name=get_node_name_from_id(edge.destination_node_id),
                    ),
                    available=True,
                ))
            case "door":
                options.append(ListedOption(
                    action=ActionGoToNode(
                        node_id=edge.destination_node_id,
                        node_name=get_node_name_from_id(edge.destination_node_id),
                    ),
                    available=user_has_key_for_door(user_id, edge._id),
                ))

    # TODO: add other options

    return GetStateResponse(
        current_node_name=current_node_name,
        current_node_description=current_node_description,
        options=options,
    )


class DoActionRequest(BaseModel):
    action: Action

class DoActionResponse(BaseModel):
    message: str

@router.post("/do-action", status_code=200, response_model=DoActionResponse)
def do_action(
    request: DoActionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> DoActionResponse:
    """Perform a given action for the current user."""

    user_id = get_current_user_id(credentials)

    user = db["users"].find_one({"_id": ObjectId(user_id)})
    user = User.model_validate(user)

    match request.action:
        case ActionCreateNodeGeneric():
            raise HTTPException(status_code=400, detail="You cannot perform an `ActionCreateNodeGeneric` action, use the `ActionCreateNode` action instead")

        case ActionCreateNode():
            if user.current_node_id is None:
                raise HTTPException(status_code=400, detail="User has no current node")

            validate_user_can_create_node_from_current(user_id, user.current_node_id)

            node_id = utils.create_node(
                user_id,
                request.action.node_data,
                request.action.name,
                request.action.adjectives,
            )

            validate_edge_creation(user_id, user.current_node_id, node_id)
            utils.create_edge(user.current_node_id, node_id, NormalEdge())

            validate_edge_creation(user_id, node_id, user.current_node_id)
            utils.create_edge(node_id, user.current_node_id, NormalEdge())

            return DoActionResponse(message="Node created successfully")

        case ActionGoToNode():
            can_go_to_node = db["edges"].find_one({
                "source_node_id": user.current_node_id,
                "destination_node_id": request.action.node_id,
            }) is not None

            if not can_go_to_node:
                raise HTTPException(status_code=400, detail="You cannot move to this node")

            db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"current_node_id": request.action.node_id}},
            )
            return DoActionResponse(message="Moved to node successfully")
