from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import os

# Connects to your model.py schema
from model import db, User, Restaurant, MenuItem, CartItem, Order

app = Flask(__name__)
app.secret_key = 'upskill_internship_secret_key'

# --- CONFIGURATION ---
basedir = os.path.abspath(os.path.dirname(__file__))
if os.environ.get('VERCEL'):
    db_path = '/tmp/food_delivery.db'
else:
    db_path = os.path.join(basedir, 'food_delivery.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()

# --- AUTHENTICATION ---
@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'restaurant': return redirect(url_for('dashboard'))
        if role == 'driver': return redirect(url_for('driver_dashboard'))
        return redirect(url_for('explore'))
    return render_template('register.html')

@app.route('/login_page')
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.query.filter_by(email=email).first()
    
    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['role'] = user.role
        
        if user.role == 'restaurant': return redirect(url_for('dashboard'))
        if user.role == 'driver': return redirect(url_for('driver_dashboard'))
        return redirect(url_for('explore'))
            
    flash("Invalid credentials", "danger")
    return redirect(url_for('login_page'))

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    if User.query.filter_by(email=email).first():
        flash("Email already registered!", "danger")
        return redirect(url_for('index'))
        
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = User(name=name, email=email, password_hash=hashed_pw, role=role)
    db.session.add(new_user)
    db.session.commit()
    flash("Registration successful! Please login.", "success")
    return redirect(url_for('login_page'))

# --- RESTAURANT MODULE ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('role') != 'restaurant':
        return redirect(url_for('login_page'))
    user_id = session.get('user_id')
    restaurant = Restaurant.query.filter_by(user_id=user_id).first()
    if not restaurant:
        restaurant = Restaurant(user_id=user_id, restaurant_name=f"{session['user_name']}'s Kitchen", address="City Center")
        db.session.add(restaurant)
        db.session.commit()
    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).all()
    return render_template('dashboard.html', restaurant=restaurant, items=items)

@app.route('/add_item', methods=['POST'])
def add_item():
    if 'user_id' not in session or session.get('role') != 'restaurant': return redirect(url_for('login_page'))
    new_item = MenuItem(
        restaurant_id=request.form.get('restaurant_id'),
        dish_name=request.form.get('dish_name'),
        price=float(request.form.get('price')),
        description=request.form.get('description')
    )
    db.session.add(new_item)
    db.session.commit()
    return redirect(url_for('dashboard'))

# --- CUSTOMER & CART MODULE ---
@app.route('/explore')
def explore():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    restaurants = Restaurant.query.all()
    return render_template('customer_home.html', restaurants=restaurants)

@app.route('/restaurant/<int:restaurant_id>')
def view_menu(restaurant_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    restaurant = Restaurant.query.get_or_404(restaurant_id)
    items = MenuItem.query.filter_by(restaurant_id=restaurant_id).all()
    return render_template('restaurant_menu.html', restaurant=restaurant, items=items)

@app.route('/add_to_cart/<int:item_id>', methods=['POST'])
def add_to_cart(item_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user_id = session.get('user_id')
    cart_item = CartItem.query.filter_by(user_id=user_id, menu_item_id=item_id).first()
    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = CartItem(user_id=user_id, menu_item_id=item_id, quantity=1)
        db.session.add(cart_item)
    db.session.commit()
    return redirect(request.referrer)

@app.route('/cart')
def view_cart():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user_id = session.get('user_id')
    cart_data = db.session.query(CartItem, MenuItem).join(MenuItem).filter(CartItem.user_id == user_id).all()
    total = sum(item.price * cart.quantity for cart, item in cart_data)
    return render_template('cart.html', cart_data=cart_data, total=total)

@app.route('/checkout', methods=['POST'])
def checkout():
    user_id = session.get('user_id')
    cart_items = CartItem.query.filter_by(user_id=user_id).all()
    if not cart_items: return redirect(url_for('explore'))

    first_item = MenuItem.query.get(cart_items[0].menu_item_id)
    total = sum(MenuItem.query.get(i.menu_item_id).price * i.quantity for i in cart_items)

    new_order = Order(
        customer_id=user_id,
        restaurant_id=first_item.restaurant_id,
        total_amount=total,
        status='Preparing',
        eta='25 mins'
    )
    db.session.add(new_order)
    CartItem.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return redirect(url_for('track_orders'))

@app.route('/track_orders')
def track_orders():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    orders = Order.query.filter_by(customer_id=session.get('user_id')).order_by(Order.id.desc()).all()
    return render_template('track_orders.html', orders=orders)

# --- DRIVER MODULE ---
@app.route('/driver_dashboard')
def driver_dashboard():
    if 'user_id' not in session or session.get('role') != 'driver':
        return redirect(url_for('login_page'))
    available_orders = Order.query.filter_by(status='Preparing').all()
    my_orders = Order.query.filter_by(driver_id=session.get('user_id')).all()
    return render_template('driver_dashboard.html', available=available_orders, mine=my_orders)

@app.route('/accept_order/<int:order_id>', methods=['POST'])
def accept_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.driver_id = session.get('user_id')
    order.status = 'Out for Delivery'
    order.eta = '10 mins'
    db.session.commit()
    return redirect(url_for('driver_dashboard'))

@app.route('/complete_order/<int:order_id>', methods=['POST'])
def complete_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = 'Delivered'
    order.eta = 'Arrived'
    db.session.commit()
    return redirect(url_for('driver_dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == '__main__':
    app.run(debug=True)
