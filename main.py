from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
import psycopg2, secrets, stripe, os

app = Flask(__name__)
app.secret_key = 'super-secret-key'
serializer = URLSafeTimedSerializer(app.secret_key)
stripe.api_key = os.getenv("Idio")
accounts_counter = 0

def connect_db():
    return psycopg2.connect(
        host="ep-late-cherry-adgy6c1t.c-2.us-east-1.aws.neon.tech",
        database="neondb",
        user="neondb_owner",
        password="npg_eHcYaBiT4lD8",
        port=5432
    )

def init_db():
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_verified BOOLEAN DEFAULT FALSE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                price NUMERIC NOT NULL,
                discount INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS donations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                type TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                message TEXT NOT NULL
            );
        """)
        conn.commit()

def generate_token(email):
    return serializer.dumps(email, salt="email-confirm")

def verify_token(token, max_age=3600):
    try:
        return serializer.loads(token, salt="email-confirm", max_age=max_age)
    except Exception:
        return None

@app.route("/register", methods=["GET", "POST"])
def register():
    global accounts_counter
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        token = generate_token(email)

        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (email, password, username) VALUES (%s, %s) ON CONFLICT DO NOTHING", (email, password, username))
            conn.commit()

        accounts_counter += 1
        return render_template("confirm_email.html", token=token)

    return render_template("register.html")

@app.route("/verify")
def verify_email():
    token = request.args.get("token")
    email = verify_token(token)

    if email:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_verified = TRUE WHERE email = %s", (email,))
            conn.commit()
        return redirect(url_for("login"))
    return "Invalid or expired token", 400

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, password, is_verified FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
            if user and check_password_hash(user[1], password):
                session["user_id"] = user[0]
                session["is_verified"] = user[2]
                session.permanent = True
                return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/donate", methods=["GET", "POST"])
def donate():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        limb = request.form["limb"]
        width = float(request.form["width"])
        length = float(request.form["length"])
        reason = request.form["reason"]
        description = request.form["description"]
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO donations (user_id, width, length, limb, reason, description)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session["user_id"], width, length, limb, reason, description))
            cur.execute("UPDATE users SET is_verified = TRUE WHERE id = %s", (session["user_id"],))
            conn.commit()
        session["is_verified"] = True
        return redirect(url_for("home"))
    return render_template("donate.html")
    
@app.route("/buy", methods=["GET", "POST"])
def buy():
    if "user_id" not in session:
        return redirect(url_for("login"))

    price = 100
    discount = 15 if session.get("is_verified") else 0

    with connect_db() as conn:
        cur = conn.cursor()
        if request.method == "POST" and "delete_id" in request.form:
            cur.execute("DELETE FROM donations WHERE id = %s AND user_id = %s", 
                        (request.form["delete_id"], session["user_id"]))
            conn.commit()
            return redirect(url_for("buy"))
        cur.execute("""
            SELECT d.id, d.limb, d.width, d.length, d.reason, u.username, d.user_id, d.description
            FROM donations d
            JOIN users u ON u.id = d.user_id
            WHERE d.id NOT IN (SELECT donation_id FROM purchases WHERE donation_id IS NOT NULL)
        """)
        available_donations = cur.fetchall()

    return render_template("buy.html", price=price, discount=discount, final_price=price - (price * discount / 100), donations=available_donations)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        message = request.form["message"]
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO contacts (user_id, message) VALUES (%s, %s)", (session["user_id"], message))
            conn.commit()
        return redirect(url_for("home"))
    return render_template("contact.html")

@app.route("/messages", methods=["GET", "POST"])
def messages():
    if "user_id" not in session:
        return redirect(url_for("login"))

    with connect_db() as conn:
        cur = conn.cursor()

        if request.method == "POST":
            if "message" in request.form:
                cur.execute("INSERT INTO contacts (user_id, message) VALUES (%s, %s)", (session["user_id"], request.form["message"]))
            elif "delete_id" in request.form:
                cur.execute("DELETE FROM contacts WHERE id = %s AND user_id = %s", (request.form["delete_id"], session["user_id"]))
            conn.commit()

        cur.execute("""
            SELECT contacts.id, message, users.email, contacts.user_id
            FROM contacts
            JOIN users ON contacts.user_id = users.id
            ORDER BY contacts.id DESC
        """)
        all_messages = cur.fetchall()

    return render_template("messages.html", messages=all_messages)

@app.route("/")
def home():
    return render_template("home.html", accounts_counter=accounts_counter)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/about")
def about():
    return render_template("about.html")

def init_counter():
    global accounts_counter
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        accounts_counter = cur.fetchone()[0]

@app.route("/purchase/<int:donation_id>", methods=["POST"])
def purchase_donation(donation_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    price = float(request.form["price"])
    discount = float(request.form["discount"])

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO purchases (user_id, price, discount, donation_id) VALUES (%s, %s, %s, %s)",
            (session["user_id"], price, discount, donation_id),
        )
        conn.commit()

    return redirect(url_for("home"))

@app.route("/checkout", methods=["POST"])
def checkout():
    if "user_id" not in session:
        return redirect(url_for("login"))

    price = float(request.form["price"])
    discount = float(request.form["discount"])
    final_price = int((price - (price * discount / 100)) * 100)
    donation_id = int(request.form["donation_id"])
    session["pending_donation_id"] = donation_id

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Prosthetic Donation",
                    },
                    "unit_amount": final_price,
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        billing_address_collection="required",
        shipping_address_collection={
            "allowed_countries": ["US", "CA", "DE", "FR", "IN", "GB"]
        },
        success_url=url_for("home", _external=True),
        cancel_url=url_for("buy", _external=True),
    )

    return redirect(str(checkout_session.url), code=303)

if __name__ == "__main__":
    init_db()
    init_counter()
    app.run(debug=True)
