import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text

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
@st.dialog("⚠️ Confirm Clear All")
def confirm_clear_all(table, label):
    st.warning(f"Are you sure you want to delete **ALL** {label} from the database?")
    if st.button(f"Yes, Wipe All {label}", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table};"))
            s.commit()
        st.toast(f"🚨 All {label} cleared.")
        st.rerun()

@st.dialog("⚠️ Confirm Deletion")
def confirm_delete_dialog(table, column, value, label):
    st.write(f"Delete **'{value}'** from {label}?")
    if st.button("Confirm Delete", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val;"), {"val": value})
            s.commit()
        st.toast(f"🗑️ Deleted: {value}")
        st.rerun()

# --- Shared UI Component (Merging your logic with SQL) ---
def manage_list_ui(label, table, column, session_key_prefix):
    st.subheader(f"Manage {label}")
    existing = get_items_sql(table, column)
    input_key = f"input_{session_key_prefix}"

    mode = st.radio(f"Add Mode ({label})", ["Single", "Bulk"], horizontal=True, key=f"mode_{session_key_prefix}")

    if mode == "Single":
        c1, c2 = st.columns([3, 1])
        c1.text_input(f"Add New {label}", key=input_key)
        c2.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        if c2.button("Add", key=f"btn_s_{session_key_prefix}", use_container_width=True):
            val = st.session_state[input_key].strip()
            if val:
                add_item_sql(table, column, val)
                st.toast(f"✅ Added {val}")
                st.rerun()
    else:
        bulk_text = st.text_area(f"Paste {label} (one per line)", key=f"bulk_{session_key_prefix}", height=100)
        if st.button(f"Bulk Add {label}", key=f"btn_b_{session_key_prefix}", type="primary"):
            new_items = [t.strip() for t in bulk_text.split('\n') if t.strip()]
            for ni in new_items:
                add_item_sql(table, column, ni)
            st.toast(f"✅ {len(new_items)} items added.")
            st.rerun()

    if existing:
        with st.expander(f"🔍 View / Delete {label} ({len(existing)})"):
            search_query = st.text_input(f"Search {label}...", key=f"search_{session_key_prefix}")
            filtered = [item for item in existing if search_query.lower() in item.lower()]
            for item in filtered:
                col_t, col_d = st.columns([6, 1])
                col_t.write(f"• {item}")
                if col_d.button("🗑️", key=f"del_{session_key_prefix}_{item}"):
                    confirm_delete_dialog(table, column, item, label)
        
        if st.button(f"🚨 Clear All {label}", key=f"clr_{session_key_prefix}", use_container_width=True):
            confirm_clear_all(table, label)

# --- Main Admin UI ---
try:
    st.image("80x68.png", width=100)
except:
    st.info("Akademi Sains Malaysia")

st.title("🛡️ Admin Control Center")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

with tab1: manage_list_ui("Proposals", "proposals", "title", "prop")
with tab2: manage_list_ui("Evaluators", "evaluators", "name", "eval")
with tab3:
    st.subheader("Personalized Access Links")
    EVALS_LIST = get_items_sql("evaluators", "name")
    if EVALS_LIST:
        base_url = st.text_input("Application Base URL", value="https://your-app.streamlit.app").rstrip('/')
        copy_text = "📋 *ASM EVALUATOR LINKS*\n\n"
        link_data = []
        for i, name in enumerate(EVALS_LIST):
            link = f"{base_url}/?user={i}"
            copy_text += f"👤 {name}:\n🔗 {link}\n\n"
            link_data.append({"Evaluator": name, "URL": link})
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        st.text_area("Copy-Paste Block", value=copy_text, height=200)

st.divider()

# --- Tracker & Executive Summary ---
st.header("📊 Executive Summary & Tracker")
df_scores = conn.query("SELECT * FROM scores;", ttl=0)

if not df_scores.empty:
    with st.expander("👀 View Global Performance Summary", expanded=True):
        col_stats, col_leader = st.columns([2, 1])
        numeric_cols = df_scores.select_dtypes(include=['number']).columns
        grand_means = df_scores[numeric_cols].mean().round(2)
        
        with col_stats:
            st.write("**Average Score per Criteria:**")
            st.table(grand_means.rename("Score / 5.0"))

        with col_leader:
            st.write("**Top Rated Proposal:**")
            prop_avgs = df_scores.groupby('proposal_title')['total'].mean()
            leader = prop_avgs.idxmax()
            st.success(f"🏆 **{leader}**\n\nAvg Score: {prop_avgs.max():.2f}")

        st.write("**Detailed Raw Data:**")
        st.dataframe(df_scores, use_container_width=True, hide_index=True)

# --- Submission Tracker Logic ---
unique_submitted = df_scores['evaluator'].unique().tolist() if not df_scores.empty else []
count = len(unique_submitted)
total_evals = len(EVALS_LIST)

if total_evals > 0:
    progress_val = min(count / total_evals, 1.0)
    st.progress(progress_val)
    st.write(f"**Participation:** {count} of {total_evals} Evaluators have submitted reviews.")
    
    cols = st.columns(4)
    for i, name in enumerate(EVALS_LIST):
        is_done = name in unique_submitted
        bg_color = "#28a745" if is_done else "#F1F5F9"
        text_color = "white" if is_done else "#475569"
        
        p_count = len(df_scores[df_scores['evaluator'] == name]) if is_done else 0
        status_text = f"✅ {p_count} Done" if is_done else "⌛ WAITING"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="padding:15px; border-radius:10px; background-color:{bg_color}; color:{text_color}; border: 1px solid #E2E8F0; text-align:center; margin-bottom:10px;">
                    <p style="font-size:0.85em; font-weight:bold; margin:0;">{name}</p>
                    <p style="font-size:1em; font-weight:bold; margin-top:5px;">{status_text}</p>
                </div>
            """, unsafe_allow_html=True)

st.divider()

# --- Session Control ---
st.header("🚀 Session Control")
force_mode = st.toggle("⚠️ Enable Force Archive")
archive_name = st.text_input("Session Tag (e.g. Batch 1)")
can_archive = (count >= total_evals and total_evals > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not (can_archive and archive_name)):
    if not df_scores.empty:
        with conn.session as s:
            s.execute(text("""
                INSERT INTO history (archive_tag, evaluator, proposal_title, total, recommendation, comments, last_updated)
                SELECT :tag, evaluator, proposal_title, total, recommendation, comments, last_updated FROM scores;
            """), {"tag": archive_name})
            s.execute(text("DELETE FROM scores;"))
            s.commit()
        st.balloons()
        st.rerun()
