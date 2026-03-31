from bson import ObjectId as BSONObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from typing import Annotated, Literal


def _coerce_mongo_id(v):
    """Map BSON ObjectId to str; Pydantic ignores fields named _id, so we use mongo_id + alias."""
    if v is None:
        return None
    if isinstance(v, BSONObjectId):
        return str(v)
    return v


MongoIdStr = Annotated[str | None, BeforeValidator(_coerce_mongo_id)]


# nodes
class ParkNode(BaseModel):
    node_type: Literal["park"] = "park"

class StreetNode(BaseModel):
    node_type: Literal["street"] = "street"

class BedroomNode(BaseModel):
    node_type: Literal["bedroom"] = "bedroom"

NodeData = Annotated[
    ParkNode | StreetNode | BedroomNode,
    Field(discriminator="node_type"),
]

class Node(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    mongo_id: MongoIdStr = Field(default=None, validation_alias="_id", serialization_alias="_id")
    owner_id: str | None = None
    node_data: NodeData
    name: str | None = None
    adjectives: list[str] = []


# edges
class NormalEdge(BaseModel):
    edge_type: Literal["normal"] = "normal"

class DoorEdge(BaseModel):
    edge_type: Literal["door"] = "door"

EdgeData = Annotated[
    NormalEdge | DoorEdge,
    Field(discriminator="edge_type"),
]

class Edge(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    mongo_id: MongoIdStr = Field(default=None, validation_alias="_id", serialization_alias="_id")
    source_node_id: str
    destination_node_id: str
    edge_data: EdgeData = Field(default_factory=NormalEdge)


# users and friend requests
class FriendRequest(BaseModel):
    sender_id: str
    sender_username: str | None = None
    connector_node_id: str
    connector_node_name: str | None = None

class User(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    mongo_id: MongoIdStr = Field(default=None, validation_alias="_id", serialization_alias="_id")
    username: str
    password_hash: str
    current_node_id: str | None = None
    received_friend_requests: list[FriendRequest] = []

class Friendship(BaseModel):
    user_id_1: str
    user_id_2: str


# actions
class ActionCreateNodeGeneric(BaseModel):
    """This is a generic action that represents the user's ability to create a new node. It cannot be used directly."""
    action_type: Literal["create_node_generic"] = "create_node_generic"

class ActionCreateNode(BaseModel):
    action_type: Literal["create_node"] = "create_node"
    node_data: NodeData
    name: str | None = None
    adjectives: list[str] = []

class ActionGoToNode(BaseModel):
    action_type: Literal["go_to_node"] = "go_to_node"
    node_id: str
    node_name: str | None

Action = Annotated[
    ActionCreateNodeGeneric | ActionCreateNode | ActionGoToNode,
    Field(discriminator="action_type"),
]

class ListedOption(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    action: Action
    available: bool


# items
class ItemLocationNode(BaseModel):
    location_type: Literal["node"] = "node"
    node_id: str

class ItemLocationUserInventory(BaseModel):
    location_type: Literal["user_inventory"] = "user_inventory"
    user_id: str

ItemLocation = Annotated[
    ItemLocationNode | ItemLocationUserInventory,
    Field(discriminator="location_type"),
]

class KeyItem(BaseModel):
    item_type: Literal["key"] = "key"
    edge_id: str
    """The ID of the edge that the key can open."""

class NoteItem(BaseModel):
    item_type: Literal["note"] = "note"
    note_text: str
    """The text of the note."""

ItemData = Annotated[
    KeyItem | NoteItem,
    Field(discriminator="item_type"),
]

class Item(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    mongo_id: MongoIdStr = Field(default=None, validation_alias="_id", serialization_alias="_id")
    owner_id: str | None = None
    location: ItemLocation
    item_data: ItemData
