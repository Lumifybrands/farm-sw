from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import timedelta

# Generate a secure secret key
def generate_secret_key():
    return os.urandom(24).hex()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', generate_secret_key())  # More secure secret key handling
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)  # Set session lifetime for remember me

# Session configuration
if app.debug:
    # Development settings
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['REMEMBER_COOKIE_SECURE'] = False
else:
    # Production settings
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_SECURE'] = True

app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config.update(
    SESSION_COOKIE_NAME='bismi_session',  # Custom session cookie name
    REMEMBER_COOKIE_DURATION=timedelta(days=31),  # Remember me duration
    REMEMBER_COOKIE_HTTPONLY=True
)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), nullable=False, default='user')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_db():
    with app.app_context():
        db.create_all()
        # Create admin user if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', user_type='admin')
            admin.set_password('admin123')  # Change this password in production
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    if request.is_json:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        remember = data.get('remember', False)
    else:
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
    
    user = User.query.filter_by(username=username).first()
    
    if user and user.check_password(password):
        if remember:
            # Set session as permanent for remembered users
            session.permanent = True
        login_user(user, remember=remember)
        return jsonify({
            "success": True,
            "user_type": user.user_type
        }) if request.is_json else redirect(url_for('dashboard'))
    return jsonify({"success": False}) if request.is_json else redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/overview')
@login_required
def get_overview():
    # This will be connected to a database in future iterations
    # Currently returning dummy data
    return jsonify({
        "success": True,
        "totalBirds": 1000,
        "todayEggs": 850,
        "todaySales": 5000,
        "feedStock": 500
    })

@app.route('/api/inventory')
@login_required
def get_inventory():
    return jsonify({"success": True, "data": []})

@app.route('/api/sales')
@login_required
def get_sales():
    return jsonify({"success": True, "data": []})

@app.route('/api/reports')
@login_required
def get_reports():
    return jsonify({"success": True, "data": []})

@app.route('/api/users')
@login_required
def get_users():
    if current_user.user_type != 'admin':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    users = User.query.all()
    return jsonify({
        "success": True,
        "data": [{"id": user.id, "username": user.username, "type": user.user_type} 
                 for user in users]
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0')