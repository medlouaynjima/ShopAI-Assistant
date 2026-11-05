"""
FastAPI Application — Agent Gateway entry point.

Run with:
    uvicorn src.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.config import settings
from src.services.database import init_db
from src.observability.langfuse_setup import flush_observability, init_observability
from src.security import RateLimitMiddleware

app = FastAPI(
    title="ShopAssist AI",
    description="LangGraph ReAct agent for e-commerce customer support",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    init_db()
    init_observability()


@app.on_event("shutdown")
def on_shutdown():
    """Flush pending workflow traces before exit."""
    flush_observability()

app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.api_host, port=settings.api_port, reload=True)
