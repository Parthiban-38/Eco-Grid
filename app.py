from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# MongoDB (Compass) Connection
client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["ecogrid"]
users = db["users"]

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/signup")
def signup_page():
    return render_template("signup.html")

# Signup API
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json
    if users.find_one({"email": data["email"]}):
        return jsonify({"message": "Email already exists!"}), 400
    hashed = generate_password_hash(data["password"])
    users.insert_one({"name": data["name"], "email": data["email"], "password": hashed})
    return jsonify({"message": "Signup successful!"}), 201

# Login API
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = users.find_one({"email": data["email"]})
    if not user or not check_password_hash(user["password"], data["password"]):
        return jsonify({"message": "Invalid email or password!"}), 401
    return jsonify({"message": f"Welcome {user['name']}!"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
