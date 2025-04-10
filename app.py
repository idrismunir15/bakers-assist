from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from io import StringIO
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure random key in production

# Database setup
DB_NAME = 'baker_inventory.db'

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return User(user[0], user[1]) if user else None

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recipes 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
                  flour INTEGER, water INTEGER, yeast INTEGER, salt INTEGER, sugar INTEGER, 
                  eggs INTEGER, butter INTEGER, chocolate INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id),
                  UNIQUE(user_id, name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, year INTEGER, 
                  ingredient TEXT, amount INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id),
                  UNIQUE(user_id, year, ingredient))''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, year INTEGER, 
                  item TEXT, quantity INTEGER, date TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

def populate_user_data(user_id, year=datetime.now().year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM recipes WHERE user_id = ?", (user_id,))
    if c.fetchone()[0] == 0:
        initial_recipes = [
            (user_id, 'Bread', 500, 300, 10, 10, 0, 0, 0, 0),
            (user_id, 'Cake', 300, 0, 0, 0, 200, 3, 150, 0),
            (user_id, 'Cookies', 200, 0, 0, 0, 100, 0, 100, 50)
        ]
        c.executemany("INSERT INTO recipes (user_id, name, flour, water, yeast, salt, sugar, eggs, butter, chocolate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", initial_recipes)
    c.execute("SELECT COUNT(*) FROM inventory WHERE user_id = ? AND year = ?", (user_id, year))
    if c.fetchone()[0] == 0:
        initial_inventory = [
            (user_id, year, 'flour', 10000), (user_id, year, 'water', 5000), (user_id, year, 'yeast', 200), 
            (user_id, year, 'salt', 200), (user_id, year, 'sugar', 2000), (user_id, year, 'eggs', 50), 
            (user_id, year, 'butter', 3000), (user_id, year, 'chocolate', 1000)
        ]
        c.executemany("INSERT INTO inventory (user_id, year, ingredient, amount) VALUES (?, ?, ?, ?)", initial_inventory)
    conn.commit()
    conn.close()

# Helper functions
def get_recipes(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, flour, water, yeast, salt, sugar, eggs, butter, chocolate FROM recipes WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: dict(zip(['flour', 'water', 'yeast', 'salt', 'sugar', 'eggs', 'butter', 'chocolate'], row[1:])) for row in rows}

def get_inventory(user_id, year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT ingredient, amount FROM inventory WHERE user_id = ? AND year = ?", (user_id, year))
    rows = c.fetchall()
    conn.close()
    return dict(rows)

def get_years(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT year FROM inventory WHERE user_id = ?", (user_id,))
    years = [row[0] for row in c.fetchall()]
    conn.close()
    return years

def compute_ingredients(daily_sales, user_id):
    recipes = get_recipes(user_id)
    total_ingredients = {}
    for item, quantity_sold in daily_sales.items():
        if quantity_sold > 0 and item in recipes:
            for ingredient, amount in recipes[item].items():
                if amount > 0:
                    total_ingredients[ingredient] = total_ingredients.get(ingredient, 0) + amount * quantity_sold
    return total_ingredients

def update_inventory(total_ingredients, user_id, year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    low_stock = []
    for ingredient, amount_used in total_ingredients.items():
        c.execute("UPDATE inventory SET amount = amount - ? WHERE user_id = ? AND year = ? AND ingredient = ?", 
                  (amount_used, user_id, year, ingredient))
        c.execute("SELECT amount FROM inventory WHERE user_id = ? AND year = ? AND ingredient = ?", 
                  (user_id, year, ingredient))
        remaining = c.fetchone()[0]
        if remaining < 0:
            low_stock.append(f"{ingredient} is depleted! ({remaining} units)")
        elif remaining < max([r.get(ingredient, 0) for r in get_recipes(user_id).values()]):
            low_stock.append(f"{ingredient} is running low ({remaining} units left)")
    conn.commit()
    conn.close()
    return low_stock

def log_sales(daily_sales, user_id, year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    date = datetime.now().strftime('%Y-%m-%d')
    for item, quantity in daily_sales.items():
        if quantity > 0:
            c.execute("INSERT INTO sales (user_id, year, item, quantity, date) VALUES (?, ?, ?, ?, ?)", 
                      (user_id, year, item, quantity, date))
    conn.commit()
    conn.close()

def generate_report(total_ingredients, low_stock, user_id, year):
    report = StringIO()
    report.write("Total Ingredients Used Today:\n")
    for ingredient, amount in total_ingredients.items():
        report.write(f"{ingredient}: {amount} units\n")
    if not total_ingredients:
        report.write("No items were sold today.\n")
    
    report.write(f"\nRemaining Inventory for {year}:\n")
    for ingredient, amount in get_inventory(user_id, year).items():
        report.write(f"{ingredient}: {amount} units\n")
    
    if low_stock:
        report.write("\nInventory Alerts:\n")
        for alert in low_stock:
            report.write(f"{alert}\n")
    return report.getvalue()

# Routes
@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    years = get_years(current_user.id)
    selected_year = request.form.get('year', datetime.now().year, type=int)
    if selected_year not in years:
        populate_user_data(current_user.id, selected_year)
    return render_template('home.html', recipes=get_recipes(current_user.id), inventory=get_inventory(current_user.id, selected_year), 
                           username=current_user.username, years=years, selected_year=selected_year)

@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    recipes = get_recipes(current_user.id)
    years = get_years(current_user.id)
    selected_year = request.args.get('year', datetime.now().year, type=int)
    if request.method == 'POST':
        selected_year = int(request.form.get('year'))
        daily_sales = {item: int(request.form.get(item, 0)) for item in recipes.keys()}
        total_ingredients = compute_ingredients(daily_sales, current_user.id)
        low_stock = update_inventory(total_ingredients, current_user.id, selected_year)
        log_sales(daily_sales, current_user.id, selected_year)
        report = generate_report(total_ingredients, low_stock, current_user.id, selected_year)
        with open(f'daily_report_{current_user.id}_{selected_year}.txt', 'w') as f:
            f.write(report)
        return render_template('report.html', report=report.split('\n'), year=selected_year)
    return render_template('sales.html', items=recipes.keys(), years=years, selected_year=selected_year)

@app.route('/download_report')
@login_required
def download_report():
    year = request.args.get('year', datetime.now().year, type=int)
    return send_file(f'daily_report_{current_user.id}_{year}.txt', as_attachment=True, download_name=f'daily_report_{year}.txt')

@app.route('/add_recipe', methods=['GET', 'POST'])
@login_required
def add_recipe():
    if request.method == 'POST':
        name = request.form['name']
        ingredients = {key: int(request.form.get(key, 0)) for key in ['flour', 'water', 'yeast', 'salt', 'sugar', 'eggs', 'butter', 'chocolate']}
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        Балансовая стоимость = c.execute("INSERT OR REPLACE INTO recipes (user_id, name, flour, water, yeast, salt, sugar, eggs, butter, chocolate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                  (current_user.id, name, *ingredients.values()))
        conn.commit()
        conn.close()
        return redirect('/')
    return render_template('add_recipe.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[2], password):
            login_user(User(user[0], user[1]))
            populate_user_data(current_user.id)  # Populate for current year
            return redirect('/')
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", 
                      (username, generate_password_hash(password)))
            conn.commit()
            flash('Registration successful! Please log in.')
            return redirect('/login')
        except sqlite3.IntegrityError:
            flash('Username already exists')
        conn.close()
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# Initialize app
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
