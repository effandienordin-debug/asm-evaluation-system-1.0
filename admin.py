import streamlit as st
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-anon-key"
BUCKET_NAME = "evaluator-photos"

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Connection Error: Check Supabase Credentials.")

conn = st.connection("postgresql", type="sql")

# --- 2. DIALOGS (The missing Pop-ups) ---
@st.dialog("🗑️ Confirm Deletion")
def confirm_delete_item(table, column, value):
    st.write(f"Are you sure you want to delete **{value}** from {table}?")
    if st.button("Confirm Delete", type="primary"):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :v"), {"v": value})
            s.commit()
        st.success(f"Deleted {value}")
        time.sleep(1) # Small delay to see success
        st.rerun()

# --- 3. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except: return []

def add_item_sql(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value})
        s.commit()

# --- 4. UI SETUP ---
st.title("🛡️ ASM Admin Control Center")

col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=False)
if auto_refresh:
    st_autorefresh(interval=10000, key="admin_refresh")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

# --- TAB 1: PROPOSALS ---
with tab1:
    st.subheader("Manage Proposals")
    p_name = st.text_input("Proposal Title", key="p_input")
    if st.button("Add Proposal"):
        if p_name:
            add_item_sql("proposals", "title", p_name.strip())
            st.toast(f"Added: {p_name}") # Non-intrusive pop-up
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"🔍 View Proposals ({len(props)})"):
        for p in props:
            c1, c2 = st.columns([6, 1])
            c1.write(f"• {p}")
            if c2.button("🗑️", key=f"del_p_{p}"):
                confirm_delete_item("proposals", "title", p)

# --- TAB 2: EVALUATORS ---
with tab2:
    st.subheader("Manage Evaluators")
    with st.form("eval_form", clear_on_submit=True):
        e_name = st.text_input("Evaluator Full Name")
        e_photo = st.file_uploader("Upload Photo", type=['png', 'jpg'])
        if st.form_submit_button("Add Evaluator", type="primary"):
            if e_name:
                add_item_sql("evaluators", "name", e_name.strip())
                if e_photo:
                    file_path = f"{e_name.strip().replace(' ', '_')}.png"
                    supabase.storage.from_(BUCKET_NAME).upload(
                        path=file_path, file=e_photo.getvalue(),
                        file_options={"content-type": "image/png", "x-upsert": "true"}
                    )
                st.rerun()

    evals = get_items_sql("evaluators", "name")
    # Cache Buster: Adding a timestamp so browser realizes the image updated
    ts = int(time.time()) 
    
    with st.expander(f"🔍 View Evaluators ({len(evals)})"):
        for e in evals:
            c1, c2, c3 = st.columns([1, 5, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={ts}"
            c1.image(img_url, width=40)
            c2.write(e)
            if c3.button("🗑️", key=f"del_e_{e}"):
                confirm_delete_item("evaluators", "name", e)

# --- TAB 3: LINKS ---
with tab3:
    eval_list = get_items_sql("evaluators", "name")
    if eval_list:
        base_url = st.text_input("App URL", value="http://localhost:8501").rstrip('/')
        link_data = [{"Evaluator": n, "Link": f"{base_url}/?user={i}"} for i, n in enumerate(eval_list)]
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)

# --- 6. TRACKER ---
st.divider()
st.header("📊 Tracker")
df = conn.query("SELECT * FROM scores;", ttl=0)
unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []

if evals:
    cols = st.columns(4)
    for i, name in enumerate(evals):
        is_done = name in unique_submitted
        bg = "#E6FFFA" if is_done else "#F8F9FA"
        # Using the cache buster here too
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={ts}"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="padding:10px; border-radius:10px; border:1px solid #ddd; background-color:{bg}; text-align:center;">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" 
                    onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="margin:0; font-weight:bold; font-size:0.8em;">{name}</p>
                </div>
            """, unsafe_allow_html=True)
