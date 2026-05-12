from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import blueprint, health, quote

app = FastAPI(title="Manufacturing AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(blueprint.router, prefix="/api/blueprint")
app.include_router(quote.router, prefix="/api/quote")