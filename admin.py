import streamlit as st
import pandas as pd
import time
import qrcode
import re
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

def load_secret(key):
    if key in st.secrets:
        return st.secrets[key]
    st.error(f"❌ Missing Secret: **{key}**")
    st.stop()

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"

# --- 3. INITIALIZE CLIENTS (Moved up for Auth) ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase Connection Error.")

conn = st.connection("postgresql", type="sql")

# --- 2. UPDATED LOGIN LOGIC ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin Access</h1>", unsafe_allow_html=True)
        _, center, _ = st.columns([1, 1.5, 1])
        
        with center:
            with st.form("login_form"):
                u_input = st.text_input("Username")
                p_input = st.text_input("Password", type="password")
                submit = st.form_submit_button("Sign In", use_container_width=True)
                
                if submit:
                    # FIX: Use a plain string instead of text("...")
                    query = "SELECT username, password_hash, role FROM users WHERE username = :u"
                    
                    # conn.query handles the :u parameter binding safely
                    user_data = conn.query(query, params={"u": u_input}, ttl=0)
                    
                    if not user_data.empty and user_data.iloc[0]['password_hash'] == p_input:
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = user_data.iloc[0]['username']
                        st.session_state["user_role"] = user_data.iloc[0]['role']
                        st.rerun()
                    else:
                        st.error("Invalid username or password")
        return False
    return True

# --- 4. THEME & CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px; min-height: 140px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 5. DIALOGS ---

@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("Edit Proposal Title", value=old_val)
    if st.button("Update Title", type="primary"):
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :new WHERE title = :old"), {"new": new_val.strip(), "old": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :new WHERE proposal_title = :old"), {"new": new_val.strip(), "old": old_val})
            s.commit()
        st.rerun()

@st.dialog("🔑 Add System User")
def add_user_dialog():
    new_un = st.text_input("New Username")
    new_pw = st.text_input("New Password", type="password")
    new_role = st.selectbox("Role", ["SuperAdmin", "Editor", "Viewer"])
    if st.button("Create User", type="primary"):
        with conn.session as s:
            s.execute(text("INSERT INTO users (username, password_hash, role) VALUES (:u, :p, :r)"),
                      {"u": new_un.strip(), "p": new_pw.strip(), "r": new_role})
            s.commit()
        st.success("User added!")
        st.rerun()

# --- 6. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except: return []

# --- 7. SIDEBAR NAVIGATION ---
cache_buster = int(time.time())

with st.sidebar:
    st.title("🛡️ ASM Admin")
    st.write(f"Logged in: **{st.session_state['username']}**")
    st.caption(f"Role: {st.session_state['user_role']}")
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()
    
    st.divider()
    auto_refresh = st.toggle("🔄 Auto Refresh (15s)", value=False)
    if auto_refresh: st_autorefresh(interval=15000, key="admin_refresh")
    
    menu_list = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state["user_role"] == "SuperAdmin":
        menu_list.append("🔑 User Management")
        
    menu_choice = st.radio("Navigate to:", menu_list)
    
    # --- SESSION CONTROL (Restricted to SuperAdmin/Editor) ---
    if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
        st.divider()
        st.subheader("🚀 Session Control")
        force_mode = st.toggle("⚠️ Enable Force Archive")
        if st.button("🆕 Archive & Reset", type="primary", use_container_width=True, disabled=not force_mode):
            with conn.session as s:
                s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
                s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
                s.commit()
            st.balloons()
            st.rerun()

# --- 8. MAIN CONTENT AREA ---

if menu_choice == "📊 Tracker":
    st.header("📊 Live Proposal Progress")
    # ... (Same logic as original Tracker)
    try:
        df_scores = conn.query("SELECT * FROM scores;", ttl=0)
        evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
        props_all = get_items_sql("proposals", "title")
        
        total_required = len(props_all) * len(evals_df)
        current_subs = len(df_scores) if not df_scores.empty else 0
        
        if total_required > 0:
            st.progress(min(current_subs / total_required, 1.0))
            st.write(f"**Progress:** {current_subs} / {total_required}")
            
        # Evaluator status cards logic...
        # [Insert original card loops here]
    except Exception as e: st.error(f"Tracker Load Error: {e}")

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
    if st.session_state["user_role"] == "Viewer":
        st.info("View-only access.")
    else:
        p_name = st.text_input("Add Proposal Title")
        if st.button("Add Single"):
            if p_name: 
                with conn.session as s:
                    s.execute(text("INSERT INTO proposals (title) VALUES (:v)"), {"v": p_name.strip()})
                    s.commit()
                st.rerun()

    props = get_items_sql("proposals", "title")
    for p in props:
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.write(f"• {p}")
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c2.button("✏️", key=f"edit_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "🔑 User Management":
    st.header("🔑 System Admin Users")
    if st.button("➕ Add New User"):
        add_user_dialog()
    
    users_df = conn.query("SELECT id, username, role FROM users ORDER BY username ASC;", ttl=0)
    st.dataframe(users_df, use_container_width=True)
    
    # Simple Delete User
    target_un = st.selectbox("Select user to remove", users_df['username'])
    if st.button("🗑️ Remove User", type="secondary"):
        if target_un == st.session_state["username"]:
            st.error("Cannot delete yourself!")
        else:
            with conn.session as s:
                s.execute(text("DELETE FROM users WHERE username = :u"), {"u": target_un})
                s.commit()
            st.rerun()

# [Include original logic for "👤 Evaluators & Links" and "📜 History" here]

