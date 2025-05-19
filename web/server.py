from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from loguru import logger
from web.vtt.router import router as vtt_router
@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Запуск Voice-To-Text API 💫")
    yield
    logger.info("Остановка Voice-To-Text API 💔")

app = FastAPI(root_path="/api",
              title="API для локального Voice-To-Text",
              description="API для локального Voice-To-Text",
              version="0.1.0",
              docs_url="/docs",
              redoc_url="/redoc",
              lifespan=lifespan,
              )

app.include_router(vtt_router)

@app.get("/")
async def root():
    return {"message": "API для локального Voice-To-Text"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

# todo:
# - через websocket отправлять частями текст
# - выносить работу сервиса в отдельный процесс
