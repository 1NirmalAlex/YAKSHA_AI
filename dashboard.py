"""
YAKSHA AI - Next-Gen Studio Dashboard (Premium Dark/Ember Theme)
Autonomous Multi-Agent Engineering Intelligence & Interactive Studio Interface
"""

import streamlit as st
import sys
import os
import time

# Page Configuration
st.set_page_config(
    page_title="YAKSHA AI - Multi-Agent Studio",
    page_icon="👹",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Session States for Interactive Workspaces
if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False
if "agent_logs" not in st.session_state:
    st.session_state.agent_logs = {
        "PM Architect": [],
        "Backend Dev": [],
        "Frontend Dev": [],
        "AI/ML Specialist": [],
        "QA Tester": []
    }
if "chat_history" not in st.session_state:
    st.session_state.chat_history = {
        "PM Architect": [],
        "Backend Dev": [],
        "Frontend Dev": [],
        "AI/ML Specialist": [],
        "QA Tester": []
    }

# Premium Custom CSS (Cyber-Yaksha Aesthetic + Glassmorphism)
st.markdown("""
<style>
    /* Dark Cyberpunk Ambient Background */
    .stApp {
        background: radial-gradient(circle at 50% 20%, #170B0E 0%, #0B0C10 60%, #050508 100%);
        color: #FFFFFF;
        font-family: 'Inter', sans-serif;
    }

    /* Subtle Animated Glow Effect */
    @keyframes yakshaGlow {
        0% { box-shadow: 0 0 15px rgba(255, 87, 34, 0.15); }
        50% { box-shadow: 0 0 30px rgba(255, 87, 34, 0.35); }
        100% { box-shadow: 0 0 15px rgba(255, 87, 34, 0.15); }
    }

    /* Centered Header Title */
    .centered-header {
        text-align: center;
        padding: 20px 0 30px 0;
        border-bottom: 1px solid rgba(255, 87, 34, 0.2);
        margin-bottom: 30px;
    }
    .main-title {
        font-size: 42px;
        font-weight: 900;
        letter-spacing: 2px;
        background: linear-gradient(90deg, #FFFFFF 0%, #FF5722 50%, #FF6B00 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
        text-transform: uppercase;
    }
    .sub-title {
        color: #A0A0A0;
        font-size: 14px;
        margin-top: 8px;
        letter-spacing: 1px;
    }

    /* ChatGPT Style Floating Input Box Container */
    .chat-container {
        background: rgba(18, 19, 28, 0.7);
        border: 1px solid #2A2D3D;
        border-radius: 20px;
        padding: 20px;
        backdrop-filter: blur(16px);
        margin-bottom: 30px;
        animation: yakshaGlow 6s infinite ease-in-out;
    }

    /* Custom Button Styling */
    .stButton>button {
        background: linear-gradient(90deg, #FF5722 0%, #FF6B00 100%) !important;
        color: white !important;
        font-weight: 800 !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 12px 24px !important;
        box-shadow: 0 4px 20px rgba(255, 87, 34, 0.4) !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 25px rgba(255, 87, 34, 0.7) !important;
    }

    /* Agent Card Layout */
    .agent-status-card {
        background: rgba(18, 19, 28, 0.8);
        border: 1px solid #2A2D3D;
        border-radius: 16px;
        padding: 18px;
        text-align: center;
        transition: all 0.3s ease;
    }
    .agent-status-card:hover {
        border-color: #FF5722;
        transform: translateY(-3px);
    }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: bold;
        margin-top: 8px;
    }
    .badge-idle { background: rgba(255, 255, 255, 0.1); color: #888; }
    .badge-active { background: rgba(255, 87, 34, 0.2); color: #FF5722; border: 1px solid #FF5722; }

    /* Progress & Metrics Box */
    .metrics-card {
        background: rgba(12, 13, 20, 0.9);
        border: 1px solid #2A2D3D;
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 25px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# 1. Centered Header Section
# ----------------------------------------------------
st.markdown("""
<div class="centered-header">
    <div style="font-size: 38px; margin-bottom: 5px;">👹</div>
    <h1 class="main-title">YAKSHA AI DASHBOARD</h1>
    <p class="sub-title">Autonomous Multi-Agent Engineering Intelligence & Code Generation Studio</p>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# 2. Modern ChatGPT-Style Input & Upload Section
# ----------------------------------------------------
st.markdown("### 💬 Enter Project Prompt Instructions")

with st.container():
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    
    col_input, col_file = st.columns([3, 1])
    
    with col_input:
        user_prompt = st.text_area(
            label="Prompt Input",
            placeholder="e.g. Create a modern web calculator interface...",
            height=120,
            label_visibility="collapsed"
        )
    
    with col_file:
        st.markdown("**📁 Attach Context Files**")
        uploaded_files = st.file_uploader(
            "Upload docs/images",
            type=["png", "jpg", "jpeg", "pdf", "txt", "py", "json"],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        if uploaded_files:
            st.caption(f"📎 Attached {len(uploaded_files)} file(s)")

    col_btn, col_space = st.columns([1, 3])
    with col_btn:
        run_btn = st.button("🚀 EXECUTE FULL PIPELINE", use_container_width=True)
        
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ----------------------------------------------------
# 3. Agents Workspace Status Grid (5 Cards)
# ----------------------------------------------------
st.markdown("### 🤖 Agents Workspace Status")

c1, c2, c3, c4, c5 = st.columns(5)

agents_info = [
    ("📐 PM Architect", "System Planner", "gemini-3.6-flash", c1),
    ("⚙️ Backend Dev", "Python & APIs", "gpt-oss-120b", c2),
    ("🎨 Frontend Dev", "UI/UX Logic", "gpt-oss-120b", c3),
    ("🧠 AI/ML Specialist", "Data Pipelines", "gpt-oss-20b", c4),
    ("🛡️ QA Tester", "Code Audit", "gpt-oss-120b", c5),
]

for name, role, model, col in agents_info:
    with col:
        badge_class = "badge-idle"
        status_text = "IDLE"
        if st.session_state.pipeline_running:
            badge_class = "badge-active"
            status_text = "WORKING..."
            
        st.markdown(f"""
        <div class="agent-status-card">
            <div style="font-weight: 800; color: #FF5722; font-size: 15px;">{name}</div>
            <div style="color: #A0A0A0; font-size: 12px; margin-top: 2px;">{role}</div>
            <div style="color: #666; font-size: 11px; margin-top: 4px;"><code>{model}</code></div>
            <span class="status-badge {badge_class}">● {status_text}</span>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ----------------------------------------------------
# 4. Overall Execution Pipeline Dashboard
# ----------------------------------------------------
st.markdown("### 📊 Live Pipeline Progress Dashboard")

with st.container():
    st.markdown('<div class="metrics-card">', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    
    with m1:
        st.metric(label="System Status", value="Ready" if not st.session_state.pipeline_running else "Executing", delta="Operational")
    with m2:
        st.metric(label="Active Agents", value="5 Multi-LLMs")
    with m3:
        st.metric(label="Target File", value="project_files/app.py")
    with m4:
        st.metric(label="Estimated Completion", value="~45 Seconds")
        
    progress_bar = st.progress(0)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ----------------------------------------------------
# 5. Individual Agent Workspaces & Direct Chat Tabs
# ----------------------------------------------------
st.markdown("### 🔬 Agent Workspaces & Direct Interactive Studio")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📐 PM Architect Workspace",
    "⚙️ Backend Dev Workspace",
    "🎨 Frontend Dev Workspace",
    "🧠 AI/ML Specialist Workspace",
    "🛡️ QA Tester Workspace"
])

agent_tabs = [
    ("PM Architect", tab1),
    ("Backend Dev", tab2),
    ("Frontend Dev", tab3),
    ("AI/ML Specialist", tab4),
    ("QA Tester", tab5)
]

for agent_name, tab in agent_tabs:
    with tab:
        col_logs, col_chat = st.columns([3, 2])
        
        with col_logs:
            st.subheader(f"📜 {agent_name} Workspace Activity Log")
            log_container = st.empty()
            if st.session_state.agent_logs[agent_name]:
                log_container.code("\n".join(st.session_state.agent_logs[agent_name]), language="python")
            else:
                log_container.info(f"No active execution logs for {agent_name} yet. Run the pipeline to stream activity.")
                
        with col_chat:
            st.subheader(f"💬 Direct Chat with {agent_name}")
            chat_box = st.container(height=220)
            
            # Display Agent Chat History
            for msg in st.session_state.chat_history[agent_name]:
                with chat_box.chat_message(msg["role"]):
                    st.write(msg["content"])
                    
            direct_msg = st.chat_input(f"Assign specific sub-task to {agent_name}...", key=f"chat_{agent_name}")
            if direct_msg:
                st.session_state.chat_history[agent_name].append({"role": "user", "content": direct_msg})
                st.session_state.chat_history[agent_name].append({
                    "role": "assistant",
                    "content": f"[{agent_name}] Understood! Processing sub-instruction: '{direct_msg}'"
                })
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ----------------------------------------------------
# 6. Execution Terminal & Live Pipeline Runner
# ----------------------------------------------------
st.markdown("### 🖥️ Execution Terminal & Project Artifacts")

if run_btn:
    if not user_prompt.strip():
        st.warning("⚠️ Please enter a prompt instruction before running!")
    else:
        st.session_state.pipeline_running = True
        
        with st.status("👹 YAKSHA AI Multi-Agent Pipeline Executing...", expanded=True) as status:
            try:
                status.write("1️⃣ Initializing Agents & Loading Sub-modules...")
                progress_bar.progress(15)
                
                # Import dynamic pipeline runner from app.py
                from app import run_pipeline
                
                status.write("2️⃣ PM Architect planning execution steps...")
                progress_bar.progress(35)
                
                status.write("3️⃣ Developers generating Backend, Frontend UI & Integration...")
                progress_bar.progress(65)
                
                # Execute CrewAI Pipeline
                execution_result = run_pipeline(user_prompt)
                
                progress_bar.progress(100)
                st.session_state.pipeline_running = False
                status.update(label="✅ YAKSHA AI Pipeline Completed Successfully!", state="complete", expanded=True)
                
                st.balloons()
                st.success("🎉 Code successfully generated and saved to 'project_files/app.py'!")
                
                st.markdown("### 📄 Generated Artifact Output Summary")
                st.code(str(execution_result), language="python")

            except Exception as e:
                st.session_state.pipeline_running = False
                progress_bar.progress(0)
                status.update(label="❌ Pipeline Execution Failed!", state="error", expanded=True)
                st.error(f"Execution Error: {type(e).__name__}: {str(e)}")