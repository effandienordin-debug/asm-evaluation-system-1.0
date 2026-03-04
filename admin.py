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
SUPABASE_URL = "https://qizxricvzsnsfjibfmxw.supabase.co"
SUPABASE_KEY = "sb_publishable_bWcVZlRASQwMaUCtgklX3Q_yaCUAfxO"
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

# --- 3. DIALOGS ---
@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("Edit Proposal Title", value=old_val)
    if st.button("Update Title", type="primary"):
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :new WHERE title = :old"), 
                      {"new": new_val.strip(), "old": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :new WHERE proposal_title = :old"), 
                      {"new": new_val.strip(), "old": old_val})
            s.commit()
        st.success("Proposal updated!")
        time.sleep(1)
        st.rerun()

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(old_name):
    new_name = st.text_input("Edit Evaluator Name", value=old_name)
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    
    if st.button("Save Changes", type="primary"):
        clean_new_name = new_name.strip()
        
        with conn.session as s:
            # 1. Update database names in evaluators and scores tables
            s.execute(text("UPDATE evaluators SET name = :new WHERE name = :old"), 
                      {"new": clean_new_name, "old": old_name})
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), 
                      {"new": clean_new_name, "old": old_name})
            s.commit()
        
        # 2. Handle Photo Update
        if new_photo:
            file_path = f"{clean_new_name.replace(' ', '_')}.png"
            try:
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=file_path, 
                    file=new_photo.getvalue(),
                    file_options={"content-type": "image/png", "x-upsert": "true"} # CRITICAL: Allows overwriting
                )
                st.toast("📷 Photo updated successfully!")
            except Exception as e:
                st.error(f"Photo upload failed: {e}")
        
        st.success(f"Updated {clean_new_name}!")
        time.sleep(1)
        st.rerun()

@st.dialog("🗑️ Confirm Delete")
def confirm_delete_dialog(table, column, value):
    st.warning(f"Are you sure you want to delete '{value}'?")
    st.info("This will also remove any associated photos and scores.")
    
    if st.button("Yes, Delete permanently", type="primary"):
        # 1. If we are deleting an evaluator, clean up their photo first
        if table == "evaluators":
            try:
                file_path = f"{value.strip().replace(' ', '_')}.png"
                # Remove the file from Supabase Storage
                supabase.storage.from_(BUCKET_NAME).remove([file_path])
                st.toast(f"🗑️ Photo for {value} deleted.")
            except Exception as e:
                # We use a silent log here because sometimes a user might not have a photo
                print(f"Storage cleanup skip/fail: {e}")

        # 2. Delete from the Database
        with conn.session as s:
            # CASCADE will handle scores if your foreign keys are set up, 
            # otherwise, this line removes the main record.
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {"val": value})
            s.commit()
            
        st.success(f"Successfully deleted {value}")
        time.sleep(1)
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

# --- DEFINE CACHE BUSTER AT TOP OF UI TO PREVENT NAMEERROR ---
cache_buster = int(time.time())

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
                st.toast(f"✅ Proposal '{p_name}' added!") # The pop-up
                time.sleep(1)
                st.rerun()
    else:
        bulk_p = st.text_area("Paste (one per line)")
        if st.button("Bulk Add"):
            for item in bulk_p.split('\n'):
                if item.strip(): 
                    add_item_sql("proposals", "title", item)
            st.toast("✅ Bulk proposals added!")
            time.sleep(1)
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"🔍 View/Edit Proposals ({len(props)})"):
        search_p = st.text_input("Filter Proposals...")
        for p in [x for x in props if search_p.lower() in x.lower()]:
            c1, c2, c3 = st.columns([5, 1, 1])
            c1.write(f"• {p}")
            if c2.button("✏️", key=f"edit_p_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_p_{p}"): confirm_delete_dialog("proposals", "title", p)

# --- TAB 2: EVALUATORS ---
with tab2:
    st.subheader("Add New Evaluator")
    with st.form("eval_add_form", clear_on_submit=True):
        e_name_in = st.text_input("Evaluator Name")
        e_photo_in = st.file_uploader("Photo", type=['png', 'jpg', 'jpeg'])
        
        if st.form_submit_button("Add Evaluator"):
            if e_name_in:
                clean_name = e_name_in.strip()
                add_item_sql("evaluators", "name", clean_name)
                
                if e_photo_in:
                    file_path = f"{clean_name.replace(' ', '_')}.png"
                    supabase.storage.from_(BUCKET_NAME).upload(
                        path=file_path, 
                        file=e_photo_in.getvalue(),
                        file_options={"content-type": "image/png", "x-upsert": "true"}
                    )
                
                st.toast(f"✅ {clean_name} added to the system!") # Pop-up notification
                time.sleep(1)
                st.rerun()

    evals = get_items_sql("evaluators", "name")
    with st.expander(f"🔍 View/Edit Evaluators ({len(evals)})"):
        search_e = st.text_input("Filter Evaluators...")
        for e in [x for x in evals if search_e.lower() in x.lower()]:
            c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
            c1.image(img_url, width=40)
            c2.write(e)
            if c3.button("✏️", key=f"edit_e_{e}"): edit_evaluator_dialog(e)
            if c4.button("🗑️", key=f"del_e_{e}"): confirm_delete_dialog("evaluators", "name", e)

# --- TAB 3: LINKS ---
with tab3:
    st.subheader("Personalized Access Links")
    evals_list = get_items_sql("evaluators", "name")
    if evals_list:
        base_url = st.text_input("Base URL", value="https://your-app.streamlit.app").rstrip('/')
        link_data = [{"Evaluator": n, "Link": f"{base_url}/?user={i}"} for i, n in enumerate(evals_list)]
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

# 1. Fetch History to display it
try:
    df_history = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
except:
    df_history = pd.DataFrame()

with st.expander(f"📚 View Archived Sessions ({len(df_history)})"):
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.info("No archived sessions found.")

# 2. Archive Action
force_mode = st.toggle("⚠️ Enable Force Archive")
can_archive = (len(unique_submitted) >= len(evals_all) and len(evals_all) > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    try:
        with conn.session as s:
            # Move data to history
            s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
            # Clear the current scores
            s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
            s.commit()
        
        st.balloons()
        st.success("Current session has been moved to history!")
        time.sleep(2)
        st.rerun()
    except Exception as e:
        st.error(f"Archive failed: {e}")







