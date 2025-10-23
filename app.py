from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import io
from twilio.rest import Client

# ------------------ APP SETUP ------------------
app = Flask(__name__)
CORS(app)
app.secret_key = "your_secret_key_here"


# # ------------------ TWILIO CONFIG ------------------


# ------------------ SUBSCRIPTION PLANS ------------------
# ------------------ DATABASE ------------------
client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["ecogrid"]
users = db["users"]


plans = [
    {"id": 1, "name": "Starter Plan", "price": 199, "power_output": "50 kWh/month"},
    {"id": 2, "name": "Pro Plan", "price": 499, "power_output": "150 kWh/month"},
    {"id": 3, "name": "Enterprise Plan", "price": 999, "power_output": "500 kWh/month"},
]

# ========================================================
#                       FRONTEND ROUTES
# ========================================================

@app.route("/")
def home():
    user = session.get("user")
    return render_template("index.html", user=user, plans=plans)

@app.route("/about")
def about():
    return render_template("about.html", user=session.get("user"))

@app.route("/contact")
def contact():
    return render_template("contact.html", user=session.get("user"))

@app.route("/login")
def login_page():
    if "user" in session:
        return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/signup")
def signup_page():
    if "user" in session:
        return redirect(url_for("home"))
    return render_template("signup.html")

@app.route("/heatmap")
def heatmap_page():
    return render_template("heatmap.html", user=session.get("user"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ========================================================
#                       AUTH APIS
# ========================================================

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    mobile = data.get("mobile")
    password = data.get("password")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not all([name, email, mobile, password]):
        return jsonify({"message": "All fields are required"}), 400

    if users.find_one({"email": email}):
        return jsonify({"message": "Email already registered"}), 409
    if users.find_one({"mobile": mobile}):
        return jsonify({"message": "Mobile already registered"}), 409

    hashed_password = generate_password_hash(password)
    users.insert_one({
        "name": name,
        "email": email,
        "mobile": mobile,
        "password": hashed_password,
        "location": {"latitude": latitude, "longitude": longitude},
        "plan": None,
        "role": "user"
    })
    return jsonify({"message": "Signup successful! Please log in."}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    user = users.find_one({"email": email})
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"message": "Invalid credentials"}), 401

    session["user"] = {"name": user["name"], "email": user["email"]}
    return jsonify({"message": f"Welcome {user['name']}!"}), 200


@app.route("/get_user_details")
def get_user_details():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 403
    user = users.find_one({"email": session["user"]["email"]}, {"_id": 0, "password": 0})
    return jsonify(user)

# ========================================================
#                     UTILITY FEATURES
# ========================================================

# --------------- QR Code Generator ----------------
@app.route("/generate_qr", methods=["POST"])
def generate_qr():
    data = request.get_json()
    payment_url = data.get("payment_url")

    if not payment_url:
        return jsonify({"error": "Payment URL missing"}), 400

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(payment_url)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")

# --------------- SMS Sender ----------------
@app.route("/send_sms", methods=["POST"])
def send_sms():
    if "user" not in session:
        return jsonify({"success": False, "message": "Login required"}), 403

    data = request.get_json()
    message = data.get("message", "Thank you for subscribing to EcoGrid!")

    # Fetch logged-in user's details from MongoDB
    user = users.find_one({"email": session["user"]["email"]})

    if not user or "mobile" not in user:
        return jsonify({"success": False, "message": "User mobile number not found"}), 400

    phone = user["mobile"]
    if not phone.startswith("+"):
        phone = f"+91{phone}"  # Automatically add Indian country code if missing

    try:
        # 🔍 Check if this mobile number is verified in Twilio (for trial accounts)
        verified_numbers = [num.phone_number for num in twilio_client.outgoing_caller_ids.list()]
        if phone not in verified_numbers:
            return jsonify({
                "success": False,
                "message": f"The number {phone} is not verified in your Twilio trial account."
            }), 403

        # ✅ Send SMS via Twilio
        twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone
        )

        # ✅ Save user's plan info in MongoDB
        users.update_one(
            {"email": session["user"]["email"]},
            {"$set": {"plan": message}}
        )

        return jsonify({"success": True, "message": f"SMS sent successfully to {phone}!"})

    except Exception as e:
        return jsonify({"success": False, "message": f"Twilio Error: {str(e)}"}), 500
# --------------- Get All User Locations ----------------
@app.route("/api/locations")
def get_locations():
    locations = []
    for user in users.find({}, {"_id": 0, "location": 1}):
        loc = user.get("location")
        if loc and loc.get("latitude") and loc.get("longitude"):
            locations.append([loc["latitude"], loc["longitude"]])
    return jsonify(locations)

# --------------- Get Subscription Plans ----------------
@app.route("/plans", methods=["GET"])
def get_plans():
    return jsonify(plans)

# ========================================================
#                       RUN APP
# ========================================================
if __name__ == "__main__":
    app.run(debug=True, port=5000)
