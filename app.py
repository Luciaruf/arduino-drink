from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
import requests
import time

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-segreta')

# Global variables for Arduino data
dato_da_arduino = None
timestamp_dato = None

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
    response = requests.get(url, headers=get_airtable_headers())
    drinks = response.json()['records']
    
    if bar_id:
        filtered_drinks = [d for d in drinks if bar_id in d['fields'].get('Bar', [])]
        return filtered_drinks
    return drinks

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

def create_consumazione(user_id, drink_id, bar_id, tasso):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    data = {
        'records': [{
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id],
                'Tasso': tasso,
                'Esito': 'Positivo' if tasso < 0.5 else 'Negativo'
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    response_data = response.json()
    
    if response.status_code != 200:
        print(f"Errore Airtable: {response.status_code}")
        print(f"Risposta: {response_data}")
        return None
        
    if 'records' not in response_data:
        print(f"Risposta Airtable non valida: {response_data}")
        return None
        
    return response_data['records'][0]

def get_user_consumazioni(user_id=None, bar_id=None):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    if user_id and bar_id:
        formula = f"AND(ARRAYJOIN({{User}}, ',') = '{user_id}', {{Bar}}='{bar_id}')"
    elif user_id:
        formula = f"ARRAYJOIN({{User}}, ',') = '{user_id}'"
    elif bar_id:
        formula = f"{{Bar}}='{bar_id}'"
    else:
        formula = ""
    params = {}
    if formula:
        params['filterByFormula'] = formula
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    return response.json().get('records', [])

def get_bar_by_id(bar_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Bar/{bar_id}'
    response = requests.get(url, headers=get_airtable_headers())
    return response.json()

def get_user_by_id(user_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users/{user_id}'
    response = requests.get(url, headers=get_airtable_headers())
    if response.status_code == 200:
        return response.json()
    return None

# === FUNZIONI ===
def calcola_tasso_alcolemico(peso, genere, volume, gradazione, stomaco):
    grammi_alcol = volume * (gradazione / 100) * 0.8
    r = 0.68 if genere == 'uomo' else 0.55
    assorbimento = 0.9 if stomaco == 'vuoto' else 0.7
    bac = (grammi_alcol * assorbimento) / (peso * r)
    return round(bac, 3)

# === CONTEXT PROCESSORS ===
@app.context_processor
def utility_processor():
    return {
        'get_bar_by_id': get_bar_by_id
    }

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
            return redirect(url_for('dashboard'))
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

    # Get all bars for the city dropdown
    bars = get_bars()
    citta_list = list(set(bar['fields'].get('Città', '') for bar in bars if bar['fields']))

    # Check if bar is selected from URL
    bar_id = request.args.get('bar')
    if bar_id:
        session['bar_id'] = bar_id
        return redirect(url_for('simula'))

    if request.method == 'POST':
        if 'citta' in request.form:
            # Prima selezione: città
            citta = request.form.get('citta')
            if citta:
                bar_list = [bar for bar in bars if bar['fields'].get('Città') == citta]
                return render_template('seleziona_bar.html', 
                                    citta_selezionata=citta,
                                    bar_list=bar_list,
                                    citta_list=citta_list)

    return render_template('seleziona_bar.html', 
                         citta_list=citta_list,
                         bar_list=[],
                         citta_selezionata=None)

@app.route('/simula', methods=['GET', 'POST'])
def simula():
    if 'user' not in session or 'bar_id' not in session:
        return redirect(url_for('login'))

    bar_id = session['bar_id']
    drinks = get_drinks(bar_id)
    tasso = None
    drink_selezionato = None
    esito = None

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
            esito = 'Positivo' if tasso < 0.5 else 'Negativo'

            # Registra la consumazione con l'esito
            try:
                create_consumazione(session['user'], drink_id, bar_id, tasso)
            except Exception as e:
                print(f"Errore durante la creazione della consumazione: {str(e)}")
                flash('Errore durante il salvataggio della simulazione. Il risultato è stato calcolato ma non salvato.')

    bar = next((b for b in get_bars() if b['id'] == bar_id), None)
    return render_template('simula.html', 
                         bar=bar,
                         drinks=drinks,
                         tasso=tasso,
                         drink_selezionato=drink_selezionato,
                         esito=esito)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

    user_id = session['user']
    bar_id = session.get('bar_id')

    if not bar_id:
        # Statistiche globali
        consumazioni = get_user_consumazioni(user_id)
        all_consumazioni = get_user_consumazioni(None)
        drinks = get_drinks()
        bars = get_bars()
        print("DEBUG - consumazioni trovate:", consumazioni)
        print("DEBUG - all_consumazioni:", all_consumazioni)
        print("DEBUG - drinks:", drinks)
        print("DEBUG - bars:", bars)

        # Raggruppa per bar e drink
        user_drinks = {}
        for cons in consumazioni:
            if 'Bar' not in cons['fields'] or not cons['fields']['Bar']:
                continue
            if 'Drink' not in cons['fields'] or not cons['fields']['Drink']:
                continue
            bar = next((b for b in bars if b['id'] == cons['fields']['Bar'][0]), None)
            drink = next((d for d in drinks if d['id'] == cons['fields']['Drink'][0]), None)
            bar_name = bar['fields']['Name'] if bar else 'Bar Sconosciuto'
            drink_name = drink['fields']['Name'] if drink else 'Drink Sconosciuto'
            key = f"{bar_name} - {drink_name}"
            user_drinks[key] = user_drinks.get(key, 0) + 1
        user_drinks = [
            {'nome': k, 'conteggio': v}
            for k, v in user_drinks.items()
        ]

        # Classifica generale su tutti i bar
        user_counts = {}
        for cons in all_consumazioni:
            if 'User' not in cons['fields'] or not cons['fields']['User']:
                continue
            uid = cons['fields']['User'][0]
            user = get_user_by_id(uid)
            user_email = user['fields']['Email'] if user and 'fields' in user and 'Email' in user['fields'] else 'Utente Sconosciuto'
            user_counts[user_email] = user_counts.get(user_email, 0) + 1
        classifica = [
            {'nome': email, 'conteggio': count}
            for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ][:10]

        return render_template('dashboard.html',
                             bar=None,
                             user_drinks=user_drinks,
                             classifica=classifica)

    # Statistiche per bar selezionato (come ora)
    drinks = get_drinks(bar_id)
    consumazioni = get_user_consumazioni(user_id, bar_id)
    drink_counts = {}
    for cons in consumazioni:
        if 'Drink' not in cons['fields'] or not cons['fields']['Drink']:
            continue
        drink_id = cons['fields']['Drink'][0]
        drink_counts[drink_id] = drink_counts.get(drink_id, 0) + 1
    user_drinks = [
        {
            'nome': next((d['fields']['Name'] for d in drinks if d['id'] == drink_id), 'Drink Sconosciuto'),
            'conteggio': count
        }
        for drink_id, count in drink_counts.items()
    ]
    all_consumazioni = get_user_consumazioni(None, bar_id)
    user_counts = {}
    for cons in all_consumazioni:
        if 'User' not in cons['fields'] or not cons['fields']['User']:
            continue
        uid = cons['fields']['User'][0]
        user = get_user_by_id(uid)
        user_email = user['fields']['Email'] if user and 'fields' in user and 'Email' in user['fields'] else 'Utente Sconosciuto'
        user_counts[user_email] = user_counts.get(user_email, 0) + 1
    classifica = [
        {'nome': email, 'conteggio': count}
        for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    ][:10]
    return render_template('dashboard.html',
                         bar=get_bar_by_id(bar_id),
                         user_drinks=user_drinks,
                         classifica=classifica)

@app.route('/invia_dato', methods=['POST'])
def invia_dato():
    global dato_da_arduino, timestamp_dato
    
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400
    
    data = request.get_json()
    
    if 'peso' not in data:
        return jsonify({"error": "Missing 'peso' field"}), 400
    
    try:
        peso = float(data['peso'])
        dato_da_arduino = peso
        timestamp_dato = time.time()
        return jsonify({"status": "ok", "ricevuto": peso})
    except ValueError:
        return jsonify({"error": "Invalid 'peso' value"}), 400

@app.route('/test-arduino')
def test_arduino():
    global dato_da_arduino, timestamp_dato
    
    if dato_da_arduino is None:
        return render_template('test_arduino.html', 
                             dato=None, 
                             tempo_trascorso=None)
    
    tempo_trascorso = time.time() - timestamp_dato
    return render_template('test_arduino.html', 
                         dato=dato_da_arduino, 
                         tempo_trascorso=round(tempo_trascorso, 2))

if __name__ == '__main__':
    app.run(debug=True)