import os
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

# Mock OpenAI API — тестовая поверхность для проверки обработки ошибок.
# Из GUI пока не используется, поэтому по умолчанию выключена.
# Включить: переменная окружения NEUROMITA_ENABLE_MOCK_API=1
if os.environ.get("NEUROMITA_ENABLE_MOCK_API", "0") == "1":
    from web.mock_api.router import router as mock_api_router
    app.include_router(mock_api_router)
    logger.info("Mock OpenAI API включён (NEUROMITA_ENABLE_MOCK_API=1)")

@app.get("/")
async def root():
    return {"message": "API для локального Voice-To-Text"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

# todo:
# - через websocket отправлять частями текст
# - выносить работу сервиса в отдельный процесс
