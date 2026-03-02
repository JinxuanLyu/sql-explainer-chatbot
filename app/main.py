from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pathlib import Path

from app.guardrails import route_message
from app.llm import generate_answer

app = FastAPI()

INDEX_PATH = Path(__file__).parent / "index.html"


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/", response_class=HTMLResponse)
def home():
    return INDEX_PATH.read_text(encoding="utf-8")


@app.post("/chat")
def chat(req: ChatRequest):
    user_message = (req.message or "").strip()
    decision = route_message(user_message)

    # Controlled responses (no LLM call)
    if decision["type"] in {
        "safety",
        "uncertain",
        "oos_non_sql",
        "oos_missing_query",
        "oos_advanced_sql",
    }:
        return {
            "response": decision["response"],
            "type": decision["type"],
            "session_id": req.session_id,
        }

    # smalltalk or in_domain -> LLM
    response_text = generate_answer(
        user_message=user_message,
        mode=decision["type"],
    )

    return {
        "response": response_text,
        "type": decision["type"],
        "session_id": req.session_id,
    }