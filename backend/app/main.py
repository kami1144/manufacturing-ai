from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

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


# SPA fallback - serve index.html for unknown routes (must be last)
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve SPA index.html for any unknown routes (Vue router paths)"""
    FRONTEND_DIST = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "frontend", "dist"
    )
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Frontend not found")


# Static files (must be after API routes for precedence)
FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "frontend", "dist"
)

if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
else:
    print(f"[WARNING] Frontend dist not found at {FRONTEND_DIST}, static files not mounted")