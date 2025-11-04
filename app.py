from flask import Flask, render_template, request, redirect, session, g
import sqlite3

app = Flask(__name__)
app.secret_key = "supersecretkey"

DATABASE = 'database.db'


# ---------------- DATABASE SETUP ----------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT UNIQUE,
                password TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vaccines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                stock INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                vaccine TEXT,
                date TEXT,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                vaccine_name TEXT,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Default vaccines
        cursor.execute(
            "INSERT OR IGNORE INTO vaccines(name, stock) VALUES ('Covishield', 10)")
        cursor.execute(
            "INSERT OR IGNORE INTO vaccines(name, stock) VALUES ('Covaxin', 10)")
        cursor.execute(
            "INSERT OR IGNORE INTO vaccines(name, stock) VALUES ('Sputnik V', 5)")

        db.commit()


# ---------------- ROUTES ----------------

@app.route('/')
def home():
    return render_template('index.html')


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO users(name, email, password) VALUES (?, ?, ?)", (name, email, password))
            db.commit()
            return redirect('/login')
        except:
            return "❌ User already exists!"
    return render_template('register.html')


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = cursor.fetchone()

        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            return redirect('/user_dashboard')
        else:
            return "❌ Invalid credentials!"
    return render_template('login.html')


# USER DASHBOARD
@app.route('/user_dashboard', methods=['GET', 'POST'])
def user_dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    cursor = db.cursor()

    # Get vaccines
    cursor.execute("SELECT * FROM vaccines")
    vaccines = cursor.fetchall()

    # Handle booking
    if request.method == 'POST':
        if 'vaccine' in request.form:
            vaccine = request.form['vaccine']
            date = request.form['date']

            cursor.execute(
                "SELECT stock FROM vaccines WHERE name=?", (vaccine,))
            stock = cursor.fetchone()
            if not stock or stock[0] <= 0:
                return "❌ Vaccine not available."

            cursor.execute("INSERT INTO bookings(user_id, vaccine, date) VALUES (?, ?, ?)",
                           (session['user_id'], vaccine, date))
            cursor.execute(
                "UPDATE vaccines SET stock = stock - 1 WHERE name=?", (vaccine,))
            db.commit()
        elif 'request_vaccine' in request.form:
            vaccine_name = request.form['request_vaccine']
            cursor.execute("INSERT INTO requests(user_id, vaccine_name) VALUES (?, ?)",
                           (session['user_id'], vaccine_name))
            db.commit()

    # Get bookings and requests
    cursor.execute(
        "SELECT id, vaccine, date, status FROM bookings WHERE user_id=?", (session['user_id'],))
    bookings = cursor.fetchall()

    cursor.execute(
        "SELECT vaccine_name, status FROM requests WHERE user_id=?", (session['user_id'],))
    requests_data = cursor.fetchall()

    return render_template('user_dashboard.html',
                           name=session['user_name'],
                           bookings=bookings,
                           vaccines=vaccines,
                           requests_data=requests_data)


# ADMIN LOGIN
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email == "admin@portal.com" and password == "admin123":
            session['admin'] = True
            return redirect('/admin_dashboard')
        else:
            return "❌ Invalid admin credentials!"
    return render_template('admin_login.html')


# ADMIN DASHBOARD
@app.route('/admin_dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if 'admin' not in session:
        return redirect('/admin')

    db = get_db()
    cursor = db.cursor()

    # ---------- ADMIN ACTIONS ----------
    if request.method == 'POST':
        # 1️⃣ Delete booking
        if 'delete_id' in request.form:
            cursor.execute("DELETE FROM bookings WHERE id=?",
                           (request.form['delete_id'],))

        # 2️⃣ Mark booking done
        elif 'done_id' in request.form:
            cursor.execute(
                "UPDATE bookings SET status='done' WHERE id=?", (request.form['done_id'],))

        # 3️⃣ Add new vaccine or update if exists
        elif 'new_vaccine' in request.form:
            name = request.form['new_vaccine'].strip()
            stock = int(request.form['new_stock'])
            # Insert or update vaccine
            cursor.execute(
                "INSERT OR IGNORE INTO vaccines(name, stock) VALUES (?, ?)", (name, stock))
            cursor.execute(
                "UPDATE vaccines SET stock = stock + ? WHERE name=?", (stock, name))
            # If any user requested this vaccine, mark as available
            cursor.execute(
                "UPDATE requests SET status='available now' WHERE vaccine_name=? AND status='pending'", (name,))

        # 4️⃣ Restock existing vaccine (custom quantity)
        elif 'restock_id' in request.form and 'restock_amount' in request.form:
            name = request.form['restock_id']
            amount = int(request.form['restock_amount'])
            cursor.execute(
                "UPDATE vaccines SET stock = stock + ? WHERE name=?", (amount, name))
            # Update request status if it was pending
            cursor.execute(
                "UPDATE requests SET status='available now' WHERE vaccine_name=? AND status='pending'", (name,))

        # 5️⃣ Delete a vaccine request
        elif 'delete_request' in request.form:
            cursor.execute("DELETE FROM requests WHERE id=?",
                           (request.form['delete_request'],))

        db.commit()

    # Auto remove completed bookings
    cursor.execute("DELETE FROM bookings WHERE status='done'")

    # ---------- FETCH DASHBOARD DATA ----------
    cursor.execute('''SELECT bookings.id, users.name, users.email,
                             bookings.vaccine, bookings.date, bookings.status
                      FROM bookings JOIN users ON users.id = bookings.user_id''')
    bookings = cursor.fetchall()

    cursor.execute("SELECT * FROM vaccines")
    vaccines = cursor.fetchall()

    cursor.execute('''SELECT requests.id, users.name, requests.vaccine_name, requests.status
                      FROM requests JOIN users ON users.id = requests.user_id''')
    requests_data = cursor.fetchall()

    return render_template('admin_dashboard.html',
                           bookings=bookings,
                           vaccines=vaccines,
                           requests_data=requests_data)


# LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
