from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
from functools import wraps
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bismi_farm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)  # Session expires after 2 hours

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Custom login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Admin access decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session['user_type'] != 'admin':
            flash('Access denied. Administrators only.', 'error')
            if session.get('user_type') == 'manager':
                return redirect(url_for('manager_dashboard'))
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), nullable=False, default='assistant_manager')  # 'admin', 'senior_manager', or 'assistant_manager'
    employee = db.relationship('Employee', backref='user', uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Farm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    total_capacity = db.Column(db.Integer, nullable=False)
    num_sheds = db.Column(db.Integer, nullable=False)
    shed_capacities = db.Column(db.Text, nullable=False, default='[]')  # Store as JSON string
    total_area = db.Column(db.Float, nullable=False)  # Total area in square meters
    owner_name = db.Column(db.String(100), nullable=False)
    contact_number = db.Column(db.String(20), nullable=False)  # Contact number as string to preserve leading zeros
    farm_condition = db.Column(db.String(20), nullable=False, default='average')  # 'average', 'medium', 'good'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_shed_capacities(self):
        return json.loads(self.shed_capacities)

    def set_shed_capacities(self, capacities):
        self.shed_capacities = json.dumps(capacities)

    def get_available_capacity(self):
        """Calculate available capacity considering all active batches"""
        active_batches = Batch.query.filter(
            Batch.farm_id == self.id,
            Batch.status.in_(['ongoing', 'closing'])
        ).all()
        
        total_birds_in_farm = sum(batch.total_birds for batch in active_batches)
        return self.total_capacity - total_birds_in_farm

    def get_shed_available_capacities(self):
        """Calculate available capacity for each shed"""
        shed_capacities = self.get_shed_capacities()
        shed_used = [0] * len(shed_capacities)
        
        # Get all active batches
        active_batches = Batch.query.filter(
            Batch.farm_id == self.id,
            Batch.status.in_(['ongoing', 'closing'])
        ).all()
        
        # Sum up birds in each shed from all active batches
        for batch in active_batches:
            batch_shed_birds = batch.get_shed_birds()
            for i, birds in enumerate(batch_shed_birds):
                if i < len(shed_used):
                    shed_used[i] += birds
        
        # Calculate available capacity for each shed
        return [capacity - used for capacity, used in zip(shed_capacities, shed_used)]

class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farm.id'), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Allow nullable for backward compatibility
    batch_number = db.Column(db.String(50), nullable=False)
    brand = db.Column(db.String(100), nullable=True)  # Optional brand field
    total_birds = db.Column(db.Integer, nullable=False)
    available_birds = db.Column(db.Integer, nullable=False)
    total_mortality = db.Column(db.Integer, nullable=False, default=0)  # Total mortality count
    feed_stock = db.Column(db.Float, nullable=False, default=0)  # Current feed stock in kg
    shed_birds = db.Column(db.Text, nullable=False, default='[]')  # Store as JSON string
    cost_per_chicken = db.Column(db.Float, nullable=False, default=0.0)
    feed_usage = db.Column(db.Float, nullable=False, default=0.0)  # Total feed used in kg
    status = db.Column(db.String(20), nullable=False, default='ongoing')  # 'ongoing', 'closing', 'closed'
    created_at = db.Column(db.DateTime, nullable=False)  # Remove default to make it editable
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    farm = db.relationship('Farm', backref=db.backref('batches', lazy=True))
    manager = db.relationship('User', backref=db.backref('managed_batches', lazy=True))

    def get_shed_birds(self):
        return json.loads(self.shed_birds)

    def set_shed_birds(self, birds):
        self.shed_birds = json.dumps(birds)

    def get_age_days(self):
        today = datetime.utcnow().date()
        created_date = self.created_at.date()
        return (today - created_date).days

    def check_and_update_status(self):
        """Check if batch should be marked as closed based on available birds"""
        if self.available_birds <= 0 and self.status == 'closing':
            self.status = 'closed'

    def get_total_revenue(self):
        """Calculate total revenue from all harvests"""
        total = 0
        for harvest in self.harvests:
            total += harvest.total_value
        return total

    def get_feed_cost(self):
        """Calculate total feed cost from all batch updates"""
        total = 0
        for update in self.updates:
            for feed in update.feeds:
                quantity = update.get_feed_quantity(feed.id)
                total += quantity * feed.price
        return total

    def get_medicine_cost(self):
        """Calculate total medicine cost from all batch updates"""
        total = 0
        for update in self.updates:
            for medicine in update.medicines:
                quantity = update.get_medicine_quantity(medicine.id)
                total += quantity * medicine.price
        return total

    def get_health_materials_cost(self):
        """Calculate total health materials cost from all batch updates"""
        total = 0
        for update in self.updates:
            for material in update.health_materials:
                quantity = update.get_health_material_quantity(material.id)
                total += quantity * material.price
        return total

    def get_vaccine_cost(self):
        """Calculate total vaccine cost from all vaccine schedules"""
        total = 0
        for schedule in self.vaccine_schedules:
            if schedule.completed:  # Only count completed vaccinations
                total += schedule.vaccine.price
        return total

    def get_total_expenses(self):
        """Calculate total expenses including chicken cost, feed, medicines, health materials, and vaccines"""
        chicken_cost = self.cost_per_chicken * self.total_birds
        feed_cost = self.get_feed_cost()
        medicine_cost = self.get_medicine_cost()
        health_materials_cost = self.get_health_materials_cost()
        vaccine_cost = self.get_vaccine_cost()
        return chicken_cost + feed_cost + medicine_cost + health_materials_cost + vaccine_cost

    def get_total_profit(self):
        """Calculate total profit (revenue - expenses)"""
        return self.get_total_revenue() - self.get_total_expenses()

    def get_average_selling_price(self):
        """Calculate average selling price per kg across all harvests"""
        total_weight = 0
        total_value = 0
        for harvest in self.harvests:
            total_weight += harvest.weight
            total_value += harvest.total_value
        return total_value / total_weight if total_weight > 0 else 0

    def get_total_weight_sold(self):
        """Calculate total weight sold across all harvests"""
        return sum(harvest.weight for harvest in self.harvests)

class Feed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # pre-starter, starter, finisher
    weight = db.Column(db.Float, nullable=False)  # in kg
    price = db.Column(db.Float, nullable=False)  # per kg
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Feed {self.brand} - {self.category}>'

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity_per_unit = db.Column(db.Float, nullable=False)  # in litres/grams
    unit_type = db.Column(db.String(20), nullable=False)  # 'litre' or 'gram'
    price = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def convert_to_kg(self, quantity):
        """Convert the given quantity to kilograms if needed"""
        if self.unit_type == 'gram':
            return quantity / 1000  # Convert grams to kg
        return quantity  # Already in kg or litres

    def convert_from_kg(self, quantity):
        """Convert the given quantity from kilograms if needed"""
        if self.unit_type == 'gram':
            return quantity * 1000  # Convert kg to grams
        return quantity  # Already in kg or litres

class Vaccine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity_per_unit = db.Column(db.Float, nullable=False)  # in ml
    price = db.Column(db.Float, nullable=False)
    doses_required = db.Column(db.Integer, nullable=False)  # Number of times vaccine should be given
    dose_ages = db.Column(db.Text, nullable=False)  # JSON string of ages for each dose in days
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_dose_ages(self):
        return json.loads(self.dose_ages)

    def set_dose_ages(self, ages):
        self.dose_ages = json.dumps(ages)

class MedicineSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'), nullable=False)
    schedule_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    medicine = db.relationship('Medicine', backref='schedules')
    batches = db.relationship('Batch', secondary='medicine_schedule_batches', backref='medicine_schedules')

# Association table for many-to-many relationship between MedicineSchedule and Batch
medicine_schedule_batches = db.Table('medicine_schedule_batches',
    db.Column('medicine_schedule_id', db.Integer, db.ForeignKey('medicine_schedule.id'), primary_key=True),
    db.Column('batch_id', db.Integer, db.ForeignKey('batch.id'), primary_key=True)
)

# Association table for many-to-many relationship between VaccineSchedule and Batch
vaccine_schedule_batches = db.Table('vaccine_schedule_batches',
    db.Column('vaccine_schedule_id', db.Integer, db.ForeignKey('vaccine_schedule.id'), primary_key=True),
    db.Column('batch_id', db.Integer, db.ForeignKey('batch.id'), primary_key=True)
)

# Association table for many-to-many relationship between HealthMaterialSchedule and Batch
health_material_schedule_batches = db.Table('health_material_schedule_batches',
    db.Column('health_material_schedule_id', db.Integer, db.ForeignKey('health_material_schedule.id'), primary_key=True),
    db.Column('batch_id', db.Integer, db.ForeignKey('batch.id'), primary_key=True)
)

class VaccineSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey('vaccine.id'), nullable=False)
    dose_number = db.Column(db.Integer, nullable=False)  # Which dose number this is (1st, 2nd, etc.)
    scheduled_date = db.Column(db.Date, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vaccine = db.relationship('Vaccine', backref='schedules')
    batches = db.relationship('Batch', secondary=vaccine_schedule_batches, backref='vaccine_schedules')

class HealthMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # e.g., 'Disinfectant', 'Sanitizer', 'Equipment'
    quantity_per_unit = db.Column(db.Float, nullable=False)
    unit_type = db.Column(db.String(20), nullable=False)  # e.g., 'litre', 'piece', 'box'
    price = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class HealthMaterialSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    health_material_id = db.Column(db.Integer, db.ForeignKey('health_material.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    health_material = db.relationship('HealthMaterial', backref='schedules')
    batches = db.relationship('Batch', secondary=health_material_schedule_batches, backref='health_material_schedules')

# Association tables for BatchUpdate relationships
batch_update_feeds = db.Table('batch_update_feeds',
    db.Column('batch_update_id', db.Integer, db.ForeignKey('batch_update.id'), primary_key=True),
    db.Column('feed_id', db.Integer, db.ForeignKey('feed.id'), primary_key=True),
    db.Column('quantity', db.Float, nullable=False, default=0)
)

batch_update_medicines = db.Table('batch_update_medicines',
    db.Column('batch_update_id', db.Integer, db.ForeignKey('batch_update.id'), primary_key=True),
    db.Column('medicine_id', db.Integer, db.ForeignKey('medicine.id'), primary_key=True),
    db.Column('quantity', db.Float, nullable=False, default=0)
)

batch_update_health_materials = db.Table('batch_update_health_materials',
    db.Column('batch_update_id', db.Integer, db.ForeignKey('batch_update.id'), primary_key=True),
    db.Column('health_material_id', db.Integer, db.ForeignKey('health_material.id'), primary_key=True),
    db.Column('quantity', db.Float, nullable=False, default=0)
)

class BatchUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    mortality_count = db.Column(db.Integer, nullable=False, default=0)
    feed_used = db.Column(db.Float, nullable=False, default=0)  # Feed used in packets
    avg_weight = db.Column(db.Float, nullable=False, default=0)  # Average weight in kg
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    batch = db.relationship('Batch', backref=db.backref('updates', lazy=True))
    feeds = db.relationship('Feed', secondary=batch_update_feeds, backref=db.backref('batch_updates', lazy=True))
    medicines = db.relationship('Medicine', secondary=batch_update_medicines, backref=db.backref('batch_updates', lazy=True))
    health_materials = db.relationship('HealthMaterial', secondary=batch_update_health_materials, backref=db.backref('batch_updates', lazy=True))

    def get_feed_quantity(self, feed_id):
        """Get the quantity of a specific feed"""
        result = db.session.query(batch_update_feeds.c.quantity).filter(
            batch_update_feeds.c.batch_update_id == self.id,
            batch_update_feeds.c.feed_id == feed_id
        ).scalar()
        return result or 0

    def get_medicine_quantity(self, medicine_id):
        """Get the quantity of a specific medicine"""
        result = db.session.query(batch_update_medicines.c.quantity).filter(
            batch_update_medicines.c.batch_update_id == self.id,
            batch_update_medicines.c.medicine_id == medicine_id
        ).scalar()
        return result or 0

    def get_health_material_quantity(self, health_material_id):
        """Get the quantity of a specific health material"""
        result = db.session.query(batch_update_health_materials.c.quantity).filter(
            batch_update_health_materials.c.batch_update_id == self.id,
            batch_update_health_materials.c.health_material_id == health_material_id
        ).scalar()
        return result or 0

class Harvest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    quantity = db.Column(db.Integer, nullable=False)
    weight = db.Column(db.Float, nullable=False)  # Weight in kg
    selling_price = db.Column(db.Float, nullable=False)  # Price per kg
    total_value = db.Column(db.Float, nullable=False)  # Total value (weight * selling_price)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    batch = db.relationship('Batch', backref=db.backref('harvests', lazy=True))

def init_db():
    with app.app_context():
        try:
            # # Drop existing tables to recreate with new schema
            # db.drop_all()

            # Create all tables
            db.create_all()

            # # Create a default admin user
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
        if session.get('user_type') == 'manager':
            return redirect(url_for('manager_dashboard'))
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
            
            # Redirect based on user type
            if user.user_type in ['assistant_manager', 'senior_manager']:
                return redirect(url_for('manager_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        flash('An error occurred during login', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
@admin_required
def dashboard():
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
                total_area=float(request.form.get('total_area', 0)),
                owner_name=request.form.get('owner_name'),
                contact_number=request.form.get('contact_number', ''),
                farm_condition=request.form.get('farm_condition', 'average')
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
            farm.total_area = float(request.form.get('total_area', 0))
            farm.owner_name = request.form.get('owner_name')
            farm.contact_number = request.form.get('contact_number', '')
            farm.farm_condition = request.form.get('farm_condition', 'average')
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
    return render_template('batches.html', 
                         batches=batches,
                         now=datetime.utcnow(),
                         timedelta=timedelta)  # Add timedelta to template context

def generate_batch_number():
    # Get the last batch number
    last_batch = Batch.query.order_by(Batch.id.desc()).first()
    
    if last_batch:
        # Extract the sequence number from the last batch number
        try:
            last_seq = int(last_batch.batch_number)
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = 1
    else:
        new_seq = 1
    
    # Return just the sequence number
    return str(new_seq)

@app.route('/batches/add', methods=['GET', 'POST'])
@login_required
def add_batch():
    if request.method == 'POST':
        try:
            farm_id = int(request.form.get('farm_id'))
            farm = Farm.query.get_or_404(farm_id)
            
            # Get total birds and validate against farm capacity
            total_birds = int(request.form.get('total_birds', 0))
            available_capacity = farm.get_available_capacity()
            if total_birds > available_capacity:
                raise ValueError(f'Total birds ({total_birds}) exceeds available farm capacity ({available_capacity})')
            
            # Get created_at date or use current date
            try:
                created_at = datetime.strptime(request.form.get('created_at'), '%Y-%m-%dT%H:%M')
            except (ValueError, TypeError):
                created_at = datetime.utcnow()
            
            # Get manager_id if provided
            manager_id = request.form.get('manager_id')
            if manager_id:
                manager_id = int(manager_id)
                # Verify manager exists and is actually a manager
                manager = User.query.get(manager_id)
                if not manager or manager.user_type not in ['assistant_manager', 'senior_manager']:
                    raise ValueError('Invalid manager selected')
            
            # Get brand if provided
            brand = request.form.get('brand', '').strip() or None
            
            # Get shed capacities from farm and validate
            shed_capacities = farm.get_shed_capacities()
            shed_available = farm.get_shed_available_capacities()
            shed_birds = []
            total_shed_birds = 0
            
            # Get individual shed bird counts
            for i in range(1, farm.num_sheds + 1):
                birds = int(request.form.get(f'shed_birds_{i}', 0))
                if birds > shed_available[i-1]:
                    raise ValueError(f'Number of birds in Shed {i} ({birds}) exceeds available capacity ({shed_available[i-1]})')
                shed_birds.append(birds)
                total_shed_birds += birds
            
            # Validate total birds matches sum of shed birds
            if total_birds != total_shed_birds:
                raise ValueError(f'Sum of birds in sheds ({total_shed_birds}) does not match total birds ({total_birds})')
            
            # Get cost per chicken and initial feed usage
            cost_per_chicken = float(request.form.get('cost_per_chicken', 0))
            feed_usage = float(request.form.get('feed_usage', 0))
            
            # Generate batch number automatically
            batch_number = generate_batch_number()
            
            batch = Batch(
                farm_id=farm_id,
                manager_id=manager_id,
                batch_number=batch_number,
                brand=brand,
                total_birds=total_birds,
                available_birds=total_birds,  # Initially all birds are available
                cost_per_chicken=cost_per_chicken,
                feed_usage=feed_usage,
                created_at=created_at
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
    managers = User.query.filter(User.user_type.in_(['assistant_manager', 'senior_manager'])).all()
    return render_template('add_batch.html', farms=farms, managers=managers)

@app.route('/batches/edit/<int:batch_id>', methods=['GET', 'POST'])
@login_required
def edit_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    if request.method == 'POST':
        try:
            # Get total birds and validate against farm capacity
            new_total_birds = int(request.form.get('total_birds', 0))
            current_total_birds = batch.total_birds
            farm = batch.farm
            
            # Calculate available capacity excluding current batch
            available_capacity = farm.get_available_capacity() + current_total_birds
            
            if new_total_birds > available_capacity:
                raise ValueError(f'Total birds ({new_total_birds}) exceeds available farm capacity ({available_capacity})')
            
            # Get created_at date
            try:
                created_at = datetime.strptime(request.form.get('created_at'), '%Y-%m-%dT%H:%M')
                batch.created_at = created_at
            except (ValueError, TypeError):
                pass  # Keep existing created_at if invalid
            
            # Update manager if provided
            manager_id = request.form.get('manager_id')
            if manager_id:
                manager_id = int(manager_id)
                # Verify manager exists and is actually a manager
                manager = User.query.get(manager_id)
                if not manager or manager.user_type not in ['assistant_manager', 'senior_manager']:
                    raise ValueError('Invalid manager selected')
                batch.manager_id = manager_id
            else:
                batch.manager_id = None
            
            # Update brand
            brand = request.form.get('brand', '').strip() or None
            batch.brand = brand
            
            # Get shed capacities from farm and validate
            shed_available = [cap + curr for cap, curr in zip(farm.get_shed_available_capacities(), batch.get_shed_birds())]
            new_shed_birds = []
            total_shed_birds = 0
            
            # Get individual shed bird counts
            for i in range(1, farm.num_sheds + 1):
                birds = int(request.form.get(f'shed_birds_{i}', 0))
                if birds > shed_available[i-1]:
                    raise ValueError(f'Number of birds in Shed {i} ({birds}) exceeds available capacity ({shed_available[i-1]})')
                new_shed_birds.append(birds)
                total_shed_birds += birds
            
            # Validate total birds matches sum of shed birds
            if new_total_birds != total_shed_birds:
                raise ValueError(f'Sum of birds in sheds ({total_shed_birds}) does not match total birds ({new_total_birds})')
            
            # Update batch fields
            batch.total_birds = new_total_birds
            batch.available_birds = new_total_birds - (current_total_birds - batch.available_birds)  # Maintain the same number of used birds
            batch.cost_per_chicken = float(request.form.get('cost_per_chicken', 0))
            batch.feed_usage = float(request.form.get('feed_usage', 0))
            batch.set_shed_birds(new_shed_birds)
            
            db.session.commit()
            flash('Batch updated successfully', 'success')
            return redirect(url_for('batches'))
        except Exception as e:
            flash('Error updating batch: ' + str(e), 'error')
            db.session.rollback()
    
    managers = User.query.filter(User.user_type.in_(['assistant_manager', 'senior_manager'])).all()
    return render_template('edit_batch.html', batch=batch, managers=managers)

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
        
        # First delete all related batch updates
        BatchUpdate.query.filter_by(batch_id=batch_id).delete()
        
        # Then delete the batch
        db.session.delete(batch)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/batches/<int:batch_id>/update-status', methods=['POST'])
@login_required
def update_batch_status(batch_id):
    try:
        batch = Batch.query.get_or_404(batch_id)
        data = request.get_json()
        new_status = data.get('status')
        
        if new_status not in ['ongoing', 'closing', 'closed']:
            return jsonify({'success': False, 'message': 'Invalid status'})
        
        batch.status = new_status
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/batches/<int:batch_id>/update', methods=['GET', 'POST'])
@login_required
def update_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    today = datetime.utcnow().date()
    
    # Get all available feeds, medicines, and health materials
    feeds = Feed.query.all()
    medicines = Medicine.query.all()
    health_materials = HealthMaterial.query.all()
    
    # Check if an update already exists for today
    existing_update = BatchUpdate.query.filter(
        BatchUpdate.batch_id == batch_id,
        db.func.date(BatchUpdate.date) == today
    ).first()
    
    if request.method == 'POST':
        if existing_update:
            flash('An update for this batch has already been submitted today.', 'error')
            return redirect(url_for('batches'))
            
        try:
            # Get basic form data
            mortality_count = int(request.form.get('mortality_count', 0))
            feed_used = float(request.form.get('feed_used', 0))
            avg_weight = float(request.form.get('avg_weight', 0))
            notes = request.form.get('notes', '')

            # Get feed data
            feed_ids = request.form.getlist('feed_id[]')
            feed_quantities = request.form.getlist('feed_quantity[]')
            
            # Calculate total feed allocation (default to 0 if no feeds added)
            total_feed_allocation = 0
            if feed_ids and feed_quantities:
                total_feed_allocation = sum(float(qty) for qty, fid in zip(feed_quantities, feed_ids) if qty and fid)

            # Create new batch update
            update = BatchUpdate(
                batch_id=batch.id,
                date=today,
                mortality_count=mortality_count,
                feed_used=feed_used,
                avg_weight=avg_weight,
                notes=notes
            )

            # Update batch's available birds and total mortality
            batch.available_birds -= mortality_count
            batch.total_mortality += mortality_count
            batch.check_and_update_status()
            
            # Update feed stock and feed usage
            batch.feed_stock = (batch.feed_stock - feed_used) + total_feed_allocation
            batch.feed_usage += feed_used

            # First save the batch update to get an ID
            db.session.add(update)
            db.session.flush()

            # Process feeds if any
            if feed_ids and feed_quantities:
                for feed_id, quantity in zip(feed_ids, feed_quantities):
                    if feed_id and float(quantity) > 0:
                        db.session.execute(
                            batch_update_feeds.insert().values(
                                batch_update_id=update.id,
                                feed_id=int(feed_id),
                                quantity=float(quantity)
                            )
                        )

            # Process medicines if any
            medicine_ids = request.form.getlist('medicine_id[]')
            medicine_quantities = request.form.getlist('medicine_quantity[]')
            if medicine_ids and medicine_quantities:
                for medicine_id, quantity in zip(medicine_ids, medicine_quantities):
                    if medicine_id and float(quantity) > 0:
                        db.session.execute(
                            batch_update_medicines.insert().values(
                                batch_update_id=update.id,
                                medicine_id=int(medicine_id),
                                quantity=float(quantity)
                            )
                        )

            # Process health materials if any
            health_material_ids = request.form.getlist('health_material_id[]')
            health_material_quantities = request.form.getlist('health_material_quantity[]')
            if health_material_ids and health_material_quantities:
                for health_material_id, quantity in zip(health_material_ids, health_material_quantities):
                    if health_material_id and float(quantity) > 0:
                        db.session.execute(
                            batch_update_health_materials.insert().values(
                                batch_update_id=update.id,
                                health_material_id=int(health_material_id),
                                quantity=float(quantity)
                            )
                        )

            db.session.commit()
            flash('Batch update saved successfully!', 'success')
            return redirect(url_for('batches'))
        except ValueError as e:
            db.session.rollback()
            flash(f'Invalid input: {str(e)}', 'error')
            return redirect(url_for('update_batch', batch_id=batch_id))
        except Exception as e:
            db.session.rollback()
            flash('Error saving batch update. Please try again.', 'error')
            print(f"Error: {str(e)}")
            return redirect(url_for('update_batch', batch_id=batch_id))

    return render_template('update_batch.html', 
                         batch=batch, 
                         existing_update=existing_update,
                         feeds=feeds,
                         medicines=medicines,
                         health_materials=health_materials)

@app.route('/batches/<int:batch_id>/update/<date>')
@login_required
def get_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        update_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter(
            BatchUpdate.batch_id == batch_id,
            db.func.date(BatchUpdate.date) == update_date
        ).first()
        
        if update:
            # Get feeds with their quantities
            feeds = []
            for feed in update.feeds:
                feeds.append({
                    'brand': feed.brand,
                    'category': feed.category,
                    'quantity': update.get_feed_quantity(feed.id)
                })

            # Get medicines with their quantities
            medicines = []
            for medicine in update.medicines:
                medicines.append({
                    'name': medicine.name,
                    'unit_type': medicine.unit_type,
                    'quantity': update.get_medicine_quantity(medicine.id)
                })

            # Get health materials with their quantities
            health_materials = []
            for material in update.health_materials:
                health_materials.append({
                    'name': material.name,
                    'category': material.category,
                    'unit_type': material.unit_type,
                    'quantity': update.get_health_material_quantity(material.id)
                })

            return jsonify({
                'success': True,
                'update': {
                    'date': update.date.strftime('%Y-%m-%d'),
                    'mortality_count': update.mortality_count,
                    'feed_used': update.feed_used,
                    'avg_weight': update.avg_weight,
                    'notes': update.notes,
                    'feeds': feeds,
                    'medicines': medicines,
                    'health_materials': health_materials
                }
            })
        else:
            return jsonify({
                'success': True,
                'update': None
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/batches/<int:batch_id>/update/<date>/edit', methods=['GET', 'POST'])
@login_required
def edit_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        update_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter(
            BatchUpdate.batch_id == batch_id,
            db.func.date(BatchUpdate.date) == update_date
        ).first_or_404()
        
        # Get all available feeds, medicines, and health materials
        feeds = Feed.query.all()
        medicines = Medicine.query.all()
        health_materials = HealthMaterial.query.all()
        
        if request.method == 'POST':
            try:
                # Get the current mortality count to calculate difference
                old_mortality = update.mortality_count
                new_mortality = int(request.form.get('mortality_count', 0))
                mortality_difference = new_mortality - old_mortality
                
                # Get old feed quantities for stock calculation
                old_feed_allocation = sum(update.get_feed_quantity(feed.id) for feed in update.feeds)
                
                # Get old feed used
                old_feed_used = update.feed_used

                # Update basic information
                update.mortality_count = new_mortality
                new_feed_used = float(request.form.get('feed_used', 0))
                update.avg_weight = float(request.form.get('avg_weight', 0))
                update.notes = request.form.get('notes', '')

                # Update batch's available birds and total mortality
                batch.available_birds -= mortality_difference
                batch.total_mortality += mortality_difference
                batch.check_and_update_status()

                # Calculate new feed allocation from feed quantities
                feed_data = request.form.getlist('feed_id[]')
                feed_quantities = request.form.getlist('feed_quantity[]')
                new_feed_allocation = 0
                for quantity in feed_quantities:
                    if quantity and float(quantity) > 0:
                        new_feed_allocation += float(quantity)

                # Update feed stock and feed usage
                batch.feed_stock = batch.feed_stock - (old_feed_allocation - new_feed_allocation) + (old_feed_used - new_feed_used)
                batch.feed_usage = batch.feed_usage - old_feed_used + new_feed_used  # Update total feed usage
                update.feed_used = new_feed_used

                # Update feeds
                db.session.execute(batch_update_feeds.delete().where(
                    batch_update_feeds.c.batch_update_id == update.id
                ))
                for feed_id, quantity in zip(feed_data, feed_quantities):
                    if feed_id and float(quantity) > 0:
                        feed = Feed.query.get(int(feed_id))
                        if feed:
                            db.session.execute(
                                batch_update_feeds.insert().values(
                                    batch_update_id=update.id,
                                    feed_id=feed.id,
                                    quantity=float(quantity)
                                )
                            )

                # Update medicines
                db.session.execute(batch_update_medicines.delete().where(
                    batch_update_medicines.c.batch_update_id == update.id
                ))
                medicine_data = request.form.getlist('medicine_id[]')
                medicine_quantities = request.form.getlist('medicine_quantity[]')
                for medicine_id, quantity in zip(medicine_data, medicine_quantities):
                    if medicine_id and float(quantity) > 0:
                        medicine = Medicine.query.get(int(medicine_id))
                        if medicine:
                            db.session.execute(
                                batch_update_medicines.insert().values(
                                    batch_update_id=update.id,
                                    medicine_id=medicine.id,
                                    quantity=float(quantity)
                                )
                            )

                # Update health materials
                db.session.execute(batch_update_health_materials.delete().where(
                    batch_update_health_materials.c.batch_update_id == update.id
                ))
                health_material_data = request.form.getlist('health_material_id[]')
                health_material_quantities = request.form.getlist('health_material_quantity[]')
                for health_material_id, quantity in zip(health_material_data, health_material_quantities):
                    if health_material_id and float(quantity) > 0:
                        health_material = HealthMaterial.query.get(int(health_material_id))
                        if health_material:
                            db.session.execute(
                                batch_update_health_materials.insert().values(
                                    batch_update_id=update.id,
                                    health_material_id=health_material.id,
                                    quantity=float(quantity)
                                )
                            )

                db.session.commit()
                flash('Batch update edited successfully!', 'success')
                return redirect(url_for('view_batch', batch_id=batch.id))
            except Exception as e:
                db.session.rollback()
                flash('Error editing batch update. Please try again.', 'error')
                print(f"Error: {str(e)}")
                
        return render_template('edit_batch_update.html',
                             batch=batch,
                             update=update,
                             feeds=feeds,
                             medicines=medicines,
                             health_materials=health_materials)
                             
    except Exception as e:
        flash('Error accessing batch update. Please try again.', 'error')
        return redirect(url_for('view_batch', batch_id=batch_id))

@app.route('/batches/<int:batch_id>/update/<date>/delete', methods=['POST'])
@login_required
def delete_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        update_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter(
            BatchUpdate.batch_id == batch_id,
            db.func.date(BatchUpdate.date) == update_date
        ).first_or_404()
        
        # Get feed quantities for stock calculation
        feed_allocation = sum(update.get_feed_quantity(feed.id) for feed in update.feeds)
        
        # Reverse all calculations
        # 1. Add back the mortality count to available birds
        batch.available_birds += update.mortality_count
        # 2. Subtract the mortality count from total mortality
        batch.total_mortality -= update.mortality_count
        # 3. Reverse feed stock calculation: current_stock - allocation + used
        batch.feed_stock = batch.feed_stock - feed_allocation + update.feed_used
        # 4. Subtract feed used from total feed usage
        batch.feed_usage -= update.feed_used
        
        # Delete the update
        db.session.delete(update)
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
                price=float(request.form.get('price'))
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

@app.route('/medicines')
def medicines():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    medicines = Medicine.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('medicines.html', medicines=medicines, batches=batches)

@app.route('/medicine/add', methods=['GET', 'POST'])
def add_medicine():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        quantity_per_unit = float(request.form.get('quantity_per_unit'))
        unit_type = request.form.get('unit_type')
        price = float(request.form.get('price'))
        stock = int(request.form.get('stock'))
        notes = request.form.get('notes')

        medicine = Medicine(
            name=name,
            quantity_per_unit=quantity_per_unit,
            unit_type=unit_type,
            price=price,
            notes=notes
        )

        db.session.add(medicine)
        db.session.commit()
        flash('Medicine added successfully!', 'success')
        return redirect(url_for('medicines'))

    return render_template('add_medicine.html')

@app.route('/medicine/<int:id>')
def view_medicine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    medicine = Medicine.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_medicine.html', medicine=medicine, batches=batches)

@app.route('/medicine/<int:id>/edit', methods=['GET', 'POST'])
def edit_medicine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    medicine = Medicine.query.get_or_404(id)
    
    if request.method == 'POST':
        medicine.name = request.form.get('name')
        medicine.quantity_per_unit = float(request.form.get('quantity_per_unit'))
        medicine.unit_type = request.form.get('unit_type')
        medicine.price = float(request.form.get('price'))
        medicine.notes = request.form.get('notes')

        db.session.commit()
        flash('Medicine updated successfully!', 'success')
        return redirect(url_for('view_medicine', id=medicine.id))

    return render_template('edit_medicine.html', medicine=medicine)

@app.route('/medicine/<int:id>/delete', methods=['POST'])
def delete_medicine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    medicine = Medicine.query.get_or_404(id)
    db.session.delete(medicine)
    db.session.commit()
    flash('Medicine deleted successfully!', 'success')
    return redirect(url_for('medicines'))

@app.route('/medicine/schedule', methods=['POST'])
def schedule_medicine():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    medicine_id = request.form.get('medicine_id')
    batch_ids = request.form.getlist('batch_ids')  # Get list of selected batch IDs
    schedule_date = datetime.strptime(request.form.get('schedule_date'), '%Y-%m-%d').date()
    notes = request.form.get('notes')

    schedule = MedicineSchedule(
        medicine_id=medicine_id,
        schedule_date=schedule_date,
        notes=notes
    )

    # Add selected batches to the schedule
    for batch_id in batch_ids:
        batch = Batch.query.get(batch_id)
        if batch:
            schedule.batches.append(batch)

    db.session.add(schedule)
    db.session.commit()
    flash('Medicine scheduled successfully!', 'success')
    return redirect(url_for('view_medicine', id=medicine_id))

@app.route('/medicine/schedule/<int:id>/delete', methods=['POST'])
def delete_schedule(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    schedule = MedicineSchedule.query.get_or_404(id)
    medicine_id = schedule.medicine_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Schedule deleted successfully!', 'success')
    return redirect(url_for('view_medicine', id=medicine_id))

@app.route('/medicine/schedule/<int:id>/complete', methods=['POST'])
@login_required
def complete_medicine_schedule(id):
    if session.get('user_type') not in ['admin', 'senior_manager', 'assistant_manager']:
        return jsonify({'success': False, 'message': 'Access denied. Only administrators and managers can complete schedules.'}), 403
    
    try:
        schedule = MedicineSchedule.query.get_or_404(id)
        
        # Check if assistant manager has access to any of the batches
        if session.get('user_type') == 'assistant_manager':
            has_access = any(batch.manager_id == session.get('user_id') for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied. You can only complete schedules for your assigned batches.'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/vaccines')
def vaccines():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    vaccines = Vaccine.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('vaccines.html', vaccines=vaccines, batches=batches)

@app.route('/vaccine/add', methods=['GET', 'POST'])
def add_vaccine():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            quantity_per_unit = float(request.form.get('quantity_per_unit'))
            price = float(request.form.get('price'))
            doses_required = int(request.form.get('doses_required'))
            
            # Get dose ages
            dose_ages = []
            for i in range(1, doses_required + 1):
                age = int(request.form.get(f'dose_age_{i}'))
                dose_ages.append(age)
            
            notes = request.form.get('notes')

            vaccine = Vaccine(
                name=name,
                quantity_per_unit=quantity_per_unit,
                price=price,
                doses_required=doses_required,
                notes=notes
            )
            vaccine.set_dose_ages(dose_ages)

            db.session.add(vaccine)
            db.session.commit()
            flash('Vaccine added successfully!', 'success')
            return redirect(url_for('vaccines'))
        except Exception as e:
            flash('Error adding vaccine: ' + str(e), 'error')
            db.session.rollback()
    
    return render_template('add_vaccine.html')

@app.route('/vaccine/<int:id>')
def view_vaccine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    vaccine = Vaccine.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_vaccine.html', vaccine=vaccine, batches=batches)

@app.route('/vaccine/<int:id>/edit', methods=['GET', 'POST'])
def edit_vaccine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    vaccine = Vaccine.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            vaccine.name = request.form.get('name')
            vaccine.quantity_per_unit = float(request.form.get('quantity_per_unit'))
            vaccine.price = float(request.form.get('price'))
            vaccine.doses_required = int(request.form.get('doses_required'))
            
            # Get dose ages
            dose_ages = []
            for i in range(1, vaccine.doses_required + 1):
                age = int(request.form.get(f'dose_age_{i}'))
                dose_ages.append(age)
            
            vaccine.set_dose_ages(dose_ages)
            vaccine.notes = request.form.get('notes')

            db.session.commit()
            flash('Vaccine updated successfully!', 'success')
            return redirect(url_for('view_vaccine', id=vaccine.id))
        except Exception as e:
            flash('Error updating vaccine: ' + str(e), 'error')
            db.session.rollback()
    
    return render_template('edit_vaccine.html', vaccine=vaccine)

@app.route('/vaccine/<int:id>/delete', methods=['POST'])
def delete_vaccine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    vaccine = Vaccine.query.get_or_404(id)
    db.session.delete(vaccine)
    db.session.commit()
    flash('Vaccine deleted successfully!', 'success')
    return redirect(url_for('vaccines'))

@app.route('/vaccine/schedule', methods=['POST'])
def schedule_vaccine():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    try:
        vaccine_id = request.form.get('vaccine_id')
        batch_ids = request.form.getlist('batch_ids')  # Get list of selected batch IDs
        dose_number = int(request.form.get('dose_number'))
        scheduled_date = datetime.strptime(request.form.get('scheduled_date'), '%Y-%m-%d').date()
        notes = request.form.get('notes')

        schedule = VaccineSchedule(
            vaccine_id=vaccine_id,
            dose_number=dose_number,
            scheduled_date=scheduled_date,
            notes=notes
        )

        # Add selected batches to the schedule
        for batch_id in batch_ids:
            batch = Batch.query.get(batch_id)
            if batch:
                schedule.batches.append(batch)

        db.session.add(schedule)
        db.session.commit()
        flash('Vaccine scheduled successfully!', 'success')
    except Exception as e:
        flash('Error scheduling vaccine: ' + str(e), 'error')
        db.session.rollback()
    
    return redirect(url_for('view_vaccine', id=vaccine_id))

@app.route('/vaccine/schedule/<int:id>/delete', methods=['POST'])
def delete_vaccine_schedule(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    schedule = VaccineSchedule.query.get_or_404(id)
    vaccine_id = schedule.vaccine_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Vaccine schedule deleted successfully!', 'success')
    return redirect(url_for('view_vaccine', id=vaccine_id))

@app.route('/health-materials')
def health_materials():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    health_materials = HealthMaterial.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('health_materials.html', health_materials=health_materials, batches=batches)

@app.route('/health-material/add', methods=['GET', 'POST'])
def add_health_material():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            category = request.form.get('category')
            quantity_per_unit = float(request.form.get('quantity_per_unit'))
            unit_type = request.form.get('unit_type')
            price = float(request.form.get('price'))
            notes = request.form.get('notes')

            health_material = HealthMaterial(
                name=name,
                category=category,
                quantity_per_unit=quantity_per_unit,
                unit_type=unit_type,
                price=price,
                notes=notes
            )

            db.session.add(health_material)
            db.session.commit()
            flash('Health material added successfully!', 'success')
            return redirect(url_for('health_materials'))
        except Exception as e:
            flash('Error adding health material: ' + str(e), 'error')
            db.session.rollback()
    
    return render_template('add_health_material.html')

@app.route('/health-material/<int:id>')
def view_health_material(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    health_material = HealthMaterial.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_health_material.html', health_material=health_material, batches=batches)

@app.route('/health-material/<int:id>/edit', methods=['GET', 'POST'])
def edit_health_material(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    health_material = HealthMaterial.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            health_material.name = request.form.get('name')
            health_material.category = request.form.get('category')
            health_material.quantity_per_unit = float(request.form.get('quantity_per_unit'))
            health_material.unit_type = request.form.get('unit_type')
            health_material.price = float(request.form.get('price'))
            health_material.notes = request.form.get('notes')

            db.session.commit()
            flash('Health material updated successfully!', 'success')
            return redirect(url_for('view_health_material', id=health_material.id))
        except Exception as e:
            flash('Error updating health material: ' + str(e), 'error')
            db.session.rollback()
    
    return render_template('edit_health_material.html', health_material=health_material)

@app.route('/health-material/<int:id>/delete', methods=['POST'])
def delete_health_material(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    health_material = HealthMaterial.query.get_or_404(id)
    db.session.delete(health_material)
    db.session.commit()
    flash('Health material deleted successfully!', 'success')
    return redirect(url_for('health_materials'))

@app.route('/health-material/schedule', methods=['POST'])
def schedule_health_material():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    try:
        health_material_id = request.form.get('health_material_id')
        batch_ids = request.form.getlist('batch_ids')  # Get list of selected batch IDs
        
        # Validate that at least one batch is selected
        if not batch_ids:
            flash('Please select at least one batch', 'error')
            return redirect(url_for('view_health_material', id=health_material_id))
            
        scheduled_date = datetime.strptime(request.form.get('scheduled_date'), '%Y-%m-%d').date()
        notes = request.form.get('notes')

        # Create the schedule first
        schedule = HealthMaterialSchedule(
            health_material_id=health_material_id,
            scheduled_date=scheduled_date,
            notes=notes
        )
        
        # Add the schedule to the session to get an ID
        db.session.add(schedule)
        db.session.flush()

        # Add selected batches to the schedule through the association table
        for batch_id in batch_ids:
            batch = Batch.query.get(batch_id)
            if batch:
                schedule.batches.append(batch)

        db.session.commit()
        flash('Health material scheduled successfully!', 'success')
    except Exception as e:
        flash('Error scheduling health material: ' + str(e), 'error')
        db.session.rollback()
    
    return redirect(url_for('view_health_material', id=health_material_id))

@app.route('/health-material/schedule/<int:id>/delete', methods=['POST'])
def delete_health_material_schedule(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    schedule = HealthMaterialSchedule.query.get_or_404(id)
    health_material_id = schedule.health_material_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Health material schedule deleted successfully!', 'success')
    return redirect(url_for('view_health_material', id=health_material_id))

@app.route('/health-material/schedule/<int:id>/complete', methods=['POST'])
@login_required
def complete_health_material_schedule(id):
    if session.get('user_type') not in ['admin', 'senior_manager', 'assistant_manager']:
        return jsonify({'success': False, 'message': 'Access denied. Only administrators and managers can complete schedules.'}), 403
    
    try:
        schedule = HealthMaterialSchedule.query.get_or_404(id)
        
        # Check if assistant manager has access to any of the batches
        if session.get('user_type') == 'assistant_manager':
            has_access = any(batch.manager_id == session.get('user_id') for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied. You can only complete schedules for your assigned batches.'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/manager/harvest')
@login_required
def manager_harvest():
    try:
        # Get current date and time
        now = datetime.now()
        today = now.date()
        yesterday = today - timedelta(days=1)
        
        # Get batches in closing or closed status
        if session.get('user_type') == 'assistant_manager':
            batches = Batch.query.filter(
                Batch.manager_id == session.get('user_id'),
                Batch.status.in_(['closing', 'closed'])
            ).all()
        else:
            batches = Batch.query.filter(
                Batch.status.in_(['closing', 'closed'])
            ).all()
        
        # Get harvests for these batches
        harvests = []
        for batch in batches:
            batch_harvests = Harvest.query.filter_by(batch_id=batch.id).order_by(Harvest.date.desc()).all()
            for harvest in batch_harvests:
                harvests.append({
                    'id': harvest.id,
                    'batch_number': batch.batch_number,
                    'date': harvest.date,
                    'quantity': harvest.quantity,
                    'weight': harvest.weight,
                    'selling_price': harvest.selling_price,
                    'total_value': harvest.total_value,
                    'notes': harvest.notes
                })
        
        return render_template('manager/harvest.html', 
                             batches=batches,
                             harvests=harvests,
                             now=now,
                             today=today,
                             yesterday=yesterday,
                             timedelta=timedelta)  # Add timedelta to template context
    except Exception as e:
        flash('Error loading harvest data: ' + str(e), 'error')
        return redirect(url_for('manager_dashboard'))

@app.route('/manager/harvest/<int:batch_id>', methods=['GET', 'POST'])
@login_required
def manager_harvest_batch(batch_id):
    try:
        # Get current date and time
        now = datetime.now()
        
        batch = Batch.query.get_or_404(batch_id)
        
        # Check if batch is in closing or closed status
        if batch.status not in ['closing', 'closed']:
            flash('Harvesting is only available for batches in closing or closed status', 'error')
            return redirect(url_for('manager_harvest'))
        
        # Check if assistant manager has access to this batch
        if session.get('user_type') == 'assistant_manager' and batch.manager_id != session.get('user_id'):
            flash('You do not have access to this batch', 'error')
            return redirect(url_for('manager_harvest'))
        
        if request.method == 'POST':
            try:
                quantity = int(request.form.get('quantity', 0))
                weight = float(request.form.get('weight', 0))
                selling_price = float(request.form.get('selling_price', 0))
                notes = request.form.get('notes', '')
                
                if quantity > batch.available_birds:
                    flash('Harvest quantity cannot exceed available birds', 'error')
                    return redirect(url_for('manager_harvest_batch', batch_id=batch_id))
                
                total_value = weight * selling_price
                
                harvest = Harvest(
                    batch_id=batch.id,
                    date=now.date(),
                    quantity=quantity,
                    weight=weight,
                    selling_price=selling_price,
                    total_value=total_value,
                    notes=notes
                )
                
                # Update batch's available birds
                batch.available_birds -= quantity
                batch.check_and_update_status()
                
                db.session.add(harvest)
                db.session.commit()
                
                flash('Harvest record added successfully', 'success')
                return redirect(url_for('manager_harvest'))
            except Exception as e:
                db.session.rollback()
                flash('Error adding harvest record: ' + str(e), 'error')
        
        # Get existing harvests for this batch
        harvests = Harvest.query.filter_by(batch_id=batch.id).order_by(Harvest.date.desc()).all()
        
        return render_template('manager/harvest_batch.html', 
                             batch=batch,
                             harvests=harvests,
                             now=now,
                             today=now.date())
    except Exception as e:
        flash('Error accessing harvest data: ' + str(e), 'error')
        return redirect(url_for('manager_harvest'))

# Schedule Management Routes
@app.route('/manager/schedules')
@login_required
def manager_schedules():
    try:
        # Get current date and time
        today = datetime.now().date()
        end_date = today + timedelta(days=30)
        
        # Get schedules based on user type
        if session.get('user_type') == 'assistant_manager':
            # Health Material Schedules
            health_material_schedules = HealthMaterialSchedule.query.join(
                health_material_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.manager_id == session.get('user_id'),
                Batch.status.in_(['ongoing', 'closing']),
                HealthMaterialSchedule.scheduled_date >= today,
                HealthMaterialSchedule.scheduled_date <= end_date
            ).order_by(HealthMaterialSchedule.scheduled_date).all()
            
            # Medical Schedules
            medical_schedules = MedicineSchedule.query.join(
                medicine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.manager_id == session.get('user_id'),
                Batch.status.in_(['ongoing', 'closing']),
                MedicineSchedule.schedule_date >= today,
                MedicineSchedule.schedule_date <= end_date
            ).order_by(MedicineSchedule.schedule_date).all()
            
            # Vaccine Schedules
            vaccine_schedules = VaccineSchedule.query.join(
                vaccine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.manager_id == session.get('user_id'),
                Batch.status.in_(['ongoing', 'closing']),
                VaccineSchedule.scheduled_date >= today,
                VaccineSchedule.scheduled_date <= end_date
            ).order_by(VaccineSchedule.scheduled_date).all()
        else:
            # Senior managers see all schedules
            health_material_schedules = HealthMaterialSchedule.query.join(
                health_material_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                HealthMaterialSchedule.scheduled_date >= today,
                HealthMaterialSchedule.scheduled_date <= end_date
            ).order_by(HealthMaterialSchedule.scheduled_date).all()
            
            medical_schedules = MedicineSchedule.query.join(
                medicine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                MedicineSchedule.schedule_date >= today,
                MedicineSchedule.schedule_date <= end_date
            ).order_by(MedicineSchedule.schedule_date).all()
            
            vaccine_schedules = VaccineSchedule.query.join(
                vaccine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                VaccineSchedule.scheduled_date >= today,
                VaccineSchedule.scheduled_date <= end_date
            ).order_by(VaccineSchedule.scheduled_date).all()
        
        # Get recent activities (last 5 activities)
        recent_activities = []
        
        # Add health material activities
        recent_health = HealthMaterialSchedule.query.join(
            health_material_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(HealthMaterialSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_health:
            # Get the first batch for display
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-spray-can',
                    'title': 'Health Material Scheduled',
                    'description': f'{schedule.health_material.name} for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Add medical activities
        recent_medical = MedicineSchedule.query.join(
            medicine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(MedicineSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_medical:
            # Get the first batch for display
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-pills',
                    'title': 'Medicine Scheduled',
                    'description': f'{schedule.medicine.name} for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Add vaccine activities
        recent_vaccine = VaccineSchedule.query.join(
            vaccine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(VaccineSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_vaccine:
            # Get the first batch for display
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-syringe',
                    'title': 'Vaccine Scheduled',
                    'description': f'{schedule.vaccine.name} (Dose {schedule.dose_number}) for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Sort activities by time
        recent_activities.sort(key=lambda x: x['time'], reverse=True)
        
        return render_template('manager/schedules.html',
                             health_material_schedules=health_material_schedules,
                             medical_schedules=medical_schedules,
                             vaccine_schedules=vaccine_schedules,
                             recent_activities=recent_activities,
                             today=today)
    except Exception as e:
        flash('Error loading schedules', 'error')
        return redirect(url_for('manager_dashboard'))

@app.route('/manager/schedule/<int:schedule_id>/complete', methods=['POST'])
@login_required
@admin_required
def complete_schedule(schedule_id):
    try:
        schedule = Schedule.query.get_or_404(schedule_id)
        
        # Check if assistant manager has access to this schedule
        if session.get('user_type') == 'assistant_manager' and schedule.batch.manager_id != session.get('user_id'):
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        schedule.status = 'completed'
        schedule.completed_at = datetime.now()
        schedule.completed_by = session.get('user_id')
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/manager/schedule/health-material/<int:schedule_id>/complete', methods=['POST'])
@login_required
def complete_health_material_schedule_manager(schedule_id):
    try:
        schedule = HealthMaterialSchedule.query.get_or_404(schedule_id)
        
        # Check if assistant manager has access to this schedule
        if session.get('user_type') == 'assistant_manager':
            # Check if any of the batches are assigned to this manager
            has_access = any(batch.manager_id == session.get('user_id') for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/manager/schedule/vaccine/<int:schedule_id>/complete', methods=['POST'])
@login_required
def complete_vaccine_schedule_manager(schedule_id):
    if session.get('user_type') not in ['admin', 'senior_manager', 'assistant_manager']:
        return jsonify({'success': False, 'message': 'Access denied. Only administrators and managers can complete schedules.'}), 403
    
    try:
        schedule = VaccineSchedule.query.get_or_404(schedule_id)
        
        # Check if assistant manager has access to any of the batches
        if session.get('user_type') == 'assistant_manager':
            has_access = any(batch.manager_id == session.get('user_id') for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied. You can only complete schedules for your assigned batches.'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

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

@app.route('/farm_manager')
@login_required
@admin_required
def farm_manager():
    users = User.query.filter(User.user_type.in_(['assistant_manager', 'senior_manager'])).all()
    return render_template('farm_manager.html', users=users)

@app.route('/add_manager', methods=['POST'])
@login_required
@admin_required
def add_manager():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        name = request.form.get('name')
        user_type = request.form.get('user_type', 'assistant_manager')
        
        # Validate user type
        if user_type not in ['assistant_manager', 'senior_manager']:
            flash('Invalid user type', 'error')
            return redirect(url_for('farm_manager'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('farm_manager'))
        
        user = User(username=username, user_type=user_type)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # This will get us the user.id
        
        employee = Employee(name=name, user_id=user.id)
        db.session.add(employee)
        db.session.commit()
        
        flash('Manager added successfully', 'success')
        return redirect(url_for('farm_manager'))

@app.route('/edit_manager/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def edit_manager(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get('username')
    password = request.form.get('password')
    name = request.form.get('name')
    user_type = request.form.get('user_type')
    
    # Validate user type
    if user_type not in ['assistant_manager', 'senior_manager']:
        flash('Invalid user type', 'error')
        return redirect(url_for('farm_manager'))
    
    if username != user.username and User.query.filter_by(username=username).first():
        flash('Username already exists', 'error')
        return redirect(url_for('farm_manager'))
    
    user.username = username
    user.user_type = user_type
    if password:
        user.set_password(password)
    
    if user.employee:
        user.employee.name = name
    else:
        employee = Employee(name=name, user_id=user.id)
        db.session.add(employee)
    
    db.session.commit()
    flash('Manager updated successfully', 'success')
    return redirect(url_for('farm_manager'))

@app.route('/delete_manager/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_manager(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting the last admin
    if user.user_type == 'admin' and User.query.filter_by(user_type='admin').count() <= 1:
        return jsonify({'success': False, 'message': 'Cannot delete the last admin user'})
    
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})

# Manager Dashboard Route
@app.route('/manager/dashboard')
@login_required
def manager_dashboard():
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    
    # Get current date and time
    now = datetime.now()
    
    # Get batches based on user type
    if session.get('user_type') == 'senior_manager':
        # Senior managers can see all batches
        batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    else:
        # Assistant managers can only see their assigned batches
        batches = Batch.query.filter(
            Batch.manager_id == session.get('user_id'),
            Batch.status.in_(['ongoing', 'closing'])
        ).all()
    
    # Calculate statistics based on filtered batches
    total_birds = sum(batch.total_birds for batch in batches)
    active_batches = len(batches)
    
    # Get pending vaccinations and medicines for the filtered batches
    batch_ids = [batch.id for batch in batches]
    
    # Get pending vaccinations using the many-to-many relationship
    pending_vaccinations = VaccineSchedule.query.join(
        vaccine_schedule_batches
    ).filter(
        vaccine_schedule_batches.c.batch_id.in_(batch_ids),
        VaccineSchedule.completed == False
    ).count()
    
    pending_medicines = MedicineSchedule.query.join(
        medicine_schedule_batches
    ).filter(
        medicine_schedule_batches.c.batch_id.in_(batch_ids),
        MedicineSchedule.completed == False
    ).count()
    
    # Get recent activities (last 5 activities)
    recent_activities = []
    
    # Add batch activities
    recent_batches = Batch.query.filter(Batch.id.in_(batch_ids)).order_by(Batch.created_at.desc()).limit(3).all()
    for batch in recent_batches:
        recent_activities.append({
            'icon': 'fa-kiwi-bird',
            'title': 'New Batch Added',
            'description': f'Batch {batch.batch_number} with {batch.total_birds} birds',
            'time': batch.created_at.strftime('%Y-%m-%d %H:%M')
        })
    
    # Add vaccination activities
    recent_vaccines = VaccineSchedule.query.join(
        vaccine_schedule_batches
    ).filter(
        vaccine_schedule_batches.c.batch_id.in_(batch_ids)
    ).order_by(VaccineSchedule.created_at.desc()).limit(2).all()
    
    for vaccine in recent_vaccines:
        # Get the first batch for display
        batch = vaccine.batches[0] if vaccine.batches else None
        if batch:
            recent_activities.append({
                'icon': 'fa-syringe',
                'title': 'Vaccination Scheduled',
                'description': f'{vaccine.vaccine.name} for Batch {batch.batch_number}',
                'time': vaccine.created_at.strftime('%Y-%m-%d %H:%M')
            })
    
    # Sort activities by time
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    
    return render_template('manager/dashboard.html',
                         now=now,
                         total_birds=total_birds,
                         active_batches=active_batches,
                         pending_vaccinations=pending_vaccinations,
                         pending_medicines=pending_medicines,
                         recent_activities=recent_activities)

# Manager-specific routes
@app.route('/manager/batches')
@login_required
def manager_batches():
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    
    # Get batches based on user type
    if session.get('user_type') == 'senior_manager':
        # Senior managers can see all batches
        batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    else:
        # Assistant managers can only see their assigned batches
        batches = Batch.query.filter(
            Batch.manager_id == session.get('user_id'),
            Batch.status.in_(['ongoing', 'closing'])
        ).all()
    
    return render_template('manager/batches.html', 
                         batches=batches,
                         now=datetime.utcnow(),
                         timedelta=timedelta)  # Add timedelta to template context

@app.route('/manager/medicines')
@login_required
def manager_medicines():
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    medicines = Medicine.query.all()
    return render_template('manager/medicines.html', medicines=medicines)

@app.route('/manager/vaccines')
@login_required
def manager_vaccines():
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    vaccines = Vaccine.query.all()
    return render_template('manager/vaccines.html', vaccines=vaccines)

@app.route('/manager/reports')
@login_required
def manager_reports():
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('manager/reports.html')

@app.route('/manager/batches/<int:batch_id>/view')
@login_required
def manager_view_batch(batch_id):
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    
    batch = Batch.query.get_or_404(batch_id)
    return render_template('manager/view_batch.html', 
                         batch=batch,
                         now=datetime.utcnow())

@app.route('/manager/batches/<int:batch_id>/update', methods=['GET', 'POST'])
@login_required
def manager_update_batch(batch_id):
    if session.get('user_type') not in ['assistant_manager', 'senior_manager']:
        flash('Access denied. Managers only.', 'error')
        return redirect(url_for('dashboard'))
    
    batch = Batch.query.get_or_404(batch_id)
    
    # Check if assistant manager has access to this batch
    if session.get('user_type') == 'assistant_manager' and batch.manager_id != session.get('user_id'):
        flash('Access denied. You can only update batches assigned to you.', 'error')
        return redirect(url_for('manager_batches'))
    
    today = datetime.utcnow().date()
    
    # Get all available feeds, medicines, and health materials
    feeds = Feed.query.all()
    medicines = Medicine.query.all()
    health_materials = HealthMaterial.query.all()
    
    # Check if an update already exists for today
    existing_update = BatchUpdate.query.filter(
        BatchUpdate.batch_id == batch_id,
        db.func.date(BatchUpdate.date) == today
    ).first()
    
    if request.method == 'POST':
        if existing_update:
            flash('An update for this batch has already been submitted today.', 'error')
            return redirect(url_for('manager_batches'))
            
        try:
            # Get basic form data
            mortality_count = int(request.form.get('mortality_count', 0))
            feed_used = float(request.form.get('feed_used', 0))
            avg_weight = float(request.form.get('avg_weight', 0))
            notes = request.form.get('notes', '')

            # Calculate total feed allocation from feed quantities
            feed_data = request.form.getlist('feed_id[]')
            feed_quantities = request.form.getlist('feed_quantity[]')
            total_feed_allocation = 0
            for quantity in feed_quantities:
                if quantity and float(quantity) > 0:
                    total_feed_allocation += float(quantity)

            # Create new batch update
            update = BatchUpdate(
                batch_id=batch.id,
                date=today,
                mortality_count=mortality_count,
                feed_used=feed_used,
                avg_weight=avg_weight,
                notes=notes
            )

            # Update batch's available birds and total mortality
            batch.available_birds -= mortality_count
            batch.total_mortality += mortality_count
            batch.check_and_update_status()
            
            # Update feed stock and feed usage
            batch.feed_stock = (batch.feed_stock - feed_used) + total_feed_allocation
            batch.feed_usage += feed_used  # Add to total feed usage

            # First save the batch update to get an ID
            db.session.add(update)
            db.session.flush()

            # Process feeds
            for feed_id, quantity in zip(feed_data, feed_quantities):
                if feed_id and float(quantity) > 0:
                    feed = Feed.query.get(int(feed_id))
                    if feed:
                        db.session.execute(
                            batch_update_feeds.insert().values(
                                batch_update_id=update.id,
                                feed_id=feed.id,
                                quantity=float(quantity)
                            )
                        )

            # Process medicines
            medicine_data = request.form.getlist('medicine_id[]')
            medicine_quantities = request.form.getlist('medicine_quantity[]')
            for medicine_id, quantity in zip(medicine_data, medicine_quantities):
                if medicine_id and float(quantity) > 0:
                    medicine = Medicine.query.get(int(medicine_id))
                    if medicine:
                        db.session.execute(
                            batch_update_medicines.insert().values(
                                batch_update_id=update.id,
                                medicine_id=medicine.id,
                                quantity=float(quantity)
                            )
                        )

            # Process health materials
            health_material_data = request.form.getlist('health_material_id[]')
            health_material_quantities = request.form.getlist('health_material_quantity[]')
            for health_material_id, quantity in zip(health_material_data, health_material_quantities):
                if health_material_id and float(quantity) > 0:
                    health_material = HealthMaterial.query.get(int(health_material_id))
                    if health_material:
                        db.session.execute(
                            batch_update_health_materials.insert().values(
                                batch_update_id=update.id,
                                health_material_id=health_material.id,
                                quantity=float(quantity)
                            )
                        )

            # Now commit everything
            db.session.commit()
            flash('Batch update saved successfully!', 'success')
            return redirect(url_for('manager_view_batch', batch_id=batch.id))
        except Exception as e:
            db.session.rollback()
            flash('Error saving batch update. Please try again.', 'error')
            print(f"Error: {str(e)}")

    return render_template('manager/update_batch.html', 
                         batch=batch, 
                         existing_update=existing_update,
                         feeds=feeds,
                         medicines=medicines,
                         health_materials=health_materials)

@app.route('/batches/<int:batch_id>/harvest')
@login_required
def harvest_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    if batch.status not in ['closing', 'closed']:
        flash('Harvesting is only available for batches in closing or closed status', 'error')
        return redirect(url_for('batches'))
    
    harvests = Harvest.query.filter_by(batch_id=batch_id).order_by(Harvest.date.desc()).all()
    return render_template('harvesting.html', batch=batch, harvests=harvests)

@app.route('/batches/<int:batch_id>/harvest/add', methods=['GET', 'POST'])
@login_required
def add_harvest(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    if batch.status not in ['closing', 'closed']:
        flash('Harvesting is only available for batches in closing or closed status', 'error')
        return redirect(url_for('batches'))
    
    if request.method == 'POST':
        try:
            quantity = int(request.form.get('quantity', 0))
            weight = float(request.form.get('weight', 0))
            selling_price = float(request.form.get('selling_price', 0))
            notes = request.form.get('notes', '')
            
            if quantity > batch.available_birds:
                flash('Harvest quantity cannot exceed available birds', 'error')
                return redirect(url_for('add_harvest', batch_id=batch_id))
            
            total_value = weight * selling_price
            
            harvest = Harvest(
                batch_id=batch_id,
                date=datetime.utcnow().date(),
                quantity=quantity,
                weight=weight,
                selling_price=selling_price,
                total_value=total_value,
                notes=notes
            )
            
            # Update batch's available birds
            batch.available_birds -= quantity
            batch.check_and_update_status()
            
            db.session.add(harvest)
            db.session.commit()
            
            flash('Harvest record added successfully', 'success')
            return redirect(url_for('harvest_batch', batch_id=batch_id))
        except Exception as e:
            db.session.rollback()
            flash('Error adding harvest record: ' + str(e), 'error')
    
    return render_template('add_harvest.html', batch=batch)

@app.route('/harvests/<int:harvest_id>/delete', methods=['POST'])
@login_required
def delete_harvest(harvest_id):
    try:
        harvest = Harvest.query.get_or_404(harvest_id)
        batch = harvest.batch
        
        # Add back the harvested birds to available birds
        batch.available_birds += harvest.quantity
        batch.check_and_update_status()
        
        db.session.delete(harvest)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/harvests/<int:harvest_id>/view')
@login_required
def view_harvest(harvest_id):
    harvest = Harvest.query.get_or_404(harvest_id)
    return render_template('view_harvest.html', harvest=harvest)

@app.route('/harvests/<int:harvest_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_harvest(harvest_id):
    harvest = Harvest.query.get_or_404(harvest_id)
    batch = harvest.batch
    
    if batch.status != 'closing':
        flash('Harvesting is only available for batches in closing status', 'error')
        return redirect(url_for('batches'))
    
    if request.method == 'POST':
        try:
            quantity = int(request.form.get('quantity', 0))
            weight = float(request.form.get('weight', 0))
            selling_price = float(request.form.get('selling_price', 0))
            notes = request.form.get('notes', '')
            
            # Calculate the difference in quantity
            quantity_diff = quantity - harvest.quantity
            
            if quantity_diff > batch.available_birds:
                flash('Harvest quantity cannot exceed available birds', 'error')
                return redirect(url_for('edit_harvest', harvest_id=harvest_id))
            
            total_value = weight * selling_price
            
            # Update harvest record
            harvest.quantity = quantity
            harvest.weight = weight
            harvest.selling_price = selling_price
            harvest.total_value = total_value
            harvest.notes = notes
            
            # Update batch's available birds
            batch.available_birds -= quantity_diff
            batch.check_and_update_status()
            
            db.session.commit()
            flash('Harvest record updated successfully', 'success')
            return redirect(url_for('harvest_batch', batch_id=batch.id))
        except Exception as e:
            db.session.rollback()
            flash('Error updating harvest record: ' + str(e), 'error')
    
    return render_template('edit_harvest.html', harvest=harvest)

@app.route('/schedules')
@login_required
@admin_required
def schedules():
    try:
        # Get current date and time
        today = datetime.now().date()
        end_date = today + timedelta(days=30)
        
        # Get all schedules for the next 30 days
        health_material_schedules = HealthMaterialSchedule.query.join(
            health_material_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing']),
            HealthMaterialSchedule.scheduled_date >= today,
            HealthMaterialSchedule.scheduled_date <= end_date
        ).order_by(HealthMaterialSchedule.scheduled_date).all()
        
        medical_schedules = MedicineSchedule.query.join(
            medicine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing']),
            MedicineSchedule.schedule_date >= today,
            MedicineSchedule.schedule_date <= end_date
        ).order_by(MedicineSchedule.schedule_date).all()
        
        vaccine_schedules = VaccineSchedule.query.join(
            vaccine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing']),
            VaccineSchedule.scheduled_date >= today,
            VaccineSchedule.scheduled_date <= end_date
        ).order_by(VaccineSchedule.scheduled_date).all()
        
        # Get recent activities (last 6 activities)
        recent_activities = []
        
        # Add health material activities
        recent_health = HealthMaterialSchedule.query.join(
            health_material_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(HealthMaterialSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_health:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-spray-can',
                    'title': 'Health Material Scheduled',
                    'description': f'{schedule.health_material.name} for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Add medical activities
        recent_medical = MedicineSchedule.query.join(
            medicine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(MedicineSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_medical:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-pills',
                    'title': 'Medicine Scheduled',
                    'description': f'{schedule.medicine.name} for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Add vaccine activities
        recent_vaccine = VaccineSchedule.query.join(
            vaccine_schedule_batches
        ).join(
            Batch
        ).filter(
            Batch.status.in_(['ongoing', 'closing'])
        ).order_by(VaccineSchedule.created_at.desc()).limit(2).all()
        
        for schedule in recent_vaccine:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                recent_activities.append({
                    'icon': 'fa-syringe',
                    'title': 'Vaccine Scheduled',
                    'description': f'{schedule.vaccine.name} (Dose {schedule.dose_number}) for Batch {batch.batch_number}',
                    'time': schedule.created_at.strftime('%Y-%m-%d %H:%M')
                })
        
        # Sort activities by time
        recent_activities.sort(key=lambda x: x['time'], reverse=True)
        
        return render_template('schedules.html',
                             health_material_schedules=health_material_schedules,
                             medical_schedules=medical_schedules,
                             vaccine_schedules=vaccine_schedules,
                             recent_activities=recent_activities,
                             today=today)
    except Exception as e:
        flash('Error loading schedules', 'error')
        return redirect(url_for('dashboard'))

@app.route('/vaccine/schedule/<int:id>/complete', methods=['POST'])
@login_required
def complete_vaccine_schedule(id):
    if session.get('user_type') not in ['admin', 'senior_manager', 'assistant_manager']:
        return jsonify({'success': False, 'message': 'Access denied. Only administrators and managers can complete schedules.'}), 403
    
    try:
        schedule = VaccineSchedule.query.get_or_404(id)
        
        # Check if assistant manager has access to any of the batches
        if session.get('user_type') == 'assistant_manager':
            has_access = any(batch.manager_id == session.get('user_id') for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied. You can only complete schedules for your assigned batches.'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')