from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from agent import chat  # noqa: E402  (import after load_dotenv so env vars are set)

app = FastAPI(title="Skylark Drones - BI Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory session store. Fine for a prototype; swap for Redis/DB for real use.
SESSIONS = {}


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    history = SESSIONS.get(req.session_id, [])
    history = history + [{"role": "user", "content": req.message}]
    answer, full_history = chat(history)
    SESSIONS[req.session_id] = full_history
    return {"answer": answer}


@app.post("/leadership-summary")
def leadership_summary():
    prompt = "Prepare a leadership update covering pipeline health, revenue collected vs receivable, and top data quality risks."
    answer, _ = chat([{"role": "user", "content": prompt}])
    return {"summary": answer}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)