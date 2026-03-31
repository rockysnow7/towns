from bson import ObjectId
from fastapi import HTTPException
from db import db
from model import Edge, EdgeData, Node, NodeData, User


def create_node(
    owner_id: str,
    node_data: NodeData,
    name: str | None = None,
    adjectives: list[str] = [],
) -> str:
    node = Node(
        owner_id=owner_id,
        node_data=node_data,
        name=name,
        adjectives=adjectives,
    )
    result = db["nodes"].insert_one(node.model_dump(mode="json", exclude_none=True))
    return str(result.inserted_id)

def create_edge(source_node_id: str, destination_node_id: str, edge_data: EdgeData) -> str:
    edge = Edge(
        source_node_id=source_node_id,
        destination_node_id=destination_node_id,
        edge_data=edge_data,
    )
    result = db["edges"].insert_one(edge.model_dump(mode="json", exclude_none=True))
    return str(result.inserted_id)

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
