from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
from functools import wraps
import json
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bismi_farm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)  # Session expires after 2 hours

# Add custom strftime filter
@app.template_filter('strftime')
def strftime_filter(date, format):
    if date is None:
        return ""
    return date.strftime(format)

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
    phone_number = db.Column(db.String(20), unique=True, nullable=True)  # Primary phone number
    alternate_phone_number = db.Column(db.String(20), nullable=True)  # Alternate phone number
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    farm_batch_number = db.Column(db.Integer, nullable=False)  # New column for farm-specific batch number
    brand = db.Column(db.String(100), nullable=True)  # Optional brand field
    total_birds = db.Column(db.Integer, nullable=False)
    extra_chicks = db.Column(db.Integer, nullable=False, default=0)
    available_birds = db.Column(db.Integer, nullable=False)
    total_mortality = db.Column(db.Integer, nullable=False, default=0)  # Total mortality count
    feed_stock = db.Column(db.Float, nullable=False, default=0)  # Current feed stock in kg
    shed_birds = db.Column(db.Text, nullable=False, default='[]')  # Store as JSON string with default empty array
    cost_per_chicken = db.Column(db.Float, nullable=False, default=0.0)
    feed_usage = db.Column(db.Float, nullable=False, default=0.0)  # Total feed used in kg
    status = db.Column(db.String(20), nullable=False, default='ongoing')  # 'ongoing', 'closing', 'closed'
    created_at = db.Column(db.DateTime, nullable=False)  # Remove default to make it editable
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    farm = db.relationship('Farm', backref=db.backref('batches', lazy=True))
    manager = db.relationship('User', backref=db.backref('managed_batches', lazy=True))

    def get_shed_birds(self):
        try:
            return json.loads(self.shed_birds) if self.shed_birds else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_shed_birds(self, birds):
        try:
            self.shed_birds = json.dumps(birds) if birds is not None else '[]'
        except (TypeError, ValueError):
            self.shed_birds = '[]'

    def get_age_days(self):
        # Use local timezone instead of UTC
        today = datetime.now().date()
        created_date = self.created_at.date()
        return (today - created_date).days + 1

    def check_and_update_status(self):
        """Check if batch should be marked as closed based on available birds"""
        if self.available_birds <= 0 and self.status == 'closing':
            self.status = 'closed'
            financial_summary = self.financial_summary or FinancialSummary(batch_id=self.id)
            financial_summary.calculate_summary(self)
            db.session.add(financial_summary)

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
        """Calculate total vaccine cost from all batch updates"""
        total = 0
        for update in self.updates:
            for vaccine_update in update.vaccine_updates:
                vaccine_id = vaccine_update[0]
                quantity = vaccine_update[2]
                vaccine = next((v for v in update.vaccines if v.id == vaccine_id), None)
                if vaccine:
                    total += vaccine.price * quantity
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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<Feed {self.brand} - {self.category}>'

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity_per_unit = db.Column(db.Float, nullable=False)  # in litres/grams
    unit_type = db.Column(db.String(20), nullable=False)  # 'litre' or 'gram'
    price = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class HealthMaterialSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    health_material_id = db.Column(db.Integer, db.ForeignKey('health_material.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    health_material = db.relationship('HealthMaterial', backref='schedules')
    batches = db.relationship('Batch', secondary=health_material_schedule_batches, backref='health_material_schedules')

# Association tables for batch updates
batch_update_feeds = db.Table('batch_update_feeds',
    db.Column('batch_update_id', db.Integer, db.ForeignKey('batch_update.id'), primary_key=True),
    db.Column('feed_id', db.Integer, db.ForeignKey('feed.id'), primary_key=True),
    db.Column('quantity', db.Float, nullable=False),
    db.Column('quantity_per_unit_at_time', db.Float, nullable=False),  # Weight per unit at time of update
    db.Column('price_at_time', db.Float, nullable=False),
    db.Column('total_cost', db.Float, nullable=False)
)

batch_update_items = db.Table('batch_update_items',
    db.Column('batch_update_id', db.Integer, db.ForeignKey('batch_update.id'), primary_key=True),
    db.Column('item_id', db.Integer, nullable=False),  # ID of medicine/health_material/vaccine
    db.Column('item_type', db.String(20), nullable=False),  # 'medicine', 'health_material', or 'vaccine'
    db.Column('quantity', db.Float, nullable=False),
    db.Column('schedule_id', db.Integer, nullable=True),  # ID of the schedule if it's a scheduled item
    db.Column('dose_number', db.Integer, nullable=True)  # For vaccines only
)

class BatchUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    mortality_count = db.Column(db.Integer, nullable=False, default=0)
    feed_used = db.Column(db.Float, nullable=False, default=0)  # Feed used in packets
    avg_weight = db.Column(db.Float, nullable=False, default=0)  # Average weight in kg
    male_weight = db.Column(db.Float, nullable=False, default=0) # Male weight in kg
    female_weight = db.Column(db.Float, nullable=False, default=0) # Female weight in kg
    remarks = db.Column(db.Text, nullable=True)  # Changed from notes to remarks
    remarks_priority = db.Column(db.String(20), nullable=True, default='low')  # 'low', 'medium', 'high'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    # Relationships
    batch = db.relationship('Batch', backref=db.backref('updates', lazy=True))
    feeds = db.relationship('Feed', secondary=batch_update_feeds, backref=db.backref('batch_updates', lazy=True))
    items = db.relationship(
        'BatchUpdateItem',
        backref='batch_update',
        lazy=True,
        cascade='all, delete-orphan'
    )
    feed_returns = db.relationship('BatchFeedReturn', backref='batch_update', lazy=True, cascade='all, delete-orphan')
    miscellaneous_items = db.relationship('MiscellaneousItem', backref='batch_update', lazy=True, cascade='all, delete-orphan')

    def get_feed_quantity(self, feed_id):
        """Get the quantity of a specific feed used in this update"""
        result = db.session.query(batch_update_feeds.c.quantity).filter(
            batch_update_feeds.c.batch_update_id == self.id,
            batch_update_feeds.c.feed_id == feed_id
        ).scalar()
        return result or 0

    def get_feed_price(self, feed_id):
        """Get the price of a specific feed at the time of this update"""
        result = db.session.query(batch_update_feeds.c.price_at_time).filter(
            batch_update_feeds.c.batch_update_id == self.id,
            batch_update_feeds.c.feed_id == feed_id
        ).scalar()
        return result or 0
    
    def get_feed_quantity_per_unit(self, feed_id):
        
        result = db.session.query(batch_update_feeds.c.quantity_per_unit_at_time).filter(
            batch_update_feeds.c.batch_update_id == self.id,
            batch_update_feeds.c.feed_id == feed_id
        ).scalar()
        return result

    def get_item_quantity(self, item_id, item_type):
        """Get the quantity of a specific item used in this update"""
        item = BatchUpdateItem.query.filter_by(
            batch_update_id=self.id,
            item_id=item_id,
            item_type=item_type
        ).first()
        return item.quantity if item else 0

class BatchFeedReturn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_update_id = db.Column(db.Integer, db.ForeignKey('batch_update.id'), nullable=False)
    feed_id = db.Column(db.Integer, db.ForeignKey('feed.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    feed = db.relationship('Feed', backref='returns')

class BatchUpdateItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_update_id = db.Column(db.Integer, db.ForeignKey('batch_update.id'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)  # ID of medicine/health_material/vaccine
    item_type = db.Column(db.String(20), nullable=False)  # 'medicine', 'health_material', or 'vaccine'
    quantity = db.Column(db.Float, nullable=False)
    quantity_per_unit_at_time = db.Column(db.Float, nullable=False)  # Quantity per unit at time of update
    unit_type = db.Column(db.String(20), nullable=False)  # 'kg', 'litre', 'piece', 'box'
    price_at_time = db.Column(db.Float, nullable=False)  # Price at the time of update
    total_cost = db.Column(db.Float, nullable=False)  # Total cost (quantity * price_at_time)
    schedule_id = db.Column(db.Integer, nullable=True)  # ID of the schedule if it's a scheduled item
    dose_number = db.Column(db.Integer, nullable=True)  # For vaccines only
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def get_item(self):
        """Get the actual item object based on item_type and item_id"""
        if self.item_type == 'medicine':
            return Medicine.query.get(self.item_id)
        elif self.item_type == 'health_material':
            return HealthMaterial.query.get(self.item_id)
        elif self.item_type == 'vaccine':
            return Vaccine.query.get(self.item_id)
        return None

class Harvest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    quantity = db.Column(db.Integer, nullable=False)
    weight = db.Column(db.Float, nullable=False)  # Weight in kg
    selling_price = db.Column(db.Float, nullable=False)  # Price per kg
    total_value = db.Column(db.Float, nullable=False)  # Total value (weight * selling_price)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationship
    batch = db.relationship('Batch', backref=db.backref('harvests', lazy=True))

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(50), nullable=False)  # Font Awesome icon class
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<Activity {self.title}>'

class MiscellaneousItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_update_id = db.Column(db.Integer, db.ForeignKey('batch_update.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    quantity_per_unit = db.Column(db.Float, nullable=False)
    unit_type = db.Column(db.String(20), nullable=False)  # e.g., 'piece', 'kg', 'litre'
    price_per_unit = db.Column(db.Float, nullable=False)
    units_used = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<MiscellaneousItem {self.name}>'

class FinancialSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id', ondelete='CASCADE'), nullable=False)
    total_feed_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_medicine_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_vaccine_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_health_material_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_miscellaneous_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_bird_cost = db.Column(db.Float, nullable=False, default=0.0)
    total_revenue = db.Column(db.Float, nullable=False, default=0.0)
    total_profit = db.Column(db.Float, nullable=False, default=0.0)
    fcr_value = db.Column(db.Float, nullable=True)  # Store the calculated FCR value
    fcr_rate = db.Column(db.Float, nullable=True)  # Store the determined FCR rate
    fcr_price = db.Column(db.Float, nullable=True)  # Store the determined FCR price
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationship
    batch = db.relationship('Batch', backref=db.backref('financial_summary', uselist=False, cascade='all, delete-orphan'))

    def calculate_fcr(self, batch):
        """Calculate FCR (Feed Conversion Ratio) and determine the appropriate rate"""
        # Calculate total feed used in kg
        total_feed_used = 0
        for update in batch.updates:
            for feed in update.feeds:
                feed_quantity = update.get_feed_quantity(feed.id)
                quantity_per_unit = update.get_feed_quantity_per_unit(feed.id)
                if feed_quantity and quantity_per_unit:
                    total_feed_used += feed_quantity * quantity_per_unit

        # Subtract feed stock from total feed used
        if batch.feed_stock > 0:
            # Get the latest feed quantity per unit
            latest_update = batch.updates[-1] if batch.updates else None
            if latest_update and latest_update.feeds:
                latest_feed = latest_update.feeds[0]
                quantity_per_unit = latest_update.get_feed_quantity_per_unit(latest_feed.id)
                if quantity_per_unit:
                    total_feed_used -= batch.feed_stock * quantity_per_unit

        # Calculate total weight sold
        total_weight_sold = batch.get_total_weight_sold()

        # Calculate FCR
        if total_weight_sold > 0:
            self.fcr_value = total_feed_used / total_weight_sold
        else:
            self.fcr_value = 0.0

        # Determine FCR rate based on the calculated FCR value
        if self.fcr_value > 0:
            fcr_rates = FCRRate.query.order_by(FCRRate.lower_limit).all()
            for rate in fcr_rates:
                if self.fcr_value >= rate.lower_limit and (rate.upper_limit is None or self.fcr_value < rate.upper_limit):
                    self.fcr_rate = rate.rate
                    break
            self.fcr_price = total_weight_sold * (self.fcr_rate or 0.0)
        else:
            self.fcr_rate = 0.0
            self.fcr_price = 0.0

    def calculate_summary(self, batch):
        """Calculate financial summary for a batch"""
        # Calculate feed costs from batch updates
        feed_costs = 0
        for update in batch.updates:
            for feed in update.feeds:
                feed_prices = db.session.query(batch_update_feeds.c.total_cost).filter(
                    batch_update_feeds.c.batch_update_id == update.id,
                    batch_update_feeds.c.feed_id == feed.id
                ).scalar()
                
                if feed_prices:
                    feed_costs += feed_prices
                
        # Subtract feed stock cost from total feed costs
        feed_stock_cost = 0
        if batch.feed_stock > 0 and batch.updates:
            # Get the latest update with feeds
            latest_update = None
            for update in reversed(batch.updates):
                if update.feeds:
                    latest_update = update
                    break
            
            if latest_update:
                # Get the latest feed price for each feed type
                for feed in latest_update.feeds:
                    latest_price = db.session.query(batch_update_feeds.c.price_at_time).filter(
                        batch_update_feeds.c.feed_id == feed.id
                    ).order_by(batch_update_feeds.c.batch_update_id.desc()).first()
                    
                    if latest_price:
                        # Calculate cost of feed stock for this feed type
                        feed_stock_cost += latest_price[0] * batch.feed_stock
                        break  # Since we only need one feed price for the stock
        
        feed_costs -= feed_stock_cost

        # Calculate medicine costs from batch updates
        medicine_costs = 0
        for update in batch.updates:
            for item in update.items:
                if item.item_type == 'medicine':
                    medicine_costs += item.total_cost

        # Calculate vaccine costs from batch updates
        vaccine_costs = 0
        for update in batch.updates:
            for item in update.items:
                if item.item_type == 'vaccine':
                    vaccine_costs += item.total_cost

        # Calculate health material costs from batch updates
        health_material_costs = 0
        for update in batch.updates:
            for item in update.items:
                if item.item_type == 'health_material':
                    health_material_costs += item.total_cost

        # Calculate miscellaneous costs from batch updates
        misc_costs = 0
        for update in batch.updates:
            for misc_item in update.miscellaneous_items:
                misc_costs += misc_item.total_cost

        # Calculate total bird cost
        bird_cost = (batch.total_birds - batch.extra_chicks) * batch.cost_per_chicken

        # Calculate FCR and determine rate
        self.calculate_fcr(batch)

        # Calculate total revenue from harvests
        total_revenue = sum(harvest.total_value for harvest in batch.harvests)

        # Calculate total profit
        total_profit = total_revenue - (feed_costs + medicine_costs + vaccine_costs + 
                                      health_material_costs + misc_costs + bird_cost + (self.fcr_price or 0))

        # Update the summary
        self.total_feed_cost = feed_costs
        self.total_medicine_cost = medicine_costs
        self.total_vaccine_cost = vaccine_costs
        self.total_health_material_cost = health_material_costs
        self.total_miscellaneous_cost = misc_costs
        self.total_bird_cost = bird_cost
        self.total_revenue = total_revenue
        self.total_profit = total_profit

class FCRRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lower_limit = db.Column(db.Float, nullable=False)
    upper_limit = db.Column(db.Float, nullable=True)  # Null means no upper limit (Max)
    rate = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<FCRRate {self.lower_limit}-{self.upper_limit or "Max"}: {self.rate}>'

class AutoSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(20), nullable=False)  # 'medicine', 'vaccine', or 'health_material'
    item_id = db.Column(db.Integer, nullable=False)
    schedule_ages = db.Column(db.Text, nullable=False)  # JSON string of ages in days
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def get_schedule_ages(self):
        try:
            ages = json.loads(self.schedule_ages)
            # Ensure all ages are integers
            return [int(age) for age in ages if age is not None]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    def set_schedule_ages(self, ages):
        # Ensure all ages are integers and filter out None values
        valid_ages = [int(age) for age in ages if age is not None]
        self.schedule_ages = json.dumps(valid_ages)

def init_db():
    with app.app_context():
        try:
            # # Drop existing tables to recreate with new schema
            # db.drop_all()

            # Create all tables
            db.create_all()

            # +
            
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
        username_or_phone = request.form.get('username')
        password = request.form.get('password')
        
        if not username_or_phone or not password:
            flash('Please provide both username/phone and password', 'error')
            return redirect(url_for('index'))
        
        # First try to find user by username
        user = User.query.filter_by(username=username_or_phone).first()
        
        # If not found by username, try phone number in Employee table
        if not user:
            try:
                employee = Employee.query.filter_by(phone_number=username_or_phone).first()
                if employee:
                    user = employee.user
            except Exception as db_error:
                print(f"Error checking phone number: {str(db_error)}")
                pass
        
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
            flash('Invalid username/phone or password', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        print(f"Login error: {str(e)}")
        flash('An error occurred during login', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Get total farms
    farms = Farm.query.all()
    
    # Get active batches
    active_batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    
    # Calculate total birds
    total_birds = sum(batch.available_birds for batch in active_batches)
    
    # Get pending schedules count
    pending_schedules_count = (
        MedicineSchedule.query.filter_by(completed=False).count() +
        VaccineSchedule.query.filter_by(completed=False).count() +
        HealthMaterialSchedule.query.filter_by(completed=False).count()
    )
    
    # Get upcoming schedules (next 7 days)
    today = datetime.now().date()
    next_week = today + timedelta(days=7)
    
    upcoming_schedules = []
    
    # Get medicine schedules
    medicine_schedules = MedicineSchedule.query.filter(
        MedicineSchedule.schedule_date >= today,
        MedicineSchedule.schedule_date <= next_week
    ).all()
    upcoming_schedules.extend(medicine_schedules)
    
    # Get vaccine schedules
    vaccine_schedules = VaccineSchedule.query.filter(
        VaccineSchedule.scheduled_date >= today,
        VaccineSchedule.scheduled_date <= next_week
    ).all()
    upcoming_schedules.extend(vaccine_schedules)
    
    # Get health material schedules
    health_schedules = HealthMaterialSchedule.query.filter(
        HealthMaterialSchedule.scheduled_date >= today,
        HealthMaterialSchedule.scheduled_date <= next_week
    ).all()
    upcoming_schedules.extend(health_schedules)
    
    # Sort all schedules by date
    upcoming_schedules.sort(key=lambda x: x.schedule_date if hasattr(x, 'schedule_date') else x.scheduled_date)
    
    return render_template('dashboard.html',
                         farms=farms,
                         active_batches=active_batches,
                         total_birds=total_birds,
                         pending_schedules_count=pending_schedules_count,
                         upcoming_schedules=upcoming_schedules)

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
    farm_stats = {}
    for farm in farms:
        # Get active batches (ongoing and closing)
        active_batches = Batch.query.filter(
            Batch.farm_id == farm.id,
            Batch.status.in_(['ongoing', 'closing'])
        ).count()
        
        # Get completely available sheds
        shed_available = farm.get_shed_available_capacities()
        shed_capacities = farm.get_shed_capacities()
        completely_available_sheds = sum(1 for available, capacity in zip(shed_available, shed_capacities) if available == capacity)
        
        farm_stats[farm.id] = {
            'ongoing_batches': active_batches,
            'completely_available_sheds': completely_available_sheds
        }
    
    return render_template('farms.html', farms=farms, farm_stats=farm_stats)

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
        
        # Check if farm has any active batches
        active_batches = Batch.query.filter(
            Batch.farm_id == farm_id,
            Batch.status.in_(['ongoing', 'closing'])
        ).first()
        
        if active_batches:
            return jsonify({
                'success': False, 
                'message': 'Cannot delete farm with active batches. Please close all batches first.'
            })

        # Get all batches for this farm
        batches = Batch.query.filter_by(farm_id=farm_id).all()
        
        for batch in batches:
            # Delete all batch updates and their associations
            for update in batch.updates:
                # Delete feed associations
                db.session.execute(
                    batch_update_feeds.delete().where(
                        batch_update_feeds.c.batch_update_id == update.id
                    )
                )
                # Delete items (medicines, health materials, vaccines)
                BatchUpdateItem.query.filter_by(batch_update_id=update.id).delete()
                # Delete miscellaneous items
                MiscellaneousItem.query.filter_by(batch_update_id=update.id).delete()
                db.session.delete(update)
            
            # Delete vaccine schedule associations
            db.session.execute(
                vaccine_schedule_batches.delete().where(
                    vaccine_schedule_batches.c.batch_id == batch.id
                )
            )
            
            # Delete medicine schedule associations
            db.session.execute(
                medicine_schedule_batches.delete().where(
                    medicine_schedule_batches.c.batch_id == batch.id
                )
            )
            
            # Delete health material schedule associations
            db.session.execute(
                health_material_schedule_batches.delete().where(
                    health_material_schedule_batches.c.batch_id == batch.id
                )
            )
            
            # Delete harvests
            Harvest.query.filter_by(batch_id=batch.id).delete()
            
            # Finally delete the batch
            db.session.delete(batch)
        
        # Delete the farm
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
                         now=datetime.now(),
                         timedelta=timedelta)  # Add timedelta to template context

def generate_batch_number():
    # Get the last batch number
    last_batch = Batch.query.order_by(Batch.id.desc()).first()
    if last_batch:
        # Extract the number from the last batch number and increment
        try:
            last_number = int(last_batch.batch_number.split('-')[1])
            new_number = last_number + 1
        except (IndexError, ValueError):
            new_number = 1
    else:
        new_number = 1
    
    # Format the new batch number with leading zeros
    return f"BATCH-{new_number:04d}"

def get_next_farm_batch_number(farm_id):
    # Get all batch numbers for this farm
    farm_batches = Batch.query.filter_by(farm_id=farm_id).all()
    
    # Get all used batch numbers
    used_numbers = {batch.farm_batch_number for batch in farm_batches if batch.farm_batch_number is not None}
    
    # Get all closed batch numbers
    closed_numbers = {batch.farm_batch_number for batch in farm_batches 
                     if batch.farm_batch_number is not None and batch.status == 'closed'}
    
    # Get all ongoing batch numbers
    ongoing_numbers = {batch.farm_batch_number for batch in farm_batches 
                      if batch.farm_batch_number is not None and batch.status == 'ongoing'}
    
    # Find available closed numbers (closed numbers not used by ongoing batches)
    available_closed_numbers = closed_numbers - ongoing_numbers
    
    # Find the first available number, prioritizing available closed batch numbers
    if available_closed_numbers:
        # If there are available closed batches, use the lowest available closed batch number
        return min(available_closed_numbers)
    else:
        # If no available closed batches, use the next available number
        if used_numbers:
            return max(used_numbers) + 1
        return 1

@app.route('/batches/add', methods=['GET', 'POST'])
@login_required
def add_batch():
    if request.method == 'POST':
        try:
            farm_id = request.form.get('farm_id')
            manager_id = request.form.get('manager_id')
            brand = request.form.get('brand')
            total_birds = int(request.form.get('total_birds'))
            extra_chicks = int(request.form.get('extra_chicks', 0))
            created_at = datetime.strptime(request.form.get('created_at'), '%Y-%m-%dT%H:%M')
            cost_per_chicken = float(request.form.get('cost_per_chicken'))

            # Generate batch number
            batch_number = generate_batch_number()
            farm_batch_number = get_next_farm_batch_number(farm_id)

            # Get shed distribution
            shed_birds = []
            farm = Farm.query.get(farm_id)
            for i in range(farm.num_sheds):
                birds = int(request.form.get(f'shed_{i+1}_birds', 0))
                shed_birds.append(birds)

            # Create new batch
            batch = Batch(
                farm_id=farm_id,
                manager_id=manager_id if manager_id else None,
                batch_number=batch_number,
                farm_batch_number=farm_batch_number,
                brand=brand,
                total_birds=total_birds,
                extra_chicks=extra_chicks,
                available_birds=total_birds,
                shed_birds=json.dumps(shed_birds),
                cost_per_chicken=cost_per_chicken,
                created_at=created_at
            )

            db.session.add(batch)
            db.session.flush()  # Get the batch ID without committing

            # Create schedules for the batch
            create_schedules_for_batch(batch)

            db.session.commit()
            flash('Batch added successfully!', 'success')
            return redirect(url_for('batches'))
        except Exception as e:
            db.session.rollback()
            flash('Error adding batch: ' + str(e), 'error')
            return redirect(url_for('add_batch'))
    
    # GET request - show form
    farms = Farm.query.all()
    managers = User.query.filter(User.user_type.in_(['senior_manager', 'assistant_manager'])).all()
    
    # Create farm_sheds dictionary with proper JSON serializable values
    farm_sheds = {}
    for farm in farms:
        try:
            shed_capacities = farm.get_shed_capacities()
            shed_available = farm.get_shed_available_capacities()
            shed_status = []
            
            for cap, avail in zip(shed_capacities, shed_available):
                shed_status.append({
                    'is_partially_allocated': bool(cap > avail)
                })
            
            farm_sheds[str(farm.id)] = {
                'num_sheds': int(farm.num_sheds),
                'shed_capacities': [int(cap) for cap in shed_capacities],
                'shed_available': [int(avail) for avail in shed_available],
                'shed_status': shed_status
            }
        except Exception as e:
            print(f"Error processing farm {farm.id}: {str(e)}")
            continue
    
    return render_template('add_batch.html', 
                         farms=farms, 
                         managers=managers, 
                         farm_sheds=farm_sheds)

@app.route('/batches/edit/<int:batch_id>', methods=['GET', 'POST'])
@login_required
def edit_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    if request.method == 'POST':
        try:
            manager_id = request.form.get('manager_id')
            brand = request.form.get('brand')
            total_birds = int(request.form.get('total_birds'))
            extra_chicks = int(request.form.get('extra_chicks', 0))
            new_created_at = datetime.strptime(request.form.get('created_at'), '%Y-%m-%dT%H:%M')
            cost_per_chicken = float(request.form.get('cost_per_chicken'))

            # Get shed distribution
            shed_birds = []
            for i in range(batch.farm.num_sheds):
                birds = int(request.form.get(f'shed_{i+1}_birds', 0))
                shed_birds.append(birds)

            # Calculate date difference if created_at is changed
            if new_created_at != batch.created_at:
                date_diff = new_created_at - batch.created_at
                
                # Update medicine schedules
                medicine_schedules = MedicineSchedule.query.filter(
                    MedicineSchedule.batches.any(id=batch.id)
                ).all()
                for schedule in medicine_schedules:
                    schedule.schedule_date = schedule.schedule_date + date_diff
                
                # Update vaccine schedules
                vaccine_schedules = VaccineSchedule.query.filter(
                    VaccineSchedule.batches.any(id=batch.id)
                ).all()
                for schedule in vaccine_schedules:
                    schedule.scheduled_date = schedule.scheduled_date + date_diff
                
                # Update health material schedules
                health_material_schedules = HealthMaterialSchedule.query.filter(
                    HealthMaterialSchedule.batches.any(id=batch.id)
                ).all()
                for schedule in health_material_schedules:
                    schedule.scheduled_date = schedule.scheduled_date + date_diff

            # Update batch
            batch.manager_id = manager_id if manager_id else None
            batch.brand = brand
            batch.total_birds = total_birds
            batch.extra_chicks = extra_chicks
            batch.available_birds = total_birds - batch.total_mortality
            batch.shed_birds = json.dumps(shed_birds)
            batch.cost_per_chicken = cost_per_chicken
            batch.created_at = new_created_at

            db.session.commit()
            flash('Batch updated successfully', 'success')
            return redirect(url_for('batches'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating batch: {str(e)}', 'error')
            return redirect(url_for('edit_batch', batch_id=batch_id))

    # GET request - show form
    managers = User.query.filter(User.user_type.in_(['senior_manager', 'assistant_manager'])).all()
    return render_template('edit_batch.html', batch=batch, managers=managers)

@app.route('/batches/<int:batch_id>/view')
@login_required
def view_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    return render_template('view_batch.html', batch=batch)

@app.route('/batches/<int:batch_id>/delete', methods=['POST'])
@login_required
def delete_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    # Check if user has permission to delete this batch
    if session.get('user_type') == 'manager' and batch.manager_id != session.get('user_id'):
        return jsonify({'success': False, 'message': 'You do not have permission to delete this batch'})
    
    try:
        # First, delete all schedules associated with this batch
        try:
            # Delete medicine schedules
            medicine_schedules = MedicineSchedule.query.filter(
                MedicineSchedule.batches.any(id=batch.id)
            ).all()
            for schedule in medicine_schedules:
                db.session.delete(schedule)
            
            # Delete vaccine schedules
            vaccine_schedules = VaccineSchedule.query.filter(
                VaccineSchedule.batches.any(id=batch.id)
            ).all()
            for schedule in vaccine_schedules:
                db.session.delete(schedule)
            
            # Delete health material schedules
            health_material_schedules = HealthMaterialSchedule.query.filter(
                HealthMaterialSchedule.batches.any(id=batch.id)
            ).all()
            for schedule in health_material_schedules:
                db.session.delete(schedule)
            
            db.session.flush()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Error deleting schedules: {str(e)}'})

        # Delete all batch updates and their items
        updates = BatchUpdate.query.filter_by(batch_id=batch.id).all()
        for update in updates:
            try:
                # Delete all items associated with this update
                BatchUpdateItem.query.filter_by(batch_update_id=update.id).delete()
                # Delete all miscellaneous items
                MiscellaneousItem.query.filter_by(batch_update_id=update.id).delete()
                # Delete feed associations
                db.session.execute(
                    batch_update_feeds.delete().where(
                        batch_update_feeds.c.batch_update_id == update.id
                    )
                )
                # Delete the update itself
                db.session.delete(update)
                db.session.flush()
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'message': f'Error deleting batch update {update.id}: {str(e)}'})
        
        # Delete all harvests
        try:
            Harvest.query.filter_by(batch_id=batch.id).delete()
            db.session.flush()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Error deleting harvests: {str(e)}'})
        
        # Delete financial summary
        try:
            FinancialSummary.query.filter_by(batch_id=batch.id).delete()
            db.session.flush()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Error deleting financial summary: {str(e)}'})
        
        # Finally delete the batch
        try:
            db.session.delete(batch)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Batch deleted successfully'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Error deleting batch: {str(e)}'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}'})

@app.route('/batches/<int:batch_id>/update-status', methods=['POST'])
@login_required
def update_batch_status(batch_id):
    try:
        batch = Batch.query.get_or_404(batch_id)
        data = request.get_json()
        new_status = data.get('status')
        
        if new_status not in ['ongoing', 'closing', 'closed']:
            return jsonify({
                'success': False,
                'message': 'Invalid status'
            }), 400
        
        # If changing from closed to another status, remove the financial summary
        if batch.status == 'closed' and new_status != 'closed':
            if batch.financial_summary:
                db.session.delete(batch.financial_summary)
        
        # If changing to closed, create or update financial summary
        if new_status == 'closed':
            financial_summary = batch.financial_summary or FinancialSummary(batch_id=batch.id)
            financial_summary.calculate_summary(batch)
            db.session.add(financial_summary)
        
        batch.status = new_status
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Batch status updated to {new_status}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/batches/<int:batch_id>/update', methods=['GET', 'POST'])
@login_required
def update_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    # Check if an update has already been submitted today
    selected_date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()

    existing_update = BatchUpdate.query.filter_by(batch_id=batch.id, date=selected_date).first()

    if request.method == 'POST':
        if existing_update:
            flash('An update has already been submitted for this batch today.', 'error')
            return redirect(url_for('update_batch', batch_id=batch.id, date=selected_date_str))

        # Create new batch update
        mortality_count = int(request.form.get('mortality_count', 0))
        feed_used = float(request.form.get('feed_used', 0))
        avg_weight = float(request.form.get('avg_weight', 0))
        male_weight = float(request.form.get('male_weight', 0))
        female_weight = float(request.form.get('female_weight', 0))
        remarks = request.form.get('remarks')
        remarks_priority = request.form.get('remarks_priority')

        # Update batch stats
        batch.available_birds -= mortality_count
        batch.total_mortality += mortality_count
        batch.feed_usage += feed_used
        batch.feed_stock -= feed_used
        
        new_update = BatchUpdate(
            batch_id=batch.id,
            date=selected_date,
            mortality_count=mortality_count,
            feed_used=feed_used,
            avg_weight=avg_weight,
            male_weight=male_weight,
            female_weight=female_weight,
            remarks=remarks,
            remarks_priority=remarks_priority
        )
        db.session.add(new_update)

        # Process feed allocation
        feed_ids = request.form.getlist('feed_id[]')
        feed_quantities = request.form.getlist('feed_quantity[]')
        
        for i in range(len(feed_ids)):
            if feed_ids[i] and feed_quantities[i]:
                feed_id = int(feed_ids[i])
                quantity = float(feed_quantities[i])
                
                feed = Feed.query.get(feed_id)
                if feed:
                    # Update batch feed stock
                    batch.feed_stock += quantity
                    
                    # Add feed to batch_update_feeds table
                    update_feed = batch_update_feeds.insert().values(
                        batch_update_id=new_update.id,
                        feed_id=feed_id,
                        quantity=quantity,
                        price=feed.price, # Store price at the time of update
                        quantity_per_unit_at_time=feed.weight
                    )
                    db.session.execute(update_feed)

        # Process feed returns
        feed_return_ids = request.form.getlist('feed_return_id[]')
        feed_return_quantities = request.form.getlist('feed_return_quantity[]')

        total_returned_feed = 0
        for i in range(len(feed_return_ids)):
            if feed_return_ids[i] and feed_return_quantities[i]:
                feed_id = int(feed_return_ids[i])
                quantity = float(feed_return_quantities[i])

                if quantity > 0:
                    feed_return = BatchFeedReturn(
                        batch_update=new_update,
                        feed_id=feed_id,
                        quantity=quantity
                    )
                    db.session.add(feed_return)
                    total_returned_feed += quantity
        
        # Adjust batch feed stock for returns
        batch.feed_stock -= total_returned_feed

        # Process scheduled items
        scheduled_items_data = request.form.getlist('scheduled_items')
        if scheduled_items_data:
            for item_data in scheduled_items_data:
                item_type, item_id, field, value = item_data.split('|')
                if field == 'selected':
                    quantity = float(value)
                    if item_type == 'medicine':
                        medicine = Medicine.query.get(item_id)
                        if medicine:
                            schedule = MedicineSchedule.query.get(item_id)
                            if schedule:
                                schedule.completed = True
                                schedule.batches.append(batch)
                                db.session.add(schedule)
                    elif item_type == 'health_material':
                        health_material = HealthMaterial.query.get(item_id)
                        if health_material:
                            schedule = HealthMaterialSchedule.query.get(item_id)
                            if schedule:
                                schedule.completed = True
                                schedule.batches.append(batch)
                                db.session.add(schedule)
                    elif item_type == 'vaccine':
                        vaccine = Vaccine.query.get(item_id)
                        if vaccine:
                            schedule = VaccineSchedule.query.get(item_id)
                            if schedule:
                                schedule.completed = True
                                schedule.batches.append(batch)
                                db.session.add(schedule)

        db.session.commit()
        flash('Batch update recorded successfully!', 'success')
        return redirect(url_for('view_batch', batch_id=batch.id))
    
    # GET request - show form
    managers = User.query.filter(User.user_type.in_(['senior_manager', 'assistant_manager'])).all()

    medicines = Medicine.query.all()
    medicines_dict = [{
        'id': m.id,
        'name': m.name,
        'quantity_per_unit': m.quantity_per_unit,
        'unit_type': m.unit_type,
        'price': m.price,
        'notes': m.notes
    } for m in medicines]

    health_materials = HealthMaterial.query.all()
    health_materials_dict = [{
        'id': h.id,
        'name': h.name,
        'category': h.category,
        'quantity_per_unit': h.quantity_per_unit,
        'unit_type': h.unit_type,
        'price': h.price,
        'notes': h.notes
    } for h in health_materials]

    vaccines = Vaccine.query.all()
    vaccines_dict = [{
        'id': v.id,
        'name': v.name,
        'quantity_per_unit': v.quantity_per_unit,
        'price': v.price,
        'doses_required': v.doses_required,
        'dose_ages': v.get_dose_ages(),
        'notes': v.notes
    } for v in vaccines]

    feeds = Feed.query.all()

    return render_template('update_batch.html', 
                         batch=batch, 
                         medicine_schedules=MedicineSchedule.query.filter(
                             MedicineSchedule.batches.any(id=batch.id)
                         ).all(),
                         health_material_schedules=HealthMaterialSchedule.query.filter(
                             HealthMaterialSchedule.batches.any(id=batch.id)
                         ).all(),
                         vaccine_schedules=VaccineSchedule.query.filter(
                             VaccineSchedule.batches.any(id=batch.id)
                         ).all(),
                         medicines=medicines_dict,
                         health_materials=health_materials_dict,
                         vaccines=vaccines_dict,
                         feeds=feeds,
                         today=datetime.now().date(),
                         selected_date=selected_date,
                         existing_update=existing_update)

@app.route('/batches/<int:batch_id>/update/<date>')
@login_required
def get_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        try:
            update_date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError as e:
            print(f"Date format error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Please use YYYY-MM-DD format.'
            })
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter_by(
            batch_id=batch.id,
            date=update_date
        ).first()
        
        if not update:
            return jsonify({
                'success': False,
                'message': 'No update found for the specified date'
            })
        
        # Get feeds with their quantities and prices
        feeds = []
        for feed in update.feeds:
            try:
                stmt = batch_update_feeds.select().where(
                    batch_update_feeds.c.batch_update_id == update.id,
                    batch_update_feeds.c.feed_id == feed.id
                )
                result = db.session.execute(stmt).first()
                if result:
                    feeds.append({
                        'id': feed.id,
                        'brand': feed.brand,
                        'category': feed.category,
                        'quantity': float(result.quantity),
                        'quantity_per_unit_at_time': float(result.quantity_per_unit_at_time),
                        'price_at_time': float(result.price_at_time),
                        'total_cost': float(result.total_cost)
                    })
            except Exception as e:
                print(f"Error getting feed data for feed {feed.id}: {str(e)}")
                continue
        
        # Get items with their details
        items = []
        for item in update.items:
            try:
                item_data = {
                    'id': item.item_id,
                    'item_type': item.item_type,
                    'quantity': float(item.quantity),
                    'quantity_per_unit_at_time': float(item.quantity_per_unit_at_time),
                    'price_at_time': float(item.price_at_time),
                    'total_cost': float(item.total_cost),
                    'schedule_id': item.schedule_id,
                    'dose_number': item.dose_number if item.item_type == 'vaccine' else None
                }
                
                # Get the actual item details based on type
                if item.item_type == 'medicine':
                    medicine = Medicine.query.get(item.item_id)
                    if medicine:
                        item_data.update({
                            'name': medicine.name,
                            'unit_type': medicine.unit_type,
                            'notes': medicine.notes
                        })
                elif item.item_type == 'health_material':
                    material = HealthMaterial.query.get(item.item_id)
                    if material:
                        item_data.update({
                            'name': material.name,
                            'category': material.category,
                            'unit_type': material.unit_type,
                            'notes': material.notes
                        })
                elif item.item_type == 'vaccine':
                    vaccine = Vaccine.query.get(item.item_id)
                    if vaccine:
                        item_data.update({
                            'name': vaccine.name,
                            'unit_type': 'ml',
                            'notes': vaccine.notes
                        })
                
                items.append(item_data)
            except Exception as e:
                print(f"Error getting item data for item {item.id}: {str(e)}")
                continue
        
        # Get miscellaneous items
        misc_items = []
        for item in update.miscellaneous_items:
            try:
                misc_items.append({
                    'name': item.name,
                    'quantity_per_unit': float(item.quantity_per_unit),
                    'unit_type': item.unit_type,
                    'price_per_unit': float(item.price_per_unit),
                    'units_used': float(item.units_used),
                    'total_cost': float(item.total_cost)
                })
            except Exception as e:
                print(f"Error getting miscellaneous item data: {str(e)}")
                continue

        return jsonify({
            'success': True,
            'update': {
                'date': update.date.strftime('%Y-%m-%d'),
                'mortality_count': update.mortality_count,
                'feed_used': float(update.feed_used),
                'avg_weight': float(update.avg_weight),
                'remarks': update.remarks,
                'remarks_priority': update.remarks_priority,
                'feeds': feeds,
                'items': items,
                'miscellaneous_items': misc_items
            }
        })
            
    except Exception as e:
        print(f"Error in get_batch_update: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/batches/<int:batch_id>/update/<date>/edit', methods=['GET', 'POST'])
@login_required
def edit_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        try:
            update_date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('view_batch', batch_id=batch.id))
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter(
            BatchUpdate.batch_id == batch_id,
            db.func.date(BatchUpdate.date) == update_date
        ).first()
        
        if not update:
            flash('Update not found', 'error')
            return redirect(url_for('view_batch', batch_id=batch.id))
        
        # Get all scheduled items
        medicine_schedules = MedicineSchedule.query.filter(
            MedicineSchedule.schedule_date <= update_date,
            MedicineSchedule.batches.contains(batch),
        ).all()
        
        health_material_schedules = HealthMaterialSchedule.query.filter(
            HealthMaterialSchedule.scheduled_date <= update_date,
            HealthMaterialSchedule.batches.contains(batch),
        ).all()
        
        vaccine_schedules = VaccineSchedule.query.filter(
            VaccineSchedule.scheduled_date <= update_date,
            VaccineSchedule.batches.contains(batch),
        ).all()
        
        # Get selected schedules
        selected_medicine_schedules = set()
        selected_health_material_schedules = set()
        selected_vaccine_schedules = set()
        
        for item in update.items:
            if item.schedule_id:
                if item.item_type == 'medicine':
                    selected_medicine_schedules.add(item.schedule_id)
                elif item.item_type == 'health_material':
                    selected_health_material_schedules.add(item.schedule_id)
                elif item.item_type == 'vaccine':
                    selected_vaccine_schedules.add(item.schedule_id)
        
        if request.method == 'POST':
            try:
                # Get form data with default values for empty strings
                mortality_count = int(request.form.get('mortality_count', 0) or 0)
                feed_used = float(request.form.get('feed_used', 0) or 0)
                avg_weight = float(request.form.get('avg_weight', 0) or 0)
                male_weight = float(request.form.get('male_weight', 0) or 0)
                female_weight = float(request.form.get('female_weight', 0) or 0)
                remarks = request.form.get('remarks', '')
                remarks_priority = request.form.get('remarks_priority', 'low')

                # Get old feed used
                old_feed_used = update.feed_used

                # Get the current mortality count to calculate difference
                old_mortality = update.mortality_count
                new_mortality = mortality_count
                mortality_difference = new_mortality - old_mortality

                # Update basic metrics
                update.mortality_count = mortality_count
                update.feed_used = feed_used
                update.avg_weight = avg_weight
                update.male_weight = male_weight
                update.female_weight = female_weight
                update.remarks = remarks
                update.remarks_priority = remarks_priority

                # Update batch's available birds and total mortality
                batch.available_birds = batch.available_birds - mortality_difference
                batch.total_mortality = batch.total_mortality - old_mortality + new_mortality

                # Calculate feed allocation changes
                old_feed_allocation = sum(update.get_feed_quantity(feed.id) for feed in update.feeds)

                # Calculate new feed allocation from form data
                new_feed_allocation = 0
                feed_data = request.form.getlist('feed_id[]')
                feed_quantities = request.form.getlist('feed_quantity[]')
                for quantity in feed_quantities:
                    if quantity and float(quantity) > 0:
                        new_feed_allocation += float(quantity)

                # Update feed stock and feed usage
                batch.feed_usage = batch.feed_usage - old_feed_used + update.feed_used
                batch.feed_stock = batch.feed_stock - (old_feed_allocation - new_feed_allocation) + (old_feed_used - update.feed_used)

                # --- FEED RETURNS ---
                # Remove all previous returns for this update
                BatchFeedReturn.query.filter_by(batch_update_id=update.id).delete()
                db.session.flush()
                # Add new feed returns
                feed_return_ids = request.form.getlist('feed_return_id[]')
                feed_return_quantities = request.form.getlist('feed_return_quantity[]')
                total_returned_feed = 0
                for i in range(len(feed_return_ids)):
                    if feed_return_ids[i] and feed_return_quantities[i]:
                        feed_id = int(feed_return_ids[i])
                        quantity = float(feed_return_quantities[i])
                        if quantity > 0:
                            feed_return = BatchFeedReturn(
                                batch_update_id=update.id,
                                feed_id=feed_id,
                                quantity=quantity
                            )
                            db.session.add(feed_return)
                            total_returned_feed += quantity
                batch.feed_stock -= total_returned_feed

                # Reset only the schedules that were previously completed by this update
                for item in update.items:
                    if item.schedule_id:
                        if item.item_type == 'medicine':
                            schedule = MedicineSchedule.query.get(item.schedule_id)
                            if schedule:
                                schedule.completed = False
                        elif item.item_type == 'health_material':
                            schedule = HealthMaterialSchedule.query.get(item.schedule_id)
                            if schedule:
                                schedule.completed = False
                        elif item.item_type == 'vaccine':
                            schedule = VaccineSchedule.query.get(item.schedule_id)
                            if schedule:
                                schedule.completed = False

                # Clear existing items
                BatchUpdateItem.query.filter_by(batch_update_id=update.id).delete()
                db.session.execute(batch_update_feeds.delete().where(
                    batch_update_feeds.c.batch_update_id == update.id
                ))
                MiscellaneousItem.query.filter_by(batch_update_id=update.id).delete()

                # Process feeds
                for feed_id, quantity in zip(feed_data, feed_quantities):
                    if feed_id and quantity and float(quantity) > 0:
                        feed = Feed.query.get(int(feed_id))
                        if feed:
                            # Create BatchUpdateItem for feed instead of using the relationship
                            stmt = batch_update_feeds.insert().values(
                                batch_update_id=update.id,
                                feed_id=feed_id,
                                quantity=float(quantity),
                                quantity_per_unit_at_time=feed.weight,
                                price_at_time=feed.price,
                                total_cost=float(quantity) * feed.price
                            )
                            db.session.execute(stmt)

                # Process miscellaneous items
                misc_names = request.form.getlist('misc_name[]')
                misc_quantities = request.form.getlist('misc_quantity_per_unit[]')
                misc_units = request.form.getlist('misc_unit_type[]')
                misc_prices = request.form.getlist('misc_price_per_unit[]')
                misc_used = request.form.getlist('misc_units_used[]')
                
                for name, qty_per_unit, unit, price, used in zip(misc_names, misc_quantities, misc_units, misc_prices, misc_used):
                    if name and qty_per_unit and unit and price and used:
                        misc_item = MiscellaneousItem(
                            batch_update_id=update.id,
                            name=name,
                            quantity_per_unit=float(qty_per_unit),
                            unit_type=unit,
                            price_per_unit=float(price),
                            units_used=float(used),
                            total_cost=float(price) * float(used)
                        )
                        db.session.add(misc_item)

                # Process scheduled items
                for key, value in request.form.items():
                    if key.startswith('scheduled_items['):
                        try:
                            # Extract type, id, and field from the key
                            # Format: scheduled_items[type][id][field]
                            key_parts = key.replace('scheduled_items[', '').replace(']', '').split('[')
                            if len(key_parts) == 3:
                                item_type, item_id, field = key_parts
                                item_id = int(item_id)
                                
                                # Only process selected items with quantity
                                if field == 'selected' and value == '1':
                                    quantity_key = f'scheduled_items[{item_type}][{item_id}][quantity]'
                                    quantity = float(request.form.get(quantity_key, 0) or 0)
                                    
                                    if quantity > 0:
                                        # Get the appropriate schedule
                                        schedule = None
                                        if item_type == 'medicine':
                                            schedule = MedicineSchedule.query.get(item_id)
                                            item_id = schedule.medicine_id if schedule else None
                                        elif item_type == 'health_material':
                                            schedule = HealthMaterialSchedule.query.get(item_id)
                                            item_id = schedule.health_material_id if schedule else None
                                        elif item_type == 'vaccine':
                                            schedule = VaccineSchedule.query.get(item_id)
                                            item_id = schedule.vaccine_id if schedule else None
                                        
                                        if schedule and item_id:
                                            # Get the item to get its current price
                                            item = None
                                            if item_type == 'medicine':
                                                item = Medicine.query.get(item_id)
                                            elif item_type == 'health_material':
                                                item = HealthMaterial.query.get(item_id)
                                            elif item_type == 'vaccine':
                                                item = Vaccine.query.get(item_id)
                                                item.unit_type = 'ml'
                                            
                                            if item:
                                                # Create batch update item with current price
                                                update_item = BatchUpdateItem(
                                                    batch_update_id=update.id,
                                                    item_id=item_id,
                                                    item_type=item_type,
                                                    quantity=quantity,
                                                    quantity_per_unit_at_time=item.quantity_per_unit,  # Use item's quantity_per_unit
                                                    unit_type=item.unit_type,  # Add unit_type from item
                                                    price_at_time=item.price,
                                                    total_cost=item.price * quantity,
                                                    schedule_id=schedule.id,
                                                    dose_number=schedule.dose_number if item_type == 'vaccine' else None
                                                )
                                                db.session.add(update_item)
                                                schedule.completed = True
                        except (ValueError, IndexError) as e:
                            print(f"Error processing scheduled item {key}: {str(e)}")
                            continue

                # Process other items (medicines, health materials, vaccines)
                for key, value in request.form.items():
                    if key.startswith('other_items['):
                        try:
                            # Extract type, index, and field from the key
                            # Format: other_items[type][index][field]
                            key_parts = key.replace('other_items[', '').replace(']', '').split('[')
                            if len(key_parts) == 3:
                                item_type, index, field = key_parts
                                
                                if field == 'id' and value:
                                    item_id = int(value)
                                    quantity_key = f'other_items[{item_type}][{index}][quantity]'
                                    quantity = float(request.form.get(quantity_key, 0) or 0)
                                    
                                    if quantity > 0:
                                        # Get the appropriate item
                                        item = None
                                        if item_type == 'medicine':
                                            item = Medicine.query.get(item_id)
                                        elif item_type == 'health_material':
                                            item = HealthMaterial.query.get(item_id)
                                        elif item_type == 'vaccine':
                                            item = Vaccine.query.get(item_id)
                                            dose_number_key = f'other_items[{item_type}][{index}][dose_number]'
                                            dose_number = int(request.form.get(dose_number_key, 1) or 1)
                                            item.unit_type = 'ml'
                                        
                                        if item:
                                            # Create batch update item with current price
                                            print(f"Saving {item_type}: id={item.id}, quantity={quantity}, batch_update_id={update.id}")
                                            update_item = BatchUpdateItem(
                                                batch_update_id=update.id,
                                                item_id=item.id,
                                                item_type=item_type,
                                                quantity=quantity,
                                                quantity_per_unit_at_time=item.quantity_per_unit,  # Use item's quantity_per_unit
                                                unit_type=item.unit_type,  # Add unit_type from item
                                                price_at_time=item.price,
                                                total_cost=item.price * quantity,
                                                schedule_id=None,  # No schedule ID for other items
                                                dose_number=dose_number if item_type == 'vaccine' else None
                                            )
                                            db.session.add(update_item)
                                        else:
                                            print(f"Warning: Could not find item for {item_type} with ID {item_id}")
                        except (ValueError, IndexError) as e:
                            print(f"Error processing other item {key}: {str(e)}")
                            continue

                db.session.commit()
                flash('Batch update edited successfully!', 'success')
                return redirect(url_for('view_batch', batch_id=batch.id))
            except ValueError as e:
                db.session.rollback()
                print(f"Value error in edit_batch_update: {str(e)}")
                flash(f'Invalid input: {str(e)}', 'error')
            except Exception as e:
                db.session.rollback()
                print(f"Error in edit_batch_update: {str(e)}")
                flash('Error saving batch update. Please try again.', 'error')
        
        # Get available items for extra items
        medicines = Medicine.query.all()
        health_materials = HealthMaterial.query.all()
        vaccines = Vaccine.query.all()
        feeds = Feed.query.all()
                
        return render_template('edit_batch_update.html',
                             batch=batch,
                             update=update,
                             medicine_schedules=medicine_schedules,
                             health_material_schedules=health_material_schedules,
                             vaccine_schedules=vaccine_schedules,
                             selected_medicine_schedules=selected_medicine_schedules,
                             selected_health_material_schedules=selected_health_material_schedules,
                             selected_vaccine_schedules=selected_vaccine_schedules,
                             medicines=medicines,
                            health_materials=health_materials,
                             vaccines=vaccines,
                             feeds=feeds,
                             today=datetime.now().date())  # Add today to template context
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('view_batch', batch_id=batch.id))

@app.route('/batches/<int:batch_id>/update/<date>/delete', methods=['POST'])
@login_required
def delete_batch_update(batch_id, date):
    try:
        batch = Batch.query.get_or_404(batch_id)
        try:
            update_date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError as e:
            print(f"Date format error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Please use YYYY-MM-DD format.'
            }), 400
        
        # Find the update for the specified date
        update = BatchUpdate.query.filter(
            BatchUpdate.batch_id == batch_id,
            db.func.date(BatchUpdate.date) == update_date
        ).first()
        
        if not update:
            return jsonify({
                'success': False,
                'message': 'Update not found.'
            }), 404
        

        # Reset all schedules that were completed by this update
        for item in update.items:
            if item.schedule_id:
                if item.item_type == 'medicine':
                    schedule = MedicineSchedule.query.get(item.schedule_id)
                    if schedule:
                        schedule.completed = False
                elif item.item_type == 'health_material':
                    schedule = HealthMaterialSchedule.query.get(item.schedule_id)
                    if schedule:
                        schedule.completed = False
                elif item.item_type == 'vaccine':
                    schedule = VaccineSchedule.query.get(item.schedule_id)
                    if schedule:
                        schedule.completed = False
        
        # Update batch metrics
        batch.available_birds += update.mortality_count
        batch.total_mortality -= update.mortality_count
        
        batch.feed_usage -= update.feed_used
        
        # Calculate total feed quantity from the update
        total_feed_quantity = 0
        for feed in update.feeds:
            # Get the quantity from the association table
            feed_quantity = db.session.query(batch_update_feeds.c.quantity).filter(
                batch_update_feeds.c.batch_update_id == update.id,
                batch_update_feeds.c.feed_id == feed.id
            ).scalar()
            if feed_quantity:
                total_feed_quantity += feed_quantity
        
        # Update batch feed stock
        batch.feed_stock = max(0, batch.feed_stock - total_feed_quantity + update.feed_used)
        
        # Delete the update
        db.session.delete(update)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Batch update deleted successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error in delete_batch_update: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while deleting the update.'
        }), 500

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
        
        # Check if feed is used in any batch updates
        feed_usage = db.session.query(batch_update_feeds).filter_by(feed_id=feed_id).first()
        if feed_usage:
            return jsonify({
                'success': False, 
                'message': 'Cannot delete feed that has been used in batch updates.'
            })
        
        db.session.delete(feed)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/medicines')
@login_required
def medicines():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    medicines = Medicine.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('medicines.html', medicines=medicines, batches=batches)

@app.route('/medicine/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def view_medicine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    medicine = Medicine.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_medicine.html', medicine=medicine, batches=batches)

@app.route('/medicine/<int:id>/edit', methods=['GET', 'POST'])
@login_required
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
@login_required
def delete_medicine(id):
    medicine = Medicine.query.get_or_404(id)
    try:
        # First check if there are any schedules using this medicine
        schedules = MedicineSchedule.query.filter_by(medicine_id=id).all()
        if schedules:
            return jsonify({'success': False, 'message': 'Cannot delete medicine that has scheduled uses. Please delete the schedules first.'})
        
        db.session.delete(medicine)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Medicine deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting medicine: {str(e)}'})

@app.route('/medicine/schedule', methods=['POST'])
@login_required
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
@login_required
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
@login_required 
def vaccines():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    vaccines = Vaccine.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('vaccines.html', vaccines=vaccines, batches=batches)

@app.route('/vaccine/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def view_vaccine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    vaccine = Vaccine.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_vaccine.html', vaccine=vaccine, batches=batches)

@app.route('/vaccine/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vaccine(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    vaccine = Vaccine.query.get_or_404(id)
    print(vaccine.dose_ages)
    
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

@app.route('/health-material/<int:id>/delete', methods=['POST'])
@login_required
def delete_health_material(id):
    health_material = HealthMaterial.query.get_or_404(id)
    try:
        # First check if there are any schedules using this material
        schedules = HealthMaterialSchedule.query.filter_by(health_material_id=id).all()
        if schedules:
            return jsonify({'success': False, 'message': 'Cannot delete health material that has scheduled uses. Please delete the schedules first.'})
        
        db.session.delete(health_material)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Health material deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting health material: {str(e)}'})

@app.route('/health-material/schedule', methods=['POST'])
@login_required
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
@login_required
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
        # Get selected date from query parameters, default to today
        selected_date_str = request.args.get('date')
        if selected_date_str:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        else:
            selected_date = datetime.now().date()

        # Get current date and time
        today = datetime.now().date()
        end_date = today + timedelta(days=30)
        
        # Get schedules based on user type
        if session.get('user_type') == 'assistant_manager':
            # Get batches assigned to this manager
            manager_batches = Batch.query.filter_by(manager_id=session.get('user_id')).all()
            batch_ids = [batch.id for batch in manager_batches]
            
            # Health Material Schedules
            health_material_schedules = HealthMaterialSchedule.query.join(
                health_material_schedule_batches
            ).filter(
                health_material_schedule_batches.c.batch_id.in_(batch_ids),
                HealthMaterialSchedule.scheduled_date == selected_date
            ).order_by(HealthMaterialSchedule.scheduled_date).all()
            
            # Medical Schedules
            medical_schedules = MedicineSchedule.query.join(
                medicine_schedule_batches
            ).filter(
                medicine_schedule_batches.c.batch_id.in_(batch_ids),
                MedicineSchedule.schedule_date == selected_date
            ).order_by(MedicineSchedule.schedule_date).all()
            
            # Vaccine Schedules
            vaccine_schedules = VaccineSchedule.query.join(
                vaccine_schedule_batches
            ).filter(
                vaccine_schedule_batches.c.batch_id.in_(batch_ids),
                VaccineSchedule.scheduled_date == selected_date
            ).order_by(VaccineSchedule.scheduled_date).all()
            
            # Get all scheduled dates for the calendar
            scheduled_dates = set()
            
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).join(
                health_material_schedule_batches
            ).filter(
                health_material_schedule_batches.c.batch_id.in_(batch_ids),
                HealthMaterialSchedule.scheduled_date >= today,
                HealthMaterialSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).join(
                medicine_schedule_batches
            ).filter(
                medicine_schedule_batches.c.batch_id.in_(batch_ids),
                MedicineSchedule.schedule_date >= today,
                MedicineSchedule.schedule_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).join(
                vaccine_schedule_batches
            ).filter(
                vaccine_schedule_batches.c.batch_id.in_(batch_ids),
                VaccineSchedule.scheduled_date >= today,
                VaccineSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)
            
        elif session.get('user_type') == 'senior_manager':
            # Health Material Schedules
            health_material_schedules = HealthMaterialSchedule.query.join(
                health_material_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                HealthMaterialSchedule.scheduled_date == selected_date
            ).order_by(HealthMaterialSchedule.scheduled_date).all()
            
            # Medical Schedules
            medical_schedules = MedicineSchedule.query.join(
                medicine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                MedicineSchedule.schedule_date == selected_date
            ).order_by(MedicineSchedule.schedule_date).all()
            
            # Vaccine Schedules
            vaccine_schedules = VaccineSchedule.query.join(
                vaccine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                VaccineSchedule.scheduled_date == selected_date
            ).order_by(VaccineSchedule.scheduled_date).all()
        
            # Get all scheduled dates for the calendar
            scheduled_dates = set()
        
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).join(
            health_material_schedule_batches
        ).join(
            Batch
        ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                HealthMaterialSchedule.scheduled_date >= today,
                HealthMaterialSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).join(
            medicine_schedule_batches
        ).join(
            Batch
        ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                MedicineSchedule.schedule_date >= today,
                MedicineSchedule.schedule_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).join(
            vaccine_schedule_batches
        ).join(
            Batch
        ).filter(
                Batch.status.in_(['ongoing', 'closing']),
                VaccineSchedule.scheduled_date >= today,
                VaccineSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)
        else:
            # Admin sees all schedules
            health_material_schedules = HealthMaterialSchedule.query.filter(
                HealthMaterialSchedule.scheduled_date == selected_date
            ).order_by(HealthMaterialSchedule.scheduled_date).all()
            
            medical_schedules = MedicineSchedule.query.filter(
                MedicineSchedule.schedule_date == selected_date
            ).order_by(MedicineSchedule.schedule_date).all()
            
            vaccine_schedules = VaccineSchedule.query.filter(
                VaccineSchedule.scheduled_date == selected_date
            ).order_by(VaccineSchedule.scheduled_date).all()
            
            # Get all scheduled dates for the calendar
            scheduled_dates = set()
            
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).filter(
                HealthMaterialSchedule.scheduled_date >= today,
                HealthMaterialSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).filter(
                MedicineSchedule.schedule_date >= today,
                MedicineSchedule.schedule_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).filter(
                VaccineSchedule.scheduled_date >= today,
                VaccineSchedule.scheduled_date <= end_date
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)

        # Get recent activities
        recent_activities = Activity.query.order_by(Activity.timestamp.desc()).limit(5).all()
        
        return render_template('manager/schedules.html',
                             health_material_schedules=health_material_schedules,
                             medical_schedules=medical_schedules,
                             vaccine_schedules=vaccine_schedules,
                             recent_activities=recent_activities,
                             selected_date=selected_date,
                             scheduled_dates=list(scheduled_dates))
    except Exception as e:
        flash(str(e), 'error')
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
        phone_number = request.form.get('phone_number')
        alternate_phone_number = request.form.get('alternate_phone_number')
        
        # Validate user type
        if user_type not in ['assistant_manager', 'senior_manager']:
            flash('Invalid user type', 'error')
            return redirect(url_for('farm_manager'))
        
        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('farm_manager'))
        
        # Check if phone number already exists
        if phone_number and Employee.query.filter_by(phone_number=phone_number).first():
            flash('Phone number already exists', 'error')
            return redirect(url_for('farm_manager'))
        
        # Create user first
        user = User(username=username, user_type=user_type)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # This will get us the user.id
        
        # Create employee record with phone numbers
        employee = Employee(
            name=name, 
            user_id=user.id,
            phone_number=phone_number,
            alternate_phone_number=alternate_phone_number
        )
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
    phone_number = request.form.get('phone_number')
    alternate_phone_number = request.form.get('alternate_phone_number')
    
    # Validate user type
    if user_type not in ['assistant_manager', 'senior_manager']:
        flash('Invalid user type', 'error')
        return redirect(url_for('farm_manager'))
    
    # Check if username already exists (excluding current user)
    if username != user.username and User.query.filter_by(username=username).first():
        flash('Username already exists', 'error')
        return redirect(url_for('farm_manager'))
    
    # Check if phone number already exists (excluding current employee)
    if phone_number and phone_number != user.employee.phone_number and Employee.query.filter_by(phone_number=phone_number).first():
        flash('Phone number already exists', 'error')
        return redirect(url_for('farm_manager'))
    
    # Update user
    user.username = username
    user.user_type = user_type
    if password:
        user.set_password(password)
    
    # Update or create employee record
    if user.employee:
        user.employee.name = name
        user.employee.phone_number = phone_number
        user.employee.alternate_phone_number = alternate_phone_number
    else:
        employee = Employee(
            name=name,
            user_id=user.id,
            phone_number=phone_number,
            alternate_phone_number=alternate_phone_number
        )
        db.session.add(employee)
    
    db.session.commit()
    flash('Manager updated successfully', 'success')
    return redirect(url_for('farm_manager'))

@app.route('/delete_manager/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_manager(user_id):
    try:
        user = User.query.get_or_404(user_id)
        
        # Prevent deleting the last admin
        if user.user_type == 'admin' and User.query.filter_by(user_type='admin').count() <= 1:
            return jsonify({'success': False, 'message': 'Cannot delete the last admin user'})
    
        # Check if manager has any active batches
        active_batches = Batch.query.filter(
            Batch.manager_id == user_id,
            Batch.status.in_(['ongoing', 'closing'])
        ).first()
        
        if active_batches:
            return jsonify({
                'success': False, 
                'message': 'Cannot delete manager with active batches. Please reassign or close all batches first.'
            })
        
        # Update any closed batches to remove manager reference
        Batch.query.filter_by(manager_id=user_id).update({Batch.manager_id: None})
        
        # Delete employee record first if exists
        if user.employee:
            db.session.delete(user.employee)
        
        # Delete the user
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

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
                         now=datetime.now(),
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
                         now=datetime.now())

@app.route('/manager/batches/<int:batch_id>/update', methods=['GET', 'POST'])
@login_required
def manager_update_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    # Check if user has permission to update this batch
    if session.get('user_type') == 'assistant_manager' and batch.manager_id != session.get('user_id'):
        flash('You do not have permission to update this batch.', 'error')
        return redirect(url_for('manager_batches'))
    
    # Check if update already exists for today
    today = datetime.now().date()
    existing_update = BatchUpdate.query.filter_by(batch_id=batch_id, date=today).first()
    
    if request.method == 'POST':
        try:
            mortality_count = int(request.form.get('mortality_count', 0) or 0)
            feed_used = float(request.form.get('feed_used', 0) or 0)
            avg_weight = float(request.form.get('avg_weight', 0) or 0)
            male_weight = float(request.form.get('male_weight', 0) or 0)
            female_weight = float(request.form.get('female_weight', 0) or 0)
            remarks = request.form.get('remarks', '')
            remarks_priority = request.form.get('remarks_priority', 'low')

            # Create new batch update
            batch_update = BatchUpdate(
                batch_id=batch_id,
                date=today,
                mortality_count=mortality_count,
                feed_used=feed_used,
                avg_weight=avg_weight,
                male_weight=male_weight,
                female_weight=female_weight,
                remarks=remarks,
                remarks_priority=remarks_priority
            )
            db.session.add(batch_update)
            db.session.flush()  # Get the batch_update.id

            # Update batch statistics
            batch.total_mortality += mortality_count
            batch.available_birds = batch.total_birds - batch.total_mortality
            batch.feed_usage += feed_used
            total_quantity = 0

            # Process feed items
            feed_ids = request.form.getlist('feed_id[]')
            feed_quantities = request.form.getlist('feed_quantity[]')
            for feed_id, quantity in zip(feed_ids, feed_quantities):
                if feed_id and quantity and float(quantity) > 0:
                    feed = Feed.query.get(feed_id)
                    if feed:
                        quantity_float = float(quantity)
                        total_quantity += quantity_float
                        price_at_time = feed.price
                        total_cost = quantity_float * price_at_time
                        # Insert directly into the association table with quantity and price
                        stmt = batch_update_feeds.insert().values(
                            batch_update_id=batch_update.id,
                            feed_id=feed_id,
                            quantity=quantity_float,
                            quantity_per_unit_at_time=feed.weight,  # Store the weight per unit at time of update
                            price_at_time=price_at_time,
                            total_cost=total_cost
                        )
                        db.session.execute(stmt)

            batch.feed_stock = max(0, batch.feed_stock + total_quantity - feed_used)  # Ensure feed stock doesn't go negative

            # Process feed returns
            feed_return_ids = request.form.getlist('feed_return_id[]')
            feed_return_quantities = request.form.getlist('feed_return_quantity[]')
            total_returned_feed = 0
            for i in range(len(feed_return_ids)):
                if feed_return_ids[i] and feed_return_quantities[i]:
                    feed_id = int(feed_return_ids[i])
                    quantity = float(feed_return_quantities[i])
                    if quantity > 0:
                        feed_return = BatchFeedReturn(
                            batch_update_id=batch_update.id,
                            feed_id=feed_id,
                            quantity=quantity
                        )
                        db.session.add(feed_return)
                        total_returned_feed += quantity
            batch.feed_stock -= total_returned_feed

            # Process miscellaneous items
            misc_names = request.form.getlist('misc_name[]')
            misc_quantities = request.form.getlist('misc_quantity_per_unit[]')
            misc_units = request.form.getlist('misc_unit_type[]')
            misc_prices = request.form.getlist('misc_price_per_unit[]')
            misc_used = request.form.getlist('misc_units_used[]')
            
            for name, qty_per_unit, unit, price, used in zip(misc_names, misc_quantities, misc_units, misc_prices, misc_used):
                if name and qty_per_unit and unit and price and used:
                    misc_item = MiscellaneousItem(
                        batch_update_id=batch_update.id,
                        name=name,
                        quantity_per_unit=float(qty_per_unit),
                        unit_type=unit,
                        price_per_unit=float(price),
                        units_used=float(used),
                        total_cost=float(price) * float(used)
                    )
                    db.session.add(misc_item)
            
            # Process scheduled items
            for key, value in request.form.items():
                if key.startswith('scheduled_items['):
                    try:
                        # Extract type, id, and field from the key
                        # Format: scheduled_items[type][id][field]
                        key_parts = key.replace('scheduled_items[', '').replace(']', '').split('[')
                        if len(key_parts) == 3:
                            item_type, item_id, field = key_parts
                            item_id = int(item_id)
                            
                            # Only process selected items with quantity
                            if field == 'selected' and value == '1':
                                quantity_key = f'scheduled_items[{item_type}][{item_id}][quantity]'
                                quantity = float(request.form.get(quantity_key, 0) or 0)
                                
                                if quantity > 0:
                                    # Get the appropriate schedule and item
                                    schedule = None
                                    item = None
                                    if item_type == 'medicine':
                                        schedule = MedicineSchedule.query.get(item_id)
                                        item = schedule.medicine if schedule else None
                                    elif item_type == 'health_material':
                                        schedule = HealthMaterialSchedule.query.get(item_id)
                                        item = schedule.health_material if schedule else None
                                    elif item_type == 'vaccine':
                                        schedule = VaccineSchedule.query.get(item_id)
                                        item = schedule.vaccine if schedule else None
                                        item.unit_type = 'ml'

                                    # if item.unit_type:
                                    #     unit_type = item.unit_type
                                    # else:
                                    #     unit_type = 'ml'
                                    
                                    if schedule and item:
                                        # Create batch update item with current price and schedule ID
                                        update_item = BatchUpdateItem(
                                            batch_update_id=batch_update.id,
                                            item_id=item.id,
                                            item_type=item_type,
                                            quantity=quantity,
                                            quantity_per_unit_at_time=item.quantity_per_unit,  # Use item's quantity_per_unit
                                            unit_type=item.unit_type,  # Add unit_type from item
                                            price_at_time=item.price,
                                            total_cost=item.price * quantity,
                                            schedule_id=schedule.id,
                                            dose_number=schedule.dose_number if item_type == 'vaccine' else None
                                        )
                                        db.session.add(update_item)
                                        
                                        # Mark schedule as completed
                                        schedule.completed = True

                                    # Add batch to schedule's batches if not already present
                                    if batch not in schedule.batches:
                                        schedule.batches.append(batch)
                                    else:
                                        print(f"Warning: Could not find schedule or item for {item_type} with ID {item_id}")
                    except (ValueError, IndexError) as e:
                        print(f"Error processing scheduled item {key}: {str(e)}")
                        continue

            # Process other items (medicines, health materials, vaccines)
            for key, value in request.form.items():
                if key.startswith('other_items['):
                    try:
                        # Extract type, index, and field from the key
                        # Format: other_items[type][index][field]
                        key_parts = key.replace('other_items[', '').replace(']', '').split('[')
                        if len(key_parts) == 3:
                            item_type, index, field = key_parts
                            
                            if field == 'id' and value:
                                item_id = int(value)
                                quantity_key = f'other_items[{item_type}][{index}][quantity]'
                                quantity = float(request.form.get(quantity_key, 0) or 0)
                                
                                if quantity > 0:
                                    # Get the appropriate item
                                    item = None
                                    if item_type == 'medicine':
                                        item = Medicine.query.get(item_id)
                                    elif item_type == 'health_material':
                                        item = HealthMaterial.query.get(item_id)
                                    elif item_type == 'vaccine':
                                        item = Vaccine.query.get(item_id)
                                        dose_number_key = f'other_items[{item_type}][{index}][dose_number]'
                                        dose_number = int(request.form.get(dose_number_key, 1) or 1)
                                        item.unit_type = 'ml'
                                    
                                    if item:
                                        # Create batch update item without schedule ID
                                        update_item = BatchUpdateItem(
                                            batch_update_id=batch_update.id,
                                            item_id=item.id,
                                            item_type=item_type,
                                            quantity=quantity,
                                            quantity_per_unit_at_time=item.quantity_per_unit,  # Use item's quantity_per_unit
                                            unit_type=item.unit_type,  # Add unit_type from item
                                            price_at_time=item.price,
                                            total_cost=item.price * quantity,
                                            schedule_id=None,  # No schedule ID for other items
                                            dose_number=dose_number if item_type == 'vaccine' else None
                                        )
                                        db.session.add(update_item)
                                    else:
                                        print(f"Warning: Could not find item for {item_type} with ID {item_id}")
                    except (ValueError, IndexError) as e:
                        print(f"Error processing other item {key}: {str(e)}")
                        continue

            db.session.commit()
            flash('Batch update recorded successfully!', 'success')
            return redirect(url_for('manager_view_batch', batch_id=batch.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording batch update: {str(e)}', 'error')
            return redirect(url_for('update_batch', batch_id=batch.id))
    
    # Get scheduled items for today
    medicine_schedules = MedicineSchedule.query.filter(
        MedicineSchedule.batches.contains(batch),
        MedicineSchedule.schedule_date <= today,
        MedicineSchedule.completed == False
    ).all()
    
    health_material_schedules = HealthMaterialSchedule.query.filter(
        HealthMaterialSchedule.batches.contains(batch),
        HealthMaterialSchedule.scheduled_date <= today,
        HealthMaterialSchedule.completed == False
    ).all()
    
    vaccine_schedules = VaccineSchedule.query.filter(
        VaccineSchedule.batches.contains(batch),
        VaccineSchedule.scheduled_date <= today,
        VaccineSchedule.completed == False
    ).all()

    return render_template('manager/update_batch.html', 
                         batch=batch, 
                         existing_update=existing_update,
                         feeds=Feed.query.all(),
                         medicines=Medicine.query.all(),
                         health_materials=HealthMaterial.query.all(),
                         vaccines=Vaccine.query.all(),
                         medicine_schedules=medicine_schedules,
                         health_material_schedules=health_material_schedules,
                         vaccine_schedules=vaccine_schedules,
                         today=today)

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
                date=datetime.now().date(),
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
        
        # If batch was closed and this was the last harvest, revert status to closing
        if batch.status == 'closed' and len(batch.harvests) == 1:
            batch.status = 'closing'
        
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

@app.route('/pending-schedules-count')
@login_required
def pending_schedules_count():
    today = datetime.now().date()
    
    # Count vaccine schedules
    vaccine_count = VaccineSchedule.query.filter(
        VaccineSchedule.scheduled_date < today,
        VaccineSchedule.completed == False
    ).count()
    
    # Count health material schedules
    health_count = HealthMaterialSchedule.query.filter(
        HealthMaterialSchedule.scheduled_date < today,
        HealthMaterialSchedule.completed == False
    ).count()
    
    # Count medical schedules
    medical_count = MedicineSchedule.query.filter(
        MedicineSchedule.schedule_date < today,
        MedicineSchedule.completed == False
    ).count()
    
    total_count = health_count + medical_count + vaccine_count
    
    return jsonify({'count': total_count})

@app.route('/pending-schedules')
@login_required
def pending_schedules():
    today = datetime.now().date()
    schedules = []
        
    # Get health material schedules
    health_schedules = HealthMaterialSchedule.query.filter(
        HealthMaterialSchedule.scheduled_date < today,
        HealthMaterialSchedule.completed == False
    ).all()
        
    for schedule in health_schedules:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                schedules.append({
                    'id': schedule.id,
                    'type': 'health-material',
                    'name': schedule.health_material.name,
                    'batch_number': batch.batch_number,
                    'scheduled_date': schedule.scheduled_date.strftime('%d-%m-%Y'),
                    'icon': 'fa-spray-can'
                })
        
    # Get medical schedules
    medical_schedules = MedicineSchedule.query.filter(
        MedicineSchedule.schedule_date < today,
        MedicineSchedule.completed == False
    ).all()
        
    for schedule in medical_schedules:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                schedules.append({
                    'id': schedule.id,
                    'type': 'medicine',
                    'name': schedule.medicine.name,
                    'batch_number': batch.batch_number,
                    'scheduled_date': schedule.schedule_date.strftime('%d-%m-%Y'),
                    'icon': 'fa-pills'
                })
        
    # Get vaccine schedules
    vaccine_schedules = VaccineSchedule.query.filter(
        VaccineSchedule.scheduled_date < today,
        VaccineSchedule.completed == False
    ).all()
        
    for schedule in vaccine_schedules:
            batch = schedule.batches[0] if schedule.batches else None
            if batch:
                schedules.append({
                    'id': schedule.id,
                    'type': 'vaccine',
                    'name': schedule.vaccine.name,
                    'batch_number': batch.batch_number,
                    'scheduled_date': schedule.scheduled_date.strftime('%d-%m-%Y'),
                    'icon': 'fa-syringe'
            })
    
    # Sort schedules by date
    schedules.sort(key=lambda x: datetime.strptime(x['scheduled_date'], '%d-%m-%Y'))
    
    return jsonify({'schedules': schedules})

@app.route('/schedules')
@login_required
def schedules():
    # Get the selected date from query parameters, default to today
    selected_date = request.args.get('date')
    if selected_date:
        try:
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            selected_date = datetime.now().date()
    else:
        selected_date = datetime.now().date()
    
    # Get schedules for the selected date
    health_material_schedules = HealthMaterialSchedule.query.filter(
        HealthMaterialSchedule.scheduled_date == selected_date
    ).all()
    
    medical_schedules = MedicineSchedule.query.filter(
        MedicineSchedule.schedule_date == selected_date
    ).all()
    
    vaccine_schedules = VaccineSchedule.query.filter(
        VaccineSchedule.scheduled_date == selected_date
    ).all()
    
    recent_activities = Activity.query.order_by(Activity.timestamp.desc()).limit(10).all()
        
    return render_template('schedules.html',
                         health_material_schedules=health_material_schedules,
                         medical_schedules=medical_schedules,
                         vaccine_schedules=vaccine_schedules,
                         recent_activities=recent_activities,
                         selected_date=selected_date)  # Add selected_date to template context

@app.route('/vaccine/schedule/<int:id>/complete', methods=['POST'])
@login_required
def complete_vaccine_schedule(id):
    if session.get('user_type') not in ['admin', 'senior_manager', 'assistant_manager']:
        return jsonify({'success': False, 'message': 'Access denied. Only administrators and managers can complete schedules.'}), 403
    
    try:
        schedule = VaccineSchedule.query.get_or_404(id)
        
        # Check if assistant manager has access to any of the batches
        if session.get('user_type') == 'assistant_manager':
            has_access = any(batch in schedule.batches for batch in schedule.batches)
            if not has_access:
                return jsonify({'success': False, 'message': 'Access denied. You can only complete schedules for your assigned batches.'}), 403
        
        schedule.completed = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/health-materials')
@login_required
def health_materials():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    health_materials = HealthMaterial.query.all()
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('health_materials.html', health_materials=health_materials, batches=batches)

@app.route('/health-material/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def view_health_material(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    health_material = HealthMaterial.query.get_or_404(id)
    # Only show ongoing and closing batches
    batches = Batch.query.filter(Batch.status.in_(['ongoing', 'closing'])).all()
    return render_template('view_health_material.html', health_material=health_material, batches=batches)

@app.route('/health-material/<int:id>/edit', methods=['GET', 'POST'])
@login_required
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

@app.route('/vaccine/schedule', methods=['POST'])
@login_required
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
@login_required
def delete_vaccine_schedule(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    schedule = VaccineSchedule.query.get_or_404(id)
    vaccine_id = schedule.vaccine_id
    db.session.delete(schedule)
    db.session.commit()
    flash('Vaccine schedule deleted successfully!', 'success')
    return redirect(url_for('view_vaccine', id=vaccine_id))

@app.route('/vaccine/<int:id>/delete', methods=['POST'])
@login_required
def delete_vaccine(id):
    vaccine = Vaccine.query.get_or_404(id)
    try:
        # First check if there are any schedules using this vaccine
        schedules = VaccineSchedule.query.filter_by(vaccine_id=id).all()
        if schedules:
            return jsonify({'success': False, 'message': 'Cannot delete vaccine that has scheduled uses. Please delete the schedules first.'})
        
        db.session.delete(vaccine)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Vaccine deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting vaccine: {str(e)}'})

@app.route('/api/fcr-rates', methods=['GET'])
@login_required
def get_fcr_rates():
    try:
        rates = FCRRate.query.order_by(FCRRate.lower_limit).all()
        return jsonify([{
            'id': rate.id,
            'lower_limit': rate.lower_limit,
            'upper_limit': rate.upper_limit,
            'rate': rate.rate
        } for rate in rates])
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/fcr-rates', methods=['POST'])
@login_required
def save_fcr_rates():
    try:
        data = request.get_json()
        rates = data.get('rates', [])
        
        # Delete existing rates
        FCRRate.query.delete()
        
        # Add new rates
        for rate_data in rates:
            rate = FCRRate(
                lower_limit=rate_data['lower_limit'],
                upper_limit=rate_data['upper_limit'],
                rate=rate_data['rate']
            )
            db.session.add(rate)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/scheduled-dates')
@login_required
def get_scheduled_dates():
    try:
        # Get all scheduled dates for the calendar
        scheduled_dates = set()
        
        if session.get('user_type') == 'assistant_manager':
            # Get batches assigned to this manager
            manager_batches = Batch.query.filter_by(manager_id=session.get('user_id')).all()
            batch_ids = [batch.id for batch in manager_batches]
            
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).join(
                health_material_schedule_batches
            ).filter(
                health_material_schedule_batches.c.batch_id.in_(batch_ids)
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).join(
                medicine_schedule_batches
            ).filter(
                medicine_schedule_batches.c.batch_id.in_(batch_ids)
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).join(
                vaccine_schedule_batches
            ).filter(
                vaccine_schedule_batches.c.batch_id.in_(batch_ids)
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)
        elif session.get('user_type') == 'senior_manager':
            # Senior managers see all dates
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).join(
                health_material_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing'])
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).join(
                medicine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing'])
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).join(
                vaccine_schedule_batches
            ).join(
                Batch
            ).filter(
                Batch.status.in_(['ongoing', 'closing'])
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)
        else:
            # Senior managers see all dates
            # Get health material schedule dates
            health_dates = db.session.query(HealthMaterialSchedule.scheduled_date).join(
                health_material_schedule_batches
            ).join(
                Batch
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in health_dates)
            
            # Get medical schedule dates
            medical_dates = db.session.query(MedicineSchedule.schedule_date).join(
                medicine_schedule_batches
            ).join(
                Batch
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in medical_dates)
            
            # Get vaccine schedule dates
            vaccine_dates = db.session.query(VaccineSchedule.scheduled_date).join(
                vaccine_schedule_batches
            ).join(
                Batch
            ).all()
            scheduled_dates.update(date[0].strftime('%Y-%m-%d') for date in vaccine_dates)
        
        return jsonify({
            'success': True,
            'dates': list(scheduled_dates)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# Auto Schedule Routes
@app.route('/set_auto_schedule', methods=['POST'])
@login_required
def set_auto_schedule():
    try:
        # Check if this is a removal request
        if request.is_json and request.json.get('remove'):
            item_type = request.json.get('item_type')
            item_id = request.json.get('item_id')
            
            # Find and delete the auto schedule
            auto_schedule = AutoSchedule.query.filter_by(
                item_type=item_type,
                item_id=item_id
            ).first()
            
            if auto_schedule:
                db.session.delete(auto_schedule)
                db.session.commit()
                flash('Auto schedule has been removed successfully!', 'success')
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'message': 'No auto schedule found to remove'})
        
        # Handle normal auto schedule creation/update
        item_type = request.form.get('item_type')
        item_id = request.form.get('item_id')
        ages = request.form.getlist('ages[]')
        notes = request.form.get('notes')

        # Convert ages to integers and sort them
        ages = sorted([int(age) for age in ages])
        
        # Check if auto-schedule already exists
        auto_schedule = AutoSchedule.query.filter_by(
            item_type=item_type,
            item_id=item_id
        ).first()

        if auto_schedule:
            # Update existing auto-schedule
            auto_schedule.set_schedule_ages(ages)
            auto_schedule.notes = notes
        else:
            # Create new auto-schedule
            auto_schedule = AutoSchedule(
                item_type=item_type,
                item_id=item_id,
                schedule_ages=json.dumps(ages),
                notes=notes
            )
            db.session.add(auto_schedule)

        db.session.commit()
        flash('Auto schedule has been set successfully!', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        flash('Error setting auto schedule: ' + str(e), 'error')
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_auto_schedule/<item_type>/<int:item_id>')
@login_required
def get_auto_schedule(item_type, item_id):
    auto_schedule = AutoSchedule.query.filter_by(
        item_type=item_type,
        item_id=item_id
    ).first()

    if auto_schedule:
        return jsonify({
            'success': True,
            'ages': auto_schedule.get_schedule_ages(),
            'notes': auto_schedule.notes
        })
    return jsonify({'success': False, 'message': 'No auto schedule found'})

def create_schedules_for_batch(batch):
    """Create schedules for a new batch based on auto-schedules"""
    try:
        # Get all auto-schedules
        auto_schedules = AutoSchedule.query.all()
        
        for auto_schedule in auto_schedules:
            try:
                # Get schedule ages and ensure they are integers
                ages = [int(age) for age in auto_schedule.get_schedule_ages() if age is not None]
                batch_created_date = batch.created_at.date()
                
                for age in ages:
                    schedule_date = batch_created_date + timedelta(days=age)
                    
                    if auto_schedule.item_type == 'medicine':
                        medicine = Medicine.query.get(auto_schedule.item_id)
                        if medicine:
                            schedule = MedicineSchedule(
                                medicine_id=medicine.id,
                                schedule_date=schedule_date,
                                notes=auto_schedule.notes or '',
                                completed=False
                            )
                            schedule.batches.append(batch)
                            db.session.add(schedule)
                    
                    elif auto_schedule.item_type == 'vaccine':
                        vaccine = Vaccine.query.get(auto_schedule.item_id)
                        if vaccine:
                            # Find the appropriate dose number based on age
                            dose_ages = vaccine.get_dose_ages()
                            if isinstance(dose_ages, list) and age in dose_ages:
                                dose_number = dose_ages.index(age) + 1
                            else:
                                dose_number = 1
                                
                            schedule = VaccineSchedule(
                                vaccine_id=vaccine.id,
                                dose_number=dose_number,
                                scheduled_date=schedule_date,
                                notes=auto_schedule.notes or '',
                                completed=False
                            )
                            schedule.batches.append(batch)
                            db.session.add(schedule)
                    
                    elif auto_schedule.item_type == 'health_material':
                        material = HealthMaterial.query.get(auto_schedule.item_id)
                        if material:
                            schedule = HealthMaterialSchedule(
                                health_material_id=material.id,
                                scheduled_date=schedule_date,
                                notes=auto_schedule.notes or '',
                                completed=False
                            )
                            schedule.batches.append(batch)
                            db.session.add(schedule)
            except Exception as e:
                print(f"Error processing auto schedule {auto_schedule.id}: {str(e)}")
                continue
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error creating schedules for batch: {str(e)}")
        raise

# # Modify the add_batch route to include auto-scheduling
# @app.route('/batches/add', methods=['GET', 'POST'])
# @login_required
# def add_batch():
#     if request.method == 'POST':
#         try:
#             farm_id = request.form.get('farm_id')
#             manager_id = request.form.get('manager_id')
#             brand = request.form.get('brand')
#             total_birds = int(request.form.get('total_birds'))
#             extra_chicks = int(request.form.get('extra_chicks', 0))
#             created_at = datetime.strptime(request.form.get('created_at'), '%Y-%m-%dT%H:%M')
#             cost_per_chicken = float(request.form.get('cost_per_chicken'))

#             # Generate batch number
#             batch_number = generate_batch_number()
#             farm_batch_number = get_next_farm_batch_number(farm_id)

#             # Get shed distribution
#             shed_birds = []
#             farm = Farm.query.get(farm_id)
#             for i in range(farm.num_sheds):
#                 birds = int(request.form.get(f'shed_{i+1}_birds', 0))
#                 shed_birds.append(birds)

#             # Create new batch
#             batch = Batch(
#                 farm_id=farm_id,
#                 manager_id=manager_id if manager_id else None,
#                 batch_number=batch_number,
#                 farm_batch_number=farm_batch_number,
#                 brand=brand,
#                 total_birds=total_birds,
#                 extra_chicks=extra_chicks,
#                 available_birds=total_birds,
#                 shed_birds=json.dumps(shed_birds),
#                 cost_per_chicken=cost_per_chicken,
#                 created_at=created_at
#             )

#             db.session.add(batch)
#             db.session.flush()  # Get the batch ID without committing

#             # Get all vaccines and create schedules based on their dose ages
#             vaccines = Vaccine.query.all()
#             for vaccine in vaccines:
#                 dose_ages = vaccine.get_dose_ages()
#                 for dose_number, age_days in enumerate(dose_ages, 1):
#                     # Calculate schedule date based on batch creation date and age in days
#                     schedule_date = created_at.date() + timedelta(days=age_days)
                    
#                     # Create vaccine schedule
#                     schedule = VaccineSchedule(
#                         vaccine_id=vaccine.id,
#                         dose_number=dose_number,
#                         scheduled_date=schedule_date,
#                         notes=f"Automatically scheduled for {vaccine.name} dose {dose_number}"
#                     )
#                     schedule.batches.append(batch)
#                     db.session.add(schedule)

#             db.session.commit()
            
            
            
#             flash('Batch added successfully!', 'success')
#             return redirect(url_for('batches'))
#         except Exception as e:
#             db.session.rollback()
#             flash('Error adding batch: ' + str(e), 'error')
    
#     # GET request - show form
#     farms = Farm.query.all()
#     managers = User.query.filter(User.user_type.in_(['senior_manager', 'assistant_manager'])).all()
#     farm_sheds = {farm.id: {
#         'num_sheds': farm.num_sheds,
#         'shed_capacities': farm.get_shed_capacities(),
#         'shed_available': farm.get_shed_available_capacities(),
#         'shed_status': [{'is_partially_allocated': cap > avail} for cap, avail in zip(farm.get_shed_capacities(), farm.get_shed_available_capacities())]
#     } for farm in farms}
#     return render_template('add_batch.html', farms=farms, managers=managers, farm_sheds=farm_sheds)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/offline.html')
def offline():
    return render_template('offline.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')