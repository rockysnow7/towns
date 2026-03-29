from fastapi import APIRouter, FastAPI
from routes.users import router as users_router
from routes.game import router as game_router

import uvicorn


api_router = APIRouter(prefix="/api")
api_router.include_router(users_router)
api_router.include_router(game_router)

app = FastAPI()
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", port=8000, reload=True)
