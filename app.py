from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

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
    password_hash = db.Column(db.String(300), nullable=False)

class Consumazione(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    drink_id = db.Column(db.Integer, db.ForeignKey('drink.id'), nullable=False)
    data = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('consumazioni', lazy=True))
    drink = db.relationship('Drink', backref=db.backref('consumazioni', lazy=True))

class Bar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    indirizzo = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # es. "Bar", "Pub", "Disco"
    citta = db.Column(db.String(100), nullable=False)

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
    bars = Bar.query.all()
    return render_template('home.html', bars=bars)

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

    if request.method == 'POST':
        if 'citta' in request.form:
            # Prima selezione: città
            citta = request.form.get('citta')
            if citta:
                bar_list = Bar.query.filter_by(citta=citta).all()
                return render_template('seleziona_bar.html', 
                                    citta_selezionata=citta,
                                    bar_list=bar_list,
                                    citta_list=db.session.query(Bar.citta.distinct()).all())
            else:
                flash('Seleziona una città')
                return redirect(url_for('seleziona_bar'))
        elif 'bar' in request.form:
            # Seconda selezione: bar
            session['bar_id'] = request.form['bar']
            return redirect(url_for('simula'))

    # Get unique cities for dropdown
    citta_list = db.session.query(Bar.citta.distinct()).all()
    return render_template('seleziona_bar.html', 
                         citta_list=[c[0] for c in citta_list])

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

        # Registra la consumazione
        user = User.query.filter_by(email=session['user']).first()
        consumazione = Consumazione(user_id=user.id, drink_id=drink_id)
        db.session.add(consumazione)
        db.session.commit()

    return render_template('simula.html', bar=bar, drinks=drinks, tasso=tasso, drink_selezionato=drink_selezionato)

@app.route('/gamification')
def gamification():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

    if 'bar_id' not in session:
        flash('Seleziona prima un bar')
        return redirect(url_for('seleziona_bar'))

    user = User.query.filter_by(email=session['user']).first()
    bar = Bar.query.get(session['bar_id'])

    # Ottieni le consumazioni dell'utente per questo bar
    user_drinks = db.session.query(
        Drink.nome,
        db.func.count(Consumazione.id).label('conteggio')
    ).join(Consumazione).filter(
        Consumazione.user_id == user.id,
        Drink.bar_id == bar.id
    ).group_by(Drink.nome).all()

    # Ottieni la classifica generale per questo bar
    classifica = db.session.query(
        User.email.label('nome'),
        db.func.count(Consumazione.id).label('conteggio')
    ).join(Consumazione).join(Drink).filter(
        Drink.bar_id == bar.id
    ).group_by(User.email).order_by(db.desc('conteggio')).limit(10).all()

    return render_template('gamification.html',
                         bar=bar,
                         user_drinks=user_drinks,
                         classifica=classifica)

# === SETUP DB ===
with app.app_context():
    db.create_all()
    db.drop_all()
    db.create_all()

    # Crea utente admin
    if not User.query.first():
        admin = User(email='admin', password_hash=generate_password_hash('admin'))
        db.session.add(admin)
        db.session.commit()

    # Crea bar di prova
    if not Bar.query.first():
        bars = [
            Bar(nome='Bar Centrale', indirizzo='Via Roma 1, Torino', tipo='Bar', citta='Torino'),
            Bar(nome='Bar del Porto', indirizzo='Lungomare 10, Genova', tipo='Bar', citta='Genova'),
            Bar(nome='Pub Irlandese', indirizzo='Via Milano 5, Torino', tipo='Pub', citta='Torino'),
            Bar(nome='Disco Club', indirizzo='Via Napoli 20, Genova', tipo='Disco', citta='Genova')
        ]
        db.session.add_all(bars)
        db.session.commit()

    # Crea drink di prova
    if not Drink.query.first():
        drinks = [
            Drink(nome='Mojito', ingredienti='Rum, menta, lime, zucchero, soda', bar_id=bars[0].id),
            Drink(nome='Spritz', ingredienti='Aperol, prosecco, soda', bar_id=bars[0].id),
            Drink(nome='Negroni', ingredienti='Gin, Campari, Vermouth', bar_id=bars[0].id),
            Drink(nome='Gin Tonic', ingredienti='Gin, acqua tonica, lime', bar_id=bars[1].id),
            Drink(nome='Moscow Mule', ingredienti='Vodka, ginger beer, lime', bar_id=bars[1].id),
            Drink(nome='Irish Coffee', ingredienti='Whiskey, caffè, panna', bar_id=bars[2].id),
            Drink(nome='Long Island', ingredienti='Vodka, rum, gin, tequila, triple sec', bar_id=bars[3].id)
        ]
        db.session.add_all(drinks)
        db.session.commit()

    # Crea consumazioni di prova
    if not Consumazione.query.first():
        from datetime import datetime, timedelta
        import random

        # Genera consumazioni per gli ultimi 30 giorni
        admin = User.query.filter_by(email='admin').first()
        for _ in range(20):  # 20 consumazioni per l'admin
            drink = random.choice(drinks)
            data = datetime.utcnow() - timedelta(days=random.randint(0, 30))
            consumazione = Consumazione(
                user_id=admin.id,
                drink_id=drink.id,
                data=data
            )
            db.session.add(consumazione)
        
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)