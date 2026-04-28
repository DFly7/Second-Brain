from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import router as auth_router
from app.routes.wiki import router as wiki_router

app = FastAPI(title="LLM Wiki")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(wiki_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
