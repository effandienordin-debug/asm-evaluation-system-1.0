import streamlit as st
import pandas as pd
from datetime import datetime

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

# --- Connect to SQL (Supabase/PostgreSQL) ---
# Ensure your secrets.toml has [connections.postgresql]
conn = st.connection("postgresql", type="sql")

# --- Helper Functions ---
def get_items(table, column):
    try:
        query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
        df = conn.query(query, ttl="2s")
        return df[column].dropna().tolist()
    except:
        return []

def add_item(table, column, value):
    with conn.session as s:
        s.execute(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;", {"val": value})
        s.commit()

def delete_item(table, column, value):
    with conn.session as s:
        s.execute(f"DELETE FROM {table} WHERE {column} = :val;", {"val": value})
        s.commit()

# --- Dialogs ---
@st.dialog("⚠️ Confirm Clear")
def confirm_clear(table, label, column):
    st.write(f"Are you sure you want to delete **ALL** {label} from the database?")
    if st.button(f"Yes, Clear All {label}", type="primary"):
        with conn.session as s:
            s.execute(f"DELETE FROM {table};")
            s.commit()
        st.rerun()

# --- Shared UI Component ---
def manage_list_ui(label, table_name, col_name, session_key_prefix):
    st.subheader(f"Manage {label}")
    existing = get_items(table_name, col_name)
    input_key = f"input_{session_key_prefix}"

    mode = st.radio(f"Add Mode ({label})", ["Single", "Bulk"], horizontal=True, key=f"mode_{session_key_prefix}")

    if mode == "Single":
        c1, c2 = st.columns([3, 1])
        new_val = c1.text_input(f"Add New {label}", key=input_key)
        c2.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        if c2.button("Add", key=f"btn_s_{session_key_prefix}", use_container_width=True):
            if new_val:
                add_item(table_name, col_name, new_val)
                st.toast(f"✅ Added {new_val}")
                st.rerun()
    else:
        bulk_text = st.text_area(f"Paste {label} (one per line)", key=f"bulk_{session_key_prefix}", height=100)
        if st.button(f"Bulk Add {label}", key=f"btn_b_{session_key_prefix}", type="primary"):
            new_items = [t.strip() for t in bulk_text.split('\n') if t.strip()]
            for ni in new_items:
                add_item(table_name, col_name, ni)
            st.rerun()

    if existing:
        with st.expander(f"🔍 View / Delete {label} ({len(existing)})"):
            search_query = st.text_input(f"Search {label}...", key=f"search_{session_key_prefix}")
            filtered = [item for item in existing if search_query.lower() in item.lower()]
            for item in filtered:
                col_t, col_d = st.columns([6, 1])
                col_t.write(f"• {item}")
                if col_d.button("🗑️", key=f"del_{session_key_prefix}_{item}"):
                    delete_item(table_name, col_name, item)
                    st.rerun()
        
        if st.button(f"🚨 Clear All {label}", key=f"clr_{session_key_prefix}", use_container_width=True):
            confirm_clear(table_name, label, col_name)

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
    EVALUATORS = get_items("evaluators", "name")
    if EVALUATORS:
        base_url = st.text_input("Application Base URL", value="https://your-app.streamlit.app").rstrip('/')
        copy_text = "📋 *ASM EVALUATOR LINKS*\n\n"
        link_data = []
        for i, name in enumerate(EVALUATORS):
            link = f"{base_url}/?user={i}"
            copy_text += f"👤 {name}:\n🔗 {link}\n\n"
            link_data.append({"Evaluator": name, "URL": link})
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        st.text_area("Copy-Paste Block", value=copy_text, height=200)

st.divider()

# --- Tracker & Executive Summary ---
st.header("📊 Executive Summary & Tracker")
EVALS_LIST = get_items("evaluators", "name")

# Load Scores from SQL
try:
    df = conn.query("SELECT * FROM scores;", ttl="2s")
except:
    df = pd.DataFrame()

if not df.empty:
    with st.expander("👀 View Global Performance Summary", expanded=True):
        col_stats, col_leader = st.columns([2, 1])
        numeric_cols = df.select_dtypes(include=['number']).columns
        grand_means = df[numeric_cols].mean().round(2)
        
        with col_stats:
            st.write("**Average Score per Criteria:**")
            st.table(grand_means.rename("Score / 5.0"))

        with col_leader:
            st.write("**Top Rated Proposal:**")
            if 'proposal_title' in df.columns:
                prop_avgs = df.groupby('proposal_title')['total'].mean()
                leader = prop_avgs.idxmax()
                st.success(f"🏆 **{leader}**\n\nAvg Score: {prop_avgs.max():.2f}")

        st.dataframe(df, use_container_width=True, hide_index=True)

# --- Submission Tracker ---
unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []
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
        p_count = len(df[df['evaluator'] == name]) if is_done else 0
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="padding:15px; border-radius:10px; background-color:{bg_color}; color:{text_color}; border: 1px solid #E2E8F0; text-align:center; margin-bottom:10px;">
                    <p style="font-size:0.85em; font-weight:bold; margin:0;">{name}</p>
                    <p style="font-size:1em; font-weight:bold; margin-top:5px;">{'✅ ' + str(p_count) + ' Done' if is_done else '⌛ WAITING'}</p>
                </div>
            """, unsafe_allow_html=True)

st.divider()

# --- Session Control (SQL Archive) ---
st.header("🚀 Session Control")
archive_name = st.text_input("Session Name (e.g., '2026 Batch A')")
force_mode = st.toggle("⚠️ Enable Force Archive")
can_archive = (count >= total_evals and total_evals > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    if not df.empty and archive_name:
        with conn.session as s:
            # 1. Copy to History
            s.execute("""
                INSERT INTO history (
                    archive_tag, evaluator, proposal_title, strategic_alignment, 
                    potential_impact, feasibility, budget_justification, 
                    timeline_readiness, execution_strategy, total, 
                    recommendation, comments, last_updated
                )
                SELECT 
                    :tag, evaluator, proposal_title, strategic_alignment, 
                    potential_impact, feasibility, budget_justification, 
                    timeline_readiness, execution_strategy, total, 
                    recommendation, comments, last_updated
                FROM scores;
            """, {"tag": archive_name})
            
            # 2. Clear Active Scores
            s.execute("DELETE FROM scores;")
            s.commit()
            
        st.balloons()
        st.success(f"Session '{archive_name}' archived!")
        st.rerun()
    elif not archive_name:
        st.warning("Please enter a Session Name to archive data.")
# --- Data Export & History Browser ---
st.divider()
st.header("📂 Archive Browser & Data Export")

try:
    # Fetch all unique session tags from the history table
    sessions_df = conn.query("SELECT DISTINCT archive_tag FROM history ORDER BY archive_tag DESC;", ttl="10s")
    
    if not sessions_df.empty:
        session_list = sessions_df['archive_tag'].tolist()
        selected_session = st.selectbox("Select a session to export:", session_list)

        if selected_session:
            # Fetch full data for the selected session
            export_df = conn.query(
                "SELECT * FROM history WHERE archive_tag = :tag;", 
                params={"tag": selected_session}, 
                ttl="0s"
            )

            if not export_df.empty:
                # Show a preview of the data
                st.write(f"Previewing data for: **{selected_session}**")
                st.dataframe(export_df.head(10), use_container_width=True)

                # Convert dataframe to CSV
                csv = export_df.to_csv(index=False).encode('utf-8')

                # Create the Download Button
                st.download_button(
                    label=f"📥 Download {selected_session} as CSV",
                    data=csv,
                    file_name=f"ASM_Archive_{selected_session.replace(' ', '_')}.csv",
                    mime='text/csv',
                    use_container_width=True
                )
    else:
        st.info("No archived sessions found in the database yet.")
except Exception as e:
    st.error(f"Could not load history: {e}")
