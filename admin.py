import streamlit as st
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Supabase Credentials
SUPABASE_URL = "https://qizxricvzsnsfjibfmxw.supabase.co"
SUPABASE_KEY = "sb_publishable_bWcVZlRASQwMaUCtgklX3Q_yaCUAfxO"
BUCKET_NAME = "evaluator-photos"

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase Connection Error.")

conn = st.connection("postgresql", type="sql")

# --- 2. FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px; min-height: 120px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DIALOGS (Edit/Delete Logic) ---
@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("Edit Proposal Title", value=old_val)
    if st.button("Update Title", type="primary"):
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :new WHERE title = :old"), {"new": new_val.strip(), "old": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :new WHERE proposal_title = :old"), {"new": new_val.strip(), "old": old_val})
            s.commit()
        st.rerun()

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(old_name):
    new_name = st.text_input("Edit Evaluator Name", value=old_name)
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    if st.button("Save Changes", type="primary"):
        clean_new_name = new_name.strip()
        with conn.session as s:
            s.execute(text("UPDATE evaluators SET name = :new WHERE name = :old"), {"new": clean_new_name, "old": old_name})
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), {"new": clean_new_name, "old": old_name})
            s.commit()
        if new_photo:
            file_path = f"{clean_new_name.replace(' ', '_')}.png"
            supabase.storage.from_(BUCKET_NAME).upload(path=file_path, file=new_photo.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
        st.rerun()

@st.dialog("🗑️ Confirm Delete")
def confirm_delete_dialog(table, column, value):
    st.warning(f"Delete '{value}' permanently?")
    if st.button("Yes, Delete", type="primary"):
        if table == "evaluators":
            try:
                file_path = f"{value.strip().replace(' ', '_')}.png"
                supabase.storage.from_(BUCKET_NAME).remove([file_path])
            except: pass
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {"val": value})
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
        s.execute(text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": value.strip()})
        s.commit()

# --- 5. MAIN UI ---
st.title("🛡️ ASM Admin Control Center")
cache_buster = int(time.time())

with st.sidebar:
    auto_refresh = st.toggle("🔄 Auto Refresh (15s)", value=False)
    if auto_refresh: st_autorefresh(interval=15000, key="admin_refresh")

# --- NEW TAB ARRANGEMENT ---
tab_tracker, tab_props, tab_evals, tab_history = st.tabs(["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"])

# --- TAB 1: TRACKER ---
with tab_tracker:
    st.subheader("Live Performance Metrics")
    try:
        df = conn.query("SELECT * FROM scores;", ttl=0)
    except: df = pd.DataFrame()

    if not df.empty:
        numeric_cols = df.select_dtypes(include=['number']).columns
        st.table(df[numeric_cols].mean().round(2).rename("Global Avg"))
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No scores submitted in the current session.")

    evals_all = get_items_sql("evaluators", "name")
    unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []

    if evals_all:
        st.divider()
        progress = min(len(unique_submitted) / len(evals_all), 1.0)
        st.progress(progress)
        st.write(f"**Participation:** {len(unique_submitted)} / {len(evals_all)} Completed")

        cols = st.columns(4)
        for i, name in enumerate(evals_all):
            is_done = name in unique_submitted
            bg = "#E6FFFA" if is_done else "#F8F9FA"
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
            with cols[i % 4]:
                st.markdown(f"""<div class="eval-card" style="background-color:{bg}; border-top: 5px solid {'#38B2AC' if is_done else '#CBD5E0'};">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="font-weight:bold; margin:0; color:#333;">{name}</p>
                    <p style="font-size:0.8em; color:#666;">{'✅ DONE' if is_done else '⌛ WAITING'}</p>
                </div>""", unsafe_allow_html=True)

# --- TAB 2: PROPOSALS ---
with tab_props:
    st.subheader("Manage Proposals")
    p_name = st.text_input("Add Proposal Title")
    if st.button("Add Single"):
        if p_name: add_item_sql("proposals", "title", p_name); st.rerun()
    
    with st.expander("Bulk Add Proposals"):
        bulk_p = st.text_area("Paste list (one per line)")
        if st.button("Save Bulk"):
            for item in bulk_p.split('\n'):
                if item.strip(): add_item_sql("proposals", "title", item)
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"🔍 List of Proposals ({len(props)})"):
        for p in props:
            c1, c2, c3 = st.columns([5, 1, 1])
            c1.write(f"• {p}")
            if c2.button("✏️", key=f"edit_p_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_p_{p}"): confirm_delete_dialog("proposals", "title", p)

# --- TAB 3: EVALUATORS & LINKS ---
with tab_evals:
    col_add, col_links = st.columns([1, 1])
    
    with col_add:
        st.subheader("Add Evaluator")
        with st.form("eval_form", clear_on_submit=True):
            e_name = st.text_input("Name")
            e_file = st.file_uploader("Photo", type=['png', 'jpg'])
            if st.form_submit_button("Create"):
                if e_name:
                    add_item_sql("evaluators", "name", e_name)
                    if e_file:
                        path = f"{e_name.strip().replace(' ', '_')}.png"
                        supabase.storage.from_(BUCKET_NAME).upload(path=path, file=e_file.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
                    st.rerun()

    with col_links:
        st.subheader("Access Links")
        evals_list = get_items_sql("evaluators", "name")
        if evals_list:
            base_url = st.text_input("Base URL", value="https://your-app.streamlit.app").rstrip('/')
            link_data = [{"Name": n, "Link": f"{base_url}/?user={i}"} for i, n in enumerate(evals_list)]
            st.dataframe(pd.DataFrame(link_data), hide_index=True)
            if st.button("📋 Copy All Links"):
                st.code("\n".join([f"{d['Name']}: {d['Link']}" for d in link_data]))

    st.divider()
    with st.expander("👥 Manage Existing Evaluators"):
        for e in evals_list:
            c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
            c1.image(img_url, width=40)
            c2.write(e)
            if c3.button("✏️", key=f"edit_e_{e}"): edit_evaluator_dialog(e)
            if c4.button("🗑️", key=f"del_e_{e}"): confirm_delete_dialog("evaluators", "name", e)

# --- TAB 4: HISTORY ---
with tab_history:
    st.subheader("📜 Historical Sessions")
    try:
        df_history = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
    except:
        with conn.session as s:
            s.execute(text("CREATE TABLE IF NOT EXISTS scores_history AS SELECT *, NOW() as archive_timestamp FROM scores WHERE 1=0;"))
            s.commit()
        df_history = pd.DataFrame()

    if not df_history.empty:
        csv = df_history.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download All History (CSV)", data=csv, file_name="asm_history.csv", mime="text/csv")
        st.dataframe(df_history, use_container_width=True)
        if st.toggle("Show Wipe Button"):
            if st.button("🔥 Delete All History"):
                with conn.session as s:
                    s.execute(text("TRUNCATE TABLE scores_history;"))
                    s.commit()
                st.rerun()
    else:
        st.info("No data in archive.")

# --- FOOTER: SESSION CONTROL ---
st.divider()
st.header("🚀 Session Control")
force_mode = st.toggle("⚠️ Enable Force Archive")
can_archive = (len(unique_submitted) >= len(evals_all) and len(evals_all) > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    with conn.session as s:
        s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
        s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
        s.commit()
    st.balloons()
    time.sleep(1)
    st.rerun()
