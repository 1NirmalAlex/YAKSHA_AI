"""
YAKSHA AI - FastAPI Backend Bridge
Connects CrewAI Multi-Agent System with React Dashboard UI
"""

import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Parent directory import setup for YAKSHA AI modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI(title="YAKSHA AI Engine API")

# Enable CORS for Frontend UI Connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PromptRequest(BaseModel):
    prompt: str

@app.get("/")
def read_root():
    return {"status": "YAKSHA AI Backend Running Successfully"}

@app.post("/api/run-crew")
async def run_yaksha_crew(request: PromptRequest):
    """
    Receives prompt from UI, executes CrewAI agents, and returns final code/summary
    """
    user_prompt = request.prompt.strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty!")

    try:
        # Import YAKSHA AI Core
        from app import yaksha_crew, task_plan, task_backend, task_frontend, task_review_and_save
        import app as yaksha_app

        # Dynamically update the task execution with user prompt
        yaksha_app.USER_PROMPT = user_prompt
        task_plan.description = (
            f"Analyze requirement: '{user_prompt}' and output a clear execution plan. "
            "IMPORTANT: Do NOT write any actual code here. Keep it to a short numbered list."
        )

        # Kickoff CrewAI System
        execution_result = yaksha_crew.kickoff()

        return {
            "status": "success",
            "prompt": user_prompt,
            "result": str(execution_result)
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    # "main:app" ලෙස app instance එක නිවැරදිව ලබා දීම
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)