from fastapi import FastAPI, WebSocket
from pydantic import BaseModel

app = FastAPI(title="PersonaBot API", version="0.1.0")


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="personabot-api")


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "system",
            "message": "WebSocket connected. Streaming pipeline not wired yet.",
        }
    )

    while True:
        payload = await websocket.receive_json()
        await websocket.send_json(
            {
                "type": "echo",
                "message": payload.get("message", ""),
                "session_id": payload.get("session_id"),
            }
        )
