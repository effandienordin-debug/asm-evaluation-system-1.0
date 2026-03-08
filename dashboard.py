import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --- Page Config ---
st.set_page_config(page_title="ASM Result Dashboard", layout="wide")

# --- FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .proposal-header { 
        background-color: #1E3A8A; 
        color: white; 
        padding: 10px; 
        border-radius: 5px; 
        margin-top: 20px;
        margin-bottom: 10px;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

# Define Official Criteria (Matching the SQL column names)
CRITERIA_COLS = [
    'strategic_alignment', 'potential_impact', 'feasibility', 
    'budget_justification', 'timeline_readiness', 'execution_strategy'
]

# --- Auto-Refresh Toggle ---
col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=True, help="Refresh every 10 seconds")
if auto_refresh:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, key="dashrefresh")

# --- LIVE EVALUATION CONTENT ---
# Fetch from SQL instead of CSV
df = conn.query("SELECT * FROM scores;", ttl=0)

if not df.empty:
    st.title("📊 Live Evaluation Dashboard")
    
    # Get unique proposals
    unique_proposals = df['proposal_title'].unique()
    
    for proposal in unique_proposals:
        prop_df = df[df['proposal_title'] == proposal].copy()
        
        # Header - FIXED SYNTAX HERE
        st.markdown(f"<div class='proposal-header'>📂 Proposal: {proposal}</div>", unsafe_allow_html=True)
        
        # 1. Metrics
        m1, m2, m3, m4 = st.columns(4)
        avg_score = prop_df['total'].mean()
        m1.metric("Avg Score", f"{avg_score:.2f}")
        m2.metric("Evaluators", len(prop_df))
        m3.metric("Max Score", f"{prop_df['total'].max():.2f}")
        m4.metric("Min Score", f"{prop_df['total'].min():.2f}")

        # 2. Visuals
        c1, c2 = st.columns([1, 1])
        
        with c1:
            # Bar chart using evaluator names
            fig_bar = px.bar(prop_df, x='evaluator', y='total', range_y=[0,5], 
                             title=f"Total Scores for {proposal}",
                             color='total', color_continuous_scale='GnBu')
            fig_bar.update_layout(template="plotly_white")
            st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{proposal}")

        with c2:
            # Radar chart for criteria averages
            avg_crit = prop_df[CRITERIA_COLS].mean()
            fig_radar = go.Figure(data=go.Scatterpolar(
                r=avg_crit.values, 
                theta=[c.replace('_', ' ').title() for c in CRITERIA_COLS], 
                fill='toself', line_color='#1E3A8A'
            ))
            fig_radar.update_layout(template="plotly_white", polar=dict(radialaxis=dict(range=[0, 5])))
            st.plotly_chart(fig_radar, use_container_width=True, key=f"radar_{proposal}")

        # 3. Table
        with st.expander(f"View Raw Data for {proposal}"):
            # Added 'justification' to the list below
            display_cols = ['evaluator'] + CRITERIA_COLS + ['total', 'recommendation', 'justification']
            st.dataframe(prop_df[display_cols], hide_index=True)
        
        st.divider()
else:
    st.title("📊 Live Evaluation Dashboard")
    st.info("Awaiting submissions from evaluators. Data will appear here once the first review is submitted.")
