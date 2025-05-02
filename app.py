from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import timedelta, datetime
from functools import wraps
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bismi_farm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)  # Session expires after 2 hours

# Initialize extensions
db = SQLAlchemy(app)

# Custom login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), nullable=False, default='manager')  # 'admin' or 'manager'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Farm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    total_capacity = db.Column(db.Integer, nullable=False)
    num_sheds = db.Column(db.Integer, nullable=False)
    shed_capacities = db.Column(db.Text, nullable=False, default='[]')  # Store as JSON string
    owner_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_shed_capacities(self):
        return json.loads(self.shed_capacities)

    def set_shed_capacities(self, capacities):
        self.shed_capacities = json.dumps(capacities)

class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farm.id'), nullable=False)
    batch_number = db.Column(db.String(50), nullable=False)
    total_birds = db.Column(db.Integer, nullable=False)
    available_birds = db.Column(db.Integer, nullable=False)
    shed_birds = db.Column(db.Text, nullable=False, default='[]')  # Store as JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with Farm
    farm = db.relationship('Farm', backref=db.backref('batches', lazy=True))

    def get_shed_birds(self):
        return json.loads(self.shed_birds)

    def set_shed_birds(self, birds):
        self.shed_birds = json.dumps(birds)

    def get_age_days(self):
        today = datetime.utcnow().date()
        created_date = self.created_at.date()
        return (today - created_date).days

class Feed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # pre-starter, starter, finisher
    weight = db.Column(db.Float, nullable=False)  # in kg
    price = db.Column(db.Float, nullable=False)  # per kg
    stock_quantity = db.Column(db.Float, nullable=False, default=0)  # in kg
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Feed {self.brand} - {self.category}>'

def init_db():
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            # Create a default user 
            # default_user = User(
            #     username='admin',
            #     password_hash=generate_password_hash('admin'),
            #     user_type='admin'
            # )
            # db.session.add(default_user)
            # db.session.commit()
        except Exception as e:
            print(f"Error initializing database: {str(e)}")
            db.session.rollback()

# Initialize database
init_db()

@app.before_request
def before_request():
    session.permanent = True  # Make session permanent

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please provide both username and password', 'error')
            return redirect(url_for('index'))
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_type'] = user.user_type
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        flash('An error occurred during login', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please login to access the dashboard', 'error')
        return redirect(url_for('index'))
    return render_template('dashboard.html', 
                         username=session.get('username'),
                         user_type=session.get('user_type'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    current_password = request.form.get('current_password')
    new_username = request.form.get('new_username')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # Verify current password
    if not check_password_hash(user.password_hash, current_password):
        flash('Current password is incorrect', 'error')
        return redirect(url_for('settings'))
    
    # Handle username change
    if new_username:
        if User.query.filter_by(username=new_username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('settings'))
        user.username = new_username
        session['username'] = new_username
        flash('Username updated successfully', 'success')
    
    # Handle password change
    if new_password:
        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('settings'))
        user.set_password(new_password)
        flash('Password updated successfully', 'success')
    
    db.session.commit()
    return redirect(url_for('settings'))

@app.route('/update_notifications', methods=['POST'])
def update_notifications():
    if 'user_id' not in session:
        flash('Please login to update notifications', 'error')
        return redirect(url_for('index'))
    
    try:
        user = User.query.get(session['user_id'])
        user.email_notifications = 'email_notifications' in request.form
        user.batch_alerts = 'batch_alerts' in request.form
        user.health_alerts = 'health_alerts' in request.form
        db.session.commit()
        flash('Notification settings updated successfully', 'success')
    except Exception as e:
        flash('An error occurred while updating notifications', 'error')
        db.session.rollback()
    
    return redirect(url_for('settings'))

@app.route('/update_system_settings', methods=['POST'])
def update_system_settings():
    if 'user_id' not in session:
        flash('Please login to update system settings', 'error')
        return redirect(url_for('index'))
    
    try:
        user = User.query.get(session['user_id'])
        user.language = request.form.get('language')
        user.timezone = request.form.get('timezone')
        db.session.commit()
        flash('System settings updated successfully', 'success')
    except Exception as e:
        flash('An error occurred while updating system settings', 'error')
        db.session.rollback()
    
    return redirect(url_for('settings'))

# Farm Management Routes
@app.route('/farms')
@login_required
def farms():
    farms = Farm.query.all()
    return render_template('farms.html', farms=farms)

@app.route('/farms/add', methods=['GET', 'POST'])
@login_required
def add_farm():
    if request.method == 'POST':
        try:
            num_sheds = int(request.form.get('num_sheds'))
            shed_capacities = []
            
            # Get individual shed capacities
            for i in range(1, num_sheds + 1):
                capacity = int(request.form.get(f'shed_capacity_{i}', 0))
                shed_capacities.append(capacity)
            
            farm = Farm(
                name=request.form.get('name'),
                total_capacity=int(request.form.get('total_capacity')),
                num_sheds=num_sheds,
                owner_name=request.form.get('owner_name')
            )
            farm.set_shed_capacities(shed_capacities)
            
            db.session.add(farm)
            db.session.commit()
            flash('Farm added successfully', 'success')
            return redirect(url_for('farms'))
        except Exception as e:
            flash('Error adding farm: ' + str(e), 'error')
            db.session.rollback()
    return render_template('add_farm.html')

@app.route('/farms/<int:farm_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_farm(farm_id):
    farm = Farm.query.get_or_404(farm_id)
    if request.method == 'POST':
        try:
            num_sheds = int(request.form.get('num_sheds'))
            shed_capacities = []
            
            # Get individual shed capacities
            for i in range(1, num_sheds + 1):
                capacity = int(request.form.get(f'shed_capacity_{i}', 0))
                shed_capacities.append(capacity)
            
            farm.name = request.form.get('name')
            farm.total_capacity = int(request.form.get('total_capacity'))
            farm.num_sheds = num_sheds
            farm.owner_name = request.form.get('owner_name')
            farm.set_shed_capacities(shed_capacities)
            
            db.session.commit()
            flash('Farm updated successfully', 'success')
            return redirect(url_for('farms'))
        except Exception as e:
            flash('Error updating farm: ' + str(e), 'error')
            db.session.rollback()
    return render_template('edit_farm.html', farm=farm)

@app.route('/farms/<int:farm_id>/view')
@login_required
def view_farm(farm_id):
    farm = Farm.query.get_or_404(farm_id)
    return render_template('view_farm.html', farm=farm)

@app.route('/farms/<int:farm_id>/delete', methods=['POST'])
@login_required
def delete_farm(farm_id):
    try:
        farm = Farm.query.get_or_404(farm_id)
        db.session.delete(farm)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

# Batch Management Routes
@app.route('/batches')
@login_required
def batches():
    batches = Batch.query.all()
    return render_template('batches.html', batches=batches)

@app.route('/batches/add', methods=['GET', 'POST'])
@login_required
def add_batch():
    if request.method == 'POST':
        try:
            farm_id = int(request.form.get('farm_id'))
            farm = Farm.query.get_or_404(farm_id)
            
            # Get shed capacities from farm
            shed_capacities = farm.get_shed_capacities()
            shed_birds = []
            total_birds = 0
            
            # Get individual shed bird counts
            for i in range(1, farm.num_sheds + 1):
                birds = int(request.form.get(f'shed_birds_{i}', 0))
                if birds > shed_capacities[i-1]:
                    raise ValueError(f'Number of birds in Shed {i} exceeds capacity')
                shed_birds.append(birds)
                total_birds += birds
            
            batch = Batch(
                farm_id=farm_id,
                batch_number=request.form.get('batch_number'),
                total_birds=total_birds,
                available_birds=total_birds  # Initially all birds are available
            )
            batch.set_shed_birds(shed_birds)
            
            db.session.add(batch)
            db.session.commit()
            flash('Batch added successfully', 'success')
            return redirect(url_for('batches'))
        except Exception as e:
            flash('Error adding batch: ' + str(e), 'error')
            db.session.rollback()
    
    farms = Farm.query.all()
    return render_template('add_batch.html', farms=farms)

@app.route('/batches/<int:batch_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    if request.method == 'POST':
        try:
            farm = batch.farm
            shed_capacities = farm.get_shed_capacities()
            shed_birds = []
            total_birds = 0
            
            # Get individual shed bird counts
            for i in range(1, farm.num_sheds + 1):
                birds = int(request.form.get(f'shed_birds_{i}', 0))
                if birds > shed_capacities[i-1]:
                    raise ValueError(f'Number of birds in Shed {i} exceeds capacity')
                shed_birds.append(birds)
                total_birds += birds
            
            batch.batch_number = request.form.get('batch_number')
            batch.total_birds = total_birds
            batch.available_birds = total_birds  # Reset available birds
            batch.set_shed_birds(shed_birds)
            
            db.session.commit()
            flash('Batch updated successfully', 'success')
            return redirect(url_for('batches'))
        except Exception as e:
            flash('Error updating batch: ' + str(e), 'error')
            db.session.rollback()
    
    return render_template('edit_batch.html', batch=batch)

@app.route('/batches/<int:batch_id>/view')
@login_required
def view_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    return render_template('view_batch.html', batch=batch)

@app.route('/batches/<int:batch_id>/delete', methods=['POST'])
@login_required
def delete_batch(batch_id):
    try:
        batch = Batch.query.get_or_404(batch_id)
        db.session.delete(batch)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

# Feed Management Routes
@app.route('/feeds')
@login_required
def feeds():
    feeds = Feed.query.all()
    return render_template('feeds.html', feeds=feeds)

@app.route('/feeds/add', methods=['GET', 'POST'])
@login_required
def add_feed():
    if request.method == 'POST':
        try:
            feed = Feed(
                brand=request.form.get('brand'),
                category=request.form.get('category'),
                weight=float(request.form.get('weight')),
                price=float(request.form.get('price')),
                stock_quantity=float(request.form.get('stock_quantity'))
            )
            db.session.add(feed)
            db.session.commit()
            flash('Feed added successfully', 'success')
            return redirect(url_for('feeds'))
        except Exception as e:
            flash('Error adding feed: ' + str(e), 'error')
            db.session.rollback()
    return render_template('add_feed.html')

@app.route('/feeds/<int:feed_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_feed(feed_id):
    feed = Feed.query.get_or_404(feed_id)
    if request.method == 'POST':
        try:
            feed.brand = request.form.get('brand')
            feed.category = request.form.get('category')
            feed.weight = float(request.form.get('weight'))
            feed.price = float(request.form.get('price'))
            feed.stock_quantity = float(request.form.get('stock_quantity'))
            
            db.session.commit()
            flash('Feed updated successfully', 'success')
            return redirect(url_for('feeds'))
        except Exception as e:
            flash('Error updating feed: ' + str(e), 'error')
            db.session.rollback()
    return render_template('edit_feed.html', feed=feed)

@app.route('/feeds/<int:feed_id>/view')
@login_required
def view_feed(feed_id):
    feed = Feed.query.get_or_404(feed_id)
    return render_template('view_feed.html', feed=feed)

@app.route('/feeds/<int:feed_id>/delete', methods=['POST'])
@login_required
def delete_feed(feed_id):
    try:
        feed = Feed.query.get_or_404(feed_id)
        db.session.delete(feed)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True) 