import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text  # Required for SQL execution

# --- Page Config ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# --- FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .stTable { color: #000000 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

# --- SQL Helper Functions ---
def get_items(table, column):
    try:
        query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
        df = conn.query(query, ttl="2s")
        return df[column].dropna().tolist()
    except:
        return []

def add_item(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value})
        s.commit()

def delete_item(table, column, value):
    with conn.session as s:
        query = text(f"DELETE FROM {table} WHERE {column} = :val;")
        s.execute(query, {"val": value})
        s.commit()

# --- Main Admin UI ---
try:
    st.image("80x68.png", width=100)
except:
    st.info("Akademi Sains Malaysia")

st.title("🛡️ Admin Control Center")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

# --- TAB 1 & 2: Lists Management ---
with tab1:
    st.subheader("Manage Proposals")
    p_input = st.text_input("New Proposal Title", key="new_prop")
    if st.button("Add Proposal"):
        if p_input: 
            add_item("proposals", "title", p_input)
            st.rerun()
    
    props = get_items("proposals", "title")
    for p in props:
        c1, c2 = st.columns([6, 1])
        c1.write(f"• {p}")
        if c2.button("🗑️", key=f"del_p_{p}"):
            delete_item("proposals", "title", p)
            st.rerun()

with tab2:
    st.subheader("Manage Evaluators")
    e_input = st.text_input("New Evaluator Name", key="new_eval")
    if st.button("Add Evaluator"):
        if e_input: 
            add_item("evaluators", "name", e_input)
            st.rerun()
            
    evals = get_items("evaluators", "name")
    for e in evals:
        c1, c2 = st.columns([6, 1])
        c1.write(f"• {e}")
        if c2.button("🗑️", key=f"del_e_{e}"):
            delete_item("evaluators", "name", e)
            st.rerun()

# --- TAB 3: Link Generator ---
with tab3:
    st.subheader("Personalized Access Links")
    if evals:
        base_url = st.text_input("Application Base URL", value="https://your-app.streamlit.app").rstrip('/')
        copy_text = "📋 *ASM EVALUATOR LINKS*\n\n"
        link_data = []
        for i, name in enumerate(evals):
            link = f"{base_url}/?user={i}"
            copy_text += f"👤 {name}:\n🔗 {link}\n\n"
            link_data.append({"Evaluator": name, "URL": link})
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        st.text_area("Copy-Paste Block", value=copy_text, height=200)

st.divider()

# --- Executive Summary & Tracker ---
st.header("📊 Executive Summary")
try:
    df_scores = conn.query("SELECT * FROM scores;", ttl="2s")
except:
    df_scores = pd.DataFrame()

if not df_scores.empty:
    with st.expander("👀 View Global Performance Summary", expanded=True):
        numeric_cols = df_scores.select_dtypes(include=['number']).columns
        grand_means = df_scores[numeric_cols].mean().round(2)
        st.table(grand_means.rename("Average Score"))
        st.dataframe(df_scores, use_container_width=True)

# --- Session Control (Archive) ---
st.header("🚀 Session Control")
archive_name = st.text_input("Session Tag (e.g. Batch 1)")
if st.button("🆕 Archive & Reset Dashboard", type="primary"):
    if not df_scores.empty and archive_name:
        with conn.session as s:
            s.execute(text("""
                INSERT INTO history (archive_tag, evaluator, proposal_title, total, recommendation, comments, last_updated)
                SELECT :tag, evaluator, proposal_title, total, recommendation, comments, last_updated FROM scores;
            """), {"tag": archive_name})
            s.execute(text("DELETE FROM scores;"))
            s.commit()
        st.balloons()
        st.rerun()
