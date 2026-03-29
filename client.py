from copy import deepcopy
from model import Action, ActionCreateNode, ActionCreateNodeGeneric, ActionGoToNode, ListedOption, NodeData, ParkNode, StreetNode, BedroomNode
from rich import print
from rich.prompt import Prompt
from routes.game import DoActionRequest, GetStateResponse
from routes.users import LoginRequest

import requests
import survey


BASE_URL = "http://localhost:8000/api"


def login(username: str, password: str) -> str:
    request = LoginRequest(username=username, password=password)
    response = requests.post(
        f"{BASE_URL}/users/login",
        json=request.model_dump(mode="json"),
    )
    return response.json()["token"]

def get_state(token: str) -> GetStateResponse:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(
        f"{BASE_URL}/game/state",
        headers=headers,
    )
    return GetStateResponse.model_validate(response.json())


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

        chosen_option = choose_from_options(state.options)
        action = action_from_option(chosen_option)
        print()

        result = do_action(token, action)
        print(f"[dim]({result})[/dim]")
        print()
