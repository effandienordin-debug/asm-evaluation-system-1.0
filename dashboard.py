import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

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
    }
    </style>
    """, unsafe_allow_html=True)

# --- File Paths ---
DATA_FILE = "asm_scores.csv"
HISTORY_FILE = "asm_history.csv"

# Define Official Criteria
CRITERIA_COLS = [
    'Strategic Alignment', 'Potential Impact', 'Feasibility', 
    'Budget Justification', 'Timeline Readiness', 'Execution Strategy'
]

# --- TAB 1: LIVE EVALUATION ---
tab_live, tab_hist = st.tabs(["📊 Live Evaluation", "📜 Session History"])

with tab_live:
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE).dropna(subset=['Total'])
        
        if not df.empty:
            st.title("📊 Live Evaluation Dashboard")
            
            # --- GROUPING LOGIC ---
            # Get unique proposals present in the current data
            unique_proposals = df['Proposal_Title'].unique()
            
            for proposal in unique_proposals:
                # Filter data for this specific proposal
                prop_df = df[df['Proposal_Title'] == proposal].copy()
                prop_df.set_index(prop_df.columns[0], inplace=True) # Set Evaluator Name as index
                
                # Header for the specific proposal section
                st.markdown(f"<div class='proposal-header'>📂 Proposal: {proposal}</div>", unsafe_allow_html=True)
                
                # 1. Metrics for this proposal
                m1, m2, m3, m4 = st.columns(4)
                avg_score = prop_df['Total'].mean()
                m1.metric("Avg Score", f"{avg_score:.2f}")
                m2.metric("Evaluators", len(prop_df))
                m3.metric("Max Score", f"{prop_df['Total'].max():.2f}")
                m4.metric("Min Score", f"{prop_df['Total'].min():.2f}")

                # 2. Visuals for this proposal
                c1, c2 = st.columns([1, 1])
                
                with c1:
                    fig_bar = px.bar(prop_df, x=prop_df.index, y='Total', range_y=[0,5], 
                                     title=f"Scores for {proposal}",
                                     color='Total', color_continuous_scale='GnBu')
                    fig_bar.update_layout(template="plotly_white", paper_bgcolor='#FFFFFF')
                    st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{proposal}")

                with c2:
                    avg_crit = prop_df[CRITERIA_COLS].mean()
                    fig_radar = go.Figure(data=go.Scatterpolar(
                        r=avg_crit.values, 
                        theta=CRITERIA_COLS, 
                        fill='toself', line_color='#1E3A8A'
                    ))
                    fig_radar.update_layout(template="plotly_white", polar=dict(radialaxis=dict(range=[0, 5])))
                    st.plotly_chart(fig_radar, use_container_width=True, key=f"radar_{proposal}")

                # 3. Dedicated Table for this proposal
                st.write(f"**Individual Scores for {proposal}:**")
                # Show specific columns to keep it clean
                display_cols = CRITERIA_COLS + ['Total', 'Recommendation', 'Comments']
                st.table(prop_df[display_cols])
                
                st.divider()
        else:
            st.info("Awaiting submissions from evaluators.")
    else:
        st.error("No active data file found.")

# --- TAB 2: SESSION HISTORY ---
with tab_hist:
    st.header("📜 Proposal History & Rankings")
    if os.path.exists(HISTORY_FILE):
        h_df = pd.read_csv(HISTORY_FILE)
        
        # Ranking Summary
        ranking_df = h_df.groupby('Proposal_Title')['Total'].agg(['mean', 'count']).sort_values(by='mean', ascending=False)
        ranking_df.columns = ['Avg Score', 'Evaluator Count']
        
        st.subheader("🏆 Overall Rankings")
        st.dataframe(ranking_df, use_container_width=True)
        
        with st.expander("View All Archived Data"):
            st.dataframe(h_df)
    else:
        st.info("No history recorded yet.")