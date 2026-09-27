<div align="center">

# ⚡ YAKSHA AI (v1.0)

<img width="1024" height="1536" alt="flyer" src="https://github.com/user-attachments/assets/b459b5bb-b0d4-4f60-b4ea-4b42afbe8fe0" />


### Autonomous Multi-Agent Engineering Intelligence & Code Generation Studio

*One prompt in. A production-ready web app out.*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CrewAI](https://img.shields.io/badge/CrewAI-Multi--Agent-FF6F00?style=for-the-badge&logo=robotframework&logoColor=white)](https://www.crewai.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

</div>

---

## 🧠 Overview

**YAKSHA AI** is a fully autonomous, multi-agent software engineering studio. Describe what you want to build in a single natural-language prompt, and a coordinated crew of specialized AI agents — a Project Manager, a Backend Developer, a Frontend Developer, an AI/ML Specialist, and a QA Reviewer — collaborate in sequence to design, write, validate, and ship a **single-file, production-ready web application** (Flask + Tailwind CSS + interactive JS), saved directly to disk at:

```
project_files/app.py
```

No boilerplate. No scaffolding. No manual stitching of files. Just a prompt, a crew, and working code.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A["👤 User Prompt"] --> B["🧭 PM & System Architect Agent<br/>gemini-3.6-flash"]
    B --> C["⚙️ Backend Developer Agent<br/>groq/openai/gpt-oss-120b"]
    C --> D["🎨 Frontend Developer Agent<br/>groq/openai/gpt-oss-120b"]
    D --> E["🧪 QA Reviewer & Tester Agent<br/>gemini-3.6-flash / groq"]
    E --> F["📁 File Output<br/>project_files/app.py"]

    style A fill:#0f172a,stroke:#22d3ee,color:#e2e8f0
    style B fill:#1e1b4b,stroke:#818cf8,color:#e2e8f0
    style C fill:#052e2b,stroke:#2dd4bf,color:#e2e8f0
    style D fill:#3b0764,stroke:#c084fc,color:#e2e8f0
    style E fill:#450a0a,stroke:#f87171,color:#e2e8f0
    style F fill:#082f49,stroke:#38bdf8,color:#e2e8f0
```

> The **AI/ML Specialist Agent** (`groq/openai/gpt-oss-20b`) is engaged dynamically for tasks requiring data science or ML logic within the generated application.

The **Streamlit dashboard** provides real-time, non-blocking execution monitoring via live status containers, while a **FastAPI bridge** connects the UI layer to the underlying CrewAI agent engine.

---

## 🕹️ Agent Roster

| Agent | Role | Model | Responsibility |
|---|---|---|---|
| 🧭 **PM & System Architect** | Planning & Design | `gemini-3.6-flash` | Interprets the user prompt, defines system architecture, and delegates scoped tasks to the crew |
| ⚙️ **Backend Developer** | Server Logic | `groq/openai/gpt-oss-120b` | Builds Flask routes, application logic, and data handling |
| 🎨 **Frontend Developer** | UI/UX | `groq/openai/gpt-oss-120b` | Crafts the Tailwind CSS layout and interactive JavaScript behavior |
| 🤖 **AI/ML Specialist** | Intelligence Layer | `groq/openai/gpt-oss-20b` | Implements ML/data-science logic when the requested app calls for it |
| 🧪 **QA Reviewer & Tester** | Validation & Delivery | `gemini-3.6-flash` / `groq` | Reviews, validates, and executes `FileWriterTool` to persist the final artifact |

---

## ✨ Key Features

- 🚀 **Single-Prompt Code Generation** — Full single-file web applications from one natural-language instruction.
- 🔀 **Multi-LLM Dynamic Routing** — Workload distributed across Gemini and Groq for optimal cost, speed, and context efficiency.
- 📡 **Real-Time Execution Monitoring** — Streamlit dashboard with live workspace status cards and progress indicators.
- 📦 **Autonomous File Artifact Delivery** — Generated code is compiled, validated, and written straight to `project_files/app.py`.
- 🌑 **Cyberpunk Dark Ember UI** — Glassmorphism-styled Streamlit interface built for developer focus.

---

## 🧩 Engineering Highlights (v1.0)

- Resolved multiline JSON escaping issues encountered by `FileWriterTool` during code generation.
- Implemented context token management to stay within Gemini's 250k TPM rate limits.
- Achieved non-blocking Streamlit execution using live status containers for a responsive UI during long-running agent tasks.

---

## 📥 Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/yaksha-ai.git
cd yaksha-ai
```

### 2. Create and activate the Conda environment

```bash
conda create -n yaksha_env python=3.11 -y
conda activate yaksha_env
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

---

## ▶️ Usage

### Option A — Launch the Streamlit Dashboard

```bash
streamlit run app_dashboard.py
```

Open the local URL shown in your terminal, enter your prompt, and watch the crew work in real time.

### Option B — Run via CLI

```bash
python main.py --prompt "Build a habit tracker with streak analytics"
```

### Option C — Run the generated application

Once YAKSHA AI finishes, your app is ready at `project_files/app.py`:

```bash
cd project_files
python app.py
```

Then open `http://localhost:5000` in your browser.

---

## 🗺️ Roadmap — YAKSHA AI v2.0

- [ ] Multi-file project output (`backend/`, `frontend/`, `models/`)
- [ ] Real-time WebSocket terminal log streaming
- [ ] Human-in-the-loop interactive plan approvals
- [ ] Dynamic task routing based on domain complexity

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

Built with ⚡ by the YAKSHA AI crew — humans and agents, working in sequence.

</div>
