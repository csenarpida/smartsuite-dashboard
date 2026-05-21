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

PHASE_COLS = {
    "Copy phase":          'Days in "Copy Phase"',
    "Design phase":        'Days in "Design Phase"',
    "Flow sent to QA":     'Days in "Flow Sent to QA"',
    "Uploaded & previews": 'Days in "Uploaded and Previews Sent"',
    "Revisions needed":    'Days in "Revisions Needed"',
    "AM revision":         'Days in "AM Revision Phase"',
    "Waiting on client":   "Days in \"Waiting on client's review\"",
    "Ready for Klaviyo":   'Days in "Ready For Klaviyo"',
    "Briefing":            'Days in "Briefing"',
}

POD_COL    = "Pod"
STATUS_COL = "In Advanced / Delayed / On time"
TYPE_COL   = "Type"

KEEP_COLS = [POD_COL, STATUS_COL, TYPE_COL, "First Created"] + list(PHASE_COLS.values())

def extract_date(val):
    if not val:
        return None
    m = re.search(r'on (.+)$', str(val))
    return m.group(1).strip() if m else str(val)

def fetch_page(offset, limit, headers):
    url = f"https://app.smartsuite.com/api/v1/applications/{TABLE_ID}/records/list/"
    resp = requests.post(url, headers=headers, json={"limit": limit, "offset": offset}, timeout=30)
    if resp.status_code != 200:
        return None, 0
    data = resp.json()
    return data.get("items", []), data.get("total", 0)

def slim_record(fields):
    row = {}
    for k in KEEP_COLS:
        v = fields.get(k)
        if v is not None:
            row[k] = v
    return row

@st.cache_data(ttl=3600, max_entries=1)
def load_data(max_records=5000):
    """Load up to max_records, taking a representative sample if needed."""
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Account-Id": ACCOUNT_ID,
        "Content-Type": "application/json",
    }

    # First call to get total count
    items, total = fetch_page(0, 1, headers)
    if items is None:
        st.error("Could not connect to SmartSuite. Check your API key.")
        return pd.DataFrame()

    st.info(f"Found {total:,} records. Loading up to {max_records:,} for analysis...")

    rows = []
    limit = 250  # small batches
    offsets_to_fetch = []

    if total <= max_records:
        # Fetch everything
        offsets_to_fetch = list(range(0, total, limit))
    else:
        # Sample evenly across the full dataset
        step = total / max_records * limit
        offset = 0
        while offset < total and len(rows) < max_records:
            offsets_to_fetch.append(int(offset))
            offset += step

    progress = st.progress(0, text="Loading records...")

    for i, offset in enumerate(offsets_to_fetch):
        items, _ = fetch_page(int(offset), limit, headers)
        if items is None:
            break
        for record in items:
            fields = record.get("fields", record)
            rows.append(slim_record(fields))
        progress.progress((i + 1) / len(offsets_to_fetch), text=f"Loaded batch {i+1}/{len(offsets_to_fetch)}...")
        gc.collect()

    progress.empty()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse date
    if "First Created" in df.columns:
        df["month"] = pd.to_datetime(
            df["First Created"].apply(extract_date), format="mixed", errors="coerce"
        ).dt.to_period("M").astype(str)
        df.drop(columns=["First Created"], inplace=True)

    # Numeric phase cols as float32
    for col in PHASE_COLS.values():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    # Categoricals
    for col in [POD_COL, STATUS_COL, TYPE_COL]:
        if col in df.columns:
            df[col] = df[col].astype("category")

    gc.collect()
    return df

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-card{background:#f8f9fa;border-radius:10px;padding:1rem 1.25rem;margin-bottom:.5rem}
.metric-label{font-size:13px;color:#888;margin:0}
.metric-value{font-size:26px;font-weight:600;margin:0}
.section-title{font-size:13px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.05em;margin:1.5rem 0 .5rem}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
c1, c2 = st.columns([6, 1])
with c1:
    st.title("📊 Ops Performance Dashboard")
with c2:
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Live data from SmartSuite · {datetime.now().strftime('%b %d, %Y at %H:%M')}")
st.divider()

# ── Load ──────────────────────────────────────────────────────────────────────
df = load_data(max_records=500)

if df.empty:
    st.warning("No data loaded.")
    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.header("Filters")

if "month" in df.columns:
    months = sorted(df["month"].dropna().unique())
    if len(months) >= 2:
        sel = st.sidebar.select_slider("Date range", options=months,
                                        value=(months[max(0, len(months)-6)], months[-1]))
        df = df[(df["month"] >= sel[0]) & (df["month"] <= sel[1])]

pods = sorted(df[POD_COL].dropna().unique()) if POD_COL in df.columns else []
sel_pods = st.sidebar.multiselect("Pod", pods, default=pods)

types = sorted(df[TYPE_COL].dropna().unique()) if TYPE_COL in df.columns else []
sel_types = st.sidebar.multiselect("Type", types, default=types)

if sel_pods and POD_COL in df.columns:
    df = df[df[POD_COL].isin(sel_pods)]
if sel_types and TYPE_COL in df.columns:
    df = df[df[TYPE_COL].isin(sel_types)]

# ── Metrics ───────────────────────────────────────────────────────────────────
total      = len(df)
delayed    = int((df[STATUS_COL] == "Delayed").sum()) if STATUS_COL in df.columns else 0
on_time    = int((df[STATUS_COL] == "On time").sum()) if STATUS_COL in df.columns else 0
in_advance = int((df[STATUS_COL] == "In advanced").sum()) if STATUS_COL in df.columns else 0
denom      = delayed + on_time + in_advance
delay_rate = round(delayed / denom * 100, 1) if denom > 0 else 0

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Records (sample)</p><p class="metric-value">{total:,}</p></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delivered in advance</p><p class="metric-value" style="color:#1a7f54">{in_advance:,}</p></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delayed</p><p class="metric-value" style="color:#e24b4a">{delayed:,}</p></div>', unsafe_allow_html=True)
with m4:
    clr = "#e24b4a" if delay_rate > 25 else "#ba7517" if delay_rate > 15 else "#1a7f54"
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delay rate</p><p class="metric-value" style="color:{clr}">{delay_rate}%</p></div>', unsafe_allow_html=True)

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
    pod_stats = pod_stats[pod_stats["total"] >= 20]
    pod_stats["delay_rate"] = (pod_stats["delayed"] / (pod_stats["delayed"] + pod_stats["on_time"] + pod_stats["in_advance"]) * 100).round(1)
    pod_stats = pod_stats.sort_values("delay_rate")

    colors = ["#1D9E75" if r < 15 else "#BA7517" if r < 30 else "#E24B4A" for r in pod_stats["delay_rate"]]
    fig = go.Figure(go.Bar(x=pod_stats["delay_rate"], y=pod_stats[POD_COL], orientation="h",
                           marker_color=colors, text=[f"{r}%" for r in pod_stats["delay_rate"]], textposition="outside",
                           hovertemplate="<b>%{y}</b><br>%{x:.1f}%<extra></extra>"))
    fig.update_layout(height=max(300, len(pod_stats)*28), margin=dict(l=0,r=60,t=10,b=10),
                      xaxis=dict(ticksuffix="%"), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

# ── Bottleneck + Type ─────────────────────────────────────────────────────────
cl, cr = st.columns(2)
with cl:
    st.markdown('<p class="section-title">Where time is lost</p>', unsafe_allow_html=True)
    avgs = {lbl: round(float(df[col].mean()), 2) for lbl, col in PHASE_COLS.items() if col in df.columns and not pd.isna(df[col].mean())}
    if avgs:
        pf = pd.DataFrame(list(avgs.items()), columns=["Phase","Avg days"]).sort_values("Avg days", ascending=True)
        cb = ["#E24B4A" if v>5 else "#BA7517" if v>2 else "#1D9E75" for v in pf["Avg days"]]
        fig2 = go.Figure(go.Bar(x=pf["Avg days"], y=pf["Phase"], orientation="h", marker_color=cb,
                                text=[f"{v}d" for v in pf["Avg days"]], textposition="outside"))
        fig2.update_layout(height=320, margin=dict(l=0,r=50,t=10,b=10), xaxis=dict(title="Avg days"),
                           plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)

with cr:
    st.markdown('<p class="section-title">Delay rate by type</p>', unsafe_allow_html=True)
    if TYPE_COL in df.columns and STATUS_COL in df.columns:
        core = ["Campaign","Flow","SMS","Side Quest","Text Based - Campaign"]
        tdf = df[df[TYPE_COL].isin(core)]
        ts = tdf.groupby(TYPE_COL, observed=True).apply(
            lambda x: round((x[STATUS_COL]=="Delayed").sum()/max(len(x),1)*100, 1)
        ).reset_index()
        ts.columns = ["Type","Delay rate %"]
        ts = ts.sort_values("Delay rate %")
        ct = ["#E24B4A" if v>30 else "#BA7517" if v>12 else "#1D9E75" for v in ts["Delay rate %"]]
        fig3 = go.Figure(go.Bar(x=ts["Type"], y=ts["Delay rate %"], marker_color=ct,
                                text=[f"{v}%" for v in ts["Delay rate %"]], textposition="outside"))
        fig3.update_layout(height=320, margin=dict(l=0,r=20,t=10,b=10),
                           yaxis=dict(ticksuffix="%"), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig3, use_container_width=True)

# ── Monthly volume ────────────────────────────────────────────────────────────
monthly = None
if "month" in df.columns and STATUS_COL in df.columns:
    st.markdown('<p class="section-title">Monthly volume & delays</p>', unsafe_allow_html=True)
    monthly = df.groupby("month").agg(total=("month","count"), delayed=(STATUS_COL, lambda x: (x=="Delayed").sum())).reset_index().sort_values("month")
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=monthly["month"], y=monthly["total"], name="Total", fill="tozeroy",
                              line=dict(color="#378ADD",width=2), fillcolor="rgba(55,138,221,0.1)"))
    fig4.add_trace(go.Scatter(x=monthly["month"], y=monthly["delayed"], name="Delayed",
                              line=dict(color="#E24B4A",width=2,dash="dot")))
    fig4.update_layout(height=240, margin=dict(l=0,r=20,t=10,b=10), legend=dict(orientation="h",y=1.1),
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig4, use_container_width=True)

# ── AI Q&A ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 💬 Ask Claude about your data")
question = st.text_input("", placeholder="e.g. Which pod needs help most? Why are flows delayed?")

if question:
    pod_tbl = pod_stats[["Pod","total","delay_rate"]].to_string(index=False) if pod_stats is not None else "N/A"
    mon_tbl = monthly[["month","total","delayed"]].tail(6).to_string(index=False) if monthly is not None else "N/A"
    prompt = f"""Analyzing operational data from a marketing agency SmartSuite system.

Stats (sample of {total:,} records, {delay_rate}% delay rate):
Pod performance:
{pod_tbl}

Monthly volume:
{mon_tbl}

Question: {question}
Answer concisely and practically."""

    with st.spinner("Analyzing..."):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=API_KEY)
            msg = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=600,
                                         messages=[{"role":"user","content":prompt}])
            st.info(msg.content[0].text)
        except Exception as e:
            st.error(f"Claude API error: {e}")
