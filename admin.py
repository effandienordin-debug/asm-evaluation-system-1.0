import streamlit as st
import pandas as pd
import time
import re
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
import extra_streamlit_components as stx

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")
cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")
BLANK_ICON = "https://cdn-icons-png.flaticon.com/512/149/149071.png"

try:
    cookie_manager = stx.CookieManager(key="main_cookie_manager")
except Exception:
    cookie_manager = None

# Session States
for key, val in [("authenticated", False), ("username", None), ("user_role", "Viewer"), ("logout_clicked", False)]:
    if key not in st.session_state: st.session_state[key] = val

def load_secret(key):
    if key in st.secrets: return st.secrets[key]
    st.error(f"❌ Missing Secret: **{key}**"); st.stop()

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"
conn = st.connection("postgresql", type="sql")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except Exception as e:
        return []

# --- 3. DIALOGS (New & Updated) ---
@st.dialog("📚 Bulk Add & Assign Applicants")
def bulk_add_applicants_dialog():
    evaluators = get_items_sql("evaluators", "name")
    st.markdown("**Format:** `Applicant Name, Proposal Title` (One per line)")
    target_eval = st.selectbox("Assign to Evaluator:", evaluators)
    raw_data = st.text_area("List", height=200)
    
    if st.button("Import and Assign", type="primary"):
        lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
        with conn.session as s:
            for line in lines:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2:
                    app, title = parts[0], parts[1]
                    s.execute(text("INSERT INTO proposals (title) VALUES (:t) ON CONFLICT DO NOTHING"), {"t": title})
                    s.execute(text("INSERT INTO applicant_assignments (applicant_name, evaluator_name) VALUES (:a, :e) ON CONFLICT DO NOTHING"), {"a": app, "e": target_eval})
            s.commit()
        st.success("Assigned Successfully!"); time.sleep(1); st.rerun()

@st.dialog("🔗 Assign Applicant")
def assign_single_dialog(app_name):
    evaluators = get_items_sql("evaluators", "name")
    selected = st.multiselect("Evaluators:", evaluators)
    if st.button("Update"):
        with conn.session as s:
            s.execute(text("DELETE FROM applicant_assignments WHERE applicant_name = :a"), {"a": app_name})
            for e in selected:
                s.execute(text("INSERT INTO applicant_assignments (applicant_name, evaluator_name) VALUES (:a, :e)"), {"a": app_name, "e": e})
            s.commit()
        st.rerun()

# --- 4. NAVIGATION ---
with st.sidebar:
    st.title("🛡️ ASM Admin")
    menu_options = ["📊 Tracker", "👥 Applicants", "📋 Proposals", "👤 Evaluators", "📜 History"]
    if st.session_state["user_role"] == "SuperAdmin": menu_options.append("🔑 Users")
    menu_choice = st.radio("Navigation", menu_options)
    
    if st.button("🚪 Logout"):
        st.session_state["logout_clicked"] = True
        if cookie_manager: cookie_manager.delete("asm_admin_user")
        st.session_state.clear(); st.rerun()

# --- 5. MAIN CONTENT ---
if menu_choice == "👥 Applicants":
    st.header("👥 Applicant Management")
    if st.session_state["user_role"] != "Viewer":
        if st.button("📚 Bulk Add & Assign"): bulk_add_applicants_dialog()
    
    st.divider()
    query = "SELECT applicant_name, string_agg(evaluator_name, ', ') as assigned_to FROM applicant_assignments GROUP BY applicant_name"
    df = conn.query(query, ttl=0)
    for idx, row in df.iterrows():
        c1, c2, c3 = st.columns([3, 4, 1])
        c1.write(f"👤 **{row['applicant_name']}**")
        c2.caption(f"Reviewer: {row['assigned_to']}")
        if c3.button("⚙️", key=f"edit_a_{idx}"): assign_single_dialog(row['applicant_name'])

# (Note: Tracker, Proposals, Evaluators sections remain same as your provided code)
