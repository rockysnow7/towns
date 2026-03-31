from model import Action, ActionCreateNode, ActionCreateNodeGeneric, ActionGoToNode, FriendRequest, ListedOption, NodeData, ParkNode, StreetNode, BedroomNode
from rich import print
from rich.prompt import Prompt
from routes.game import DoActionRequest, GetStateResponse
from routes.users import (
    CreateFriendRequestRequest,
    CreateFriendRequestResponse,
    DecideFriendRequestRequest,
    DecideFriendRequestResponse,
    FriendRequestDecisionAccept,
    FriendRequestDecisionReject,
    LoginRequest,
    LoginResponse,
)

import requests
import survey


BASE_URL = "http://localhost:8000/api"


def login(username: str, password: str) -> str:
    request = LoginRequest(username=username, password=password)
    response = requests.post(
        f"{BASE_URL}/users/login",
        json=request.model_dump(mode="json"),
    )
    response.raise_for_status()
    return LoginResponse.model_validate(response.json()).token

def get_state(token: str) -> GetStateResponse:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(
        f"{BASE_URL}/game/state",
        headers=headers,
    )
    response.raise_for_status()
    return GetStateResponse.model_validate(response.json())

def send_friend_request(token: str, target_username: str, connector_node_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    request = CreateFriendRequestRequest(
        target_username=target_username,
        connector_node_id=connector_node_id,
    )
    response = requests.post(
        f"{BASE_URL}/users/create-friend-request",
        json=request.model_dump(mode="json"),
        headers=headers,
    )
    response.raise_for_status()
    return CreateFriendRequestResponse.model_validate(response.json()).message

def decide_friend_request(
    token: str,
    friend_request_sender_id: str,
    decision: FriendRequestDecisionAccept | FriendRequestDecisionReject,
) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    request = DecideFriendRequestRequest(
        friend_request_sender_id=friend_request_sender_id,
        decision=decision,
    )
    response = requests.post(
        f"{BASE_URL}/users/decide-friend-request",
        json=request.model_dump(mode="json"),
        headers=headers,
    )
    response.raise_for_status()
    return DecideFriendRequestResponse.model_validate(response.json()).message


def received_friend_requests_from_state(state: GetStateResponse) -> list[FriendRequest]:
    """Incoming friend requests for the current user (same data as GET /game/state)."""
    return state.received_friend_requests


def format_friend_request(fr: FriendRequest) -> str:
    name = fr.sender_username or fr.sender_id
    conn = fr.connector_node_name or fr.connector_node_id
    return f"from {name} — their connector: {conn} (sender id: {fr.sender_id})"


def print_received_friend_requests(requests: list[FriendRequest]) -> None:
    if not requests:
        print("[dim]No incoming friend requests.[/dim]")
        return
    print("[bold]Incoming friend requests[/bold]")
    for i, fr in enumerate(requests, start=1):
        print(f"  {i}. {format_friend_request(fr)}")


def prompt_send_friend_request(token: str) -> None:
    target_username = Prompt.ask("Target user username")
    connector_node_id = Prompt.ask("Your connector node id (a node you own or unowned)")
    try:
        msg = send_friend_request(token, target_username, connector_node_id)
        print(f"[green]{msg}[/green]")
    except requests.HTTPError as e:
        response = e.response.json()
        print(f"[red]{response['detail']}[/red]")


def prompt_decide_one_friend_request(token: str, friend_requests: list[FriendRequest]) -> None:
    if not friend_requests:
        print("[dim]Nothing to respond to.[/dim]")
        return
    indices = [str(i) for i in range(1, len(friend_requests) + 1)]
    idx = int(Prompt.ask("Which request (number)", choices=indices))
    fr = friend_requests[idx - 1]
    choice = Prompt.ask("Accept or reject", choices=["accept", "reject"])
    try:
        if choice == "reject":
            msg = decide_friend_request(token, fr.sender_id, FriendRequestDecisionReject())
        else:
            connector_node_id = Prompt.ask("Your connector node id (links to their space)")
            msg = decide_friend_request(
                token,
                fr.sender_id,
                FriendRequestDecisionAccept(connector_node_id=connector_node_id),
            )
        print(f"[green]{msg}[/green]")
    except requests.HTTPError as e:
        response = e.response.json()
        print(f"[red]{response['detail']}[/red]")


def friends_menu(token: str, state: GetStateResponse) -> None:
    while True:
        print()
        print_received_friend_requests(state.received_friend_requests)
        print()
        choice = Prompt.ask(
            "Friends menu — back, send a request, or decide an incoming one",
            choices=["back", "send", "decide"],
            default="back",
        )
        if choice == "back":
            return
        if choice == "send":
            prompt_send_friend_request(token)
        elif choice == "decide":
            prompt_decide_one_friend_request(token, state.received_friend_requests)
        state = get_state(token)


def option_to_string(option: ListedOption) -> str:
    match option.action:
        case ActionCreateNodeGeneric():
            return "Create a new space."
        case ActionGoToNode():
            return f"Move to {option.action.node_name}."

def choose_from_options(options: list[ListedOption]) -> ListedOption:
    display_options = [(option_to_string(option), option.available) for option in options]

    for i, (display_option, available) in enumerate(display_options):
        if available:
            print(f"{i + 1}. {display_option}")
        else:
            print(f"[dim]{i + 1}. {display_option}[/dim]")

    available_indices = [str(i + 1) for i, (_, available) in enumerate(display_options) if available]

    chosen_option_index = Prompt.ask("Choose an option", choices=available_indices)
    return options[int(chosen_option_index) - 1]

def choose_create_node_data() -> tuple[NodeData, str | None, list[str]]:
    options = {
        "park": ParkNode,
        "street": StreetNode,
        "bedroom": BedroomNode,
    }
    keys = list(options.keys())
    idx = survey.routines.select("Choose a space type: ", options=keys)
    space_type = keys[idx]
    node_data = options[space_type]()

    name = Prompt.ask(f"Enter a name for the {space_type}", default=None)

    display_name = name or space_type
    adjectives = []
    while True:
        if adjectives:
            text = f"Enter another adjective for the {display_name} (or leave blank to finish)"
        else:
            text = f"Enter an adjective for the {display_name} (or leave blank)"
        adjective = Prompt.ask(text)
        if not adjective:
            break
        adjectives.append(adjective)

    return node_data, name, adjectives

def action_from_option(option: ListedOption) -> Action:
    match option.action:
        case ActionCreateNodeGeneric():
            node_data, name, adjectives = choose_create_node_data()
            return ActionCreateNode(node_data=node_data, name=name, adjectives=adjectives)
        case ActionGoToNode():
            return option.action

def do_action(token: str, action: Action) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    request = DoActionRequest(action=action)
    response = requests.post(
        f"{BASE_URL}/game/do-action",
        json=request.model_dump(mode="json"),
        headers=headers,
    )
    return response.json()["message"]


if __name__ == "__main__":
    token = login("finn", "password")

    while True:
        state = get_state(token)
        print(f"[bold]{state.current_node_name}[/bold]\n")
        print(state.current_node_description)
        print()

        if state.received_friend_requests:
            n = len(state.received_friend_requests)
            print(
                f"[yellow]{n} incoming friend request(s)[/yellow] — "
                "open the friends menu to view or respond.",
            )
            print()

        mode = Prompt.ask(
            "Play at this location or manage friends",
            choices=["play", "friends", "delete account"],
            default="play",
        )
        if mode == "friends":
            friends_menu(token, state)
            continue

        chosen_option = choose_from_options(state.options)
        action = action_from_option(chosen_option)
        print()

        result = do_action(token, action)
        print(f"[dim]({result})[/dim]")
        print()
