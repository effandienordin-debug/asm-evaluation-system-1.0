import streamlit as st
import pandas as pd
import os
from sqlalchemy import text
from datetime import datetime

# --- Config & Folder Setup ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")
UPLOAD_DIR = "evaluator_photos"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

# --- CSS Styling ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    div[data-testid="stExpander"] { background-color: #F8F9FA; border: 1px solid #E5E7EB; }
    </style>
    """, unsafe_allow_html=True)

# --- Helper Functions ---
def get_items_sql(table, column):
    try:
        query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
        df = conn.query(query, ttl=0) 
        return df[column].dropna().tolist()
    except:
        return []

def add_item_sql(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value})
        s.commit()

# --- Dialogs ---
@st.dialog("⚠️ Confirm Deletion")
def confirm_delete_dialog(table, column, value, label):
    st.write(f"Delete **'{value}'** from {label}?")
    if st.button("Confirm Delete", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val;"), {"val": value})
            s.commit()
        # Delete photo if it exists
        photo_path = os.path.join(UPLOAD_DIR, f"{value.replace(' ', '_')}.png")
        if table == "evaluators" and os.path.exists(photo_path):
            os.remove(photo_path)
        st.rerun()

# --- Main UI ---
st.title("🛡️ ASM Admin Control Center")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

# --- TAB 1: PROPOSALS (With Bulk Add) ---
with tab1:
    st.subheader("Manage Proposals")
    mode = st.radio("Add Mode (Proposals)", ["Single", "Bulk"], horizontal=True)
    
    if mode == "Single":
        p_name = st.text_input("Proposal Title", key="p_single")
        if st.button("Add Proposal"):
            if p_name:
                add_item_sql("proposals", "title", p_name)
                st.rerun()
    else:
        bulk_p = st.text_area("Paste Proposals (one per line)")
        if st.button("Bulk Add Proposals"):
            for item in bulk_p.split('\n'):
                if item.strip(): add_item_sql("proposals", "title", item.strip())
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"View Proposals ({len(props)})"):
        for p in props:
            c1, c2 = st.columns([6, 1])
            c1.write(f"• {p}")
            if c2.button("🗑️", key=f"del_p_{p}"):
                confirm_delete_dialog("proposals", "title", p, "Proposals")

# --- TAB 2: EVALUATORS (With Image Upload) ---
with tab2:
    st.subheader("Manage Evaluators")
    e_name = st.text_input("Evaluator Name")
    e_photo = st.file_uploader("Upload Profile Photo", type=['png', 'jpg', 'jpeg'])
    
    if st.button("Add Evaluator", type="primary"):
        if e_name:
            add_item_sql("evaluators", "name", e_name)
            if e_photo:
                path = os.path.join(UPLOAD_DIR, f"{e_name.replace(' ', '_')}.png")
                with open(path, "wb") as f:
                    f.write(e_photo.getbuffer())
            st.success(f"Added {e_name}")
            st.rerun()

    evals = get_items_sql("evaluators", "name")
    with st.expander(f"View Evaluators ({len(evals)})"):
        for e in evals:
            c1, c2, c3 = st.columns([1, 5, 1])
            img_path = os.path.join(UPLOAD_DIR, f"{e.replace(' ', '_')}.png")
            if os.path.exists(img_path):
                c1.image(img_path, width=40)
            else:
                c1.write("👤")
            c2.write(e)
            if c3.button("🗑️", key=f"del_e_{e}"):
                confirm_delete_dialog("evaluators", "name", e, "Evaluators")

# --- TAB 3: LINKS ---
with tab3:
    st.subheader("Access Links")
    base_url = st.text_input("App URL", value="https://your-app.streamlit.app").rstrip('/')
    evals_list = get_items_sql("evaluators", "name")
    link_data = []
    for i, name in enumerate(evals_list):
        url = f"{base_url}/?user={i}"
        link_data.append({"Name": name, "Link": url})
    st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
