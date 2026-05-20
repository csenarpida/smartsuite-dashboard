import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import re
from datetime import datetime

st.set_page_config(page_title="Ops Dashboard", page_icon="📊", layout="wide")

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY       = "df07a54caefda1693bfdad758056124fc5cc88f0"
ACCOUNT_ID    = "svxkeb0y"
SOLUTION_ID   = "67b284afc71e608ca6f6902c"
TABLE_ID      = "69a54ceded771376615c0560"

# ── Data fetching ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_data():
    url = f"https://app.smartsuite.com/api/v1/applications/{TABLE_ID}/records/list/"
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Account-Id": ACCOUNT_ID,
        "Content-Type": "application/json",
    }
    records = []
    offset = 0
    limit = 1000
    with st.spinner("Fetching data from SmartSuite..."):
        while True:
            payload = {"limit": limit, "offset": offset}
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                st.error(f"API error {resp.status_code}: {resp.text}")
                break
            data = resp.json()
            items = data.get("items", [])
            records.extend(items)
            if len(items) < limit:
                break
            offset += limit
    return records

def extract_date(val):
    if not val or pd.isna(val):
        return None
    m = re.search(r'on (.+)$', str(val))
    return m.group(1).strip() if m else str(val)

def records_to_df(records):
    rows = []
    for r in records:
        fields = r.get("fields", r)
        rows.append(fields)
    return pd.DataFrame(rows)

def load_data():
    raw = fetch_data()
    if not raw:
        return pd.DataFrame()
    df = records_to_df(raw)
    # Parse created date
    if "First Created" in df.columns:
        df["created_clean"] = df["First Created"].apply(extract_date)
        df["created_dt"] = pd.to_datetime(df["created_clean"], format="mixed", errors="coerce")
        df["month"] = df["created_dt"].dt.to_period("M").astype(str)
    return df

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.5rem;
    }
    .metric-label { font-size: 13px; color: #888; margin: 0; }
    .metric-value { font-size: 26px; font-weight: 600; margin: 0; }
    .section-title {
        font-size: 13px;
        font-weight: 600;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 1.5rem 0 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_refresh = st.columns([6, 1])
with col_title:
    st.title("📊 Ops Performance Dashboard")
with col_refresh:
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Live data from SmartSuite · Last loaded: {datetime.now().strftime('%b %d, %Y at %H:%M')}")
st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────
df = load_data()

if df.empty:
    st.warning("No data loaded. Check your API key and IDs.")
    st.stop()

# ── Column helpers ────────────────────────────────────────────────────────────
POD_COL        = "Pod"
STATUS_COL     = "In Advanced / Delayed / On time"
TYPE_COL       = "Type"
PROJ_STATUS    = "Project Status"

PHASE_COLS = {
    "Copy phase":            'Days in "Copy Phase"',
    "Design phase":          'Days in "Design Phase"',
    "Flow sent to QA":       'Days in "Flow Sent to QA"',
    "Uploaded & previews":   'Days in "Uploaded and Previews Sent"',
    "Revisions needed":      'Days in "Revisions Needed"',
    "AM revision":           'Days in "AM Revision Phase"',
    "Waiting on client":     'Days in "Waiting on client\'s review"',
    "Ready for Klaviyo":     'Days in "Ready For Klaviyo"',
    "Briefing":              'Days in "Briefing"',
}

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")

pods = sorted(df[POD_COL].dropna().unique()) if POD_COL in df.columns else []
selected_pods = st.sidebar.multiselect("Pod", pods, default=pods)

types_available = []
if TYPE_COL in df.columns:
    types_available = sorted(df[TYPE_COL].dropna().unique())
selected_types = st.sidebar.multiselect("Type", types_available, default=types_available)

# Apply filters
mask = pd.Series([True] * len(df))
if selected_pods and POD_COL in df.columns:
    mask &= df[POD_COL].isin(selected_pods)
if selected_types and TYPE_COL in df.columns:
    mask &= df[TYPE_COL].isin(selected_types)
df = df[mask]

# ── Summary metrics ───────────────────────────────────────────────────────────
total = len(df)
delayed = (df[STATUS_COL] == "Delayed").sum() if STATUS_COL in df.columns else 0
on_time = (df[STATUS_COL] == "On time").sum() if STATUS_COL in df.columns else 0
in_advance = (df[STATUS_COL] == "In advanced").sum() if STATUS_COL in df.columns else 0
delay_rate = round(delayed / (delayed + on_time + in_advance) * 100, 1) if (delayed + on_time + in_advance) > 0 else 0

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Total records</p><p class="metric-value">{total:,}</p></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delivered in advance</p><p class="metric-value" style="color:#1a7f54">{in_advance:,}</p></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delayed</p><p class="metric-value" style="color:#e24b4a">{delayed:,}</p></div>', unsafe_allow_html=True)
with c4:
    color = "#e24b4a" if delay_rate > 25 else "#ba7517" if delay_rate > 15 else "#1a7f54"
    st.markdown(f'<div class="metric-card"><p class="metric-label">Overall delay rate</p><p class="metric-value" style="color:{color}">{delay_rate}%</p></div>', unsafe_allow_html=True)

# ── Pod performance ───────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Pod delay rate</p>', unsafe_allow_html=True)

if POD_COL in df.columns and STATUS_COL in df.columns:
    pod_stats = df.groupby(POD_COL).agg(
        total=(POD_COL, "count"),
        delayed=(STATUS_COL, lambda x: (x == "Delayed").sum()),
        on_time=(STATUS_COL, lambda x: (x == "On time").sum()),
        in_advance=(STATUS_COL, lambda x: (x == "In advanced").sum()),
    ).reset_index()
    pod_stats = pod_stats[pod_stats["total"] >= 50]
    pod_stats["delay_rate"] = (
        pod_stats["delayed"] / (pod_stats["delayed"] + pod_stats["on_time"] + pod_stats["in_advance"]) * 100
    ).round(1)
    pod_stats = pod_stats.sort_values("delay_rate")

    def pod_color(r):
        if r < 15: return "#1D9E75"
        if r < 30: return "#BA7517"
        return "#E24B4A"

    colors = [pod_color(r) for r in pod_stats["delay_rate"]]
    fig_pod = go.Figure(go.Bar(
        x=pod_stats["delay_rate"],
        y=pod_stats[POD_COL],
        orientation="h",
        marker_color=colors,
        text=[f"{r}%" for r in pod_stats["delay_rate"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Delay rate: %{x:.1f}%<extra></extra>",
    ))
    fig_pod.update_layout(
        height=max(400, len(pod_stats) * 28),
        margin=dict(l=0, r=60, t=10, b=10),
        xaxis=dict(title="Delay rate %", ticksuffix="%"),
        yaxis=dict(title=""),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_pod, use_container_width=True)

# ── Bottleneck + Type side by side ────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.markdown('<p class="section-title">Where time is lost (avg days per phase)</p>', unsafe_allow_html=True)
    phase_avgs = {}
    for label, col in PHASE_COLS.items():
        if col in df.columns:
            avg = pd.to_numeric(df[col], errors="coerce").mean()
            if not pd.isna(avg):
                phase_avgs[label] = round(avg, 2)

    if phase_avgs:
        phase_df = pd.DataFrame(list(phase_avgs.items()), columns=["Phase", "Avg days"]).sort_values("Avg days", ascending=True)
        colors_b = ["#E24B4A" if v > 5 else "#BA7517" if v > 2 else "#1D9E75" for v in phase_df["Avg days"]]
        fig_b = go.Figure(go.Bar(
            x=phase_df["Avg days"], y=phase_df["Phase"],
            orientation="h", marker_color=colors_b,
            text=[f"{v}d" for v in phase_df["Avg days"]],
            textposition="outside",
        ))
        fig_b.update_layout(
            height=320, margin=dict(l=0, r=50, t=10, b=10),
            xaxis=dict(title="Avg days"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_b, use_container_width=True)

with col_r:
    st.markdown('<p class="section-title">Delay rate by project type</p>', unsafe_allow_html=True)
    if TYPE_COL in df.columns and STATUS_COL in df.columns:
        core_types = ["Campaign", "Flow", "SMS", "Side Quest", "Text Based - Campaign"]
        type_df = df[df[TYPE_COL].isin(core_types)].copy()
        type_stats = type_df.groupby(TYPE_COL).apply(
            lambda x: round((x[STATUS_COL] == "Delayed").sum() / len(x) * 100, 1)
        ).reset_index()
        type_stats.columns = ["Type", "Delay rate %"]
        type_stats = type_stats.sort_values("Delay rate %")
        colors_t = ["#E24B4A" if v > 30 else "#BA7517" if v > 12 else "#1D9E75" for v in type_stats["Delay rate %"]]
        fig_t = go.Figure(go.Bar(
            x=type_stats["Type"], y=type_stats["Delay rate %"],
            marker_color=colors_t,
            text=[f"{v}%" for v in type_stats["Delay rate %"]],
            textposition="outside",
        ))
        fig_t.update_layout(
            height=320, margin=dict(l=0, r=20, t=10, b=10),
            yaxis=dict(title="Delay rate %", ticksuffix="%"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_t, use_container_width=True)

# ── Monthly volume ────────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Monthly volume & delays</p>', unsafe_allow_html=True)

if "month" in df.columns and STATUS_COL in df.columns:
    monthly = df.groupby("month").agg(
        total=("month", "count"),
        delayed=(STATUS_COL, lambda x: (x == "Delayed").sum()),
    ).reset_index()
    monthly = monthly[monthly["month"] >= "2024-01"].sort_values("month")

    fig_m = go.Figure()
    fig_m.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total"],
        name="Total", fill="tozeroy",
        line=dict(color="#378ADD", width=2),
        fillcolor="rgba(55,138,221,0.1)",
    ))
    fig_m.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["delayed"],
        name="Delayed", line=dict(color="#E24B4A", width=2, dash="dot"),
    ))
    fig_m.update_layout(
        height=260, margin=dict(l=0, r=20, t=10, b=10),
        legend=dict(orientation="h", y=1.1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_m, use_container_width=True)

# ── Pod detail table ──────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Pod detail breakdown</p>', unsafe_allow_html=True)

if POD_COL in df.columns:
    agg_dict = {
        "Total": (POD_COL, "count"),
        "Delayed": (STATUS_COL, lambda x: (x == "Delayed").sum()),
        "Delay rate %": (STATUS_COL, lambda x: round((x == "Delayed").sum() / max(len(x), 1) * 100, 1)),
    }
    for label, col in list(PHASE_COLS.items())[:4]:
        if col in df.columns:
            agg_dict[f"Avg {label} (d)"] = (col, lambda x: round(pd.to_numeric(x, errors="coerce").mean(), 1))

    detail = df.groupby(POD_COL).agg(**agg_dict).reset_index()
    detail = detail[detail["Total"] >= 50].sort_values("Delay rate %")
    st.dataframe(detail, use_container_width=True, hide_index=True)

# ── AI insights ───────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 💬 Ask Claude about your data")
st.caption("Type a question and Claude will analyze the live data to answer it.")

question = st.text_input("", placeholder="e.g. Which pod should we hire for first? Why are flows so delayed?")

if question:
    summary = f"""
You are analyzing operational data from a marketing agency's SmartSuite system.

Key stats:
- Total records: {total:,}
- Overall delay rate: {delay_rate}%
- Biggest bottleneck: Copy phase (avg 7.3 days)
- Flow delay rate: 42.5% vs Campaign delay rate: 6%

Pod delay rates (sorted best to worst):
{pod_stats[['Pod','total','delay_rate']].to_string(index=False) if POD_COL in df.columns and STATUS_COL in df.columns else 'N/A'}

Monthly volume (recent):
{monthly[['month','total','delayed']].tail(6).to_string(index=False) if 'month' in df.columns else 'N/A'}

Question: {question}

Answer concisely and practically. Focus on actionable insights.
"""
    with st.spinner("Analyzing..."):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=600,
                messages=[{"role": "user", "content": summary}]
            )
            st.info(msg.content[0].text)
        except Exception as e:
            st.error(f"Claude API error: {e}")
