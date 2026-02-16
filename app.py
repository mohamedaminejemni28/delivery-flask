from flask import Flask, request, jsonify
from datetime import datetime
import re
import os

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ---------------------------
# Flask setup
# ---------------------------
app = Flask(__name__)

# ---------------------------
# Database config
# ---------------------------
USE_POSTGRES = True  # True = PostgreSQL on Render, False = SQLite local

# Use Render DATABASE_URL or hardcoded Postgres URL
POSTGRES_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://delivery_lgg1_user:ZfJwJxjizV6tymcQsIBAniHrqiJnkTpZ@dpg-d688mt3nv86c73eaje8g-a/delivery_lgg1"
)

DB_URL = POSTGRES_URL if USE_POSTGRES else "sqlite:///delivery.db"

# Create engine and session
engine = create_engine(DB_URL)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# ---------------------------
# Models
# ---------------------------
class Client(Base):
    __tablename__ = "clients"
    client_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    phone = Column(String, unique=True)
    order_qty = Column(Integer, default=0)
    delivered_qty = Column(Integer, default=0)
    status = Column(String)
    status_term = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    last_request_time = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    message_id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String)
    body = Column(String)
    received_at = Column(DateTime, default=datetime.utcnow)

# Create tables if they don't exist
Base.metadata.create_all(engine)

# ---------------------------
# Helpers
# ---------------------------
def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)

def get_status(order_qty, delivered_qty):
    return "green" if delivered_qty >= order_qty else "red"

def dms_to_decimal(dms_str):
    match = re.match(r"(\d+)°\s*(\d+)'\s*([\d\.]+)\s*([NSEW])", dms_str.strip(), re.IGNORECASE)
    if not match:
        return None
    deg, minutes, seconds, direction = match.groups()
    dec = float(deg) + float(minutes)/60 + float(seconds)/3600
    if direction.upper() in ['S','W']:
        dec = -dec
    return dec

def extract_coordinates(text):
    match = re.search(r"([-+]?\d*\.\d+),\s*([-+]?\d*\.\d+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    dms_match = re.findall(r"(\d+°\s*\d+'\s*[\d\.]+\s*[NSEW])", text, re.IGNORECASE)
    if len(dms_match) == 2:
        return dms_to_decimal(dms_match[0]), dms_to_decimal(dms_match[1])
    return None, None

# ---------------------------
# Routes
# ---------------------------
@app.route("/")
def home():
    return "Delivery API Running"

@app.route("/sms", methods=["POST"])
def receive_sms():

    # Accept JSON, FORM, or RAW TEXT
    if request.is_json:
        data = request.get_json()

    elif request.form:
        data = request.form.to_dict()

    else:
        raw = request.data.decode("utf-8", errors="ignore")
        data = {
            "From": "UNKNOWN",
            "Body": raw
        }

    phone = normalize_phone(data.get("From", "UNKNOWN"))
    body = data.get("Body", "").strip()
    name = body.split()[0].capitalize() if body else "Unknown"
    status_term = data.get("status", body)

    latitude, longitude = extract_coordinates(body)

    client = session.query(Client).filter_by(phone=phone).first()

    if client:

        client.order_qty += 1
        client.latitude = latitude or client.latitude
        client.longitude = longitude or client.longitude
        client.status_term = status_term
        client.status = get_status(client.order_qty, client.delivered_qty)
        client.name = name
        client.last_request_time = datetime.utcnow()

    else:

        client = Client(
            name=name,
            phone=phone,
            order_qty=1,
            delivered_qty=0,
            status="red",
            status_term=status_term,
            latitude=latitude or 36.8065,
            longitude=longitude or 10.1815
        )

        session.add(client)

    msg = Message(phone=phone, body=status_term)

    session.add(msg)

    session.commit()

    print("SMS SAVED:", phone, status_term)

    return "OK", 200


@app.route("/clients", methods=["GET"])
def get_clients():
    clients = session.query(Client).all()
    return jsonify([
        {
            "client_id": c.client_id,
            "name": c.name,
            "phone": c.phone,
            "order_qty": c.order_qty,
            "delivered_qty": c.delivered_qty,
            "status": c.status,
            "status_term": c.status_term,
            "latitude": c.latitude,
            "longitude": c.longitude
        } for c in clients
    ])

@app.route("/deliver", methods=["POST"])
def deliver():
    data = request.get_json() or {}
    name = data.get("name")
    qty = int(data.get("delivered_qty", 1))
    client = session.query(Client).filter_by(name=name).first()
    if client:
        client.delivered_qty += qty
        client.status = get_status(client.order_qty, client.delivered_qty)
        session.commit()
        return jsonify({"status": client.status})
    return jsonify({"error": "Client not found"}), 404

@app.route("/delete_client", methods=["POST"])
def delete_client():
    data = request.get_json() or {}
    name = data.get("name")
    client = session.query(Client).filter_by(name=name).first()
    if client:
        session.delete(client)
        session.commit()
        return jsonify({"deleted": True})
    return jsonify({"deleted": False, "error": "Client not found"}), 404

@app.route("/messages", methods=["GET"])
def get_messages():
    messages = session.query(Message).all()
    result = []
    for m in messages:
        client = session.query(Client).filter_by(phone=m.phone).first()
        result.append({
            "message_id": m.message_id,
            "phone": m.phone,
            "name": client.name if client else "",
            "body": m.body,
            "received_at": m.received_at.isoformat()
        })
    return jsonify(result)

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    app.run(debug=True)
