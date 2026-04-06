from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from model import Action, ActionCreateNode, ActionCreateNodeGeneric, ActionGoToNode, BedroomNode, ListedOption, NodeData, ParkNode, StreetNode
from pydantic import TypeAdapter
from routes.game import DoActionRequest, GetStateResponse
from routes.users import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse

import html
import httpx
import json
import os
import requests


BASE_URL = "http://localhost:8000/api"
COOKIE_MAX_AGE = int(os.getenv("SESSION_COOKIE_MAX_AGE", str(60 * 60 * 24)))  # 1 day

templates = Jinja2Templates(directory="templates")
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")

@router.post("/login", response_model=None)
def login_submit(
    request: Request,
    username: str = Form(),
    password: str = Form(),
) -> RedirectResponse | HTMLResponse:
    """Log in a user via the /api/users/login endpoint."""

    login_request = LoginRequest(username=username, password=password)
    login_response = requests.post(
        f"{BASE_URL}/users/login",
        json=login_request.model_dump(mode="json"),
    )
    if login_response.status_code != 200:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
        )
    login_response = LoginResponse.model_validate(login_response.json())

    response = RedirectResponse(
        url="/game",
        status_code=303,
    )
    response.set_cookie(
        "token",
        login_response.token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        "username",
        username,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return response


@router.get("/create-account", response_class=HTMLResponse)
def create_account_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "create-account.html")

@router.post("/create-account", response_model=None)
def create_account_submit(
    request: Request,
    username: str = Form(),
    password: str = Form(),
) -> RedirectResponse | HTMLResponse:
    """Sign up a user via the /api/users/register endpoint."""

    register_request = RegisterRequest(username=username, password=password)
    register_response = requests.post(
        f"{BASE_URL}/users/register",
        json=register_request.model_dump(mode="json"),
    )
    if register_response.status_code != 201:
        detail = _detail_from_api_response(register_response)
        return templates.TemplateResponse(request, "create-account.html", {"error": detail})
    register_response = RegisterResponse.model_validate(register_response.json())

    response = RedirectResponse(url="/game", status_code=303)
    response.set_cookie(
        "token",
        register_response.token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        "username",
        username,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return response

@router.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("token", path="/")
    response.delete_cookie("username", path="/")
    return response


@router.get("/game", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not request.cookies.get("username"):
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "game.html",
        {"username": request.cookies.get("username")},
    )

COLORS = {
    "green": "#46eb3d",
    "red": "#eb3d3d",
    "blue": "#3d54eb",
    "purple": "#943deb",
    "pink": "#eb3dd7",
    "yellow": "#ebd43d",
}
TAGS = {}
for color, hex_code in COLORS.items():
    TAGS[f"[{color}]"] = f"<span style='color: {hex_code};'>"
    TAGS[f"[/{color}]"] = "</span>"

def display_format_string_with_tags(string: str) -> str:
    string = html.escape(string) # in case the user tries to inject HTML
    for tag, replacement in TAGS.items():
        string = string.replace(tag, replacement)
    return string

def display_format_option(option: ListedOption) -> dict:
    match option.action:
        case ActionGoToNode():
            node_name = display_format_string_with_tags(option.action.node_name)
            action = option.action.model_dump(mode="json")
            return {
                "display_text": f"Move to {node_name}.",
                "available": option.available,
                "hx_vals_json": json.dumps({"action": action}),
            }
        case _:
            raise ValueError(f"Invalid action type: {option.action}")


def _game_api_headers(request: Request) -> dict[str, str]:
    token = request.cookies.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _detail_from_api_response(response: requests.Response | httpx.Response) -> str:
    text = response.text or ""
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError, TypeError):
        return text or "Request failed"
    if isinstance(body, dict) and body.get("detail") is not None:
        d = body["detail"]
        return d if isinstance(d, str) else json.dumps(d)
    return text or "Request failed"


def _game_shell_error(request: Request, response: requests.Response | httpx.Response) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "game.html",
        {"error": _detail_from_api_response(response)},
    )


def fetch_game_state(request: Request) -> GetStateResponse | HTMLResponse:
    r = requests.get(f"{BASE_URL}/game/state", headers=_game_api_headers(request))
    if r.status_code != 200:
        return _game_shell_error(request, r)
    return GetStateResponse.model_validate(r.json())


async def fetch_game_state_async(
    client: httpx.AsyncClient, request: Request
) -> GetStateResponse | HTMLResponse:
    r = await client.get(f"{BASE_URL}/game/state", headers=_game_api_headers(request))
    if r.status_code != 200:
        return _game_shell_error(request, r)
    return GetStateResponse.model_validate(r.json())


def playing_state_fragment_from_model(request: Request, state: GetStateResponse) -> HTMLResponse:
    """HTML for #game-panel only (no shell/footer)."""

    can_create_node = ListedOption(action=ActionCreateNodeGeneric(), available=True) in state.options
    options = [display_format_option(option) for option in state.options if not option.action == ActionCreateNodeGeneric()]

    return templates.TemplateResponse(
        request,
        "fragments/state.html",
        {
            "node_name": display_format_string_with_tags(state.current_node_name),
            "description": display_format_string_with_tags(state.current_node_description),
            "options": options,
            "friend_requests": state.received_friend_requests,
            "can_create_node": can_create_node,
        },
    )


def render_playing_state_fragment(request: Request) -> HTMLResponse:
    """Sync fetch + fragment. Safe from sync route handlers only."""

    result = fetch_game_state(request)
    if not isinstance(result, GetStateResponse):
        return result
    return playing_state_fragment_from_model(request, result)


@router.get("/game/state", response_class=HTMLResponse)
def get_state_fragment(request: Request) -> HTMLResponse:
    if not request.cookies.get("username"):
        return RedirectResponse(url="/login", status_code=303)

    return render_playing_state_fragment(request)

@router.post("/game/do-action", response_class=HTMLResponse)
async def do_action(request: Request) -> HTMLResponse:
    if not request.cookies.get("username"):
        return RedirectResponse(url="/login", status_code=303)

    data = await request.json()
    action = TypeAdapter(Action).validate_python(json.loads(data["action"]))
    do_action_request = DoActionRequest(action=action)
    headers = _game_api_headers(request)

    async with httpx.AsyncClient() as client:
        post = await client.post(
            f"{BASE_URL}/game/do-action",
            json=do_action_request.model_dump(mode="json"),
            headers=headers,
        )
        if post.status_code != 200:
            return _game_shell_error(request, post)
        state = await fetch_game_state_async(client, request)

    if not isinstance(state, GetStateResponse):
        return state
    return playing_state_fragment_from_model(request, state)


@router.get("/game/create-node", response_class=HTMLResponse)
def create_node_page(request: Request) -> HTMLResponse:
    if not request.cookies.get("username"):
        return RedirectResponse(url="/login", status_code=303)

    result = fetch_game_state(request)
    if not isinstance(result, GetStateResponse):
        return result
    return templates.TemplateResponse(
        request,
        "fragments/create-node.html",
        {
            "current_node_name": display_format_string_with_tags(result.current_node_name),
            "current_node_description": display_format_string_with_tags(result.current_node_description),
        },
    )

@router.post("/game/create-node", response_class=HTMLResponse)
async def create_node_submit(request: Request) -> HTMLResponse:
    if not request.cookies.get("username"):
        return RedirectResponse(url="/login", status_code=303)

    headers = _game_api_headers(request)
    data = await request.form()

    node_type = data["node-data"]
    match node_type:
        case "park":
            node_data = ParkNode()
        case "street":
            node_data = StreetNode()
        case "bedroom":
            node_data = BedroomNode()
        case _:
            return templates.TemplateResponse(request, "game.html", {"error": "Invalid node type"})

    name = data["name"] or None
    adjectives = data["adjectives"].split(",")
    adjectives = [adjective.strip() for adjective in adjectives if adjective.strip()]

    create_node_action = ActionCreateNode(node_data=node_data, name=name, adjectives=adjectives)
    do_action_request = DoActionRequest(action=create_node_action)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/game/do-action",
            json=do_action_request.model_dump(mode="json"),
            headers=headers,
        )
        if response.status_code != 200:
            return _game_shell_error(request, response)
        return RedirectResponse(url="/game", status_code=303)
