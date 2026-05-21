import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import re
import gc
from datetime import datetime

st.set_page_config(page_title="Ops Dashboard", page_icon="📊", layout="wide")

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY    = st.secrets.get("API_KEY", "")
ACCOUNT_ID = "svxkeb0y"
TABLE_ID   = "685953c5a74d7ddd3b1e6673"

# ── Field ID mapping (discovered from exported CSV) ───────────────────────────
POD_COL    = "scf1dc881f"       # 3-value dropdown: KZwgy / sHh5R / ozGeF
STATUS_COL = "s008c70baa"       # 🟢 Ideal / 🔴 Risky / 🟡 Normal
STATUS_COL2= "s2f22559d5"       # backup status col with same values

# Phase duration columns → human-readable labels
PHASE_COLS = {
    "Copy Phase":          "s250b98c1d",
    "Design Phase":        "s1a9551b92",
    "Flow sent to QA":     "s7cfa3b89a",
    "Uploaded & Previews": "sb22b37bcf",
    "Revisions Needed":    "sb9b18a3c0",
    "AM Revision":         "s01861926d",
    "Waiting on Client":   "s6fd2af8c9",
    "Ready for Klaviyo":   "sc2aecb8af",
    "Briefing":            "sg4y64ur",
}

# Status label mapping
STATUS_MAP = {
    "🟢 Ideal":  "On time",
    "🔴 Risky":  "Delayed",
    "🟡 Normal": "In advance",
}

def extract_date(val):
    if not val:
        return None
    try:
        import json
        d = json.loads(val)
        if isinstance(d, dict) and "on" in d:
            return d["on"]
    except Exception:
        pass
    m = re.search(r'on (.+)$', str(val))
    return m.group(1).strip() if m else str(val)

def infer_type(title):
    """Infer email/sms type from record title."""
    if not isinstance(title, str):
        return "Other"
    t = title.strip().upper()
    if t.startswith("SMS"):
        return "SMS"
    if "FLOW" in t:
        return "Flow"
    if "CAMPAIGN" in t:
        return "Campaign"
    if "SIDE QUEST" in t:
        return "Side Quest"
    return "Other"

def fetch_page(offset, limit, headers):
    url = f"https://app.smartsuite.com/api/v1/applications/{TABLE_ID}/records/list/"
    try:
        resp = requests.post(
            url, headers=headers,
            json={"limit": limit, "offset": offset},
            timeout=30
        )
        if resp.status_code != 200:
            st.warning(f"API error {resp.status_code} at offset {offset}: {resp.text[:200]}")
            return None, 0
        data = resp.json()
        return data.get("items", []), data.get("total", 0)
    except Exception as e:
        st.warning(f"Request failed at offset {offset}: {e}")
        return None, 0

@st.cache_data(ttl=3600, max_entries=1)
def load_all_data():
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Account-Id": ACCOUNT_ID,
        "Content-Type": "application/json",
    }

    first_batch, total = fetch_page(0, 250, headers)
    if first_batch is None:
        st.error("❌ Could not connect to SmartSuite. Check API key in Streamlit secrets.")
        return pd.DataFrame()
    if total == 0 and not first_batch:
        st.warning("⚠️ API connected but 0 records. Check TABLE_ID / ACCOUNT_ID.")
        return pd.DataFrame()

    st.info(f"📦 Table reports **{total:,}** records. Fetching all...")

    rows = []
    limit = 250
    seen_ids = set()

    def add_batch(batch):
        for record in batch:
            rid = record.get("id") or record.get("fields", {}).get("id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            fields = record.get("fields", record)
            rows.append(fields)

    add_batch(first_batch)

    offsets = list(range(limit, total, limit))
    progress = st.progress(0, text=f"Loaded {len(rows):,} / {total:,}...")

    for i, offset in enumerate(offsets):
        batch, _ = fetch_page(offset, limit, headers)
        if not batch:
            break
        add_batch(batch)
        progress.progress(min(len(rows) / total, 1.0), text=f"Loaded {len(rows):,} / {total:,}...")
        if len(rows) >= total:
            break
        gc.collect()

    progress.empty()
    st.success(f"✅ Loaded **{len(rows):,}** unique records.")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse creation date
    if "first_created" in df.columns:
        df["month"] = pd.to_datetime(
            df["first_created"].apply(extract_date), format="mixed", errors="coerce"
        ).dt.to_period("M").astype(str)
    elif "First Created" in df.columns:
        df["month"] = pd.to_datetime(
            df["First Created"].apply(extract_date), format="mixed", errors="coerce"
        ).dt.to_period("M").astype(str)

    # Normalise status → readable label
    if STATUS_COL in df.columns:
        df["Status"] = df[STATUS_COL].map(STATUS_MAP).fillna("Unknown")
    elif STATUS_COL2 in df.columns:
        df["Status"] = df[STATUS_COL2].map(STATUS_MAP).fillna("Unknown")
    else:
        df["Status"] = "Unknown"

    # Infer type from title
    title_col = "title" if "title" in df.columns else None
    if title_col:
        df["Type"] = df[title_col].apply(infer_type).astype("category")

    # Pod column (keep raw IDs for now — use as-is for grouping)
    if POD_COL in df.columns:
        df["Pod"] = df[POD_COL].astype("category")

    # Coerce phase columns to numeric
    for label, fid in PHASE_COLS.items():
        if fid in df.columns:
            df[label] = pd.to_numeric(df[fid], errors="coerce").astype("float32")

    df["Status"] = df["Status"].astype("category")
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
df = load_all_data()

if df.empty:
    st.warning("No data loaded.")
    with st.expander("🔍 Debug info"):
        st.write(f"- `API_KEY` set: `{'Yes' if API_KEY else 'No — add to secrets!'}`")
        st.write(f"- `ACCOUNT_ID`: `{ACCOUNT_ID}`")
        st.write(f"- `TABLE_ID`: `{TABLE_ID}`")
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")

if "month" in df.columns:
    months = sorted(df["month"].dropna().unique())
    if len(months) >= 2:
        sel = st.sidebar.select_slider(
            "Date range", options=months,
            value=(months[max(0, len(months)-6)], months[-1])
        )
        df = df[(df["month"] >= sel[0]) & (df["month"] <= sel[1])]

pods = sorted(df["Pod"].dropna().unique()) if "Pod" in df.columns else []
sel_pods = st.sidebar.multiselect("Pod", pods, default=pods)

types = sorted(df["Type"].dropna().unique()) if "Type" in df.columns else []
sel_types = st.sidebar.multiselect("Type", types, default=types)

if sel_pods and "Pod" in df.columns:
    df = df[df["Pod"].isin(sel_pods)]
if sel_types and "Type" in df.columns:
    df = df[df["Type"].isin(sel_types)]

# ── Raw data explorer ─────────────────────────────────────────────────────────
with st.expander("🗂️ Raw data explorer"):
    st.dataframe(df[["title","Status","Pod","Type","month"] + list(PHASE_COLS.keys()) if "title" in df.columns else df].head(200),
                 use_container_width=True, height=300)
    st.caption(f"{len(df):,} rows · {len(df.columns)} columns")

# ── Metrics ───────────────────────────────────────────────────────────────────
total      = len(df)
delayed    = int((df["Status"] == "Delayed").sum())
on_time    = int((df["Status"] == "On time").sum())
in_advance = int((df["Status"] == "In advance").sum())
denom      = delayed + on_time + in_advance
delay_rate = round(delayed / denom * 100, 1) if denom > 0 else 0

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Total records</p><p class="metric-value">{total:,}</p></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><p class="metric-label">On time / In advance</p><p class="metric-value" style="color:#1a7f54">{on_time + in_advance:,}</p></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delayed (Risky)</p><p class="metric-value" style="color:#e24b4a">{delayed:,}</p></div>', unsafe_allow_html=True)
with m4:
    clr = "#e24b4a" if delay_rate > 25 else "#ba7517" if delay_rate > 15 else "#1a7f54"
    st.markdown(f'<div class="metric-card"><p class="metric-label">Delay rate</p><p class="metric-value" style="color:{clr}">{delay_rate}%</p></div>', unsafe_allow_html=True)

# ── Pod delay rate ────────────────────────────────────────────────────────────
pod_stats = None
if "Pod" in df.columns:
    st.markdown('<p class="section-title">Pod delay rate</p>', unsafe_allow_html=True)
    pod_stats = df.groupby("Pod", observed=True).agg(
        total=("Pod", "count"),
        delayed=("Status", lambda x: (x == "Delayed").sum()),
        on_time=("Status", lambda x: (x == "On time").sum()),
        in_advance=("Status", lambda x: (x == "In advance").sum()),
    ).reset_index()
    pod_stats = pod_stats[pod_stats["total"] >= 5]
    pod_stats["delay_rate"] = (
        pod_stats["delayed"] / (pod_stats["delayed"] + pod_stats["on_time"] + pod_stats["in_advance"]) * 100
    ).round(1)
    pod_stats = pod_stats.sort_values("delay_rate")

    colors = ["#1D9E75" if r < 15 else "#BA7517" if r < 30 else "#E24B4A" for r in pod_stats["delay_rate"]]
    fig = go.Figure(go.Bar(
        x=pod_stats["delay_rate"], y=pod_stats["Pod"].astype(str), orientation="h",
        marker_color=colors,
        text=[f"{r}%" for r in pod_stats["delay_rate"]], textposition="outside",
        hovertemplate="<b>Pod %{y}</b><br>Delay rate: %{x:.1f}%<extra></extra>"
    ))
    fig.update_layout(
        height=max(300, len(pod_stats)*40),
        margin=dict(l=0, r=60, t=10, b=10),
        xaxis=dict(ticksuffix="%"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Bottleneck + Type ─────────────────────────────────────────────────────────
cl, cr = st.columns(2)
with cl:
    st.markdown('<p class="section-title">Where time is lost</p>', unsafe_allow_html=True)
    avgs = {
        lbl: round(float(df[lbl].mean()), 2)
        for lbl in PHASE_COLS
        if lbl in df.columns and df[lbl].notna().any()
    }
    if avgs:
        pf = pd.DataFrame(list(avgs.items()), columns=["Phase", "Avg days"]).sort_values("Avg days", ascending=True)
        cb = ["#E24B4A" if v > 5 else "#BA7517" if v > 2 else "#1D9E75" for v in pf["Avg days"]]
        fig2 = go.Figure(go.Bar(
            x=pf["Avg days"], y=pf["Phase"], orientation="h",
            marker_color=cb, text=[f"{v}d" for v in pf["Avg days"]], textposition="outside"
        ))
        fig2.update_layout(
            height=320, margin=dict(l=0, r=50, t=10, b=10),
            xaxis=dict(title="Avg days"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No phase duration data found.")

with cr:
    st.markdown('<p class="section-title">Delay rate by type</p>', unsafe_allow_html=True)
    if "Type" in df.columns:
        ts = df.groupby("Type", observed=True).apply(
            lambda x: round((x["Status"] == "Delayed").sum() / max(len(x), 1) * 100, 1)
        ).reset_index()
        ts.columns = ["Type", "Delay rate %"]
        ts = ts.sort_values("Delay rate %")
        ct = ["#E24B4A" if v > 30 else "#BA7517" if v > 12 else "#1D9E75" for v in ts["Delay rate %"]]
        fig3 = go.Figure(go.Bar(
            x=ts["Type"].astype(str), y=ts["Delay rate %"],
            marker_color=ct, text=[f"{v}%" for v in ts["Delay rate %"]], textposition="outside"
        ))
        fig3.update_layout(
            height=320, margin=dict(l=0, r=20, t=10, b=10),
            yaxis=dict(ticksuffix="%"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig3, use_container_width=True)

# ── Monthly volume ────────────────────────────────────────────────────────────
monthly = None
if "month" in df.columns:
    st.markdown('<p class="section-title">Monthly volume & delays</p>', unsafe_allow_html=True)
    monthly = df.groupby("month").agg(
        total=("month", "count"),
        delayed=("Status", lambda x: (x == "Delayed").sum())
    ).reset_index().sort_values("month")
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total"], name="Total",
        fill="tozeroy", line=dict(color="#378ADD", width=2), fillcolor="rgba(55,138,221,0.1)"
    ))
    fig4.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["delayed"], name="Delayed (Risky)",
        line=dict(color="#E24B4A", width=2, dash="dot")
    ))
    fig4.update_layout(
        height=240, margin=dict(l=0, r=20, t=10, b=10),
        legend=dict(orientation="h", y=1.1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
    )
    st.plotly_chart(fig4, use_container_width=True)

# ── AI Q&A ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 💬 Ask Claude about your data")
question = st.text_input("", placeholder="e.g. Which pod needs help most? What types are most delayed?")

if question:
    pod_tbl = pod_stats[["Pod", "total", "delay_rate"]].to_string(index=False) if pod_stats is not None else "N/A"
    mon_tbl = monthly[["month", "total", "delayed"]].tail(6).to_string(index=False) if monthly is not None else "N/A"
    phase_summary = "\n".join([f"  {lbl}: {round(float(df[lbl].mean()),1)}d avg" for lbl in PHASE_COLS if lbl in df.columns and df[lbl].notna().any()])
    prompt = f"""You are analyzing operational data from a marketing agency's SmartSuite system.

Total records: {total:,} | Delay rate: {delay_rate}%
Status legend: 🔴 Risky = Delayed, 🟢 Ideal = On time, 🟡 Normal = In advance

Pod performance:
{pod_tbl}

Phase durations (avg days):
{phase_summary}

Monthly volume (last 6 months):
{mon_tbl}

Question: {question}
Answer concisely and practically."""

    with st.spinner("Analyzing..."):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            st.info(msg.content[0].text)
        except Exception as e:
            st.error(f"Claude API error: {e}")
