from db import db
from model import Edge, EdgeData, Node, NodeData


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
    result = db["nodes"].insert_one(node.model_dump(mode="json"))
    return str(result.inserted_id)

def create_edge(source_node_id: str, destination_node_id: str, edge_data: EdgeData) -> str:
    edge = Edge(
        source_node_id=source_node_id,
        destination_node_id=destination_node_id,
        edge_data=edge_data,
    )
    result = db["edges"].insert_one(edge.model_dump(mode="json"))
    return str(result.inserted_id)
