from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
import qrcode
import io
import random
import pandas as pd
import joblib
import os
from datetime import datetime

# ------------------ APP SETUP ------------------
app = Flask(__name__)
CORS(app)
app.secret_key = "your_secret_key_here"


# ------------------ DATABASE ------------------
client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["ecogrid"]
users = db["users"]

# ------------------ MACHINE LEARNING MODEL ------------------
model_path = os.path.join(os.path.dirname(__file__), 'xgboost_electricity_model.pkl')
try:
    model = joblib.load(model_path)
    print("✅ Model loaded successfully")
except Exception as e:
    model = None
    print("⚠️ Warning: Model not loaded. Prediction endpoints may fail.", e)

# ------------------ SUBSCRIPTION PLANS ------------------
plans = [
    {"id": 1, "name": "Starter Plan", "price": 199, "power_output": "50 kWh/month", "capacity": 100},
    {"id": 2, "name": "Pro Plan", "price": 499, "power_output": "150 kWh/month", "capacity": 250},
    {"id": 3, "name": "Enterprise Plan", "price": 999, "power_output": "500 kWh/month", "capacity": 500},
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
    if "user" not in session:
        return redirect(url_for("login_page"))
    user = users.find_one({"email": session["user"]["email"]})
    if user and user.get("role") == "admin":
        return render_template("heatmap.html", user=session["user"])
    return redirect(url_for("home"))

@app.route("/admin")
def admin_page():
    if "user" in session and session["user"]["name"].lower() == "admin":
        return render_template("admin.html", user=session.get("user"))
    return redirect(url_for("login_page"))

@app.route("/user")
def user_page():
    if "user" in session:
        return render_template("user.html", user=session.get("user"))
    return redirect(url_for("login_page"))

@app.route("/logout")
def logout():
    session.pop("user", None)
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

    if not all([name, email, password]):
        return jsonify({"message": "All fields are required"}), 400

    if users.find_one({"email": email}):
        return jsonify({"message": "Email already registered"}), 409

    hashed_password = generate_password_hash(password)
    user_data = {
        "name": name,
        "email": email,
        "mobile": mobile,
        "password": hashed_password,
        "location": {"latitude": latitude, "longitude": longitude},
        "subscription": None,
        "role": "admin" if name.lower() == "admin" else "user"
    }
    users.insert_one(user_data)
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
    redirect_url = url_for("admin_page") if user["name"].lower() == "admin" else url_for("user_page")
    return jsonify({"message": f"Welcome {user['name']}!", "redirect": redirect_url}), 200

# ========================================================
#                  QR CODE & SMS FEATURES
# ========================================================
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

@app.route("/send_sms", methods=["POST"])
def send_sms():
    if "user" not in session:
        return jsonify({"success": False, "message": "Login required"}), 403

    data = request.get_json()
    message = data.get("message", "Thank you for subscribing to EcoGrid!")
    user = users.find_one({"email": session["user"]["email"]})

    if not user or not user.get("mobile"):
        return jsonify({"success": False, "message": "User mobile number not found"}), 400

    phone = user["mobile"]
    if not phone.startswith("+"):
        phone = f"+91{phone}"

    try:
        verified_numbers = [num.phone_number for num in twilio_client.outgoing_caller_ids.list()]
        if phone not in verified_numbers:
            return jsonify({
                "success": False,
                "message": f"The number {phone} is not verified in your Twilio trial account."
            }), 403

        twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone
        )

        users.update_one(
            {"email": session["user"]["email"]},
            {"$set": {"plan": message}}
        )

        return jsonify({"success": True, "message": f"SMS sent successfully to {phone}!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Twilio Error: {str(e)}"}), 500

# ========================================================
#                 LOCATION & USER DATA
# ========================================================
@app.route("/api/locations")
def get_locations():
    locations = []
    for user in users.find({}, {"_id": 0, "location": 1}):
        loc = user.get("location")
        if loc and loc.get("latitude") and loc.get("longitude"):
            locations.append([loc["latitude"], loc["longitude"]])
    return jsonify(locations)

@app.route("/get_user_details")
def get_user_details():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 403
    user = users.find_one({"email": session["user"]["email"]}, {"_id": 0, "password": 0})
    return jsonify(user)

@app.route("/api/users")
def get_all_users():
    if "user" in session and session["user"]["name"].lower() == "admin":
        all_users = list(users.find({}, {"_id": 0, "name": 1, "email": 1, "location": 1, "subscription": 1}))
        return jsonify(all_users)
    return jsonify({"message": "Unauthorized"}), 403

@app.route("/api/users/delete", methods=["POST"])
def delete_user():
    if "user" in session and session["user"]["name"].lower() == "admin":
        data = request.json
        email_to_delete = data.get("email")
        if email_to_delete.lower() == "admin":
            return jsonify({"message": "Cannot delete admin!"}), 400
        result = users.delete_one({"email": email_to_delete})
        if result.deleted_count == 1:
            return jsonify({"message": "User deleted successfully!"})
        else:
            return jsonify({"message": "User not found!"}), 404
    return jsonify({"message": "Unauthorized"}), 403

# ========================================================
#                  AI & PLAN RELATED FEATURES
# ========================================================
# Store last 7 days prediction
latest_hourly_generation = 0.0
@app.route("/api/predict_electricity")
def predict_electricity_route():
    global latest_hourly_generation
    if model is None:
        return jsonify({"error": "Model not loaded"}), 500

    # Simulate sensor readings
    solar_temp = random.uniform(5, 10)
    wastewater_flow = random.uniform(5, 10)

    # Prepare input for model
    input_df = pd.DataFrame([{
        "solar_temp": solar_temp,
        "wastewater_quantity": wastewater_flow
    }])

    try:
        predicted = model.predict(input_df)[0]
    except Exception as e:
        return jsonify({"error": f"Prediction failed: {str(e)}"}), 500
    
    predicted_per_hour = float(predicted) * 60
    latest_hourly_generation = round(predicted_per_hour,2)

    return jsonify({
        "avg_solar": float(round(solar_temp, 2)),
        "avg_wastewater": float(round(wastewater_flow, 2)),
        "predicted_electricity": float(round(predicted, 2))
    })

@app.route("/api/suggest_plan", methods=["POST"])
def suggest_plan():
    data = request.json
    fans = int(data.get("fans", 0))
    lights = int(data.get("lights", 0))
    fridges = int(data.get("fridges", 0))
    other = int(data.get("other", 0))
    global estimated_usage
    estimated_usage = (fans * 50) + (lights * 20) + (fridges * 150) + (other * 100)
    price = estimated_usage * 10
    # suggested = [plan for plan in plans if plan["capacity"] >= estimated_usage]

    return jsonify({"estimated_usage": estimated_usage, "price": price})

@app.route("/api/buy_plan", methods=["POST"])
def buy_plan():
    global latest_hourly_generation, estimated_usage

    if "user" not in session:
        return jsonify({"message": "User not logged in"}), 401

    data = request.json
    plan_name = data.get("plan_name")
    price = data.get("price")

    # ✅ Energy availability check
    if estimated_usage > latest_hourly_generation:
        return jsonify({
            "message": "⚠️ Not enough energy available. Please try again later."
        }), 400

    # ✅ Update user subscription in DB
    result = users.update_one(
        {"email": session["user"]["email"]},
        {"$set": {"subscription": {"plan": plan_name, "price": price, "paid": True}}}
    )

    if result.modified_count == 1:
        # ✅ Send confirmation SMS automatically
        user = users.find_one({"email": session["user"]["email"]})
        if user and "mobile" in user:
            phone = user["mobile"]
            if not phone.startswith("+"):
                phone = f"+91{phone}"

            message = f"✅ Hi {user.get('name', 'User')}, your EcoGrid plan '{plan_name}' has been successfully activated! Amount: ₹{price}."
            
            try:
                verified_numbers = [num.phone_number for num in twilio_client.outgoing_caller_ids.list()]
                if phone not in verified_numbers:
                    return jsonify({
                        "message": f"The number {phone} is not verified in your Twilio trial account."
                    }), 403

                twilio_client.messages.create(
                    body=message,
                    from_=TWILIO_PHONE_NUMBER,
                    to=phone
                )

                return jsonify({
                    "message": f"Successfully purchased {plan_name} and SMS sent to {phone}!"
                }), 200

            except Exception as e:
                return jsonify({
                    "message": f"Plan purchased but SMS sending failed: {str(e)}"
                }), 500

        # If user has no mobile number
        return jsonify({"message": f"Successfully purchased {plan_name}, but no mobile found."}), 200

    return jsonify({"message": "Failed to purchase plan."}), 500

@app.route("/plans", methods=["GET"])
def get_plans():
    return jsonify(plans)

@app.route("/api/allocate_energy", methods=["POST"])
def allocate_energy():
    global latest_hourly_generation
    data = request.json
    email = data.get("email")
    required_voltage = float(data.get("required_voltage", 0))

    # Simple allocation logic
    if required_voltage <= latest_hourly_generation:
        status = "✅ Allocated"
        message = (
            f"Energy successfully allocated for {email}. "
            f"Generated energy ({latest_hourly_generation}V/hr) "
            f"is sufficient for the required {required_voltage}V."
        )
        res = users.update_one(
        {"email": email},
        {"$set": {"subscription": {"plan": required_voltage, "price": required_voltage*10, "paid": True}}}
        )
        if res.modified_count>0:
            print("Updated")
        else:
            print("Not updated")   
    else:
        status = "❌ Insufficient Energy"
        message = (
            f"Cannot allocate energy for {email}. "
            f"Only {latest_hourly_generation}V/hr available, "
            f"but {required_voltage}V is required."
        )

    return jsonify({
        "user": email,
        "required_voltage": required_voltage,
        "available_voltage": latest_hourly_generation,
        "message": message,
        "status": status
    })

# ========================================================
#                       RUN APP
# ========================================================
if __name__ == "__main__":
    app.run(debug=True, port=5000)
