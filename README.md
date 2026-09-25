# 👺 YAKSHA AI (v1.0)
> **Autonomous Multi-Agent Engineering Intelligence & Code Generation Studio**

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-CrewAI-red.svg)](https://www.crewai.com/)
[![Backend](https://img.shields.io/badge/backend-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/frontend-Streamlit-orange.svg)](https://streamlit.io/)
[![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](LICENSE)

YAKSHA AI is an autonomous, end-to-end multi-agent orchestration engineering studio powered by **CrewAI**, **FastAPI**, and **Streamlit**[cite: 1, 2, 3]. It translates single natural language system prompts into complete, production-ready, executable single-file web applications (Flask + Tailwind CSS + Interactive JS) saved directly to your disk.

---

## 🏛 System Architecture & Workflow

YAKSHA AI delegates software engineering tasks across a specialized panel of intelligent AI agents, balancing high performance with strict rate-limit management:

```mermaid
graph TD
    A[User Prompt Input] -->|Streamlit Dashboard| B(PM & System Architect Agent)
    B -->|System Plan & Specifications| C(Backend Developer Agent)
    C -->|Flask Server & API Logic| D(Frontend Developer Agent)
    D -->|Tailwind CSS & UI Logic| E(AI/ML Specialist Agent)
    E -->|Data Pipeline / ML Logic| F(QA Reviewer & Tester Agent)
    F -->|Assembly & Validation| G[project_files/app.py]


    | Agent Role | Model Provider | Responsibilities |
| :--- | :--- | :--- |
| **PM Architect** | `gemini-3.6-flash` | Analyzes requirements, breaks down user tasks into execution plans. |
| **Backend Dev** | `groq/gpt-oss-120b` | Builds Flask routing, endpoint structure, and core logic. |
| **Frontend Dev** | `groq/gpt-oss-120b` | Generates modern responsive Tailwind CSS & JS single-page layouts. |
| **AI/ML Specialist** | `groq/gpt-oss-20b` | Integrates data processing pipelines and ML evaluation blocks. |
| **QA Tester** | `gemini-3.6-flash` / `groq` | Code assembly, syntax verification, and `FileWriterTool` execution. |


✨ Key FeaturesSingle-Prompt Code Generation: Generates complete single-file executable web applications.   Real-time Pipeline Monitoring: Cyberpunk Dark Ember themed Streamlit dashboard with workspace execution status.   Multi-LLM Provider Failover: Uses dynamic model routing across Gemini and Groq APIs for cost and speed optimization.   Autonomous Disk Artifact Delivery: Automatically verifies and writes functional code blocks into project_files/app.py[cite: 1].

🚀 Getting StartedPrerequisitesPython 3.10+Conda or Virtual Environment toolAPI Keys: Gemini API Key & Groq API Key   

InstallationClone the repository:Bashgit clone [https://github.com/1NirmalAlex/YAKSHA_AI.git](https://github.com/1NirmalAlex/YAKSHA_AI.git)
cd YAKSHA_AI
Set up virtual environment:Bashconda create -n yaksha_env python=3.10 -y
conda activate yaksha_env
Install dependencies:Bashpip install -r requirements.txt
Configure Environment Variables:
Create a .env file in the root directory:   Code snippetGEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
💻 Running YAKSHA AIOption 1: Run via Streamlit UI Dashboard (Recommended)Bashstreamlit run dashboard.py
Open your browser at http://localhost:8501 to access the interactive orchestration dashboard.   Option 2: Run via CLI DirectlyBashpython app.py
Option 3: Run generated project outputBashcd project_files
python app.py
Open your browser at http://localhost:5000 to view the generated web app.   


🛠 Engineering Challenges & Solutions (v1.0)Tool Call JSON Escaping: Resolved JSON parsing errors with multiline code escaping in FileWriterTool[cite: 1].Token Rate Limiting: Implemented context splitting between agents to bypass Gemini 250k TPM rate limits.UI Non-blocking Pipeline: Leveraged status containers in Streamlit to keep UI reactive during heavy CrewAI execution loops.   🔮 Roadmap (YAKSHA AI v2.0)[ ] Multi-file structured project code output (backend/, frontend/, models/).[ ] Real-time WebSocket terminal log streaming.[ ] Human-in-the-loop plan review & interactive approval steps.[ ] Dynamic task routing based on prompt domain complexity.📄 LicenseThis project is licensed under the MIT License - see the LICENSE file for details.
Ee markdown code-annu nimma project-nalla `README.md` file create maadi save maadi. Git add
