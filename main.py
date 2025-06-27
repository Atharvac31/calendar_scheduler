from fastapi import FastAPI, Request
from pydantic import BaseModel
from agent import process_message

app = FastAPI()

class MessageRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat(req: MessageRequest):
    response = await process_message(req.message)
    return {"response": response}
