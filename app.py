from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-segreta')

# Config DB PostgreSQL (Render.com imposta DATABASE_URL automaticamente)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///alcolemia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# === MODELLI ===
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

class Bar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    indirizzo = db.Column(db.String(200), nullable=False)

class Drink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    ingredienti = db.Column(db.Text, nullable=False)
    bar_id = db.Column(db.Integer, db.ForeignKey('bar.id'), nullable=False)
    bar = db.relationship('Bar', backref=db.backref('drinks', lazy=True))

# === FUNZIONI ===
def calcola_tasso_alcolemico(peso, genere, volume, gradazione, stomaco):
    grammi_alcol = volume * (gradazione / 100) * 0.8
    r = 0.68 if genere == 'uomo' else 0.55
    assorbimento = 0.9 if stomaco == 'vuoto' else 0.7
    bac = (grammi_alcol * assorbimento) / (peso * r)
    return round(bac, 3)

# === ROTTE ===
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Utente già registrato!')
            return redirect(url_for('register'))

        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Registrazione avvenuta!')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            session['user'] = user.email
            return redirect(url_for('seleziona_bar'))
        else:
            flash('Credenziali errate')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout effettuato')
    return redirect(url_for('home'))

@app.route('/seleziona_bar', methods=['GET', 'POST'])
def seleziona_bar():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

    bar_list = Bar.query.all()
    if request.method == 'POST':
        session['bar_id'] = request.form['bar']
        return redirect(url_for('simula'))

    return render_template('seleziona_bar.html', bar_list=bar_list)

@app.route('/simula', methods=['GET', 'POST'])
def simula():
    if 'user' not in session or 'bar_id' not in session:
        return redirect(url_for('login'))

    bar = Bar.query.get(session['bar_id'])
    drinks = bar.drinks
    tasso = None
    drink_selezionato = None

    if request.method == 'POST':
        drink_id = request.form['drink']
        genere = request.form['genere']
        peso = float(request.form['peso'])
        stomaco = request.form['stomaco']

        drink_selezionato = Drink.query.get(drink_id)
        volume = 200
        gradazione = 12

        tasso = calcola_tasso_alcolemico(peso, genere, volume, gradazione, stomaco)

    return render_template('simula.html', bar=bar, drinks=drinks, tasso=tasso, drink_selezionato=drink_selezionato)

# === SETUP DB ===
with app.app_context():
    db.create_all()

    if not Bar.query.first():
        bar1 = Bar(nome='Bar Centrale', indirizzo='Via Roma 1, Torino')
        bar2 = Bar(nome='Bar del Porto', indirizzo='Lungomare 10, Genova')
        db.session.add_all([bar1, bar2])
        db.session.commit()

    if not Drink.query.first():
        mojito = Drink(nome='Mojito', ingredienti='Rum, menta, lime, zucchero, soda', bar_id=bar1.id)
        spritz = Drink(nome='Spritz', ingredienti='Aperol, prosecco, soda', bar_id=bar1.id)
        db.session.add_all([mojito, spritz])
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)