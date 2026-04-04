from db import db
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from model import Action, ActionCreateNode, ActionCreateNodeGeneric, ActionGoToNode, BedroomNode, ListedOption, NodeData, ParkNode, StreetNode
from pydantic import TypeAdapter
from routes.game import DoActionRequest, GetStateResponse
from routes.users import LoginRequest, LoginResponse

import html
import httpx
import json
import os
import requests


BASE_URL = "http://localhost:8000/api"
WEB_ORIGIN = BASE_URL.removesuffix("/api")


templates = Jinja2Templates(directory="templates")
router = APIRouter()

COOKIE_MAX_AGE = int(os.getenv("SESSION_COOKIE_MAX_AGE", str(60 * 60 * 24)))  # 1 day


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
    return response


@router.get("/game", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "game.html")

def get_current_user_id_from_cookie(request: Request) -> str:
    return request.cookies.get("user_id")


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

@router.get("/game/state", response_class=HTMLResponse)
def get_state_fragment(request: Request) -> HTMLResponse:
    token = request.cookies.get("token")
    headers = {
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(
        f"{BASE_URL}/game/state",
        headers=headers,
    )
    if response.status_code != 200:
        detail = response.json()["detail"]
        return templates.TemplateResponse(
            request,
            "game.html",
            {"error": detail},
        )

    state = GetStateResponse.model_validate(response.json())
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

@router.post("/game/do-action", response_class=HTMLResponse)
async def do_action(request: Request) -> HTMLResponse:
    token = request.cookies.get("token")

    data = await request.json()
    action = json.loads(data["action"])
    action = TypeAdapter(Action).validate_python(action)
    do_action_request = DoActionRequest(action=action)

    headers = {
        "Authorization": f"Bearer {token}",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/game/do-action",
            json=do_action_request.model_dump(mode="json"),
            headers=headers,
        )
        if response.status_code != 200:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            return templates.TemplateResponse(
                request,
                "game.html",
                {"error": detail},
            )
        state_response = await client.get(
            f"{WEB_ORIGIN}/game/state",
            cookies=dict(request.cookies),
        )
    if state_response.status_code != 200:
        try:
            detail = state_response.json()["detail"]
        except (ValueError, KeyError):
            detail = state_response.text
        return templates.TemplateResponse(
            request,
            "game.html",
            {"error": detail},
        )
    return RedirectResponse(url="/game", status_code=303)


@router.get("/game/create-node", response_class=HTMLResponse)
def create_node_page(request: Request) -> HTMLResponse:
    token = request.cookies.get("token")
    headers = {
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(
        f"{BASE_URL}/game/state",
        headers=headers,
    )
    if response.status_code != 200:
        try:
            detail = response.json()["detail"]
        except ValueError:
            detail = response.text
        return templates.TemplateResponse(request, "game.html", {"error": detail})

    state = GetStateResponse.model_validate(response.json())
    return templates.TemplateResponse(
        request,
        "fragments/create-node.html",
        {
            "current_node_name": display_format_string_with_tags(state.current_node_name),
            "current_node_description": display_format_string_with_tags(state.current_node_description),
        },
    )

@router.post("/game/create-node", response_class=HTMLResponse)
async def create_node_submit(request: Request) -> HTMLResponse:
    token = request.cookies.get("token")
    headers = {
        "Authorization": f"Bearer {token}",
    }
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

    name = data["name"]
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
            try:
                detail = response.json()["detail"]
            except ValueError:
                detail = response.text
            return templates.TemplateResponse(
                request,
                "game.html",
                {"error": detail},
            )
        return RedirectResponse(url="/game", status_code=303)
