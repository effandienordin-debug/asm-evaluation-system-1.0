import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --- Page Config ---
st.set_page_config(page_title="ASM Result Dashboard", layout="wide")

# --- FORCED WHITE THEME & TABLE WRAPPING CSS ---
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
    /* Custom Styling for the wrapping table */
    .wrapped-table {
        width: 100%;
        border-collapse: collapse;
        font-family: sans-serif;
        font-size: 13px;
        table-layout: fixed;
    }
    .wrapped-table th {
        background-color: #f3f4f6;
        border: 1px solid #e5e7eb;
        padding: 8px;
        text-align: left;
        color: #1f2937;
    }
    .wrapped-table td {
        border: 1px solid #e5e7eb;
        padding: 8px;
        vertical-align: top;
        word-wrap: break-word;
        white-space: normal !important;
        line-height: 1.4;
    }
    /* NEW: Styling for the comment bubble from your screenshot */
    .comment-bubble {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 12px;
        margin: 2px 0;
        color: #1f2937;
        font-size: 13px;
        display: inline-block;
        width: 100%;
    }
    .comment-bubble p {
        margin: 0;
        padding: 2px 0;
    }

    /* Column Width Management */
    .col-eval { width: 10%; }
    .col-crit { width: 6%; text-align: center; }
    .col-total { width: 5%; font-weight: bold; text-align: center; }
    .col-rec { width: 10%; }
    .col-comm { width: 30%; }
    </style>
    """, unsafe_allow_html=True)

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

CRITERIA_COLS = [
    'strategic_alignment', 'potential_impact', 'feasibility', 
    'budget_justification', 'timeline_readiness', 'execution_strategy'
]

# --- Auto-Refresh Toggle ---
col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=True)
if auto_refresh:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, key="dashrefresh")

# --- LIVE EVALUATION CONTENT ---
df = conn.query("SELECT * FROM scores;", ttl=0)

if not df.empty:
    st.title("📊 Live Evaluation Dashboard")
    unique_proposals = df['proposal_title'].unique()
    
    for proposal in unique_proposals:
        prop_df = df[df['proposal_title'] == proposal].copy()
        st.markdown(f"<div class='proposal-header'>📂 Proposal: {proposal}</div>", unsafe_allow_html=True)
        
        # 1. Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Avg Score", f"{prop_df['total'].mean():.2f}")
        m2.metric("Evaluators", len(prop_df))
        m3.metric("Max Score", f"{prop_df['total'].max():.2f}")
        m4.metric("Min Score", f"{prop_df['total'].min():.2f}")

        # 2. Visuals
        c1, c2 = st.columns([1, 1])
        with c1:
            fig_bar = px.bar(prop_df, x='evaluator', y='total', range_y=[0,5], title="Total Scores", color='total', color_continuous_scale='GnBu')
            fig_bar.update_layout(template="plotly_white")
            st.plotly_chart(fig_bar, use_container_width=True)
        with c2:
            avg_crit = prop_df[CRITERIA_COLS].mean()
            fig_radar = go.Figure(data=go.Scatterpolar(r=avg_crit.values, theta=[c.replace('_', ' ').title() for c in CRITERIA_COLS], fill='toself', line_color='#1E3A8A'))
            fig_radar.update_layout(template="plotly_white", polar=dict(radialaxis=dict(range=[0, 5])))
            st.plotly_chart(fig_radar, use_container_width=True)

        # 3. Table with Screenshot-style Comments
        with st.expander(f"View Detailed Reviews for {proposal}", expanded=True):
            header_row = "".join([f"<th class='col-crit'>{c.replace('_', ' ').title()}</th>" for c in CRITERIA_COLS])
            
            table_html = f"""<table class='wrapped-table'>
                            <thead>
                                <tr>
                                    <th class='col-eval'>Evaluator</th>
                                    {header_row}
                                    <th class='col-total'>Total</th>
                                    <th class='col-rec'>Recommendation</th>
                                    <th class='col-comm'>Comments</th>
                                </tr>
                            </thead>
                            <tbody>"""
            
            for _, row in prop_df.iterrows():
                crit_data = "".join([f"<td class='col-crit'>{row.get(c, 0)}</td>" for c in CRITERIA_COLS])
                
                # Format comments to look like the screenshot (bullet points in a bubble)
                raw_comment = str(row.get('comments', '-')) if pd.notnull(row.get('comments')) else "-"
                
                # Logic to convert newline-separated text into bullet points
                if raw_comment != "-":
                    # Split by newlines and wrap in <p> tags with a dash
                    lines = raw_comment.split('\n')
                    formatted_comment = "".join([f"<p>- {line.strip()}</p>" for line in lines if line.strip()])
                    comment_html = f"<div class='comment-bubble'>{formatted_comment}</div>"
                else:
                    comment_html = "-"
                
                rec_text = row.get('recommendation', '') if pd.notnull(row.get('recommendation')) else "-"
                
                table_html += f"""
                    <tr>
                        <td class='col-eval'><b>{row['evaluator']}</b></td>
                        {crit_data}
                        <td class='col-total'>{row['total']:.2f}</td>
                        <td class='col-rec'>{rec_text}</td>
                        <td class='col-comm'>{comment_html}</td>
                    </tr>
                """
            
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)
        
        st.divider()
else:
    st.title("📊 Live Evaluation Dashboard")
    st.info("Awaiting submissions...")

