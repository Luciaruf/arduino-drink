from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-segreta')

# === Airtable API ===
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY', 'patMvTkVAFXuBTZK0.73601aeaf05c4ffb8fc1109ffc1a7aa3d8e8bf740f094bb6f980c23aecbefeb5')
BASE_ID = 'appQZSlkfRWqALhaG'

def get_airtable_headers():
    return {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }

def get_bars():
    url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
    response = requests.get(url, headers=get_airtable_headers())
    return response.json()['records']

def get_drinks(bar_id=None):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
    params = {}
    if bar_id:
        params['filterByFormula'] = f"{{Bar}}='{bar_id}'"
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    return response.json()['records']

def get_user_by_email(email):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    params = {
        'filterByFormula': f"{{Email}}='{email}'"
    }
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    records = response.json().get('records', [])
    return records[0] if records else None

def create_user(email, password_hash):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    data = {
        'records': [{
            'fields': {
                'Email': email,
                'Password': password_hash
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    return response.json()['records'][0]

def create_consumazione(user_id, drink_id, bar_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    data = {
        'records': [{
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id]
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    return response.json()['records'][0]

def get_user_consumazioni(user_id, bar_id=None):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    formula = f"AND({{User}}='{user_id}'"
    if bar_id:
        formula += f", {{Bar}}='{bar_id}'"
    formula += ")"
    params = {'filterByFormula': formula}
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    return response.json().get('records', [])

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
    bars = get_bars()
    return render_template('home.html', bars=bars)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if get_user_by_email(email):
            flash('Utente già registrato!')
            return redirect(url_for('register'))

        create_user(email, generate_password_hash(password))
        flash('Registrazione avvenuta!')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = get_user_by_email(email)

        if user and check_password_hash(user['fields']['Password'], password):
            session['user'] = user['id']
            session['user_email'] = email
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
                bars = get_bars()
                bar_list = [bar for bar in bars if bar['fields'].get('Città') == citta]
                return render_template('seleziona_bar.html', 
                                    citta_selezionata=citta,
                                    bar_list=bar_list,
                                    citta_list=list(set(bar['fields'].get('Città', '') for bar in bars)))
            else:
                flash('Seleziona una città')
                return redirect(url_for('seleziona_bar'))
        elif 'bar' in request.form:
            # Seconda selezione: bar
            session['bar_id'] = request.form['bar']
            return redirect(url_for('simula'))

    # Get unique cities for dropdown
    bars = get_bars()
    citta_list = list(set(bar['fields'].get('Città', '') for bar in bars))
    return render_template('seleziona_bar.html', citta_list=citta_list)

@app.route('/simula', methods=['GET', 'POST'])
def simula():
    if 'user' not in session or 'bar_id' not in session:
        return redirect(url_for('login'))

    bar_id = session['bar_id']
    drinks = get_drinks(bar_id)
    tasso = None
    drink_selezionato = None

    if request.method == 'POST':
        drink_id = request.form['drink']
        genere = request.form['genere']
        peso = float(request.form['peso'])
        stomaco = request.form['stomaco']

        # Trova il drink selezionato
        drink_selezionato = next((d for d in drinks if d['id'] == drink_id), None)
        if drink_selezionato:
            volume = drink_selezionato['fields'].get('Volume (ml)', 200)
            gradazione = drink_selezionato['fields'].get('Gradazione', 0.12)

            tasso = calcola_tasso_alcolemico(peso, genere, volume, gradazione * 100, stomaco)

            # Registra la consumazione
            create_consumazione(session['user'], drink_id, bar_id)

    return render_template('simula.html', 
                         bar=next((b for b in get_bars() if b['id'] == bar_id), None),
                         drinks=drinks,
                         tasso=tasso,
                         drink_selezionato=drink_selezionato)

@app.route('/gamification')
def gamification():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

    if 'bar_id' not in session:
        flash('Seleziona prima un bar')
        return redirect(url_for('seleziona_bar'))

    user_id = session['user']
    bar_id = session['bar_id']
    drinks = get_drinks(bar_id)

    # Ottieni le consumazioni dell'utente per questo bar
    consumazioni = get_user_consumazioni(user_id, bar_id)
    
    # Raggruppa le consumazioni per drink
    drink_counts = {}
    for cons in consumazioni:
        drink_id = cons['fields']['Drink'][0]
        drink_counts[drink_id] = drink_counts.get(drink_id, 0) + 1

    # Mappa i drink_id ai nomi dei drink
    user_drinks = [
        {
            'nome': next((d['fields']['Name'] for d in drinks if d['id'] == drink_id), 'Drink Sconosciuto'),
            'conteggio': count
        }
        for drink_id, count in drink_counts.items()
    ]

    # Ottieni tutte le consumazioni per questo bar
    all_consumazioni = get_user_consumazioni(None, bar_id)
    
    # Raggruppa per utente
    user_counts = {}
    for cons in all_consumazioni:
        user_id = cons['fields']['User'][0]
        user_email = get_user_by_email(user_id)['fields']['Email']
        user_counts[user_email] = user_counts.get(user_email, 0) + 1

    # Crea la classifica
    classifica = [
        {'nome': email, 'conteggio': count}
        for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    ][:10]

    return render_template('gamification.html',
                         bar=next((b for b in get_bars() if b['id'] == bar_id), None),
                         user_drinks=user_drinks,
                         classifica=classifica)

if __name__ == '__main__':
    app.run(debug=True)