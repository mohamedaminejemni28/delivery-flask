import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

#API_URL = "http://127.0.0.1:5000/clients"
#DELIVER_URL = "http://127.0.0.1:5000/deliver"
#DELETE_URL = "http://127.0.0.1:5000/delete_client"
#MESSAGES_API = "http://127.0.0.1:5000/messages"
import os
BACKEND_URL = "https://delivery-flask-izwm.onrender.com" 
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000")  # si variable non définie, il prend le local
API_URL = f"{BACKEND_URL}/clients"
DELIVER_URL = f"{BACKEND_URL}/deliver"
DELETE_URL = f"{BACKEND_URL}/delete_client"
MESSAGES_API = f"{BACKEND_URL}/messages"




st.set_page_config(page_title="Delivery Control Panel", layout="wide")
st.title("🚚 Intelligent Delivery Dashboard")

# ---------------------------
# Session State for Refresh
# ---------------------------
if "refresh_trigger" not in st.session_state:
    st.session_state["refresh_trigger"] = False

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.session_state["refresh_trigger"] = not st.session_state["refresh_trigger"]

# ---------------------------
# Load Clients
# ---------------------------
@st.cache_data(ttl=5)
def load_clients():
    try:
        res = requests.get(API_URL)
        res.raise_for_status()
        return pd.DataFrame(res.json())
    except Exception as e:
        st.error(f"Failed to fetch clients: {e}")
        return pd.DataFrame()

_ = st.session_state["refresh_trigger"]
df = load_clients()

if df.empty:
    st.warning("No clients yet.")
    st.stop()

# ---------------------------
# Client Summary
# ---------------------------
st.subheader("📊 Client Summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Clients", len(df))
col2.metric("Red Clients", len(df[df["status"]=="red"]))
col3.metric("Green Clients", len(df[df["status"]=="green"]))
col4.metric("Total Orders", df["order_qty"].sum())

# ---------------------------
# Filters
# ---------------------------
st.subheader("📋 Filters")
status_filter = st.selectbox("Filter by Status", ["All", "red", "green"])
min_orders = st.number_input("Minimum Orders", min_value=0, value=0, step=1)

filtered_df = df.copy()
if status_filter != "All":
    filtered_df = filtered_df[filtered_df["status"] == status_filter]
filtered_df = filtered_df[filtered_df["order_qty"] >= min_orders]

# ---------------------------
# Data Table
# ---------------------------
def color_status(val):
    if val == "red":
        return "background-color: #ffcccc"
    elif val == "green":
        return "background-color: #ccffcc"
    return ""

st.dataframe(filtered_df.style.applymap(color_status, subset=["status"]), use_container_width=True)

# ---------------------------
# Delivery Update Section
# ---------------------------
st.subheader("📦 Update Delivery")
col1, col2, col3 = st.columns(3)

with col1:
    name = st.selectbox("Select Client Name", df["name"], key="deliver_select")
with col2:
    delivered_qty = st.number_input("Delivered Quantity", min_value=1, value=1)
with col3:
    if st.button("✅ Confirm Delivery"):
        resp = requests.post(DELIVER_URL, json={"name": name, "delivered_qty": delivered_qty})
        if resp.status_code == 200:
            st.success("Delivery updated!")
        else:
            st.error(f"Failed: {resp.json().get('error')}")
        st.cache_data.clear()
        st.session_state["refresh_trigger"] = not st.session_state["refresh_trigger"]

# ---------------------------
# Delete Client Section
# ---------------------------





st.subheader("🗑 Delete Client")
del_name = st.selectbox("Select Client to Delete", df["name"], key="delete_select")

if st.button("❌ Delete Client"):
    resp = requests.post(DELETE_URL, json={"name": del_name})
    if resp.status_code == 200 and resp.json().get("deleted"):
        st.warning("Client deleted!")
    else:
        st.error(f"Failed: {resp.json().get('error')}")
    st.cache_data.clear()
    st.session_state["refresh_trigger"] = not st.session_state["refresh_trigger"]

# ---------------------------
# Messages Section
# ---------------------------
st.subheader("📩 Recent Messages")
try:
    response = requests.get(MESSAGES_API)
    response.raise_for_status()
    messages = response.json()
except Exception as e:
    st.error(f"Failed to fetch messages: {e}")
    messages = []

if messages:
    msg_df = pd.DataFrame(messages)
    msg_df["received_at"] = pd.to_datetime(msg_df["received_at"])
    msg_df = msg_df.sort_values("received_at", ascending=False).head(10)

    # Optional filter by client
    client_filter = st.selectbox("Filter Messages by Client", ["All"] + msg_df["name"].unique().tolist())
    if client_filter != "All":
        msg_df = msg_df[msg_df["name"] == client_filter]

    for _, row in msg_df.iterrows():
        st.markdown(f"**{row['name']}** — 📱 {row['phone']} — {row['received_at']}")
        st.markdown(f"💬 {row['body']}")
        st.markdown("---")
else:
    st.info("No messages received yet.")

# ---------------------------
# Map Section
# ---------------------------
st.subheader("🗺 Client Locations")
map_center = [df["latitude"].mean(), df["longitude"].mean()]
m = folium.Map(location=map_center, zoom_start=12)

for _, row in df.iterrows():
    color = "red" if row["status"] == "red" else "green"
    popup = f"""
    <b>Name:</b> {row['name']}<br>
    <b>Phone:</b> {row['phone']}<br>
    <b>Orders:</b> {row['order_qty']}<br>
    <b>Delivered:</b> {row['delivered_qty']}<br>
    <b>Status:</b> {row['status']}
    """
    folium.Marker([row["latitude"], row["longitude"]], popup=popup, icon=folium.Icon(color=color)).add_to(m)

st_folium(m, width=1200, height=500)
