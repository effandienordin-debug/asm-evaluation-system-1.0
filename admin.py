import streamlit as st
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Replace with your actual Supabase Credentials
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-anon-key"
BUCKET_NAME = "evaluator-photos"

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase Connection Error. Check URL/Key.")

conn = st.connection("postgresql", type="sql")

# --- 2. FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .stTable { color: #000000 !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px; min-height: 120px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DIALOGS (The missing Pop-ups) ---
@st.dialog("🗑️ Confirm Deletion")
def confirm_delete_item(table, column, value):
    st.write(f"Are you sure you want to delete **{value}**?")
    if st.button(f"Yes, Delete", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :v"), {"v": value})
            s.commit()
        st.success(f"Deleted {value}")
        time.sleep(1)
        st.rerun()

@st.dialog("🚨 Clear All Data")
def confirm_clear_table(table, label):
    st.warning(f"This will delete ALL {label} permanently!")
    if st.button(f"Nuke All {label}", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(text(f"TRUNCATE TABLE {table} CASCADE;"))
            s.commit()
        st.rerun()

# --- 4. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except: return []

def add_item_sql(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value.strip()})
        s.commit()

# --- 5. MAIN UI ---
st.title("🛡️ ASM Admin Control Center")

col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=False)
if auto_refresh:
    st_autorefresh(interval=15000, key="admin_refresh")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

# --- TAB 1: PROPOSALS ---
with tab1:
    st.subheader("Manage Proposals")
    mode_p = st.radio("Add Mode", ["Single", "Bulk"], horizontal=True, key="pmode")
    if mode_p == "Single":
        p_name = st.text_input("Proposal Title")
        if st.button("Add Proposal"):
            if p_name: 
                add_item_sql("proposals", "title", p_name)
                st.rerun()
    else:
        bulk_p = st.text_area("Paste (one per line)")
        if st.button("Bulk Add"):
            for item in bulk_p.split('\n'):
                if item.strip(): add_item_sql("proposals", "title", item)
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"🔍 View/Search Proposals ({len(props)})"):
        search_p = st.text_input("Filter Proposals...")
        for p in [x for x in props if search_p.lower() in x.lower()]:
            c1, c2 = st.columns([6, 1])
            c1.write(f"• {p}")
            if c2.button("🗑️", key=f"del_p_{p}"):
                confirm_delete_item("proposals", "title", p)
        if props:
            if st.button("🚨 Clear All Proposals", type="secondary"): confirm_clear_table("proposals", "Proposals")

# --- TAB 2: EVALUATORS ---
with tab2:
    st.subheader("Manage Evaluators")
    with st.form("eval_form", clear_on_submit=True):
        e_name = st.text_input("Evaluator Full Name")
        e_photo = st.file_uploader("Profile Photo", type=['png', 'jpg', 'jpeg'])
        if st.form_submit_button("Add Evaluator", type="primary"):
            if e_name:
                add_item_sql("evaluators", "name", e_name)
                if e_photo:
                    file_path = f"{e_name.strip().replace(' ', '_')}.png"
                    supabase.storage.from_(BUCKET_NAME).upload(
                        path=file_path, file=e_photo.getvalue(),
                        file_options={"content-type": "image/png", "x-upsert": "true"}
                    )
                st.rerun()

    evals = get_items_sql("evaluators", "name")
    cache_buster = int(time.time())
    
    with st.expander(f"🔍 View/Search Evaluators ({len(evals)})"):
        search_e = st.text_input("Filter Evaluators...")
        for e in [x for x in evals if search_e.lower() in x.lower()]:
            c1, c2, c3 = st.columns([1, 5, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
            c1.image(img_url, width=40)
            c2.write(e)
            if c3.button("🗑️", key=f"del_e_{e}"):
                confirm_delete_item("evaluators", "name", e)
        if evals:
            if st.button("🚨 Clear All Evaluators"): confirm_clear_table("evaluators", "Evaluators")

# --- TAB 3: LINKS ---
with tab3:
    st.subheader("Personalized Access Links")
    if evals:
        base_url = st.text_input("Base URL", value="https://your-app.streamlit.app").rstrip('/')
        link_data = [{"Evaluator": n, "Link": f"{base_url}/?user={i}"} for i, n in enumerate(evals)]
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        
        copy_block = "\n".join([f"👤 {d['Evaluator']}: {d['Link']}" for d in link_data])
        st.text_area("Copy-Paste Block", value=copy_block, height=150)

# --- 6. TRACKER & SUMMARY ---
st.divider()
st.header("📊 Executive Summary & Tracker")

try:
    df = conn.query("SELECT * FROM scores;", ttl=0)
except:
    df = pd.DataFrame()

if not df.empty:
    with st.expander("👀 View Performance Metrics", expanded=True):
        numeric_cols = df.select_dtypes(include=['number']).columns
        st.table(df[numeric_cols].mean().round(2).rename("Global Avg"))
        st.dataframe(df, use_container_width=True)

# Participation Grid
evals_all = get_items_sql("evaluators", "name")
unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []

if evals_all:
    progress = min(len(unique_submitted) / len(evals_all), 1.0)
    st.progress(progress)
    st.write(f"**Participation:** {len(unique_submitted)} of {len(evals_all)} active.")

    cols = st.columns(4)
    for i, name in enumerate(evals_all):
        is_done = name in unique_submitted
        bg = "#E6FFFA" if is_done else "#F8F9FA"
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div class="eval-card" style="background-color:{bg};">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" 
                    onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="font-size:0.85em; font-weight:bold; margin:0; color:#000;">{name}</p>
                    <p style="font-size:0.8em; margin:0; color:#666;">{'✅ DONE' if is_done else '⌛ WAITING'}</p>
                </div>
            """, unsafe_allow_html=True)
            # --- 7. SESSION CONTROL (Archive & Reset) ---
st.divider()
st.header("🚀 Session Control")

# Archive logic for Cloud SQL
force_mode = st.toggle("⚠️ Enable Force Archive")
total_evals_count = len(evals_all)
count_submitted = len(unique_submitted)

# Archive allowed if everyone is done OR force mode is on
can_archive = (count_submitted >= total_evals_count and total_evals_count > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    try:
        with conn.session as s:
            # 1. Copy current scores to history table
            s.execute(text("""
                INSERT INTO scores_history 
                SELECT *, NOW() as archive_timestamp FROM scores;
            """))
            # 2. Clear the active scores table
            s.execute(text("TRUNCATE TABLE scores CASCADE;"))
            s.commit()
            
        st.balloons()
        st.success("Current session archived to 'scores_history' and dashboard reset!")
        time.sleep(2)
        st.rerun()
    except Exception as e:
        st.error(f"Archive failed: {e}. Ensure a 'scores_history' table exists in your database.")

