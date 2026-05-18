from fastapi import FastAPI

app = FastAPI(title="Browser Agent")


@app.get("/health")
async def health():
    return {"status": "ok"}
