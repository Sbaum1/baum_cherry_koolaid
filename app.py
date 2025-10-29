import re
import streamlit as st
import pandas as pd
import plotly.express as px
import pgeocode
import time
import uuid  # used to regenerate widget keys on reset

# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(
    page_title="Strategic Accounts Ownership Explorer",
    page_icon="Favicon.png",      # 👈 Uses your uploaded Wausau Supply logo
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Optional mobile optimization
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        @media (max-width: 600px) {
            h1, h2, h3 {
                font-size: 1.2rem !important;
            }
            .stPlotlyChart {
                height: 420px !important;
            }
        }
        .stMultiSelect, .stSelectbox, .stCheckbox {
            margin-bottom: 12px !important;
        }
    </style>
""", unsafe_allow_html=True)

# ----------------------------
# App Title and Description
# ----------------------------
st.title("📊 Strategic Accounts Ownership Explorer")
st.caption("Cascading filters: Customer → SAM → State → ZIP. Dropdowns collapse automatically after selection.")

DATA_PATH = "Strategic_Account_Ownership_Master.xlsx"
SHEET_NAME = "Database"

# ----------------------------
# Load and clean data
# ----------------------------
@st.cache_data
def load_data():
    df = pd.read_excel(DATA_PATH, sheet_name=SHEET_NAME)
    df.columns = df.columns.str.strip()
    if "State" in df.columns:
        df["State"] = df["State"].astype(str).str.strip().str.upper()

    zip_col = next((c for c in df.columns if c.lower() in ("zip","zipcode","postal","postal_code")),
                   "Zip" if "Zip" in df.columns else None)
    if zip_col:
        df[zip_col] = df[zip_col].astype(str).str.extract(r"(\d{5})", expand=False).fillna("")
        df.rename(columns={zip_col: "Zip"}, inplace=True)

    if "Customer" not in df.columns:
        for c in df.columns:
            if re.search(r"customer|account|company", c, flags=re.I):
                df.rename(columns={c: "Customer"}, inplace=True)
                break
    df = df.apply(lambda s: s.str.strip() if s.dtype == "object" else s)
    return df

df = load_data()

# ----------------------------
# Reset logic
# ----------------------------
if "widget_suffix" not in st.session_state:
    st.session_state["widget_suffix"] = str(uuid.uuid4())

st.sidebar.header("🔍 Filters")

# --- Soft Reset button with regenerated widget keys ---
if st.sidebar.button("🔄 Reset Filters"):
    st.session_state.clear()
    st.cache_data.clear()
    st.session_state["widget_suffix"] = str(uuid.uuid4())  # force new widget keys
    st.toast("✅ Filters reset successfully!")
    time.sleep(0.6)
    st.rerun()

# Suffix makes every widget unique so reset creates new empty dropdowns
suffix = st.session_state.get("widget_suffix", "")

# ----------------------------
# Cascading Filter Controls
# ----------------------------
customers = sorted(df["Customer"].dropna().unique()) if "Customer" in df.columns else []
customer_choice = st.sidebar.multiselect("Customer(s)", customers, key=f"cust_{suffix}")

if customer_choice and "Customer" in df.columns and "WSC_SAM" in df.columns:
    sam_subset = df[df["Customer"].isin(customer_choice)]
    sam_vals = sorted(sam_subset["WSC_SAM"].dropna().unique())
else:
    sam_vals = sorted(df["WSC_SAM"].dropna().unique()) if "WSC_SAM" in df.columns else []
sam_choice = st.sidebar.multiselect("SAM(s)", sam_vals, key=f"sam_{suffix}")

state_subset = df.copy()
if customer_choice:
    state_subset = state_subset[state_subset["Customer"].isin(customer_choice)]
if sam_choice and "WSC_SAM" in state_subset.columns:
    state_subset = state_subset[state_subset["WSC_SAM"].isin(sam_choice)]
state_vals = sorted(state_subset["State"].dropna().unique().tolist())
state_choice = st.sidebar.multiselect("State(s)", state_vals, key=f"state_{suffix}")

zip_subset = state_subset.copy()
if state_choice:
    zip_subset = zip_subset[zip_subset["State"].isin(state_choice)]
zip_vals = sorted(zip_subset["Zip"].dropna().unique().tolist())
zip_choice = st.sidebar.multiselect("ZIP(s)", zip_vals, key=f"zip_{suffix}")

search_text = st.sidebar.text_input("Search any name/title/email/field", key=f"search_{suffix}")

# ----------------------------
# Stakeholder Slicers (with Email & Phone)
# ----------------------------
st.sidebar.header("👥 Stakeholder Slicers")
stakeholder_columns = {
    "WSC_SAM": "WSC_SAM",
    "WSC_VP_Sales": "WSC_VP_Sales",
    "WSC_RM": "WSC_RM",
    "WSC_Title": "WSC_Title",
    "WSC_Contact": "WSC_Contact",
    "Siding_Specialist": "Siding_Specialist",
    "Regional / Market VP/SVP": "Regional / Market VP/SVP",
    "Area Manager / District Manager / Market Manager": "Area Manager / District Manager / Market Manager",
    "General Manager / MP": "General Manager / MP",
    "Email": "Email",
    "Phone": "Phone"
}
selected_stakeholders = []
for label, col_name in stakeholder_columns.items():
    if col_name in df.columns:
        if st.sidebar.checkbox(label, value=False, key=f"slicer_{col_name}_{suffix}"):
            selected_stakeholders.append(col_name)

# ----------------------------
# Apply filters
# ----------------------------
filtered = df.copy()
if customer_choice:
    filtered = filtered[filtered["Customer"].isin(customer_choice)]
if sam_choice and "WSC_SAM" in filtered.columns:
    filtered = filtered[filtered["WSC_SAM"].isin(sam_choice)]
if state_choice:
    filtered = filtered[filtered["State"].isin(state_choice)]
if zip_choice:
    filtered = filtered[filtered["Zip"].isin(zip_choice)]
if search_text:
    patt = re.escape(search_text)
    mask = filtered.apply(lambda row: row.astype(str).str.contains(patt, case=False, na=False)).any(axis=1)
    filtered = filtered[mask]

st.write(f"### Showing {len(filtered)} matching records")

# ----------------------------
# ZIP → lat/lon
# ----------------------------
@st.cache_data
def geocode_zips(zips):
    nomi = pgeocode.Nominatim("US")
    out = nomi.query_postal_code(zips.unique().tolist())
    m = out.set_index(out["postal_code"].astype(str))[["latitude","longitude"]].to_dict(orient="index")
    return m

zip_map = geocode_zips(filtered["Zip"]) if not filtered.empty else {}
def attach_coords(df_in):
    if df_in.empty: return df_in.assign(lat=pd.NA, lon=pd.NA)
    lats,lons=[],[]
    for z in df_in["Zip"].astype(str):
        rec = zip_map.get(z)
        if rec and pd.notna(rec["latitude"]):
            lats.append(float(rec["latitude"]))
            lons.append(float(rec["longitude"]))
        else:
            lats.append(pd.NA); lons.append(pd.NA)
    return df_in.assign(lat=lats, lon=lons)
geo = attach_coords(filtered)

# ----------------------------
# Map Section
# ----------------------------
st.sidebar.header("🗺️ Map Options")
map_view = st.sidebar.radio("Map View", ["Pin Map", "Heatmap"], key=f"map_{suffix}")

has_coords = geo.dropna(subset=["lat","lon"]).shape[0] > 0
if has_coords:
    if map_view == "Pin Map":
        fig = px.scatter_mapbox(
            geo.dropna(subset=["lat","lon"]),
            lat="lat", lon="lon",
            hover_name="Customer" if "Customer" in geo.columns else None,
            hover_data={"State": True, "Zip": True, "WSC_SAM": True} if "WSC_SAM" in geo.columns else None,
            color="Customer" if "Customer" in geo.columns else None,
            zoom=3, height=560
        )
    else:
        fig = px.density_mapbox(
            geo.dropna(subset=["lat","lon"]),
            lat="lat", lon="lon",
            radius=12, mapbox_style="carto-positron",
            zoom=3, height=560
        )
    fig.update_layout(mapbox_style="carto-positron", margin=dict(l=0,r=0,t=0,b=0))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No mappable locations for current filters.")

# ----------------------------
# Results Table
# ----------------------------
st.subheader("📋 Filtered Results")
cols_to_show = ["Customer","WSC_SAM","State","Zip"]
for c in selected_stakeholders:
    if c in df.columns and c not in cols_to_show:
        cols_to_show.append(c)
for extra in ["City","Address","Branch","Region","Division"]:
    if extra in df.columns and extra not in cols_to_show:
        cols_to_show.append(extra)
filtered_to_display = filtered[cols_to_show] if set(cols_to_show).issubset(filtered.columns) else filtered
st.dataframe(filtered_to_display, use_container_width=True)

csv_bytes = filtered_to_display.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Export Filtered Data (CSV)", data=csv_bytes,
                   file_name="Filtered_Accounts.csv", mime="text/csv")

# ----------------------------
# Auto-collapse dropdowns
# ----------------------------
st.markdown("""
<script>
const selects=document.querySelectorAll('div[data-baseweb="select"]');
selects.forEach(sel=>{
 sel.addEventListener('change',()=>{document.activeElement.blur();});
});
</script>
""", unsafe_allow_html=True)


