"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(title="EU AI Compliance Assistant")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
