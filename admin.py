import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

# --- IMPROVED: SQL Helper Function (Removed ttl to ensure fresh data) ---
def get_items(table, column):
    try:
        # Setting ttl="0" ensures Streamlit doesn't show old cached data
        query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
        df = conn.query(query, ttl="0") 
        return df[column].dropna().tolist()
    except:
        return []

# --- IMPROVED: Delete Dialog ---
@st.dialog("⚠️ Confirm Deletion")
def confirm_delete_dialog(table, column, value, label):
    st.warning(f"Are you sure you want to delete **'{value}'** from {label}?")
    if st.button("Confirm Delete", type="primary", use_container_width=True):
        with conn.session as s:
            query = text(f"DELETE FROM {table} WHERE {column} = :val;")
            s.execute(query, {"val": value})
            s.commit()
        
        st.toast(f"🗑️ Deleted: {value}")
        # This is the most important line to fix your "list still there" issue
        st.rerun() 

# --- IMPROVED: Add Functions ---
def handle_add_proposal():
    val = st.session_state.new_prop.strip()
    if val:
        with conn.session as s:
            query = text("INSERT INTO proposals (title) VALUES (:val) ON CONFLICT DO NOTHING;")
            s.execute(query, {"val": val})
            s.commit()
        st.toast(f"✅ Added Proposal: {val}")
        st.session_state.new_prop = "" # Clear box
        # st.rerun() is handled automatically by Streamlit on state change in callbacks

def handle_add_evaluator():
    val = st.session_state.new_eval.strip()
    if val:
        with conn.session as s:
            query = text("INSERT INTO evaluators (name) VALUES (:val) ON CONFLICT DO NOTHING;")
            s.execute(query, {"val": val})
            s.commit()
        st.toast(f"✅ Added Evaluator: {val}")
        st.session_state.new_eval = "" # Clear box

# --- UI Layout ---
tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

with tab1:
    st.subheader("Manage Proposals")
    st.text_input("New Proposal Title", key="new_prop")
    st.button("Add Proposal", on_click=handle_add_proposal)
    
    # Fetching inside the tab ensures it runs every time the tab is clicked
    props = get_items("proposals", "title")
    for p in props:
        c1, c2 = st.columns([6, 1])
        c1.write(f"• {p}")
        if c2.button("🗑️", key=f"del_p_{p}"):
            confirm_delete_dialog("proposals", "title", p, "Proposals")

with tab2:
    st.subheader("Manage Evaluators")
    st.text_input("New Evaluator Name", key="new_eval")
    st.button("Add Evaluator", on_click=handle_add_evaluator)
            
    evals = get_items("evaluators", "name")
    for e in evals:
        c1, c2 = st.columns([6, 1])
        c1.write(f"• {e}")
        if c2.button("🗑️", key=f"del_e_{e}"):
            confirm_delete_dialog("evaluators", "name", e, "Evaluators")
