from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from io import StringIO
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure random key in production

# Database setup
DB_NAME = 'baker_inventory.db'

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role, business_id):
        self.id = id
        self.username = username
        self.role = role
        self.business_id = business_id

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username, role, business_id FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return User(user[0], user[1], user[2], user[3]) if user else None

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Businesses table
    c.execute('''CREATE TABLE IF NOT EXISTS businesses 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, password TEXT, role TEXT, 
                  business_id INTEGER, 
                  FOREIGN KEY(business_id) REFERENCES businesses(id),
                  UNIQUE(business_id, username))''')
    # Recipes table
    c.execute('''CREATE TABLE IF NOT EXISTS recipes 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, 
                  flour INTEGER, water INTEGER, yeast INTEGER, salt INTEGER, sugar INTEGER, 
                  eggs INTEGER, butter INTEGER, chocolate INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id),
                  UNIQUE(user_id, name))''')
    # Inventory table (includes week and month)
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER, year INTEGER, 
                  month INTEGER, week INTEGER, ingredient TEXT, amount INTEGER,
                  FOREIGN KEY(business_id) REFERENCES businesses(id),
                  UNIQUE(business_id, year, month, week, ingredient))''')
    # Inventory snapshots for opening/closing
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_snapshots 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER, year INTEGER, 
                  month INTEGER, week INTEGER, period_type TEXT, period_start TEXT, period_end TEXT, 
                  ingredient TEXT, amount INTEGER,
                  FOREIGN KEY(business_id) REFERENCES businesses(id))''')
    # Inventory transactions
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER, year INTEGER, 
                  month INTEGER, week INTEGER, ingredient TEXT, amount_added INTEGER, 
                  timestamp TEXT, user_id INTEGER,
                  FOREIGN KEY(business_id) REFERENCES businesses(id),
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    # Sales table
    c.execute('''CREATE TABLE IF NOT EXISTS sales 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, year INTEGER, 
                  item TEXT, quantity INTEGER, date TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    # Initial inventory table
    c.execute('''CREATE TABLE IF NOT EXISTS initial_inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient TEXT UNIQUE, amount INTEGER)''')
    
    c.execute("INSERT OR IGNORE INTO businesses (name) VALUES (?)", ("Default Bakery",))
    c.execute("SELECT id FROM businesses WHERE name = ?", ("Default Bakery",))
    business_id = c.fetchone()[0]
    c.execute("INSERT OR IGNORE INTO users (username, password, role, business_id) VALUES (?, ?, ?, ?)", 
              ("admin", generate_password_hash("adminpass"), "admin", business_id))
    
    initial_inventory_data = [
        ('flour', 10000), ('water', 5000), ('yeast', 200), ('salt', 200), 
        ('sugar', 2000), ('eggs', 50), ('butter', 3000), ('chocolate', 1000)
    ]
    c.executemany("INSERT OR IGNORE INTO initial_inventory (ingredient, amount) VALUES (?, ?)", initial_inventory_data)
    
    conn.commit()
    conn.close()
    print("Database initialized with Default Bakery, admin user, and initial inventory.")

# Helper functions for week date calculations
def get_week_start_date(year, week):
    jan4 = datetime(year, 1, 4)
    first_monday = jan4 - timedelta(days=jan4.weekday())
    week_start = first_monday + timedelta(weeks=week - 1)
    return week_start.strftime('%Y-%m-%d')

def get_week_end_date(year, week):
    start_date = datetime.strptime(get_week_start_date(year, week), '%Y-%m-%d')
    end_date = start_date + timedelta(days=6)
    return end_date.strftime('%Y-%m-%d')

def get_current_period():
    now = datetime.now()
    year = now.year
    month = now.month
    week = now.isocalendar()[1]
    return year, month, week

def populate_user_data(user_id, business_id, year=datetime.now().year, month=datetime.now().month, week=datetime.now().isocalendar()[1]):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Populate recipes if none exist for the user
    c.execute("SELECT COUNT(*) FROM recipes WHERE user_id = ?", (user_id,))
    if c.fetchone()[0] == 0:
        initial_recipes = [
            (user_id, 'Bread', 500, 300, 10, 10, 0, 0, 0, 0),
            (user_id, 'Cake', 300, 0, 0, 0, 200, 3, 150, 0),
            (user_id, 'Cookies', 200, 0, 0, 0, 100, 0, 100, 50)
        ]
        c.executemany("INSERT INTO recipes (user_id, name, flour, water, yeast, salt, sugar, eggs, butter, chocolate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", initial_recipes)
        print(f"Populated recipes for user_id {user_id}")
    
    # Populate inventory if none exist for the business, year, month, and week
    c.execute("SELECT COUNT(*) FROM inventory WHERE business_id = ? AND year = ? AND month = ? AND week = ?", 
              (business_id, year, month, week))
    if c.fetchone()[0] == 0:
        c.execute("SELECT ingredient, amount FROM initial_inventory")
        initial_inventory = c.fetchall()
        inventory_data = [(business_id, year, month, week, ingredient, amount) for ingredient, amount in initial_inventory]
        c.executemany("INSERT INTO inventory (business_id, year, month, week, ingredient, amount) VALUES (?, ?, ?, ?, ?, ?)", inventory_data)
        # Take opening snapshot
        snapshot_data = [(business_id, year, month, week, 'week', 
                          get_week_start_date(year, week),
                          get_week_end_date(year, week),
                          ingredient, amount) for ingredient, amount in initial_inventory]
        c.executemany("INSERT INTO inventory_snapshots (business_id, year, month, week, period_type, period_start, period_end, ingredient, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", snapshot_data)
        print(f"Populated inventory for business_id {business_id}, year {year}, month {month}, week {week} from initial_inventory table")
    
    conn.commit()
    conn.close()

# Helper functions
def get_businesses():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name FROM businesses")
    businesses = dict(c.fetchall())
    conn.close()
    return businesses

def get_users(business_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users WHERE business_id = ? AND id != ?", (business_id, current_user.id))
    users = c.fetchall()
    conn.close()
    return users

def get_recipes(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, flour, water, yeast, salt, sugar, eggs, butter, chocolate FROM recipes WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: dict(zip(['flour', 'water', 'yeast', 'salt', 'sugar', 'eggs', 'butter', 'chocolate'], row[1:])) for row in rows}

def get_inventory(business_id, year, month=None, week=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if month is not None and week is not None:
        c.execute("SELECT ingredient, amount FROM inventory WHERE business_id = ? AND year = ? AND month = ? AND week = ?", 
                  (business_id, year, month, week))
    elif month is not None:
        c.execute("SELECT ingredient, SUM(amount) FROM inventory WHERE business_id = ? AND year = ? AND month = ? GROUP BY ingredient", 
                  (business_id, year, month))
    else:
        c.execute("SELECT ingredient, SUM(amount) FROM inventory WHERE business_id = ? AND year = ? GROUP BY ingredient", 
                  (business_id, year))
    rows = c.fetchall()
    conn.close()
    print(f"Fetched inventory for business_id {business_id}, year {year}, month {month}, week {week}: {dict(rows)}")
    return dict(rows)

def get_opening_closing_inventory(business_id, year, period_type, period_value):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if period_type == 'week':
        c.execute("SELECT ingredient, amount FROM inventory_snapshots WHERE business_id = ? AND year = ? AND period_type = ? AND week = ?", 
                  (business_id, year, 'week', period_value))
    elif period_type == 'month':
        c.execute("SELECT ingredient, amount FROM inventory_snapshots WHERE business_id = ? AND year = ? AND period_type = ? AND month = ?", 
                  (business_id, year, 'month', period_value))
    rows = c.fetchall()
    conn.close()
    return dict(rows)

def get_inventory_transactions(business_id, year, month=None, week=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if month is not None and week is not None:
        c.execute("SELECT ingredient, amount_added, timestamp, user_id FROM inventory_transactions WHERE business_id = ? AND year = ? AND month = ? AND week = ?", 
                  (business_id, year, month, week))
    elif month is not None:
        c.execute("SELECT ingredient, amount_added, timestamp, user_id FROM inventory_transactions WHERE business_id = ? AND year = ? AND month = ?", 
                  (business_id, year, month))
    else:
        c.execute("SELECT ingredient, amount_added, timestamp, user_id FROM inventory_transactions WHERE business_id = ? AND year = ?", 
                  (business_id, year))
    rows = c.fetchall()
    conn.close()
    return rows

def get_years(business_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT year FROM inventory WHERE business_id = ?", (business_id,))
    years = [row[0] for row in c.fetchall()]
    conn.close()
    return years

def get_months(business_id, year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT month FROM inventory WHERE business_id = ? AND year = ?", (business_id, year))
    months = [row[0] for row in c.fetchall()]
    conn.close()
    return sorted(months)

def get_weeks(business_id, year, month):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT week FROM inventory WHERE business_id = ? AND year = ? AND month = ?", (business_id, year, month))
    weeks = [row[0] for row in c.fetchall()]
    conn.close()
    return sorted(weeks)

def compute_ingredients(daily_sales, user_id):
    recipes = get_recipes(user_id)
    total_ingredients = {}
    for item, quantity_sold in daily_sales.items():
        if quantity_sold > 0 and item in recipes:
            for ingredient, amount in recipes[item].items():
                if amount > 0:
                    total_ingredients[ingredient] = total_ingredients.get(ingredient, 0) + amount * quantity_sold
    return total_ingredients

def check_inventory(total_ingredients, business_id, year, month, week):
    inventory = get_inventory(business_id, year, month, week)
    insufficient = []
    for ingredient, amount_needed in total_ingredients.items():
        current_amount = inventory.get(ingredient, 0)
        if current_amount < amount_needed:
            insufficient.append(f"Not enough {ingredient}: need {amount_needed}, have {current_amount}")
    return insufficient

def update_inventory(total_ingredients, business_id, year, month, week):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    low_stock = []
    for ingredient, amount_used in total_ingredients.items():
        c.execute("UPDATE inventory SET amount = amount - ? WHERE business_id = ? AND year = ? AND month = ? AND week = ? AND ingredient = ?", 
                  (amount_used, business_id, year, month, week, ingredient))
        c.execute("SELECT amount FROM inventory WHERE business_id = ? AND year = ? AND month = ? AND week = ? AND ingredient = ?", 
                  (business_id, year, month, week, ingredient))
        remaining = c.fetchone()[0]
        if remaining < 0:
            low_stock.append(f"{ingredient} is depleted! ({remaining} units)")
        elif remaining < max([r.get(ingredient, 0) for r in get_recipes(current_user.id).values()]):
            low_stock.append(f"{ingredient} is running low ({remaining} units left)")
    # Take closing snapshot for the week
    inventory = get_inventory(business_id, year, month, week)
    snapshot_data = [(business_id, year, month, week, 'week', 
                      get_week_start_date(year, week),
                      get_week_end_date(year, week),
                      ingredient, amount) for ingredient, amount in inventory.items()]
    c.executemany("INSERT OR REPLACE INTO inventory_snapshots (business_id, year, month, week, period_type, period_start, period_end, ingredient, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", snapshot_data)
    conn.commit()
    conn.close()
    print(f"Inventory updated for business_id {business_id}, year {year}, month {month}, week {week}")
    return low_stock

def reset_inventory(business_id, year, month, week):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE business_id = ? AND year = ? AND month = ? AND week = ?", (business_id, year, month, week))
    c.execute("SELECT ingredient, amount FROM initial_inventory")
    initial_inventory = c.fetchall()
    inventory_data = [(business_id, year, month, week, ingredient, amount) for ingredient, amount in initial_inventory]
    c.executemany("INSERT INTO inventory (business_id, year, month, week, ingredient, amount) VALUES (?, ?, ?, ?, ?, ?)", inventory_data)
    # Log the reset as a transaction
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    transaction_data = [(business_id, year, month, week, ingredient, amount, timestamp, current_user.id) for ingredient, amount in initial_inventory]
    c.executemany("INSERT INTO inventory_transactions (business_id, year, month, week, ingredient, amount_added, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", transaction_data)
    # Take opening snapshot
    snapshot_data = [(business_id, year, month, week, 'week', 
                      get_week_start_date(year, week),
                      get_week_end_date(year, week),
                      ingredient, amount) for ingredient, amount in initial_inventory]
    c.executemany("INSERT OR REPLACE INTO inventory_snapshots (business_id, year, month, week, period_type, period_start, period_end, ingredient, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", snapshot_data)
    conn.commit()
    conn.close()
    print(f"Inventory reset for business_id {business_id}, year {year}, month {month}, week {week}")

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
    print(f"Sales logged for user_id {user_id}, year {year}")

def generate_daily_report(total_ingredients, low_stock, business_id, year, month, week):
    report = StringIO()
    report.write("Total Ingredients Used Today:\n")
    for ingredient, amount in total_ingredients.items():
        report.write(f"{ingredient}: {amount} units\n")
    if not total_ingredients:
        report.write("No items were sold today.\n")
    report.write(f"\nRemaining Inventory for Year {year}, Month {month}, Week {week}:\n")
    for ingredient, amount in get_inventory(business_id, year, month, week).items():
        report.write(f"{ingredient}: {amount} units\n")
    if low_stock:
        report.write("\nInventory Alerts:\n")
        for alert in low_stock:
            report.write(f"{alert}\n")
    return report.getvalue()

def generate_sales_report(user_id, period, year):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    report = StringIO()
    current_date = datetime.now()
    if period == 'weekly':
        start_date = current_date - timedelta(days=current_date.weekday())
        end_date = start_date + timedelta(days=6)
        c.execute("SELECT item, SUM(quantity) FROM sales WHERE user_id = ? AND year = ? AND date BETWEEN ? AND ? GROUP BY item",
                  (user_id, year, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
        title = f"Weekly Sales Report ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})"
    elif period == 'monthly':
        start_date = current_date.replace(day=1)
        end_date = (start_date.replace(month=start_date.month % 12 + 1, day=1) - timedelta(days=1)) if start_date.month < 12 else start_date.replace(year=start_date.year + 1, month=1, day=1) - timedelta(days=1)
        c.execute("SELECT item, SUM(quantity) FROM sales WHERE user_id = ? AND year = ? AND date BETWEEN ? AND ? GROUP BY item",
                  (user_id, year, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
        title = f"Monthly Sales Report ({start_date.strftime('%B %Y')})"
    elif period == 'yearly':
        c.execute("SELECT item, SUM(quantity) FROM sales WHERE user_id = ? AND year = ? GROUP BY item", (user_id, year))
        title = f"Yearly Sales Report ({year})"
    rows = c.fetchall()
    conn.close()
    report.write(f"{title}:\n")
    total_sold = 0
    for item, quantity in rows:
        report.write(f"{item}: {quantity} units\n")
        total_sold += quantity
    if not rows:
        report.write("No sales recorded.\n")
    else:
        report.write(f"\nTotal Items Sold: {total_sold} units\n")
    return report.getvalue()

# Routes
@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    years = get_years(current_user.business_id)
    selected_year = request.form.get('year', datetime.now().year, type=int)
    selected_month = request.form.get('month', datetime.now().month, type=int)
    selected_week = request.form.get('week', datetime.now().isocalendar()[1], type=int)
    
    if selected_year not in years:
        populate_user_data(current_user.id, current_user.business_id, selected_year, selected_month, selected_week)
    
    months = get_months(current_user.business_id, selected_year)
    weeks = get_weeks(current_user.business_id, selected_year, selected_month)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name FROM businesses WHERE id = ?", (current_user.business_id,))
    business_name = c.fetchone()[0]
    conn.close()
    
    inventory = get_inventory(current_user.business_id, selected_year, selected_month, selected_week)
    opening_inventory = get_opening_closing_inventory(current_user.business_id, selected_year, 'week', selected_week)
    transactions = get_inventory_transactions(current_user.business_id, selected_year, selected_month, selected_week)
    
    return render_template('home.html', recipes=get_recipes(current_user.id), inventory=inventory, 
                           opening_inventory=opening_inventory, transactions=transactions,
                           username=current_user.username, years=years, months=months, weeks=weeks,
                           selected_year=selected_year, selected_month=selected_month, selected_week=selected_week,
                           role=current_user.role, business_name=business_name)

@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    recipes = get_recipes(current_user.id)
    years = get_years(current_user.business_id)
    selected_year = request.args.get('year', datetime.now().year, type=int)
    selected_month = request.args.get('month', datetime.now().month, type=int)
    selected_week = request.args.get('week', datetime.now().isocalendar()[1], type=int)
    from datetime import datetime as dt
    if request.method == 'POST':
        selected_year = int(request.form.get('year'))
        selected_month = dt.today().month
        selected_week = dt.now().isocalendar()[1]
        daily_sales = {item: int(request.form.get(item, 0)) for item in recipes.keys()}
        total_ingredients = compute_ingredients(daily_sales, current_user.id)
        insufficient = check_inventory(total_ingredients, current_user.business_id, selected_year, selected_month, selected_week)
        if insufficient:
            for msg in insufficient:
                flash(msg)
            return render_template('sales.html', items=recipes.keys(), years=years, selected_year=selected_year, 
                                   selected_month=selected_month, selected_week=selected_week)
        low_stock = update_inventory(total_ingredients, current_user.business_id, selected_year, selected_month, selected_week)
        log_sales(daily_sales, current_user.id, selected_year)
        report = generate_daily_report(total_ingredients, low_stock, current_user.business_id, selected_year, selected_month, selected_week)
        with open(f'daily_report_{current_user.id}_{selected_year}_{selected_month}_{selected_week}.txt', 'w') as f:
            f.write(report)
        return render_template('report.html', report=report.split('\n'), year=selected_year, month=selected_month, week=selected_week)
    return render_template('sales.html', items=recipes.keys(), years=years, selected_year=selected_year, 
                           selected_month=selected_month, selected_week=selected_week)

@app.route('/download_report')
@login_required
def download_report():
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    week = request.args.get('week', datetime.now().isocalendar()[1], type=int)
    return send_file(f'daily_report_{current_user.id}_{year}_{month}_{week}.txt', as_attachment=True, 
                     download_name=f'daily_report_{year}_{month}_{week}.txt')

@app.route('/sales_report/<period>', methods=['GET', 'POST'])
@login_required
def sales_report(period):
    years = get_years(current_user.business_id)
    selected_year = request.form.get('year', datetime.now().year, type=int) if request.method == 'POST' else request.args.get('year', datetime.now().year, type=int)
    report = generate_sales_report(current_user.id, period, selected_year)
    if request.method == 'POST' and 'download' in request.form:
        with open(f'{period}_report_{current_user.id}_{selected_year}.txt', 'w') as f:
            f.write(report)
        return send_file(f'{period}_report_{current_user.id}_{selected_year}.txt', as_attachment=True, 
                         download_name=f'{period}_report_{selected_year}.txt')
    return render_template('sales_report.html', report=report.split('\n'), period=period.capitalize(), years=years, selected_year=selected_year)

@app.route('/add_recipe', methods=['GET', 'POST'])
@login_required
def add_recipe():
    if current_user.role != 'admin':
        flash('Only admins can add recipes.')
        return redirect('/')
    if request.method == 'POST':
        name = request.form['name']
        ingredients = {key: int(request.form.get(key, 0)) for key in ['flour', 'water', 'yeast', 'salt', 'sugar', 'eggs', 'butter', 'chocolate']}
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO recipes (user_id, name, flour, water, yeast, salt, sugar, eggs, butter, chocolate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                      (current_user.id, name, *ingredients.values()))
            conn.commit()
            print(f"Recipe '{name}' added for user_id {current_user.id}")
            flash(f"Recipe '{name}' added successfully.")
        except sqlite3.IntegrityError:
            flash('Recipe name already exists.')
        conn.close()
        return redirect('/')
    return render_template('add_recipe.html')

@app.route('/edit_recipe/<recipe_name>', methods=['GET', 'POST'])
@login_required
def edit_recipe(recipe_name):
    if current_user.role != 'admin':
        flash('Only admins can edit recipes.')
        return redirect('/')
    recipes = get_recipes(current_user.id)
    if recipe_name not in recipes:
        flash('Recipe not found.')
        return redirect('/')
    if request.method == 'POST':
        ingredients = {key: int(request.form.get(key, 0)) for key in ['flour', 'water', 'yeast', 'salt', 'sugar', 'eggs', 'butter', 'chocolate']}
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE recipes SET flour=?, water=?, yeast=?, salt=?, sugar=?, eggs=?, butter=?, chocolate=? WHERE user_id=? AND name=?", 
                  (*ingredients.values(), current_user.id, recipe_name))
        conn.commit()
        conn.close()
        print(f"Recipe '{recipe_name}' updated for user_id {current_user.id}")
        flash(f"Recipe '{recipe_name}' updated successfully.")
        return redirect('/')
    return render_template('edit_recipe.html', recipe_name=recipe_name, ingredients=recipes[recipe_name])

@app.route('/update_inventory', methods=['GET', 'POST'])
@login_required
def update_inventory_route():
    if current_user.role != 'admin':
        flash('Only admins can update inventory.')
        return redirect('/')
    years = get_years(current_user.business_id)
    selected_year = request.args.get('year', datetime.now().year, type=int)
    selected_month = request.args.get('month', datetime.now().month, type=int)
    selected_week = request.args.get('week', datetime.now().isocalendar()[1], type=int)
    
    if request.method == 'POST':
        selected_year = int(request.form.get('year'))
        selected_month = int(request.form.get('month'))
        selected_week = int(request.form.get('week'))
        inventory_updates = {key: int(request.form.get(key, 0)) for key in get_inventory(current_user.business_id, selected_year, selected_month, selected_week).keys()}
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for ingredient, new_amount in inventory_updates.items():
            c.execute("SELECT amount FROM inventory WHERE business_id = ? AND year = ? AND month = ? AND week = ? AND ingredient = ?", 
                      (current_user.business_id, selected_year, selected_month, selected_week, ingredient))
            old_amount = c.fetchone()[0]
            amount_added = new_amount - old_amount
            c.execute("UPDATE inventory SET amount = ? WHERE business_id = ? AND year = ? AND month = ? AND week = ? AND ingredient = ?", 
                      (new_amount, current_user.business_id, selected_year, selected_month, selected_week, ingredient))
            if amount_added > 0:
                c.execute("INSERT INTO inventory_transactions (business_id, year, month, week, ingredient, amount_added, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                          (current_user.business_id, selected_year, selected_month, selected_week, ingredient, amount_added, timestamp, current_user.id))
        conn.commit()
        conn.close()
        print(f"Inventory updated for business_id {current_user.business_id}, year {selected_year}, month {selected_month}, week {selected_week}")
        flash("Inventory updated successfully.")
        return redirect('/')
    return render_template('update_inventory.html', inventory=get_inventory(current_user.business_id, selected_year, selected_month, selected_week), 
                           years=years, selected_year=selected_year, selected_month=selected_month, selected_week=selected_week)

@app.route('/reset_inventory/<int:year>/<int:month>/<int:week>', methods=['POST'])
@login_required
def reset_inventory_route(year, month, week):
    if current_user.role != 'admin':
        flash('Only admins can reset inventory.')
        return redirect('/')
    reset_inventory(current_user.business_id, year, month, week)
    flash(f"Inventory for Year {year}, Month {month}, Week {week} has been reset to initial values.")
    return redirect('/')

@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        flash('Only admins can manage users.')
        return redirect('/')
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        if role not in ['admin', 'user']:
            flash('Invalid role selected.')
            return redirect('/manage_users')
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, role, business_id) VALUES (?, ?, ?, ?)", 
                      (username, generate_password_hash(password), role, current_user.business_id))
            conn.commit()
            print(f"User '{username}' added with role '{role}' for business_id {current_user.business_id}")
            flash(f'User {username} created successfully.')
        except sqlite3.IntegrityError:
            flash('Username already exists in this business.')
        c.execute("SELECT id, username, role FROM users WHERE business_id = ? AND id != ?", (current_user.business_id, current_user.id))
        users = c.fetchall()
        conn.close()
        return render_template('manage_users.html', users=users, business_id=current_user.business_id)
    users = get_users(current_user.business_id)
    return render_template('manage_users.html', users=users, business_id=current_user.business_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    businesses = get_businesses()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        business_id = int(request.form['business_id'])
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, username, password, role, business_id FROM users WHERE username = ? AND business_id = ?", (username, business_id))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[2], password):
            login_user(User(user[0], user[1], user[3], user[4]))
            populate_user_data(current_user.id, current_user.business_id)
            print(f"User '{username}' logged in for business_id {business_id}")
            return redirect('/')
        flash('Invalid username, password, or business')
    return render_template('login.html', businesses=businesses)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# Initialize app
if __name__ == '__main__':
    init_db()
    app.run(debug=True)