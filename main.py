from fastapi import APIRouter, FastAPI
from routes.game import router as game_router
from routes.users import router as users_router
from routes.web import router as web_router

import uvicorn


api_router = APIRouter(prefix="/api")
api_router.include_router(users_router)
api_router.include_router(game_router)

app = FastAPI()
app.include_router(api_router)
app.include_router(web_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", port=8000, reload=True)
