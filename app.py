from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# Secret key for session encryption
app.secret_key = "your_secret_key_here"

# MongoDB Connection
client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["ecogrid"]
users = db["users"]

@app.route("/")
def home():
    user = session.get("user")  # Check if user is logged in
    return render_template("index.html", user=user)

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

# ✅ Signup API
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json
    if users.find_one({"email": data["email"]}):
        return jsonify({"message": "Email already exists!"}), 400

    hashed = generate_password_hash(data["password"])
    user_data = {
        "name": data["name"],
        "email": data["email"],
        "password": hashed,
        "location": {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude")
        }
    }
    users.insert_one(user_data)
    return jsonify({"message": "Signup successful!"}), 201

# ✅ Login API
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = users.find_one({"email": data["email"]})
    if not user or not check_password_hash(user["password"], data["password"]):
        return jsonify({"message": "Invalid email or password!"}), 401

    session["user"] = {"name": user["name"], "email": user["email"]}
    return jsonify({"message": f"Welcome {user['name']}!"})

# ✅ Logout route
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
    
# ✅ Location route
@app.route("/api/locations")
def get_locations():
    locations = []
    for user in users.find({}, {"_id": 0, "location": 1}):
        loc = user.get("location")
        if loc and loc.get("latitude") and loc.get("longitude"):
            locations.append([loc["latitude"], loc["longitude"]])
    return jsonify(locations)


# ✅ heatmap route
@app.route("/heatmap")
def heatmap_page():
    return render_template("heatmap.html", user=session.get("user"))
