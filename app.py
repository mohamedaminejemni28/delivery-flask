from flask import Flask, request, jsonify
from datetime import datetime
import re
import os

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# ---------------------------
# Flask setup
# ---------------------------
app = Flask(__name__)

# ---------------------------
# Database config
# ---------------------------
USE_POSTGRES = True  # True = PostgreSQL, False = SQLite local

POSTGRES_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://delivery_lgg1_user:ZfJwJxjizV6tymcQsIBAniHrqiJnkTpZ@dpg-d688mt3nv86c73eaje8g-a/delivery_lgg1"
)

DB_URL = POSTGRES_URL if USE_POSTGRES else "sqlite:///delivery.db"

engine = create_engine(DB_URL, echo=False)
Base = declarative_base()
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)  # Session thread-safe

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

# Crée les tables si elles n'existent pas
Base.metadata.create_all(engine)

# ---------------------------
# Helpers
# ---------------------------
def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone) if phone else ""

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

def is_valid_name(name, phone):
    if not name: return False
    if name.startswith("UNKNOWN"): return False
    if name == phone: return False
    return True

# ---------------------------
# Routes
# ---------------------------
@app.route("/")
def home():
    return "Delivery API Running"

@app.route("/sms", methods=["POST"])
def receive_sms():
    session = Session()
    try:
        data = request.get_json() or request.form.to_dict() or {}
        print("RAW DATA:", data)

        phone = None
        name = None
        body = ""
        status_term = data.get("status", "").strip()

        # --- CASE 1: key custom format ---
        if "key" in data:
            raw_text = data.get("key", "").strip()
            phone_match = re.search(r"De\s*:\s*\+?(\d+)", raw_text)
            phone = normalize_phone(phone_match.group(1)) if phone_match else "UNKNOWN_" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            name_match = re.search(r"\((.*?)\)", raw_text)
            name = name_match.group(1).strip() if name_match else None
            body_match = re.search(r"\n(.+)", raw_text, re.DOTALL)
            body = body_match.group(1).strip() if body_match else raw_text

        # --- CASE 2: Twilio ---
        elif "From" in data and "Body" in data:
            phone = normalize_phone(data.get("From"))
            body = data.get("Body", "").strip()
            first_word = body.split()[0] if body else None
            name = first_word.capitalize() if first_word and not first_word.isdigit() else None

        # --- fallback ---
        else:
            raw = request.data.decode("utf-8", errors="ignore")
            phone_match = re.search(r"\+?\d{8,15}", raw)
            phone = normalize_phone(phone_match.group()) if phone_match else "UNKNOWN_" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            body = raw

        if not status_term:
            status_term = body

        latitude, longitude = extract_coordinates(body)

        # --- Search or create client ---
        client = session.query(Client).filter_by(phone=phone).first()

        if client:
            client.order_qty += 1
            client.latitude = latitude or client.latitude
            client.longitude = longitude or client.longitude
            client.status_term = status_term
            client.status = "red"
            client.last_request_time = datetime.utcnow()

            if is_valid_name(name, phone) and (not client.name or client.name == client.phone):
                client.name = name
        else:
            client = Client(
                name=name if is_valid_name(name, phone) else phone,
                phone=phone,
                order_qty=1,
                delivered_qty=0,
                status="red",
                status_term=status_term,
                latitude=latitude or 36.8065,
                longitude=longitude or 10.1815,
                last_request_time=datetime.utcnow()
            )
            session.add(client)

        # --- Save message ---
        msg = Message(phone=phone, body=status_term, received_at=datetime.utcnow())
        session.add(msg)

        session.commit()
        print("SAVED:", phone, name, status_term)
        return "OK", 200
    finally:
        Session.remove()

@app.route("/messages", methods=["GET"])
def get_messages():
    session = Session()
    try:
        messages = session.query(Message, Client).outerjoin(Client, Message.phone == Client.phone).order_by(Message.received_at.desc()).all()
        result = []
        for message, client in messages:
            display_name = client.name if client and client.name else message.phone
            result.append({
                "message_id": message.message_id,
                "phone": message.phone,
                "name": display_name,
                "body": message.body,
                "received_at": message.received_at.isoformat() if message.received_at else None
            })
        return jsonify(result)
    finally:
        Session.remove()

@app.route("/clients", methods=["GET"])
def get_clients():
    session = Session()
    try:
        clients = session.query(Client).all()
        return jsonify([{
            "client_id": c.client_id,
            "name": c.name,
            "phone": c.phone,
            "order_qty": c.order_qty,
            "delivered_qty": c.delivered_qty,
            "status": c.status,
            "status_term": c.status_term,
            "latitude": c.latitude,
            "longitude": c.longitude
        } for c in clients])
    finally:
        Session.remove()

@app.route("/deliver", methods=["POST"])
def deliver():
    session = Session()
    try:
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
    finally:
        Session.remove()

@app.route("/delete_client", methods=["POST"])
def delete_client():
    session = Session()
    try:
        data = request.get_json() or {}
        name = data.get("name")
        client = session.query(Client).filter_by(name=name).first()
        if client:
            session.delete(client)
            session.commit()
            return jsonify({"deleted": True})
        return jsonify({"deleted": False, "error": "Client not found"}), 404
    finally:
        Session.remove()

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    app.run(debug=True)
