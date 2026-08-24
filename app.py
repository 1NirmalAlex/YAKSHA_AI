"""
YAKSHA AI - Multi-Agent System (Multi-LLM Architecture)
CrewAI + Groq + Gemini
"""

import os
import time
import litellm
from dotenv import load_dotenv
from crewai import Agent, Crew, Process, Task, LLM
from crewai_tools import FileWriterTool, FileReadTool, DirectoryReadTool

# ----------------------------------------------------
# 1. Load API Keys
# ----------------------------------------------------
load_dotenv()

groq_key = os.getenv("GROQ_API_KEY")
gemini_key = os.getenv("GEMINI_API_KEY")

if not groq_key:
    raise ValueError("GROQ_API_KEY missing in .env file!")
if not gemini_key:
    raise ValueError("GEMINI_API_KEY missing in .env file!")

# Set Gemini Key for LiteLLM & CrewAI
os.environ["GEMINI_API_KEY"] = gemini_key

# ----------------------------------------------------
# 2. PATCH: Remove cache_breakpoint & Rate-Limit Retry
# ----------------------------------------------------
try:
    import crewai.llms.cache as _crewai_cache
    _crewai_cache.mark_cache_breakpoint = lambda msg: msg
except ImportError:
    pass

_original_completion = litellm.completion

def _custom_completion(*args, **kwargs):
    for msg in kwargs.get("messages", []):
        if isinstance(msg, dict):
            msg.pop("cache_breakpoint", None)
            msg.pop("cache_control", None)

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            return _original_completion(*args, **kwargs)
        except litellm.RateLimitError:
            if attempt == max_attempts:
                raise
            wait = 15 * attempt
            print(f"[Rate Limit Hit] Retrying in {wait}s (Attempt {attempt}/{max_attempts})...")
            time.sleep(wait)

litellm.completion = _custom_completion
litellm.drop_params = True
os.environ["LITELLM_DROP_PARAMS"] = "True"

# ----------------------------------------------------
# 3. Model Definitions (Updated to Active Models)
# ----------------------------------------------------
# Gemini Models (Updated to active gemini-3.6-flash & gemini-3.5-flash-lite)
gemini_planner = LLM(
    model="gemini/gemini-3.6-flash",
    api_key=gemini_key,
    temperature=0.2,
)

gemini_qa = LLM(
    model="gemini/gemini-3.5-flash-lite",
    api_key=gemini_key,
    temperature=0.1,
)

# Groq Models (Separate Rate Limit Buckets)
groq_backend = LLM(
    model="groq/openai/gpt-oss-120b",
    api_key=groq_key,
    temperature=0.2,
)

groq_frontend = LLM(
    model="groq/qwen/qwen3.6-27b",
    api_key=groq_key,
    temperature=0.2,
)

groq_ml = LLM(
    model="groq/openai/gpt-oss-20b",
    api_key=groq_key,
    temperature=0.2,
)

# ----------------------------------------------------
# 4. Tools Setup
# ----------------------------------------------------
file_tools = [FileWriterTool(), FileReadTool(), DirectoryReadTool()]

print("YAKSHA AI Multi-LLM System Initialized Successfully...\n")

# ----------------------------------------------------
# 5. Agents Configuration
# ----------------------------------------------------
pm_architect_agent = Agent(
    role="PM & System Architect",
    goal="Turn user requirements into a short, clear step-by-step dev plan without writing code.",
    backstory="Senior Technical Lead expert at planning clean web & ML software architectures.",
    llm=gemini_planner,
    cache=False,
    verbose=True,
)

backend_agent = Agent(
    role="Backend Developer",
    goal="Write robust Python server-side logic and Flask app APIs.",
    backstory="Senior Backend Engineer proficient in Python, Flask, and REST APIs.",
    tools=file_tools,
    llm=groq_backend,
    cache=False,
    verbose=True,
)

frontend_agent = Agent(
    role="Frontend Developer",
    goal="Design clean HTML/CSS/JS code templates for user interfaces.",
    backstory="UI/UX Developer skilled in writing clean HTML and embedded JavaScript.",
    tools=file_tools,
    llm=groq_frontend,
    cache=False,
    verbose=True,
)

ml_agent = Agent(
    role="AI/ML Specialist",
    goal="Develop Machine Learning pipelines and data analysis scripts.",
    backstory="Data Scientist proficient in Pandas and Scikit-Learn.",
    tools=file_tools,
    llm=groq_ml,
    cache=False,
    verbose=True,
)

qa_agent = Agent(
    role="QA Reviewer & Tester",
    goal="Review code for logic and syntax errors, combine components, and save final project files.",
    backstory="Quality Assurance Lead ensuring code is bug-free and properly saved.",
    tools=file_tools,
    llm=gemini_qa,
    cache=False,
    verbose=True,
)

# ----------------------------------------------------
# 6. Tasks (Flask Web App Test Prompt)
# ----------------------------------------------------
USER_PROMPT = """
Create a simple single-file Flask web app with an embedded HTML template that displays
'Welcome to YAKSHA AI Dashboard' and a button that shows a browser alert when clicked.
Save the complete code to 'project_files/app.py'.
"""

task_plan = Task(
    description=(
        f"Analyze requirement: '{USER_PROMPT}' and output a clear execution plan. "
        "IMPORTANT: Do NOT write any actual Python or HTML code here. Keep it to a short "
        "numbered list of steps (max ~100 words)."
    ),
    expected_output="A short numbered step-by-step development plan, no code.",
    agent=pm_architect_agent,
)

task_backend = Task(
    description="Write the Python Flask server setup and route code based on the plan.",
    expected_output="Flask server Python code snippet.",
    agent=backend_agent,
)

task_frontend = Task(
    description="Write the HTML template and inline JavaScript button logic based on the plan.",
    expected_output="HTML and JS UI code snippet.",
    agent=frontend_agent,
)

task_review_and_save = Task(
    description=(
        "Combine the backend and frontend code into a single executable Flask file, "
        "verify for any syntax errors, and use FileWriterTool to save it to 'project_files/app.py'."
    ),
    expected_output="Confirmation of file save.",
    agent=qa_agent,
)

# ----------------------------------------------------
# 7. Crew Setup & Execution
# ----------------------------------------------------
yaksha_crew = Crew(
    agents=[pm_architect_agent, backend_agent, frontend_agent, ml_agent, qa_agent],
    tasks=[task_plan, task_backend, task_frontend, task_review_and_save],
    process=Process.sequential,
    cache=False,
)

if __name__ == "__main__":
    print("Running YAKSHA AI Pipeline...\n")
    result = yaksha_crew.kickoff()
    print("\nExecution Completed Successfully!")
    print("Summary:\n", result)