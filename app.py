import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import re
import gc
from datetime import datetime

st.set_page_config(page_title="Ops Dashboard", page_icon="📊", layout="wide")

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY    = "df07a54caefda1693bfdad758056124fc5cc88f0"
ACCOUNT_ID = "svxkeb0y"
TABLE_ID   = "685953c5a74d7ddd3b1e6673"

# Only fetch the columns we actually need — cuts memory by ~70%
KEEP_COLS = [
    "Pod",
    "In Advanced / Delayed / On time",
    "Type",
    "First Created",
    'Days in "Copy Phase"',
    'Days in "Design Phase"',
    'Days in "Flow Sent to QA"',
    'Days in "Uploaded and Previews Sent"',
    'Days in "Revisions Needed"',
    'Days in "AM Revision Phase"',
    "Days in \"Waiting on client's review\"",
    'Days in "Ready For Klaviyo"',
    'Days in "Briefing"',
]

PHASE_COLS = {
    "Copy phase":           'Days in "Copy Phase"',
    "Design phase":         'Days in "Design Phase"',
    "Flow sent to QA":      'Days in "Flow Sent to QA"',
    "Uploaded & previews":  'Days in "Uploaded and Previews Sent"',
    "Revisions needed":     'Days in "Revisions Needed"',
    "AM revision":          'Days in "AM Revision Phase"',
    "Waiting on client":    "Days in \"Waiting on client's review\"",
    "Ready for Klaviyo":    'Days in "Ready For Klaviyo"',
    "Briefing":             'Days in "Briefing"',
}

POD_COL    = "Pod"
STATUS_COL = "In Advanced / Delayed / On time"
TYPE_COL   = "Type"

def extract_date(val):
    if not val or (isinstance(val, float)):
        return None
    m = re.search(r'on (.+)$', str(val))
    return m.group(1).strip() if m else str(val)

@st.cache_data(ttl=3600, max_entries=1)
def fetch_data():
    url = f"https://app.smartsuite.com/api/v1/applications/{TABLE_ID}/records/list/"
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Account-Id": ACCOUNT_ID,
        "Content-Type": "application/json",
    }

    rows = []
    offset = 0
    limit = 500  # smaller batches = lower peak memory

    progress = st.progress(0, text="Loading records from SmartSuite...")

    while True:
        resp = requests.post(url, headers=headers, json={"limit": limit, "offset": offset})
        if resp.status_code != 200:
            st.error(f"API error {resp.status_code}: {resp.text}")
            break

        data = resp.json()
        items = data.get("items", [])
        total_count = data.get("total", len(items))

        for record in items:
            fields = record.get("fields", record)
            # Only keep the columns we need
            slim = {k: fields.get(k) for k in KEEP_COLS if k in fields}
            rows.append(slim)

        offset += len(items)
        if total_count > 0:
            progress.progress(min(offset / total_count, 1.0), text=f"Loaded {offset:,} of {total_count:,} records...")

        if len(items) < limit:
            break

    progress.empty()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse date
    if "First Created" in df.columns:
        df["created_clean"] = df["First Created"].apply(extract_date)
        df["created_dt"] = pd.to_datetime(df["created_clean"], format="mixed", errors="coerce")
        df["month"] = df["created_dt"].dt.to_period("M").astype(str)
        df.drop(columns=["First Created", "created_clean"], inplace=True)

    # Convert phase cols to numeric now, drop the string originals
    for label, col in PHASE_COLS.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    # Downcast categoricals
    for col in [POD_COL, STATUS_COL, TYPE_COL]:
        if col in df.columns:
            df[col] = df[col].astype("category")

    gc.collect()
    return df

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card { background:#f8f9fa; border-radius:10px; padding:1rem 1.25rem; margin-bottom:0.5rem; }
    .metric-label { font-size:13px; color:#888; margin:0; }
    .metric-value { font-size:26px; font-weight:600; margin:0; }
    .section-title { font-size:13px; font-weight:600; color:#888; text-transform:uppercase; letter-spacing:.05em; margin:1.5rem 0 .5rem; }
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

# ── Load ──────────────────────────────────────────────────────────────────────
df = fetch_data()

if df.empty:
    st.warning("No data loaded. Check your API key and IDs.")
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")

# Date range filter
if "month" in df.columns:
    months = sorted(df["month"].dropna().unique())
    if months:
        default_start = months[-6] if len(months) >= 6 else months[0]
        date_range = st.sidebar.select_slider(
            "Date range",
            options=months,
            value=(default_start, months[-1])
        )
        df = df[(df["month"] >= date_range[0]) & (df["month"] <= date_range[1])]

pods = sorted(df[POD_COL].dropna().unique()) if POD_COL in df.columns else []
selected_pods = st.sidebar.multiselect("Pod", pods, default=pods)

types_available = sorted(df[TYPE_COL].dropna().unique()) if TYPE_COL in df.columns else []
selected_types = st.sidebar.multiselect("Type", types_available, default=types_available)

if selected_pods and POD_COL in df.columns:
    df = df[df[POD_COL].isin(selected_pods)]
if selected_types and TYPE_COL in df.columns:
    df = df[df[TYPE_COL].isin(selected_types)]

# ── Summary metrics ───────────────────────────────────────────────────────────
total      = len(df)
delayed    = int((df[STATUS_COL] == "Delayed").sum()) if STATUS_COL in df.columns else 0
on_time    = int((df[STATUS_COL] == "On time").sum()) if STATUS_COL in df.columns else 0
in_advance = int((df[STATUS_COL] == "In advanced").sum()) if STATUS_COL in df.columns else 0
denom      = delayed + on_time + in_advance
delay_rate = round(delayed / denom * 100, 1) if denom > 0 else 0

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

# ── Pod delay rate ────────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Pod delay rate</p>', unsafe_allow_html=True)

pod_stats = None
if POD_COL in df.columns and STATUS_COL in df.columns:
    pod_stats = df.groupby(POD_COL, observed=True).agg(
        total=(POD_COL, "count"),
        delayed=(STATUS_COL, lambda x: (x == "Delayed").sum()),
        on_time=(STATUS_COL, lambda x: (x == "On time").sum()),
        in_advance=(STATUS_COL, lambda x: (x == "In advanced").sum()),
    ).reset_index()
    pod_stats = pod_stats[pod_stats["total"] >= 30]
    pod_stats["delay_rate"] = (
        pod_stats["delayed"] / (pod_stats["delayed"] + pod_stats["on_time"] + pod_stats["in_advance"]) * 100
    ).round(1)
    pod_stats = pod_stats.sort_values("delay_rate")

    colors = ["#1D9E75" if r < 15 else "#BA7517" if r < 30 else "#E24B4A" for r in pod_stats["delay_rate"]]
    fig_pod = go.Figure(go.Bar(
        x=pod_stats["delay_rate"], y=pod_stats[POD_COL],
        orientation="h", marker_color=colors,
        text=[f"{r}%" for r in pod_stats["delay_rate"]], textposition="outside",
        hovertemplate="<b>%{y}</b><br>Delay rate: %{x:.1f}%<extra></extra>",
    ))
    fig_pod.update_layout(
        height=max(350, len(pod_stats) * 28),
        margin=dict(l=0, r=60, t=10, b=10),
        xaxis=dict(title="Delay rate %", ticksuffix="%"),
        yaxis=dict(title=""),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_pod, use_container_width=True)

# ── Bottleneck + Type ─────────────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.markdown('<p class="section-title">Where time is lost (avg days per phase)</p>', unsafe_allow_html=True)
    phase_avgs = {}
    for label, col in PHASE_COLS.items():
        if col in df.columns:
            avg = df[col].mean()
            if not pd.isna(avg):
                phase_avgs[label] = round(float(avg), 2)
    if phase_avgs:
        phase_df = pd.DataFrame(list(phase_avgs.items()), columns=["Phase", "Avg days"]).sort_values("Avg days", ascending=True)
        colors_b = ["#E24B4A" if v > 5 else "#BA7517" if v > 2 else "#1D9E75" for v in phase_df["Avg days"]]
        fig_b = go.Figure(go.Bar(
            x=phase_df["Avg days"], y=phase_df["Phase"],
            orientation="h", marker_color=colors_b,
            text=[f"{v}d" for v in phase_df["Avg days"]], textposition="outside",
        ))
        fig_b.update_layout(height=320, margin=dict(l=0, r=50, t=10, b=10),
                            xaxis=dict(title="Avg days"),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_b, use_container_width=True)

with col_r:
    st.markdown('<p class="section-title">Delay rate by project type</p>', unsafe_allow_html=True)
    if TYPE_COL in df.columns and STATUS_COL in df.columns:
        core_types = ["Campaign", "Flow", "SMS", "Side Quest", "Text Based - Campaign"]
        type_df = df[df[TYPE_COL].isin(core_types)]
        type_stats = type_df.groupby(TYPE_COL, observed=True).apply(
            lambda x: round((x[STATUS_COL] == "Delayed").sum() / max(len(x), 1) * 100, 1)
        ).reset_index()
        type_stats.columns = ["Type", "Delay rate %"]
        type_stats = type_stats.sort_values("Delay rate %")
        colors_t = ["#E24B4A" if v > 30 else "#BA7517" if v > 12 else "#1D9E75" for v in type_stats["Delay rate %"]]
        fig_t = go.Figure(go.Bar(
            x=type_stats["Type"], y=type_stats["Delay rate %"],
            marker_color=colors_t,
            text=[f"{v}%" for v in type_stats["Delay rate %"]], textposition="outside",
        ))
        fig_t.update_layout(height=320, margin=dict(l=0, r=20, t=10, b=10),
                            yaxis=dict(title="Delay rate %", ticksuffix="%"),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_t, use_container_width=True)

# ── Monthly volume ────────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Monthly volume & delays</p>', unsafe_allow_html=True)

monthly = None
if "month" in df.columns and STATUS_COL in df.columns:
    monthly = df.groupby("month").agg(
        total=("month", "count"),
        delayed=(STATUS_COL, lambda x: (x == "Delayed").sum()),
    ).reset_index().sort_values("month")

    fig_m = go.Figure()
    fig_m.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total"],
        name="Total", fill="tozeroy",
        line=dict(color="#378ADD", width=2), fillcolor="rgba(55,138,221,0.1)",
    ))
    fig_m.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["delayed"],
        name="Delayed", line=dict(color="#E24B4A", width=2, dash="dot"),
    ))
    fig_m.update_layout(height=260, margin=dict(l=0, r=20, t=10, b=10),
                        legend=dict(orientation="h", y=1.1),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_m, use_container_width=True)

# ── Pod detail table ──────────────────────────────────────────────────────────
st.markdown('<p class="section-title">Pod detail breakdown</p>', unsafe_allow_html=True)

if POD_COL in df.columns and pod_stats is not None:
    phase_means = {}
    for label, col in list(PHASE_COLS.items())[:4]:
        if col in df.columns:
            phase_means[f"Avg {label} (d)"] = df.groupby(POD_COL, observed=True)[col].mean().round(1)
    detail = pod_stats[["Pod", "total", "delayed", "delay_rate"]].rename(
        columns={"total": "Total", "delayed": "Delayed", "delay_rate": "Delay rate %"}
    )
    for col_name, series in phase_means.items():
        detail = detail.merge(series.rename(col_name).reset_index(), on=POD_COL, how="left")
    detail = detail[detail["Total"] >= 30].sort_values("Delay rate %")
    st.dataframe(detail, use_container_width=True, hide_index=True)

# ── AI insights ───────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 💬 Ask Claude about your data")
st.caption("Type a question and Claude will analyze the live data to answer it.")

question = st.text_input("", placeholder="e.g. Which pod should we hire for first? Why are flows so delayed?")

if question:
    pod_table = pod_stats[["Pod", "total", "delay_rate"]].to_string(index=False) if pod_stats is not None else "N/A"
    monthly_table = monthly[["month", "total", "delayed"]].tail(6).to_string(index=False) if monthly is not None else "N/A"

    summary = f"""You are analyzing operational data from a marketing agency's SmartSuite system.

Key stats (filtered view):
- Total records: {total:,}
- Overall delay rate: {delay_rate}%

Pod delay rates (sorted best to worst):
{pod_table}

Monthly volume (recent):
{monthly_table}

Question: {question}

Answer concisely and practically. Focus on actionable insights."""

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
