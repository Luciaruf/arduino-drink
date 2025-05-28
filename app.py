from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import hashlib, os
from datetime import datetime, timedelta
import requests
import time
from algoritmo import (
    calcola_tasso_alcolemico_widmark, 
    interpreta_tasso_alcolemico, 
    calcola_bac_cumulativo,
    calcola_alcol_metabolizzato
)
import pytz  # Aggiungiamo pytz per gestire i fusi orari
from functools import wraps
import logging

# Configurazione del logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definiamo il fuso orario italiano
TIMEZONE = pytz.timezone('Europe/Rome')

app = Flask(__name__)

# Configurazione della sessione
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'super-segreta'),
    SESSION_COOKIE_SECURE=True,  # Cookie solo su HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Previene accesso JavaScript
    SESSION_COOKIE_SAMESITE='Lax',  # Protezione CSRF
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),  # Durata massima sessione
    SESSION_REFRESH_EACH_REQUEST=True  # Rinnovo cookie ad ogni richiesta
)

class SessionManager:
    """Classe per gestire in modo centralizzato le sessioni"""
    
    @staticmethod
    def init_session(user_id, user_email):
        """Inizializza una nuova sessione per l'utente"""
        session.clear()  # Pulisce eventuali dati residui
        session.permanent = True  # Rende la sessione permanente
        session['user'] = user_id
        session['user_email'] = user_email
        session['login_time'] = datetime.now(TIMEZONE).isoformat()
        session['last_activity'] = datetime.now(TIMEZONE).isoformat()
    
    @staticmethod
    def update_activity():
        """Aggiorna il timestamp dell'ultima attività"""
        session['last_activity'] = datetime.now(TIMEZONE).isoformat()
    
    @staticmethod
    def is_session_valid():
        """Verifica se la sessione è valida"""
        if 'user' not in session or 'last_activity' not in session:
            return False
            
        last_activity = datetime.fromisoformat(session['last_activity'])
        now = datetime.now(TIMEZONE)
        
        # Sessione scade dopo 24 ore di inattività
        return (now - last_activity) < timedelta(hours=24)
    
    @staticmethod
    def clear_session():
        """Pulisce la sessione"""
        session.clear()
    
    @staticmethod
    def get_user_id():
        """Ottiene l'ID utente dalla sessione"""
        return session.get('user')
    
    @staticmethod
    def get_user_email():
        """Ottiene l'email utente dalla sessione"""
        return session.get('user_email')
    
    @staticmethod
    def set_bac_data(bac_value, timestamp):
        """Salva i dati del BAC nella sessione"""
        session['bac_cumulativo_sessione'] = bac_value
        session['ultima_ora_bac_sessione'] = timestamp
    
    @staticmethod
    def get_bac_data():
        """Ottiene i dati del BAC dalla sessione"""
        return {
            'bac': session.get('bac_cumulativo_sessione', 0.0),
            'timestamp': session.get('ultima_ora_bac_sessione')
        }
    
    @staticmethod
    def set_active_consumption(consumption_id):
        """Salva l'ID della consumazione attiva"""
        session['active_consumazione_id'] = consumption_id
    
    @staticmethod
    def get_active_consumption():
        """Ottiene l'ID della consumazione attiva"""
        return session.get('active_consumazione_id')
    
    @staticmethod
    def set_consumption_data(data):
        """Salva i dati della consumazione attiva nella sessione"""
        session['consumption_data'] = data
    
    @staticmethod
    def get_consumption_data():
        """Ottiene i dati della consumazione attiva dalla sessione"""
        return session.get('consumption_data', {})
    
    @staticmethod
    def get_stomaco_state():
        """Ottiene lo stato dello stomaco"""
        return session.get('stomaco_state', 'pieno')  # Default a 'pieno'
        
    @staticmethod
    def set_stomaco_state(state):
        """Imposta lo stato dello stomaco"""
        session['stomaco_state'] = state
        
    @staticmethod
    def set_bar_id(bar_id):
        """Salva l'ID del bar selezionato"""
        session['bar_id'] = bar_id
        
    @staticmethod
    def get_bar_id():
        """Ottiene l'ID del bar selezionato"""
        return session.get('bar_id')
        
    @staticmethod
    def set_selected_drink_id(drink_id):
        """Salva l'ID del drink selezionato"""
        session['selected_drink_id'] = drink_id
        
    @staticmethod
    def get_selected_drink_id():
        """Ottiene l'ID del drink selezionato"""
        return session.get('selected_drink_id')
        
    @staticmethod
    def get_sorsi_from_session(consumazione_id):
        """Ottiene i sorsi di una consumazione dalla sessione"""
        session_key = f'sorsi_{consumazione_id}'
        return session.get(session_key, [])
        
    @staticmethod
    def save_sorso_to_session(consumazione_id, sorso):
        """Salva un sorso nella sessione"""
        session_key = f'sorsi_{consumazione_id}'
        sorsi = session.get(session_key, [])
        sorsi.append(sorso)
        session[session_key] = sorsi
        return len(sorsi)

def login_required(f):
    """Decoratore per proteggere le route che richiedono autenticazione"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not SessionManager.is_session_valid():
            SessionManager.clear_session()
            flash('La tua sessione è scaduta. Effettua nuovamente il login.', 'warning')
            return redirect(url_for('login'))
        
        SessionManager.update_activity()
        return f(*args, **kwargs)
    return decorated_function

# Sistema semplice per l'hashing delle password compatibile con tutti i server
def hash_password(password):
    """Genera un hash della password usando PBKDF2 e SHA-256"""
    # Genera un salt casuale di 16 byte
    salt = os.urandom(16)
    # Calcola l'hash usando PBKDF2 con SHA-256
    hash_bytes = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    # Converti salt e hash in formato esadecimale e concatenali
    return salt.hex() + hash_bytes.hex()

def verify_password(stored_hash, provided_password):
    """Verifica un hash creato con hash_password"""
    try:
        # Estrai il salt (primi 32 caratteri = 16 byte in hex)
        salt_hex = stored_hash[:32]
        salt = bytes.fromhex(salt_hex)
        
        # Estrai l'hash memorizzato (resto della stringa)
        stored_digest = stored_hash[32:]
        
        # Calcola l'hash della password fornita usando lo stesso salt
        hash_bytes = hashlib.pbkdf2_hmac('sha256', provided_password.encode(), salt, 100000)
        calculated_digest = hash_bytes.hex()
        
        # Log per debug
        logger.info(f"[VERIFY] Salt estratto: {salt_hex}")
        logger.info(f"[VERIFY] Hash memorizzato: {stored_digest}")
        logger.info(f"[VERIFY] Hash calcolato: {calculated_digest}")
        
        # Confronta i due hash
        return calculated_digest == stored_digest
    except Exception as e:
        logger.error(f"[VERIFY] Errore nella verifica: {e}")
        return False
        
import os
from datetime import datetime, timedelta
import requests
import time
from algoritmo import (
    calcola_tasso_alcolemico_widmark, 
    interpreta_tasso_alcolemico, 
    calcola_bac_cumulativo,
    calcola_alcol_metabolizzato
)
import pytz  # Aggiungiamo pytz per gestire i fusi orari

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-segreta')

# Definiamo il fuso orario italiano
TIMEZONE = pytz.timezone('Europe/Rome')

# Global variables for Arduino data
dato_da_arduino = None
timestamp_dato = None

# Endpoint semplificato per ricevere dati di peso da Arduino/script esterni
# Manteniamo il vecchio endpoint GET per retrocompatibilità
@app.route('/arduino_peso/<float:peso>', methods=['GET'])
def arduino_peso_direct_get(peso):
    """Endpoint che aggiorna direttamente le variabili globali per il peso (metodo GET)"""
    global dato_da_arduino, timestamp_dato
    
    # Aggiorna le variabili globali
    dato_da_arduino = peso
    timestamp_dato = time.time()
    
    print(f"[ARDUINO-GET] Peso aggiornato a {peso}g")
    
    # Restituisci una conferma
    return jsonify({
        "status": "ok",
        "peso": peso
    })

# Endpoint POST per ricevere dati di peso (più adatto per invio dati)
@app.route('/arduino_peso', methods=['POST'])
def arduino_peso_direct_post():
    """Endpoint che riceve il peso via POST e aggiorna le variabili globali"""
    global dato_da_arduino, timestamp_dato
    
    try:
        # Accetta sia JSON che form data
        if request.is_json:
            data = request.get_json()
            peso = float(data.get('peso', 0))
        else:
            peso = float(request.form.get('peso', 0))
        
        # Aggiorna le variabili globali
        dato_da_arduino = peso
        timestamp_dato = time.time()
        
        print(f"[ARDUINO-POST] Peso aggiornato a {peso}g")
        
        # Restituisci una conferma
        return jsonify({
            "status": "ok",
            "peso": peso
        })
    except Exception as e:
        print(f"[ARDUINO-ERROR] {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# === Airtable API ===
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY', 'patMvTkVAFXuBTZK0.73601aeaf05c4ffb8fc1109ffc1a7aa3d8e8bf740f094bb6f980c23aecbefeb5')
BASE_ID = 'appQZSlkfRWqALhaG'

def get_airtable_headers():
    return {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }

def get_bars(city=None):
    logger.info(f"Richiesta get_bars con parametro city: {city}")
    url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
    response = requests.get(url, headers=get_airtable_headers())
    
    # Log della risposta completa per debug
    logger.info(f"Risposta completa da Airtable: {response.text[:200]}...")
    
    bars = response.json()['records']
    logger.info(f"Recuperati {len(bars)} bar totali da Airtable")
    
    # Log dettagliato della struttura dati dei bar
    if len(bars) > 0:
        logger.info(f"STRUTTURA DEI DATI - Esempio di bar: {bars[0]}")
        logger.info(f"CAMPI DISPONIBILI: {list(bars[0]['fields'].keys())}")
    
    if city:
        # Filtra i bar per città
        logger.info(f"Filtraggio bar per città: {city}")
        # Log delle città disponibili per debug
        available_cities = set(bar['fields'].get('Città', '') for bar in bars if 'Città' in bar['fields'])
        logger.info(f"Città disponibili nei dati: {available_cities}")
        
        # Log dei primi 5 bar e delle loro città per debug
        for i, bar in enumerate(bars[:5]):
            logger.info(f"Bar {i+1}: ID={bar['id']}, Città={bar['fields'].get('Città', 'N/A')}")
            logger.info(f"TUTTI I CAMPI del Bar {i+1}: {bar['fields']}")
        
        
        # Rendi il filtraggio insensibile alle maiuscole/minuscole
        city_lower = city.lower() if city else ''
        filtered_bars = []
        for bar in bars:
            bar_city = bar['fields'].get('Città', '')
            if bar_city and bar_city.lower() == city_lower:
                filtered_bars.append(bar)
                logger.info(f"Match trovato: Bar '{bar['fields'].get('Nome', 'N/A')}' in città '{bar_city}'")
        
        logger.info(f"Bar filtrati per {city}: {len(filtered_bars)}")
        return filtered_bars
    return bars

def get_cities():
    """Ottiene l'elenco delle città dai bar disponibili"""
    bars = get_bars()
    # Estrai tutte le città uniche
    cities = set(bar['fields'].get('Città', '') for bar in bars if 'Città' in bar['fields'])
    # Rimuovi città vuote
    cities = [city for city in cities if city]
    # Ordina le città
    return sorted(cities)

def get_drinks(bar_id=None):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
    response = requests.get(url, headers=get_airtable_headers())
    drinks = response.json()['records']
    
    # Processa i drink per assicurarsi che il campo Speciale sia sempre presente
    for drink in drinks:
        if 'fields' in drink:
            # Se il campo Speciale non esiste, impostalo a False
            if 'Speciale' not in drink['fields']:
                drink['fields']['Speciale'] = False
    
    if bar_id:
        filtered_drinks = [d for d in drinks if bar_id in d['fields'].get('Bar', [])]
        return filtered_drinks
    return drinks

def get_drink_by_id(drink_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks/{drink_id}'
    response = requests.get(url, headers=get_airtable_headers())
    if response.status_code == 200:
        return response.json()
    return None

# Cache per gli utenti, con chiave = email
user_cache = {}

def get_user_by_email(email):
    """Recupera un utente dall'API di Airtable o dalla cache"""
    # Controlla se l'utente è già nella cache
    if email in user_cache:
        print(f"DEBUG: Utente {email} recuperato dalla cache")
        return user_cache[email]
    
    # Altrimenti fa la richiesta all'API
    print(f"DEBUG: Utente {email} richiesto ad Airtable")
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    params = {
        'filterByFormula': f"{{Email}}='{email}'"
    }
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    records = response.json().get('records', [])
    
    user = records[0] if records else None
    
    # Salva nella cache solo se l'utente esiste
    if user:
        user_cache[email] = user
    
    return user

def create_user(email, password_hash, peso_kg, genere):
    logger.info(f"[CREATE_USER] Lunghezza hash password da salvare: {len(password_hash)} per email: {email}")
    logger.info(f"[CREATE_USER] Hash password da salvare: {password_hash}")
    if len(password_hash) < 100:
        logger.error(f"[CREATE_USER] ATTENZIONE: hash password troppo corto per email: {email} - Hash: {password_hash}")
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    data = {
        'records': [{
            'fields': {
                'Email': email,
                'Password': password_hash,
                'Peso': peso_kg,
                'Genere': genere.capitalize()
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    response_json = response.json()
    print(f"AIRTABLE CREATE USER STATUS CODE: {response.status_code}")
    print(f"AIRTABLE CREATE USER RESPONSE: {response_json}")
    
    if response.status_code != 200 or 'records' not in response_json:
        # Gestione più robusta dell'errore
        error_message = response_json.get('error', {}).get('message', 'Errore sconosciuto da Airtable')
        detailed_error = response_json.get('error', {}).get('type', '')
        print(f"Errore durante la creazione dell'utente in Airtable: {error_message} (Tipo: {detailed_error})")
        # Potresti voler sollevare un'eccezione personalizzata o restituire None/un messaggio d'errore specifico
        # Per ora, per coerenza con il traceback, se manca 'records' continuerà a dare KeyError,
        # ma avremo il log dell'errore.
        # Se vogliamo evitare il KeyError e propagare un errore gestito:
        # flash(f'Errore Airtable: {error_message}') # Se appropriato per il flusso utente
        # return None # O sollevare un'eccezione
        pass # Lascia che il KeyError avvenga dopo il log, per ora, per mantenere il comportamento del traceback originale

    return response_json['records'][0]

def create_consumazione(user_id, drink_id, bar_id, peso_cocktail_g, stomaco_pieno_bool, timestamp_consumazione=None):
    if timestamp_consumazione is None:
        timestamp_consumazione = datetime.now()

    # 1. Recupera dati utente (peso, genere)
    user_data = get_user_by_id(user_id)
    if not user_data or 'fields' not in user_data:
        print(f"Errore: Utente {user_id} non trovato o dati incompleti.")
        return None
    
    user_fields = user_data['fields']
    peso_utente_kg = user_fields.get('Peso')
    genere_utente = user_fields.get('Genere')

    if peso_utente_kg is None or genere_utente is None:
        print(f"Errore: Peso o Genere mancanti per l'utente {user_id}.")
        return None

    # 2. Recupera dati drink (gradazione, alcolico)
    drink_data = get_drink_by_id(drink_id)
    if not drink_data or 'fields' not in drink_data:
        print(f"Errore: Drink {drink_id} non trovato o dati incompleti.")
        return None

    drink_fields = drink_data['fields']
    print(f"DEBUG SIMULA: Dati del drink recuperati da Airtable: {drink_fields}")
    
    gradazione_drink = drink_fields.get('Gradazione')
    valore_alcolico_da_airtable = drink_fields.get('Alcolico (bool)')
    is_alcolico = True if valore_alcolico_da_airtable == '1' else False
    
    print(f"DEBUG SIMULA: gradazione_drink={gradazione_drink}, tipo={type(gradazione_drink)}")
    print(f"DEBUG SIMULA: valore_alcolico_da_airtable={valore_alcolico_da_airtable}, tipo={type(valore_alcolico_da_airtable)}")
    print(f"DEBUG SIMULA: is_alcolico={is_alcolico}, tipo={type(is_alcolico)}")

    tasso_calcolato = 0.0
    esito_calcolo = 'Negativo'

    stomaco_str = 'Pieno' if stomaco_pieno_bool else 'Vuoto'

    if is_alcolico and gradazione_drink is not None and gradazione_drink > 0:
        volume_ml = float(peso_cocktail_g)
        gradazione_percent = float(gradazione_drink)
        
        genere_str = str(genere_utente).lower()
        if genere_str not in ['uomo', 'donna']:
            print(f"Errore: Genere non valido '{genere_str}' per l'utente {user_id}.")
            return None 

        stomaco_per_algoritmo = stomaco_str.lower()
        
        ora_inizio_dt = timestamp_consumazione
        ora_fine_dt = ora_inizio_dt + timedelta(hours=2)

        ora_inizio_str = ora_inizio_dt.strftime('%H:%M')
        ora_fine_str = ora_fine_dt.strftime('%H:%M')
        
        tasso_calcolato = calcola_tasso_alcolemico_widmark(
            peso=float(peso_utente_kg),
            genere=genere_str,
            volume=volume_ml,
            gradazione=gradazione_percent,
            stomaco=stomaco_per_algoritmo,
            ora_inizio=ora_inizio_str,
            ora_fine=ora_fine_str,
        )
        
        interpretazione = interpreta_tasso_alcolemico(tasso_calcolato)
        esito_calcolo = 'Negativo' if interpretazione['legale'] else 'Positivo'
    else:
        tasso_calcolato = 0.0
        esito_calcolo = 'Negativo'

    # 4. Salva in Airtable
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    data_to_save = {
        'records': [{
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id],
                'Peso (g)': float(peso_cocktail_g),
                'Tasso Calcolato (g/L)': round(tasso_calcolato, 3),
                'Stomaco': stomaco_str,
                'Risultato': esito_calcolo
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data_to_save)
    response_data = response.json()
    
    if response.status_code != 200 or 'records' not in response_data:
        print(f"Errore Airtable durante la creazione della consumazione: {response.status_code}")
        print(f"Risposta: {response_data}")
        return None

    # 5. Aggiorna i dati di gioco
    game_data = get_game_data(user_id)
    if game_data:
        # Aggiorna Time Keeper Progress
        update_achievement_progress(game_data, 'Time Keeper')
        
        # Se il tasso è legale, aggiorna Safe Driver Progress e Daily Challenge
        if esito_calcolo == 'Negativo':
            update_achievement_progress(game_data, 'Safe Driver')
            
            # Aggiorna Daily Challenge
            current_daily = game_data['fields']['Daily Challenge Completed']
            if current_daily < 3:  # Massimo 3 sessioni al giorno
                updates = {
                    'Daily Challenge Completed': current_daily + 1
                }
                if current_daily + 1 == 3:  # Se completa la daily challenge
                    updates['Points'] = game_data['fields']['Points'] + 50  # Bonus punti
                update_game_data(game_data['id'], updates)
        
        # Aggiorna Mix Master Progress (solo se è un drink nuovo)
        user_consumazioni = get_user_consumazioni(user_id)
        drink_ids = set()
        for cons in user_consumazioni:
            if 'Drink' in cons['fields']:
                drink_ids.add(cons['fields']['Drink'][0])
        
        if drink_id not in drink_ids:
            update_achievement_progress(game_data, 'Mix Master')
        
        # Assegna punti base per la sessione
        award_points(game_data, 10, 5)  # 10 punti e 5 XP per ogni sessione
        
    return response_data['records'][0]

def get_user_consumazioni(user_id=None, bar_id=None):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    
    # Debug print to understand the input
    print(f'DEBUG: get_user_consumazioni called with user_id={user_id}, bar_id={bar_id}')
    
    # Get all records and filter manually in Python
    # This is more reliable than using Airtable formulas for array fields
    response = requests.get(url, headers=get_airtable_headers())
    
    if response.status_code != 200:
        print(f'ERROR: Failed to fetch consumazioni. Status code: {response.status_code}')
        return []
    
    all_records = response.json().get('records', [])
    print(f'DEBUG: Retrieved {len(all_records)} total records')
    
    # If no filters, return all records
    if not user_id and not bar_id:
        return all_records
    
    # Manual filtering in Python
    filtered_records = []
    for record in all_records:
        fields = record.get('fields', {})
        users = fields.get('User', [])
        bars = fields.get('Bar', [])
        
        # Apply filters based on parameters
        if user_id and bar_id:
            if user_id in users and bar_id in bars:
                filtered_records.append(record)
        elif user_id:
            if user_id in users:
                filtered_records.append(record)
        elif bar_id:
            if bar_id in bars:
                filtered_records.append(record)
    
    print(f'DEBUG: Filtered to {len(filtered_records)} records for user_id={user_id}, bar_id={bar_id}')
    return filtered_records

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
        peso_kg_str = request.form.get('peso_kg') # Recupera peso
        genere = request.form.get('genere')      # Recupera genere

        logger.info(f"[REGISTER] Tentativo di registrazione per email: {email}")

        if not peso_kg_str or not genere:
            logger.warning(f"[REGISTER] Peso o genere mancanti per email: {email}")
            flash('Peso e Genere sono campi obbligatori.')
            return redirect(url_for('register'))
        
        try:
            peso_kg = float(peso_kg_str)
            if peso_kg <= 0:
                raise ValueError("Il peso deve essere positivo.")
        except ValueError as e:
            logger.warning(f"[REGISTER] Peso non valido per email: {email} - Errore: {e}")
            flash(f'Valore del peso non valido: {e}')
            return redirect(url_for('register'))

        if get_user_by_email(email):
            logger.warning(f"[REGISTER] Email già registrata: {email}")
            flash('Email già registrata.')
            return redirect(url_for('register'))

        try:
            # Usa il nuovo sistema di hashing semplice
            secure_hash = hash_password(password)
            logger.info(f"[REGISTER] Hash password generato con successo per email: {email}")
            logger.info(f"[REGISTER] Lunghezza hash generato: {len(secure_hash)} - Hash: {secure_hash}")
            
            # Crea l'utente nel database
            create_user(email, secure_hash, peso_kg, genere)
            logger.info(f"[REGISTER] Utente creato con successo: {email}")
            
            flash('Registrazione avvenuta con successo! Effettua il login.')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"[REGISTER] Errore nella registrazione per email: {email} - Errore: {e}")
            flash('Errore interno nella registrazione. Contatta il supporto.')
            return redirect(url_for('register'))
            
    return render_template('register.html')
@app.route('/debug_all_tables', methods=['GET'])
def debug_all_tables():
    """Temporary route to debug all Airtable tables structure"""
    tables = ['Consumazioni', 'Drinks', 'Bar', 'Users', 'Sorsi']
    result = {}
    
    for table_name in tables:
        try:
            # Attempt to get records from this table
            url = f'https://api.airtable.com/v0/{BASE_ID}/{table_name}'
            headers = get_airtable_headers()
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                records = data.get('records', [])
                
                if records:
                    # Get the first record as a sample
                    sample_record = records[0]
                    field_names = list(sample_record.get('fields', {}).keys())
                    
                    # Save table info
                    result[table_name] = {
                        'record_count': len(records),
                        'field_names': field_names,
                        'sample_record': sample_record
                    }
                else:
                    result[table_name] = {
                        'status': 'empty',
                        'message': 'No records found in table'
                    }
            else:
                result[table_name] = {
                    'status': 'error',
                    'message': f'API error: {response.status_code}',
                    'details': response.text if response.text else 'No details available'
                }
        except Exception as e:
            result[table_name] = {
                'status': 'exception',
                'message': str(e)
            }
    
    return jsonify(result)

@app.route('/debug_drinks', methods=['GET'])
def debug_drinks():
    """Temporary route to debug Drinks table"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
    headers = get_airtable_headers()
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        records = data.get('records', [])
        
        # Check if we have records
        if records:
            # Get all fields from the first record
            sample_record = records[0]
            field_names = list(sample_record.get('fields', {}).keys())
            
            # Return all drinks and their details
            return jsonify({
                'success': True,
                'drink_count': len(records),
                'field_names': field_names,
                'drinks': records
            })
        else:
            return jsonify({'success': False, 'error': 'No drinks found in Airtable'})
    else:
        return jsonify({'success': False, 'error': f'API error: {response.status_code}'})

@app.route('/debug_airtable', methods=['GET'])
def debug_airtable():
    """Temporary route to debug Airtable field names"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    headers = get_airtable_headers()
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        records = data.get('records', [])
        
        if records:
            # Get the first record as a sample
            sample_record = records[0]
            field_names = list(sample_record.get('fields', {}).keys())
            
            return jsonify({
                'success': True,
                'field_names': field_names,
                'sample_fields': sample_record.get('fields')
            })
        else:
            return jsonify({'success': False, 'error': 'No records found'})
    else:
        return jsonify({'success': False, 'error': f'API error: {response.status_code}'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user_type = request.form.get('user_type', 'utente')
        logger.info(f"[LOGIN] Tentativo di login per email: {email} come {user_type}")

        # Seleziona la tabella appropriata in base al tipo di utente
        table_name = 'Users' if user_type == 'utente' else 'Locali'
        url = f'https://api.airtable.com/v0/{BASE_ID}/{table_name}'
        headers = get_airtable_headers()
        params = {
            'filterByFormula': f"{{Email}}='{email}'"
        }
        
        logger.info(f"[LOGIN] Ricerca in tabella: {table_name}")
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            records = response.json().get('records', [])
            user = records[0] if records else None
            logger.info(f"[LOGIN] Record trovato: {user is not None}")
        else:
            user = None
            logger.error(f"[LOGIN] Errore nella richiesta Airtable: {response.status_code}")

        result = False
        if user:
            try:
                stored_password = user['fields'].get('Password')
                logger.info(f"[LOGIN] Password memorizzata trovata: {stored_password is not None}")
                
                # Per i locali, la password è salvata come hash SHA-256
                if user_type == 'locale':
                    hashed_input = hashlib.sha256(password.encode()).hexdigest()
                    result = stored_password == hashed_input
                    logger.info(f"[LOGIN] Verifica hash per locale: {result}")
                else:
                    # Per gli utenti normali, usa il sistema PBKDF2
                    result = verify_password(stored_password, password)
                    logger.info(f"[LOGIN] Verifica hash per utente: {result}")
            except Exception as e:
                logger.error(f"[LOGIN] Errore nella verifica dell'hash per email {email}: {e}")
                result = False
        else:
            logger.warning(f"[LOGIN] {user_type.capitalize()} non trovato per email: {email}")

        if result:
            SessionManager.init_session(user['id'], email)
            session['user_type'] = user_type
            logger.info(f"[LOGIN] Login riuscito per {user_type} con email: {email}")
            return redirect(url_for('home'))
        else:
            logger.warning(f"[LOGIN] Login fallito per {user_type} con email: {email}")
            flash('Credenziali errate')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    # Prima di eliminare tutto, ottieni il BAC corrente per informare l'utente
    bac_data = SessionManager.get_bac_data()
    bac_corrente = bac_data['bac']
    
    if bac_corrente > 0:
        interpretazione = interpreta_tasso_alcolemico(bac_corrente)['livello']
        flash(f'Il tuo tasso alcolemico attuale è: {bac_corrente:.3f} g/L ({interpretazione}). Ricorda di non metterti alla guida se hai bevuto.', 'info')
    
    # Pulisci la sessione usando SessionManager
    SessionManager.clear_session()
    flash('Logout effettuato con successo', 'success')
    return redirect(url_for('home'))


@app.route('/world')
@login_required
def world():
    # Valori predefiniti in caso di errore
    classifica = []
    drink_popolari = []
    bar_popolari = []
    totale_consumazioni = 0
    totale_sorsi = 0
    num_bar = 0
    num_consumazioni_utente = 0
    tasso_medio_utente = 0.0
    perc_esiti_positivi_utente = 0
    drink_preferito_utente = 'N/D'
    
    try:
        user_id = SessionManager.get_user_id()
        
        # Statistiche globali del sistema
        all_consumazioni = get_all_consumazioni()
        all_bars = get_bars()
        all_drinks = get_drinks()
        
        # Calcola statistiche globali
        totale_consumazioni = len(all_consumazioni)
        num_bar = len(all_bars)
        
        # Stima il numero di sorsi (senza richiamare i sorsi reali)
        totale_sorsi = totale_consumazioni * 5
        
        # Otteniamo prima tutti gli utenti in una sola chiamata
        url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
        response = requests.get(url, headers=get_airtable_headers())
        all_users = {}
        if response.status_code == 200:
            for user in response.json().get('records', []):
                all_users[user['id']] = user
        
        # Top users (classifica globale)
        user_counts = {}
        for cons in all_consumazioni:
            if 'User' in cons['fields'] and cons['fields']['User']:
                uid = cons['fields']['User'][0]
                user = all_users.get(uid)
                if user and 'fields' in user and 'Email' in user['fields']:
                    user_email = user['fields']['Email']
                else:
                    user_email = f'Utente {uid[:5]}...'
                user_counts[user_email] = user_counts.get(user_email, 0) + 1
        
        classifica = [
            {'nome': email, 'conteggio': count}
            for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ][:20]
        
        # Top drinks
        drink_counts = {}
        for cons in all_consumazioni:
            if 'Drink' in cons['fields'] and cons['fields']['Drink']:
                drink_id = cons['fields']['Drink'][0]
                drink = next((d for d in all_drinks if d['id'] == drink_id), None)
                drink_name = 'N/D'
                if drink and 'fields' in drink and 'Name' in drink['fields']:
                    drink_name = drink['fields']['Name']
                drink_counts[drink_name] = drink_counts.get(drink_name, 0) + 1
        
        drink_popolari = [
            {'nome': nome, 'conteggio': conteggio}
            for nome, conteggio in sorted(drink_counts.items(), key=lambda x: x[1], reverse=True)
        ][:10]
        
        # Top bars
        bar_counts = {}
        for cons in all_consumazioni:
            if 'Bar' in cons['fields'] and cons['fields']['Bar']:
                bar_id = cons['fields']['Bar'][0]
                bar = next((b for b in all_bars if b['id'] == bar_id), None)
                bar_name = 'N/D'
                if bar and 'fields' in bar and 'Name' in bar['fields']:
                    bar_name = bar['fields']['Name']
                bar_counts[bar_name] = bar_counts.get(bar_name, 0) + 1
        
        bar_popolari = [
            {'nome': nome, 'conteggio': conteggio}
            for nome, conteggio in sorted(bar_counts.items(), key=lambda x: x[1], reverse=True)
        ][:10]
        
        # Troviamo le consumazioni utente tra quelle già caricate
        raw_consumazioni_utente = [c for c in all_consumazioni 
                                  if 'User' in c.get('fields', {}) and 
                                  c.get('fields', {}).get('User') and 
                                  c.get('fields', {}).get('User')[0] == user_id]
        
        num_consumazioni_utente = len(raw_consumazioni_utente)
        
        # Calcolo statistiche personali
        if num_consumazioni_utente > 0:
            # Recupera tutti i sorsi dell'utente
            all_sorsi = []
            for consumazione in raw_consumazioni_utente:
                sorsi = get_sorsi_by_consumazione(consumazione['id'])
                all_sorsi.extend(sorsi)
            
            # Calcola il BAC medio e la percentuale di positivi dai sorsi
            if all_sorsi:
                bac_values = [float(sorso['fields'].get('BAC Temporaneo', 0)) 
                            for sorso in all_sorsi 
                            if 'BAC Temporaneo' in sorso['fields']]
                
                # Calcola il BAC medio
                tasso_medio_utente = sum(bac_values) / len(bac_values) if bac_values else 0.0
                
                # Calcola la percentuale di sorsi sopra il limite legale (0.5 g/L)
                sorsi_oltre_limite = sum(1 for bac in bac_values if bac > 0.5)
                perc_esiti_positivi_utente = (sorsi_oltre_limite / len(bac_values) * 100) if bac_values else 0
            
            # Drink preferito dell'utente
            drink_counts_utente = {}
            for cons in raw_consumazioni_utente:
                if 'Drink' in cons['fields'] and cons['fields']['Drink']:
                    drink_id = cons['fields']['Drink'][0]
                    drink = next((d for d in all_drinks if d['id'] == drink_id), None)
                    drink_name = 'N/D'
                    if drink and 'fields' in drink and 'Name' in drink['fields']:
                        drink_name = drink['fields']['Name']
                    drink_counts_utente[drink_name] = drink_counts_utente.get(drink_name, 0) + 1
            
            if drink_counts_utente:
                drink_preferito_utente = max(drink_counts_utente.items(), key=lambda x: x[1])[0]
    except Exception as e:
        print(f"Errore in World: {str(e)}")
        flash('Si è verificato un errore nel caricamento delle statistiche globali.', 'error')
    
    return render_template('world.html',
                          classifica=classifica,
                          drink_popolari=drink_popolari,
                          bar_popolari=bar_popolari,
                          totale_consumazioni=totale_consumazioni,
                          totale_sorsi=totale_sorsi,
                          num_bar=num_bar,
                          num_consumazioni_utente=num_consumazioni_utente,
                          tasso_medio_utente=tasso_medio_utente,
                          perc_esiti_positivi_utente=perc_esiti_positivi_utente,
                          drink_preferito_utente=drink_preferito_utente)

def get_all_consumazioni():
    """Recupera tutte le consumazioni dal sistema"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    response = requests.get(url, headers=get_airtable_headers())
    
    if response.status_code == 200:
        return response.json().get('records', [])
    
    print(f"ERRORE GET_ALL_CONSUMAZIONI: {response.status_code}")
    return []


@app.route('/get_arduino_data')
@login_required
def get_arduino_data():
    """Ottiene l'ultimo dato inviato da Arduino"""
    global dato_da_arduino, timestamp_dato
    
    return jsonify({
        'peso': dato_da_arduino,
        'timestamp': timestamp_dato
    })

@app.route('/simulatore')
@login_required
def simulatore():
    """Pagina per simulare l'invio di dati peso da Arduino"""
    return render_template('simulatore.html')

@app.route('/test-arduino')
@login_required
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

@app.route('/registra_sorso_ajax/<consumazione_id>', methods=['POST'])
@login_required
def registra_sorso_ajax(consumazione_id):
    """Endpoint per registrare un sorso via AJAX"""
    print(f"DEBUG - Ricevuta richiesta per registrare sorso per consumazione {consumazione_id}")
    
    try:
        data = request.get_json()
        volume = float(data.get('volume', 0))
        print(f"DEBUG - Volume ricevuto: {volume}g")
        
        if volume <= 0:
            print("DEBUG - Volume non valido")
            return jsonify({'success': False, 'error': 'Volume non valido'})
        
        # Registra il sorso
        print(f"DEBUG - Chiamata a registra_sorso con consumazione_id={consumazione_id}, volume={volume}")
        sorso = registra_sorso(consumazione_id, volume)
        
        if isinstance(sorso, dict) and 'error' in sorso:
            print(f"DEBUG - Errore nella registrazione del sorso: {sorso['error']}")
            return jsonify({'success': False, 'error': sorso['error']})
        
        # Recupera la lista aggiornata dei sorsi
        print("DEBUG - Recupero lista aggiornata dei sorsi")
        sorsi = get_sorsi_by_consumazione(consumazione_id)
        print(f"DEBUG - Trovati {len(sorsi)} sorsi")
        
        # Aggiorna i dati nella sessione
        consumption_data = SessionManager.get_consumption_data()
        if consumption_data and consumption_data['id'] == consumazione_id:
            consumption_data['sorsi'].append({
                'volume': volume,
                'timestamp': sorso['fields'].get('Ora inizio', ''),
                'bac': float(sorso['fields'].get('BAC Temporaneo', 0))
            })
            consumption_data['volume_consumato'] = sum(float(s['volume']) for s in consumption_data['sorsi'])
            SessionManager.set_consumption_data(consumption_data)
        
        return jsonify({
            'success': True,
            'sorso_id': sorso['id'] if sorso else None,
            'volume': volume,
            'bac': sorso['fields'].get('BAC Temporaneo', 0) if sorso and 'fields' in sorso else 0,
            'sorsi': sorsi
        })
        
    except Exception as e:
        print(f"DEBUG - Errore durante la registrazione del sorso: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_active_consumption')
@login_required
def check_active_consumption():
    """API per verificare se c'è una consumazione attiva per l'utente corrente"""
    try:
        active_consumption = get_active_consumption()
        
        if active_consumption:
            # Calcola i dettagli della consumazione
            drink_id = active_consumption['fields'].get('Drink', [])[0] if 'Drink' in active_consumption['fields'] else None
            drink_name = "Drink sconosciuto"
            if drink_id:
                drink = get_drink_by_id(drink_id)
                if drink:
                    drink_name = drink['fields'].get('Name', 'Drink sconosciuto')
            
            # Calcola il peso consumato
            initial_weight = float(active_consumption['fields'].get('Peso (g)', 0))
            sorsi = get_sorsi_by_consumazione(active_consumption['id'])
            consumed_weight = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi) if sorsi else 0.0
            consumed_percentage = round((consumed_weight / initial_weight) * 100) if initial_weight > 0 else 0
            
            # Calcola il BAC stimato
            bac = float(active_consumption['fields'].get('Tasso Calcolato (g/L)', 0))
            
            return jsonify({
                'active': True,
                'consumption_id': active_consumption['id'],
                'drink_name': drink_name,
                'initial_weight': initial_weight,
                'consumed_weight': consumed_weight,
                'consumed_percentage': consumed_percentage,
                'bac': bac
            })
        else:
            return jsonify({'active': False})
    
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)})

@app.route('/finish_consumption', methods=['POST'])
@login_required
def finish_consumption():
    """Completa una consumazione"""
    try:
        data = request.get_json()
        consumption_id = data.get('consumption_id')
        final_weight = float(data.get('final_weight', 0))
        
        if not consumption_id:
            return jsonify({'success': False, 'error': 'ID consumazione mancante'})
        
        # Ottieni la consumazione
        consumazione = get_consumazione_by_id(consumption_id)
        if not consumazione:
            return jsonify({'success': False, 'error': 'Consumazione non trovata'})
        
        # Verifica che la consumazione appartenga all'utente corrente
        if consumazione['fields'].get('User', []) and consumazione['fields']['User'][0] != SessionManager.get_user_id():
            return jsonify({'success': False, 'error': 'Consumazione non appartenente all\'utente'})
        
        # Calcola il peso già consumato
        peso_iniziale = float(consumazione['fields'].get('Peso (g)', 0))
        sorsi = get_sorsi_by_consumazione(consumption_id)
        volume_consumato = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi) if sorsi else 0.0
        
        # Se c'è ancora del peso da consumare, registra un sorso finale
        peso_residuo = peso_iniziale - volume_consumato
        if peso_residuo > 0 and final_weight < peso_residuo:
            volume_finale = peso_residuo - final_weight
            if volume_finale > 0:
                registra_sorso(consumption_id, volume_finale)
        
        # Marca la consumazione come completata
        url = f"https://api.airtable.com/v0/{BASE_ID}/Consumazioni/{consumption_id}"
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        data = {
            'fields': {'Completato': 'Completato'}
        }
        response = requests.patch(url, json=data, headers=headers)
        if response.status_code >= 400:
            raise Exception(f"Errore Airtable: {response.status_code} - {response.text}")
        
        # Rimuovi l'ID della consumazione attiva dalla sessione
        SessionManager.set_active_consumption(None)
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_cities', methods=['GET'])
@login_required
def api_get_cities():
    """Endpoint API per ottenere l'elenco delle città disponibili"""
    cities = get_cities()
    return jsonify({'cities': cities})

@app.route('/get_bars_by_city/<city>', methods=['GET'])
@login_required
def get_bars_by_city(city):
    """Endpoint API per ottenere i bar in una specifica città"""
    logger.info(f"Richiesta bar per città: {city}")
        
    bars = get_bars(city)
    logger.info(f"Trovati {len(bars)} bar per la città {city}")
    
    formatted_bars = [{
        'id': bar['id'],
        'name': bar['fields'].get('Name', '')
    } for bar in bars]
    
    response = {'bars': formatted_bars}
    logger.info(f"Risposta: {response}")
    return jsonify(response)

@app.route('/nuovo_drink', methods=['GET', 'POST'])
@login_required
def nuovo_drink():
    # Pagina per selezionare il drink
    
    # Ottieni l'elenco delle città disponibili
    cities = get_cities()
    
    # Controlla se c'è già una consumazione attiva
    consumazione_attiva = get_active_consumption()
    drink_attivo = None
    
    # Se c'è una consumazione attiva, recupera i dettagli del drink
    if consumazione_attiva:
        drink_id = consumazione_attiva['fields'].get('Drink', [''])[0] if 'Drink' in consumazione_attiva['fields'] else ''
        drink_attivo = get_drink_by_id(drink_id) if drink_id else None
        return render_template(
            'nuovo_drink.html',
            consumazione_attiva=consumazione_attiva,
            drink_attivo=drink_attivo,
            cities=cities
        )
    
    # Se c'è una richiesta POST, verifica se c'è una consumazione attiva prima di procedere
    if request.method == 'POST':
        if consumazione_attiva:
            flash('Hai già una consumazione attiva. Completa quella attuale prima di iniziarne una nuova.', 'warning')
            return redirect(url_for('monitora_drink'))
    
    # Inizializza le variabili per i template
    selected_city = None
    bars = []
    selected_bar_id = None
    drinks = []
    
    # Controlla se c'è un bar salvato nella sessione
    bar_id_from_session = SessionManager.get_bar_id()
    if bar_id_from_session:
        # Recupera i dettagli del bar
        bar_data = get_bar_by_id(bar_id_from_session)
        if bar_data and 'fields' in bar_data:
            selected_city = bar_data['fields'].get('Città')
            selected_bar_id = bar_id_from_session
            # Recupera i bar per la città selezionata
            if selected_city:
                bars = get_bars(selected_city)
                # Recupera i drink per il bar selezionato
                drinks = get_drinks(selected_bar_id)
    
    # Gestione della selezione della città
    if request.method == 'POST' and 'city' in request.form:
        selected_city = request.form.get('city')
        if selected_city:
            logger.info(f"Città selezionata: {selected_city}")
            # Filtra i bar per la città selezionata
            bars = get_bars(selected_city)
            logger.info(f"Trovati {len(bars)} bar per {selected_city}")
    
    # Gestione della selezione del bar
    if request.method == 'POST' and 'bar_id' in request.form and request.form.get('bar_id'):
        selected_bar_id = request.form.get('bar_id')
        selected_city = request.form.get('city')  # Mantieni la città selezionata
        
        if selected_city:
            bars = get_bars(selected_city)
        
        if selected_bar_id:
            logger.info(f"Bar selezionato: {selected_bar_id}")
            # Salva il bar selezionato nella sessione
            SessionManager.set_bar_id(selected_bar_id)
            
            # Ottieni tutti i drink prima del filtraggio
            all_drinks = get_drinks()
            # Filtra i drink per questo bar
            drinks = []
            for drink in all_drinks:
                bar_list_drink = drink['fields'].get('Bar', [])
                if selected_bar_id in bar_list_drink:
                    drinks.append(drink)
            logger.info(f"Trovati {len(drinks)} drink per il bar {selected_bar_id}")
    
    # Gestione del form quando viene inviato
    if request.method == 'POST' and 'drink_id' in request.form and request.form.get('drink_id'):
        # Ottieni i valori selezionati
        drink_id = request.form.get('drink_id')
        bar_id = request.form.get('bar_id')
        stomaco = request.form.get('stomaco')
        
        logger.info(f"Drink ID: {drink_id}, Bar ID: {bar_id}, Stomaco: {stomaco}")
        
        if not drink_id or not bar_id:
            flash('Seleziona un drink e un bar prima di iniziare', 'danger')
            logger.warning("Mancano drink_id o bar_id")
        else:
            # Salva il drink_id e lo stato dello stomaco nella sessione
            SessionManager.set_selected_drink_id(drink_id)
            SessionManager.set_stomaco_state(stomaco)
            logger.info(f"Avvio monitoraggio per drink_id: {drink_id}, bar_id: {bar_id}, stomaco: {stomaco}")
            # Reindirizza alla pagina di monitoraggio
            return redirect(url_for('monitora_drink', drink_id=drink_id, bar_id=bar_id))
    
    return render_template(
        'nuovo_drink.html',
        cities=cities,
        selected_city=selected_city,
        bars=bars,
        selected_bar_id=selected_bar_id,
        drinks=drinks
    )

@app.route('/monitora_drink', methods=['GET'])
@login_required
def monitora_drink():
    # Pagina per monitorare il consumo del drink
    
    # Controlla se c'è già una consumazione attiva
    consumazione_attiva = get_active_consumption()
    consumazione_id = None
    
    # Ottieni i parametri dall'URL
    drink_id = request.args.get('drink_id')
    bar_id = request.args.get('bar_id')
    
    logger.info(f"Richiesta monitora_drink con drink_id={drink_id}, bar_id={bar_id}")
    
    # Se non ci sono parametri ma c'è una consumazione attiva, usa i suoi dati
    if consumazione_attiva:
        consumazione_id = consumazione_attiva['id']
        drink_id = consumazione_attiva['fields'].get('Drink', [''])[0] if 'Drink' in consumazione_attiva['fields'] else ''
        bar_id = consumazione_attiva['fields'].get('Bar', [''])[0] if 'Bar' in consumazione_attiva['fields'] else ''
        
        # Recupera i dati dalla sessione
        consumption_data = SessionManager.get_consumption_data()
        if consumption_data and consumption_data['id'] == consumazione_id:
            return render_template(
                'monitora_drink.html',
                drink_id=drink_id,
                bar_id=bar_id,
                drink_selezionato=get_drink_by_id(drink_id),
                bar_selezionato=get_bar_by_id(bar_id) if bar_id else None,
                consumazione_id=consumazione_id,
                peso_iniziale=consumption_data['peso_iniziale'],
                volume_consumato=consumption_data['volume_consumato'],
                sorsi=consumption_data['sorsi']
            )
    
    # Verifica che ci sia un drink_id valido
    if not drink_id:
        flash('Nessun drink selezionato', 'danger')
        return redirect(url_for('nuovo_drink'))
    
    # Ottieni i dettagli del drink
    drink_selezionato = get_drink_by_id(drink_id)
    
    if not drink_selezionato:
        flash('Drink non trovato', 'danger')
        return redirect(url_for('nuovo_drink'))
    
    # Ottieni i dettagli del bar
    bar_selezionato = get_bar_by_id(bar_id) if bar_id else None
    
    return render_template(
        'monitora_drink.html',
        drink_id=drink_id,
        bar_id=bar_id,
        drink_selezionato=drink_selezionato,
        bar_selezionato=bar_selezionato,
        consumazione_id=consumazione_id
    )

@app.route('/get_drinks_by_bar/<bar_id>', methods=['GET'])
@login_required
def get_drinks_by_bar(bar_id):
    # Endpoint API per ottenere i drink disponibili per un bar specifico
    print(f"DEBUG: Ricevuta richiesta per drink del bar ID: {bar_id}")
    
    # Ottieni tutti i drink prima del filtraggio
    all_drinks = get_drinks()
    print(f"DEBUG: Trovati {len(all_drinks)} drink totali")
    
    # Filtra manualmente i drink per questo bar
    bar_drinks = []
    for drink in all_drinks:
        bar_list = drink['fields'].get('Bar', [])
        print(f"DEBUG: Drink {drink['id']} - Bar list: {bar_list}")
        if bar_id in bar_list:
            bar_drinks.append(drink)
    
    print(f"DEBUG: Filtrati {len(bar_drinks)} drink per il bar {bar_id}")
    
    # Formatta i dati per l'API
    formatted_drinks = [{
        'id': drink['id'],
        'name': drink['fields'].get('Name', ''),
        'gradazione': drink['fields'].get('Gradazione', 0)
    } for drink in bar_drinks]
    
    return jsonify({'drinks': formatted_drinks})

@app.route('/get_drink_details/<drink_id>', methods=['GET'])
@login_required
def get_drink_details(drink_id):
    """Endpoint API per ottenere i dettagli di un drink specifico"""
    drink = get_drink_by_id(drink_id)
    if not drink:
        return jsonify({'success': False, 'error': 'Drink non trovato'})
    
    return jsonify({
        'success': True,
        'drink_name': drink['fields'].get('Name', 'Sconosciuto'),
        'gradazione': drink['fields'].get('Gradazione', '0'),
        'id': drink['id']
    })

@app.route('/create_consumption', methods=['POST'])
@login_required
def create_consumption():
    """Crea una nuova consumazione"""
    try:
        data = request.get_json()
        peso_iniziale = float(data.get('peso_iniziale', 0))
        drink_id = data.get('drink_id')
        bar_id = data.get('bar_id')
        stomaco = data.get('stomaco', 'pieno')  # Default a 'pieno' se non specificato
        
        if peso_iniziale <= 0:
            return jsonify({'success': False, 'error': 'Peso iniziale non valido. Assicurati che il bicchiere sia posizionato sul sottobicchiere.'})
        
        if not drink_id:
            return jsonify({'success': False, 'error': 'Drink non selezionato'})
            
        if not bar_id:
            return jsonify({'success': False, 'error': 'Bar non selezionato'})
        
        # Recupera i dati dell'utente e del drink
        user_id = SessionManager.get_user_id()
        drink = get_drink_by_id(drink_id)
        
        if not drink:
            return jsonify({'success': False, 'error': 'Drink non trovato'})
        
        # Salva lo stato dello stomaco nella sessione
        SessionManager.set_stomaco_state(stomaco)
        
        # Crea una nuova consumazione in Airtable
        percentuale_alcol = float(drink['fields'].get('Percentuale', 0))
        grammi_alcol = (percentuale_alcol / 100) * peso_iniziale
        
        # Calcola il BAC stimato (molto semplificato per questo esempio)
        peso_utente = 70  # Peso default 70kg
        genere = 'M'  # Genere default 'M'
        
        # Calcola il fattore di Widmark in base al genere
        r = 0.68 if genere == 'M' else 0.55
        
        # Calcola il BAC stimato
        bac = (grammi_alcol / (peso_utente * 1000 * r)) * 100
        
        # Crea la consumazione usando requests invece di Airtable
        url = f"https://api.airtable.com/v0/{BASE_ID}/Consumazioni"
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
            
        # Prepara i dati includendo lo stato dello stomaco
        data = {
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id],
                'Peso (g)': peso_iniziale,
                'Tasso Calcolato (g/L)': bac,
                'Completato': 'Non completato',
                'Stomaco': stomaco.capitalize()  # Capitalizza la prima lettera
            }
        }
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code >= 400:
            raise Exception(f"Errore Airtable: {response.status_code} - {response.text}")
            
        consumazione = response.json()
        
        # Salva l'ID della consumazione attiva nella sessione
        SessionManager.set_active_consumption(consumazione['id'])
        
        # Salva i dati della consumazione nella sessione
        consumption_data = {
            'id': consumazione['id'],
            'drink_id': drink_id,
            'bar_id': bar_id,
            'peso_iniziale': peso_iniziale,
            'volume_consumato': 0,
            'sorsi': [],
            'bac': bac,
            'stomaco': stomaco
        }
        SessionManager.set_consumption_data(consumption_data)
        
        return jsonify({
            'success': True,
            'consumption_id': consumazione['id'],
            'drink_name': drink['fields'].get('Nome', 'Drink sconosciuto'),
            'initial_weight': peso_iniziale,
            'bac': bac
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/drink_master')
@login_required
def drink_master():
    """Pagina che mostra tutte le consumazioni dell'utente con relativi sorsi"""
    user_id = SessionManager.get_user_id()
    user_email = SessionManager.get_user_email()
    
    # Recupera tutte le consumazioni dell'utente
    consumazioni = get_user_consumazioni(user_id)
    
    # Per ogni consumazione, recupera i sorsi
    consumazioni_complete = []
    for consumazione in consumazioni:
        consumazione_id = consumazione['id']
        
        # Recupera i dettagli della consumazione
        drink_id = consumazione['fields'].get('Drink', [''])[0] if 'Drink' in consumazione['fields'] else ''
        drink = get_drink_by_id(drink_id) if drink_id else None
        drink_name = drink['fields'].get('Name', 'Sconosciuto') if drink else 'Sconosciuto'
        
        bar_id = consumazione['fields'].get('Bar', [''])[0] if 'Bar' in consumazione['fields'] else ''
        bar = get_bar_by_id(bar_id) if bar_id else None
        bar_name = bar['fields'].get('Name', 'Sconosciuto') if bar else 'Sconosciuto'
        
        # Recupera i sorsi per questa consumazione
        sorsi = get_sorsi_by_consumazione(consumazione_id)
        
        # Calcola il volume totale consumato
        volume_iniziale = float(consumazione['fields'].get('Peso (g)', 0))
        volume_consumato = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi) if sorsi else 0.0
        volume_rimanente = max(volume_iniziale - volume_consumato, 0.0)
        
        # Calcola il BAC massimo raggiunto
        bac_values = [float(sorso['fields'].get('BAC Temporaneo', 0)) for sorso in sorsi if 'BAC Temporaneo' in sorso['fields']]
        bac_max = max(bac_values) if bac_values else 0.0
        
        # Timestamp della consumazione
        created_time_str = consumazione.get('createdTime')
        display_timestamp = 'N/D'
        if created_time_str:
            try:
                dt_obj = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))
                display_timestamp = dt_obj.strftime('%d/%m/%Y %H:%M')
            except ValueError:
                display_timestamp = 'Timestamp invalido'
        
        # Crea un dizionario con tutti i dati della consumazione
        consumazione_completa = {
            'id': consumazione_id,
            'drink_name': drink_name,
            'bar_name': bar_name,
            'data': display_timestamp,
            'volume_iniziale': volume_iniziale,
            'volume_consumato': volume_consumato,
            'volume_rimanente': volume_rimanente,
            'percentuale_consumata': (volume_consumato / volume_iniziale * 100) if volume_iniziale > 0 else 0,
            'sorsi_count': len(sorsi),
            'bac_max': round(bac_max, 3),
            'completata': volume_rimanente <= 0,
            'sorsi': sorsi
        }
        
        consumazioni_complete.append(consumazione_completa)
    
    # Ordina le consumazioni per data (più recenti prima)
    consumazioni_complete.sort(key=lambda x: x['data'], reverse=True)
    
    # Ricalcola il BAC corrente considerando il tempo trascorso dall'ultimo sorso
    bac_data = SessionManager.get_bac_data()
    bac_corrente = bac_data['bac']
    ultima_ora = bac_data['timestamp']
    
    if bac_corrente > 0 and ultima_ora:
        try:
            # Calcola il tempo trascorso dall'ultimo sorso
            ultima_ora_dt = datetime.fromisoformat(ultima_ora)
            ora_attuale = datetime.now(TIMEZONE)
            tempo_trascorso = (ora_attuale - ultima_ora_dt).total_seconds() / 3600  # in ore
            
            # Applica la metabolizzazione dell'alcol
            if tempo_trascorso > 0:
                print(f"DEBUG: Ricalcolo BAC. Valore precedente: {bac_corrente}, tempo trascorso: {tempo_trascorso} ore")
                bac_corrente = calcola_alcol_metabolizzato(bac_corrente, tempo_trascorso)
                print(f"DEBUG: BAC ricalcolato: {bac_corrente}")
                
                # Aggiorna il valore in sessione
                SessionManager.set_bac_data(bac_corrente, ora_attuale.isoformat())
        except Exception as e:
            print(f"Errore nel ricalcolo del BAC: {str(e)}")
    
    interpretazione_bac = interpreta_tasso_alcolemico(bac_corrente)
    
    return render_template('drink_master.html', 
                           email=user_email, 
                           consumazioni=consumazioni_complete,
                           bac_corrente=bac_corrente,
                           interpretazione_bac=interpretazione_bac)

@app.route('/game')
@login_required
def game():
    # Get user data
    user = get_user_by_id(SessionManager.get_user_id())
    
    # Get or create game data
    game_data = get_game_data(SessionManager.get_user_id())
    if not game_data:
        game_data = create_game_data(SessionManager.get_user_id())
        if not game_data:
            flash('Errore durante la creazione dei dati di gioco.')
            return redirect(url_for('home'))
    
    # Check and reset daily challenge if needed
    check_and_reset_daily_challenge(game_data)
    
    # Get all game data for leaderboard
    url = f'https://api.airtable.com/v0/{BASE_ID}/GameData'
    response = requests.get(url, headers=get_airtable_headers())
    all_game_data = response.json().get('records', [])
    
    # Process leaderboard data - keep only latest entry per user
    user_latest_data = {}
    for data in all_game_data:
        fields = data['fields']
        user_id = fields.get('User', [''])[0]
        if user_id:
            # Get timestamp of this entry
            last_updated = fields.get('Last Updated')
            if not last_updated:
                continue
                
            # If we haven't seen this user before or this is a newer entry
            if user_id not in user_latest_data or last_updated > user_latest_data[user_id]['timestamp']:
                user_data = get_user_by_id(user_id)
                if user_data and 'fields' in user_data:
                    # Calculate completed achievements
                    achievements_completed = 0
                    if fields.get('Safe Driver Progress', 0) >= 5:
                        achievements_completed += 1
                    if fields.get('Mix Master Progress', 0) >= 10:
                        achievements_completed += 1
                    if fields.get('Time Keeper Progress', 0) >= 20:
                        achievements_completed += 1
                    
                    user_latest_data[user_id] = {
                        'email': user_data['fields'].get('Email', 'Unknown'),
                        'level': fields.get('Level', 1),
                        'points': fields.get('Points', 0),
                        'achievements_completed': achievements_completed,
                        'total_achievements': 3,  # Total number of achievements
                        'timestamp': last_updated,
                        'is_current_user': user_id == SessionManager.get_user_id()  # Flag per l'utente corrente
                    }
    
    # Convert to list and sort by points
    leaderboard = list(user_latest_data.values())
    leaderboard.sort(key=lambda x: x['points'], reverse=True)
    # Take only top 10
    leaderboard = leaderboard[:10]
    
    # Prepare game data for template
    template_game_data = {
        'level': game_data['fields']['Level'],
        'points': game_data['fields']['Points'],
        'xp': game_data['fields']['XP'],
        'achievements': {
            'safe_driver': {
                'progress': game_data['fields']['Safe Driver Progress'],
                'total': 5
            },
            'mix_master': {
                'progress': game_data['fields']['Mix Master Progress'],
                'total': 10
            },
            'time_keeper': {
                'progress': game_data['fields']['Time Keeper Progress'],
                'total': 20
            }
        },
        'daily_challenge': {
            'completed_sessions': game_data['fields']['Daily Challenge Completed'],
            'total_sessions': 3
        }
    }
    
    return render_template('game.html', 
                         user=user, 
                         game_data=template_game_data,
                         leaderboard=leaderboard)

def get_consumazione_by_id(consumazione_id):
    """Recupera una consumazione specifica da Airtable"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni/{consumazione_id}'
    response = requests.get(url, headers=get_airtable_headers())
    if response.status_code == 200:
        return response.json()
    return None

def get_consumazioni_by_user(user_id):
    """Wrapper function that calls get_user_consumazioni to retrieve a user's consumptions"""
    return get_user_consumazioni(user_id=user_id)

def get_sorsi_by_consumazione(consumazione_id):
    # Recupera sia i sorsi dal database che quelli in sessione (come backup)
    sorsi_da_db = get_sorsi_by_consumazione_from_airtable(consumazione_id)
    sorsi_da_sessione = SessionManager.get_sorsi_from_session(consumazione_id)
    
    # Se troviamo sorsi nel database, usiamo quelli
    if sorsi_da_db:
        print(f'DEBUG - Usando {len(sorsi_da_db)} sorsi da Airtable per consumazione {consumazione_id}')
        return sorsi_da_db
    # Altrimenti usiamo quelli in sessione (backup)
    elif sorsi_da_sessione:
        print(f'DEBUG - Usando {len(sorsi_da_sessione)} sorsi da sessione per consumazione {consumazione_id}')
        return sorsi_da_sessione
    # Se non ci sono sorsi né in DB né in sessione
    else:
        print(f'DEBUG - Nessun sorso trovato per consumazione {consumazione_id}')
        return []

def get_sorsi_by_consumazione_from_airtable(consumazione_id):
    """Recupera i sorsi da Airtable"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
    response = requests.get(url, headers=get_airtable_headers())
    
    if response.status_code == 200:
        # Filtra i sorsi nel codice Python
        all_records = response.json().get('records', [])
        filtered_records = []
        
        for record in all_records:
            # Se il record ha 'Consumazioni Id' e contiene il consumazione_id
            if 'Consumazioni Id' in record.get('fields', {}) and consumazione_id in record['fields']['Consumazioni Id']:
                filtered_records.append(record)
        
        print(f'DEBUG - Trovati {len(filtered_records)} sorsi in Airtable per consumazione {consumazione_id}')
        return filtered_records
    return []

def registra_sorso(consumazione_id, volume):
    """Registra un nuovo sorso per una consumazione"""
    try:
        # Recupera la consumazione
        consumazione = get_consumazione_by_id(consumazione_id)
        if not consumazione:
            return {'error': 'Consumazione non trovata'}
            
        # Verifica che la consumazione appartenga all'utente corrente
        if consumazione['fields'].get('User', []) and consumazione['fields']['User'][0] != SessionManager.get_user_id():
            return {'error': 'Consumazione non appartenente all\'utente'}
            
        # Calcola il BAC temporaneo
        volume_iniziale = float(consumazione['fields'].get('Peso (g)', 0))
        sorsi_precedenti = get_sorsi_by_consumazione(consumazione_id)
        volume_consumato = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi_precedenti) if sorsi_precedenti else 0.0
        
        # Verifica che il volume non superi quello disponibile
        if volume_consumato + volume > volume_iniziale:
            return {'error': 'Volume superiore a quello disponibile'}
            
        # Recupera i dati dell'utente
        user_id = SessionManager.get_user_id()
        user_data = get_user_by_id(user_id)
        if not user_data or 'fields' not in user_data:
            return {'error': 'Dati utente non trovati'}
            
        peso_utente = float(user_data['fields'].get('Peso', 0))
        genere = user_data['fields'].get('Genere', '').lower()
        email_utente = SessionManager.get_user_email()
        
        # Recupera i dati del drink
        drink_id = consumazione['fields'].get('Drink', [''])[0]
        drink = get_drink_by_id(drink_id)
        if not drink or 'fields' not in drink:
            return {'error': 'Dati drink non trovati'}
            
        gradazione = float(drink['fields'].get('Gradazione', 0))
        
        # Prepara la lista delle bevande per il calcolo del BAC
        ora_attuale = datetime.now(TIMEZONE)
        ora_inizio = ora_attuale - timedelta(minutes=1)  # 1 minuto fa
        ora_fine = ora_attuale
        
        # Prepara la lista di tutte le bevande (sorsi precedenti + nuovo sorso)
        lista_bevande = []
        
        # Aggiungi i sorsi precedenti alla lista
        if sorsi_precedenti:
            for sorso in sorsi_precedenti:
                if 'Ora inizio' in sorso['fields'] and 'Ora fine' in sorso['fields']:
                    try:
                        # Converti i timestamp ISO in datetime
                        inizio_dt = datetime.fromisoformat(sorso['fields']['Ora inizio'].replace('Z', '+00:00'))
                        fine_dt = datetime.fromisoformat(sorso['fields']['Ora fine'].replace('Z', '+00:00'))
                        
                        # Converti in formato HH:MM
                        ora_inizio_str = inizio_dt.strftime('%H:%M')
                        ora_fine_str = fine_dt.strftime('%H:%M')
                        
                        lista_bevande.append({
                            'volume': float(sorso['fields'].get('Volume (g)', 0)),
                            'gradazione': gradazione,  # Usa la stessa gradazione del drink
                            'ora_inizio': ora_inizio_str,
                            'ora_fine': ora_fine_str
                        })
                    except Exception as e:
                        print(f"Errore nella conversione del timestamp per il sorso: {str(e)}")
                        continue
    
    # Aggiungi il nuovo sorso
        lista_bevande.append({
            'volume': volume,
            'gradazione': gradazione,
            'ora_inizio': ora_inizio.strftime('%H:%M'),
            'ora_fine': ora_fine.strftime('%H:%M')
        })
        
        print(f"DEBUG - Lista bevande per calcolo BAC: {lista_bevande}")
        
        # Calcola il BAC cumulativo considerando tutti i sorsi
        risultato_bac = calcola_bac_cumulativo(
            peso=peso_utente,
            genere=genere,
            lista_bevande=lista_bevande,
            stomaco=SessionManager.get_stomaco_state()
        )
        
        bac_totale = risultato_bac['bac_finale']
        print(f"DEBUG - BAC calcolato: {bac_totale}")
        
        # Crea il sorso in Airtable
        url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
        data = {
            'records': [{
                'fields': {
                    'Consumazioni Id': [consumazione_id],
                    'Volume (g)': float(volume),
                    'Email': email_utente,
                    'BAC Temporaneo': round(bac_totale, 3),
                    'Ora inizio': ora_inizio.isoformat(),
                    'Ora fine': ora_fine.isoformat()
                }
            }]
        }
        
        print(f"DEBUG - Dati da inviare ad Airtable: {data}")  # Debug print
        
        response = requests.post(url, headers=get_airtable_headers(), json=data)
        
        if response.status_code != 200:
            print(f"DEBUG - Errore Airtable: {response.status_code}")
            print(f"DEBUG - Risposta Airtable: {response.text}")  # Debug print
            return {'error': f'Errore Airtable: {response.status_code} - {response.text}'}
            
        sorso = response.json()['records'][0]
        
        # Aggiorna il BAC nella sessione
        SessionManager.set_bac_data(bac_totale, ora_attuale.isoformat())
        
        # Salva anche in sessione come backup
        SessionManager.save_sorso_to_session(consumazione_id, sorso)
        
        return sorso
        
    except Exception as e:
        print(f"Errore durante la registrazione del sorso: {str(e)}")
        return {'error': str(e)}

def get_sorsi_giornalieri(email, consumazione_id=None):
    """Recupera tutti i sorsi dell'utente per la giornata corrente ordinati per data"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
    params = {
        'filterByFormula': f"{{Email}}='{email}'",
    }
    
    try:
        response = requests.get(url, headers=get_airtable_headers(), params=params)
        response.raise_for_status()
        
        data = response.json()
        if 'records' not in data:
            return []
            
        oggi = datetime.now(TIMEZONE).date()
        sorsi_filtrati = []
        
        for sorso in data['records']:
            if 'fields' in sorso and 'Ora inizio' in sorso['fields']:
                timestamp = datetime.fromisoformat(sorso['fields']['Ora inizio'].replace('Z', '+00:00'))
                timestamp = timestamp.astimezone(TIMEZONE)
                
                # Filtra solo per data odierna
                if timestamp.date() == oggi:
                    sorsi_filtrati.append(sorso)
        
        return sorsi_filtrati
        
    except Exception as e:
        print(f"Errore nel recupero dei sorsi giornalieri: {str(e)}")
        return []

def get_game_data(user_id):
    """Recupera i dati di gioco dell'utente da Airtable"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/GameData'
    params = {
        'filterByFormula': f"{{User}}='{user_id}'"
    }
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    if response.status_code == 200:
        records = response.json().get('records', [])
        return records[0] if records else None
    return None

def create_game_data(user_id):
    """Crea un nuovo record di dati di gioco per l'utente basato sulla sua storia"""
    # Recupera tutte le consumazioni dell'utente
    consumazioni = get_user_consumazioni(user_id)
    
    # Inizializza i contatori
    safe_driver_progress = 0
    mix_master_progress = 0
    time_keeper_progress = len(consumazioni)
    
    # Set di drink unici provati
    drink_ids = set()
    
    # Analizza ogni consumazione
    for cons in consumazioni:
        fields = cons.get('fields', {})
        
        # Conta sessioni sicure (tasso legale)
        if fields.get('Risultato') == 'Negativo':
            safe_driver_progress += 1
        
        # Conta drink unici
        if 'Drink' in fields and fields['Drink']:
            drink_ids.add(fields['Drink'][0])
    
    mix_master_progress = len(drink_ids)
    
    # Calcola punti e XP iniziali
    # 10 punti per ogni sessione sicura
    # 5 punti per ogni drink unico
    # 1 punto per ogni sessione tracciata
    initial_points = (safe_driver_progress * 10) + (mix_master_progress * 5) + time_keeper_progress
    initial_xp = initial_points % 100  # XP va da 0 a 100
    initial_level = 1 + (initial_points // 100)  # Ogni 100 punti = 1 livello
    
    # Crea il record in Airtable
    url = f'https://api.airtable.com/v0/{BASE_ID}/GameData'
    data = {
        'records': [{
            'fields': {
                'User': [user_id],
                'Level': initial_level,
                'Points': initial_points,
                'XP': initial_xp,
                'Safe Driver Progress': safe_driver_progress,
                'Mix Master Progress': mix_master_progress,
                'Time Keeper Progress': time_keeper_progress,
                'Daily Challenge Completed': 0,  # Daily challenge inizia da 0
                'Last Daily Reset': datetime.now(TIMEZONE).isoformat(),
                'Last Updated': datetime.now(TIMEZONE).isoformat()
            }
        }]
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    if response.status_code == 200:
        return response.json()['records'][0]
    return None

def update_game_data(game_data_id, updates):
    """Aggiorna i dati di gioco dell'utente"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/GameData/{game_data_id}'
    data = {
        'fields': {
            **updates,
            'Last Updated': datetime.now(TIMEZONE).isoformat()
        }
    }
    response = requests.patch(url, headers=get_airtable_headers(), json=data)
    if response.status_code == 200:
        return response.json()
    return None

def check_and_reset_daily_challenge(game_data):
    """Controlla e resetta la daily challenge se necessario"""
    last_reset = datetime.fromisoformat(game_data['fields']['Last Daily Reset'].replace('Z', '+00:00'))
    last_reset = last_reset.astimezone(TIMEZONE)
    now = datetime.now(TIMEZONE)
    
    # Se è passato un giorno dall'ultimo reset
    if (now - last_reset).days >= 1:
        updates = {
            'Daily Challenge Completed': 0,
            'Last Daily Reset': now.isoformat()
        }
        update_game_data(game_data['id'], updates)
        return True
    return False

def calculate_level(xp):
    """Calcola il livello basato sull'XP"""
    # Formula: livello = 1 + (XP / 100)
    return 1 + (xp // 100)

def award_points(game_data, points, xp):
    """Assegna punti e XP al giocatore"""
    current_points = game_data['fields']['Points']
    current_xp = game_data['fields']['XP']
    current_level = game_data['fields']['Level']
    
    new_points = current_points + points
    new_xp = (current_xp + xp) % 100  # Mantiene XP tra 0 e 100
    new_level = calculate_level(current_xp + xp)
    
    updates = {
        'Points': new_points,
        'XP': new_xp,
        'Level': new_level
    }
    
    return update_game_data(game_data['id'], updates)

def update_achievement_progress(game_data, achievement_type, progress=1):
    """Aggiorna il progresso di un achievement"""
    field_name = f'{achievement_type} Progress'
    current_progress = game_data['fields'][field_name]
    new_progress = current_progress + progress
    
    updates = {field_name: new_progress}
    
    # Controlla se l'achievement è stato completato
    if achievement_type == 'Safe Driver' and new_progress >= 5:
        updates['Achievements Unlocked'] = ['Safe Driver']
    elif achievement_type == 'Mix Master' and new_progress >= 10:
        updates['Achievements Unlocked'] = ['Mix Master']
    elif achievement_type == 'Time Keeper' and new_progress >= 20:
        updates['Achievements Unlocked'] = ['Time Keeper']
    
    return update_game_data(game_data['id'], updates)

def get_active_consumption():
    """Recupera la consumazione attiva dell'utente corrente"""
    active_consumption_id = SessionManager.get_active_consumption()
    if not active_consumption_id:
        return None
        
    return get_consumazione_by_id(active_consumption_id)

@app.route('/partner')
def partner():
    return render_template('partner.html')

@app.route('/register_partner', methods=['POST'])
def register_partner():
    try:
        # Get form data
        bar_name = request.form['barName']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        address = request.form['address']
        city = request.form['city']

        logger.info(f"[REGISTER_PARTNER] Tentativo di registrazione per: {bar_name} ({email})")

        # Validate password
        if len(password) < 8:
            flash('La password deve contenere almeno 8 caratteri')
            return redirect(url_for('partner'))
        
        if password != confirm_password:
            flash('Le password non coincidono')
            return redirect(url_for('partner'))

        # Check if email already exists
        url = f'https://api.airtable.com/v0/{BASE_ID}/Locali'
        headers = get_airtable_headers()
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            existing_bars = response.json().get('records', [])
            for bar in existing_bars:
                if bar['fields'].get('Email') == email:
                    flash('Email già registrata')
                    return redirect(url_for('partner'))

        # Hash the password
        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        # Create new bar record
        new_bar = {
            'fields': {
                'Name': bar_name,
                'Email': email,
                'Password': hashed_password,
                'Indirizzo': address,
                'Città': city
            }
        }

        # Add to Locali table
        response = requests.post(url, headers=headers, json=new_bar)
        
        if response.status_code == 200:
            # Now create the corresponding Bar record with only necessary fields
            bar_url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
            new_bar_record = {
                'fields': {
                    'Name': bar_name,
                    'Città': city,
                    'Indirizzo': address
                }
            }
            
            # Add to Bar table
            bar_response = requests.post(bar_url, headers=headers, json=new_bar_record)
            
            if bar_response.status_code == 200:
                flash('Registrazione completata con successo! Puoi effettuare il login con le tue credenziali.')
                return redirect(url_for('home'))
            else:
                flash('Si è verificato un errore durante la sincronizzazione dei dati. Riprova più tardi.')
                return redirect(url_for('partner'))
        else:
            flash('Si è verificato un errore durante la registrazione. Riprova più tardi.')
            return redirect(url_for('partner'))

    except Exception as e:
        logger.error(f"[REGISTER_PARTNER] Errore durante la registrazione del bar: {str(e)}")
        flash('Si è verificato un errore durante la registrazione. Riprova più tardi.')
        return redirect(url_for('partner'))

@app.route('/registra_drink', methods=['GET', 'POST'])
@login_required
def registra_drink():
    # Verifica che l'utente sia un locale
    if session.get('user_type') != 'locale':
        flash('Accesso non autorizzato')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        try:
            # Recupera i dati dal form
            nome = request.form['nome']
            gradazione = float(request.form['gradazione'])
            ingredienti = request.form.get('ingredienti', '')
            alcolico = 'alcolico' in request.form
            speciale = 'speciale' in request.form
            
            logger.info(f"[REGISTRA_DRINK] Tentativo di registrazione drink: {nome}")
            
            # Ottieni il record del locale
            locale_url = f'https://api.airtable.com/v0/{BASE_ID}/Locali/{session["user"]}'
            locale_response = requests.get(locale_url, headers=get_airtable_headers())
            
            if locale_response.status_code != 200:
                logger.error(f"[REGISTRA_DRINK] Errore nel recupero del locale: {locale_response.status_code}")
                flash('Errore durante la registrazione del drink', 'danger')
                return redirect(url_for('registra_drink'))
            
            locale_data = locale_response.json()
            locale_name = locale_data['fields'].get('Name')
            
            # Cerca il bar corrispondente usando il nome
            bar_url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
            bar_params = {'filterByFormula': f"{{Name}}='{locale_name}'"}
            bar_response = requests.get(bar_url, headers=get_airtable_headers(), params=bar_params)
            
            if bar_response.status_code != 200 or not bar_response.json().get('records'):
                logger.error(f"[REGISTRA_DRINK] Errore nel recupero del bar: {bar_response.status_code}")
                flash('Errore durante la registrazione del drink', 'danger')
                return redirect(url_for('registra_drink'))
            
            bar_id = bar_response.json()['records'][0]['id']
            
            # Crea il nuovo drink in Airtable
            url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
            data = {
                'records': [{
                    'fields': {
                        'Name': nome,
                        'Gradazione': gradazione,
                        'Ingredienti': ingredienti,
                        'Alcolico (bool)': '1' if alcolico else '0',
                        'Speciale (bool)': '1' if speciale else '0',
                        'Bar': [bar_id]
                    }
                }]
            }
            
            logger.info(f"[REGISTRA_DRINK] Dati da inviare ad Airtable: {data}")
            
            response = requests.post(url, headers=get_airtable_headers(), json=data)
            
            if response.status_code == 200:
                logger.info(f"[REGISTRA_DRINK] Drink registrato con successo: {nome}")
                flash('Drink registrato con successo!', 'success')
            else:
                logger.error(f"[REGISTRA_DRINK] Errore Airtable: {response.status_code} - {response.text}")
                flash('Errore durante la registrazione del drink', 'danger')
                
        except Exception as e:
            logger.error(f"[REGISTRA_DRINK] Errore: {str(e)}")
            flash('Si è verificato un errore durante la registrazione', 'danger')
    
    # Recupera il nome del locale loggato
    locale_url = f'https://api.airtable.com/v0/{BASE_ID}/Locali/{session["user"]}'
    locale_response = requests.get(locale_url, headers=get_airtable_headers())
    locale_data = locale_response.json()
    locale_name = locale_data['fields'].get('Name')
    
    # Cerca il bar corrispondente usando il nome
    bar_url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
    bar_params = {'filterByFormula': f"{{Name}}='{locale_name}'"}
    bar_response = requests.get(bar_url, headers=get_airtable_headers(), params=bar_params)
    
    if bar_response.status_code == 200 and bar_response.json().get('records'):
        bar_id = bar_response.json()['records'][0]['id']
        
        # Recupera tutti i drink associati a questo bar
        drinks_url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
        drinks_response = requests.get(drinks_url, headers=get_airtable_headers())
        
        if drinks_response.status_code == 200:
            all_drinks = drinks_response.json().get('records', [])
            # Filtra i drink per questo bar
            drinks = [drink for drink in all_drinks if bar_id in drink['fields'].get('Bar', [])]
        else:
            drinks = []
    else:
        drinks = []
    
    # Recupera tutti i drink non speciali
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
    response = requests.get(url, headers=get_airtable_headers())
    all_drinks = response.json().get('records', [])
    non_special_drinks = [drink for drink in all_drinks if drink['fields'].get('Speciale (bool)') == '0']
    
    # Marca i drink già collegati al bar
    for drink in non_special_drinks:
        drink['is_linked'] = bar_id in drink['fields'].get('Bar', [])
    
    return render_template('registra_drink.html', drinks=drinks, non_special_drinks=non_special_drinks)

# Modifica il template base per mostrare menu diversi in base al tipo di utente
@app.context_processor
def inject_user_type():
    return {
        'is_locale': session.get('user_type') == 'locale',
        'is_utente': session.get('user_type') == 'utente'
    }

@app.route('/link_drinks_to_bar', methods=['POST'])
@login_required
def link_drinks_to_bar():
    """Collega o scollega i drink standard al bar dell'utente"""
    if session.get('user_type') != 'locale':
        return jsonify({'success': False, 'error': 'Accesso non autorizzato'}), 403
    
    try:
        # Recupera gli ID dei drink selezionati
        selected_drinks = request.json.get('drink_ids', [])
        
        # Recupera il nome del locale loggato
        locale_url = f'https://api.airtable.com/v0/{BASE_ID}/Locali/{session["user"]}'
        locale_response = requests.get(locale_url, headers=get_airtable_headers())
        locale_data = locale_response.json()
        locale_name = locale_data['fields'].get('Name')
        
        # Cerca il bar corrispondente usando il nome
        bar_url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
        bar_params = {'filterByFormula': f"{{Name}}='{locale_name}'"}
        bar_response = requests.get(bar_url, headers=get_airtable_headers(), params=bar_params)
        
        if bar_response.status_code != 200 or not bar_response.json().get('records'):
            return jsonify({'success': False, 'error': 'Bar non trovato'}), 404
        
        bar_id = bar_response.json()['records'][0]['id']
        
        # Recupera tutti i drink non speciali
        drinks_url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks'
        drinks_response = requests.get(drinks_url, headers=get_airtable_headers())
        all_drinks = drinks_response.json().get('records', [])
        non_special_drinks = [drink for drink in all_drinks if drink['fields'].get('Speciale (bool)') == '0']
        
        # Per ogni drink non speciale
        for drink in non_special_drinks:
            drink_id = drink['id']
            current_bars = drink['fields'].get('Bar', [])
            
            # Se il drink è tra quelli selezionati e non è già collegato al bar
            if drink_id in selected_drinks and bar_id not in current_bars:
                current_bars.append(bar_id)
                # Aggiorna il drink per aggiungere il bar
                update_data = {
                    'fields': {
                        'Bar': current_bars
                    }
                }
                update_url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks/{drink_id}'
                update_response = requests.patch(update_url, headers=get_airtable_headers(), json=update_data)
                
                if update_response.status_code != 200:
                    logger.error(f"Errore nell'aggiunta del bar al drink {drink_id}: {update_response.text}")
            
            # Se il drink non è tra quelli selezionati ed è collegato al bar
            elif drink_id not in selected_drinks and bar_id in current_bars:
                current_bars.remove(bar_id)
                # Aggiorna il drink per rimuovere il bar
                update_data = {
                    'fields': {
                        'Bar': current_bars
                    }
                }
                update_url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks/{drink_id}'
                update_response = requests.patch(update_url, headers=get_airtable_headers(), json=update_data)
                
                if update_response.status_code != 200:
                    logger.error(f"Errore nella rimozione del bar dal drink {drink_id}: {update_response.text}")
        
        return jsonify({'success': True, 'message': 'Drink aggiornati con successo'})
        
    except Exception as e:
        logger.error(f"Errore nell'aggiornamento dei drink: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/statistica')
@login_required
def statistica():
    """Pagina delle statistiche per i bar"""
    # Verifica che l'utente sia un locale
    if session.get('user_type') != 'locale':
        flash('Accesso non autorizzato')
        return redirect(url_for('home'))
    
    try:
        # Recupera il nome del locale loggato
        locale_url = f'https://api.airtable.com/v0/{BASE_ID}/Locali/{session["user"]}'
        locale_response = requests.get(locale_url, headers=get_airtable_headers())
        locale_data = locale_response.json()
        locale_name = locale_data['fields'].get('Name')
        
        # Cerca il bar corrispondente usando il nome
        bar_url = f'https://api.airtable.com/v0/{BASE_ID}/Bar'
        bar_params = {'filterByFormula': f"{{Name}}='{locale_name}'"}
        bar_response = requests.get(bar_url, headers=get_airtable_headers(), params=bar_params)
        
        if bar_response.status_code != 200 or not bar_response.json().get('records'):
            flash('Errore nel recupero dei dati del bar', 'danger')
            return redirect(url_for('home'))
        
        bar_id = bar_response.json()['records'][0]['id']
        
        # Recupera tutte le consumazioni per questo bar
        consumazioni = get_user_consumazioni(bar_id=bar_id)
        
        # Inizializza le variabili per le statistiche
        totale_consumazioni = len(consumazioni)
        drink_stats = {}
        bac_values = []
        totale_sorsi = 0
        
        # Analizza ogni consumazione
        for cons in consumazioni:
            drink_id = cons['fields'].get('Drink', [''])[0]
            if drink_id:
                drink = get_drink_by_id(drink_id)
                if drink:
                    drink_name = drink['fields'].get('Name', 'Sconosciuto')
                    if drink_name not in drink_stats:
                        drink_stats[drink_name] = {
                            'consumazioni': 0,
                            'sorsi': 0,
                            'tassi': [],
                            'positivi': 0
                        }
                    
                    drink_stats[drink_name]['consumazioni'] += 1
                    
                    # Recupera i sorsi per questa consumazione
                    sorsi = get_sorsi_by_consumazione(cons['id'])
                    drink_stats[drink_name]['sorsi'] += len(sorsi)
                    totale_sorsi += len(sorsi)
                    
                    # Analizza i tassi alcolemici
                    for sorso in sorsi:
                        bac = float(sorso['fields'].get('BAC Temporaneo', 0))
                        drink_stats[drink_name]['tassi'].append(bac)
                        bac_values.append(bac)
                        if bac > 0.5:  # Limite legale
                            drink_stats[drink_name]['positivi'] += 1
        
        # Calcola le statistiche generali
        media_sorsi_per_drink = totale_sorsi / totale_consumazioni if totale_consumazioni > 0 else 0
        tasso_medio = sum(bac_values) / len(bac_values) if bac_values else 0
        
        # Prepara i dati per i grafici
        drink_labels = []
        drink_data = []
        dettaglio_drink = []
        
        for drink_name, stats in sorted(drink_stats.items(), key=lambda x: x[1]['consumazioni'], reverse=True):
            drink_labels.append(drink_name)
            drink_data.append(stats['consumazioni'])
            
            # Calcola le statistiche per drink
            media_sorsi = stats['sorsi'] / stats['consumazioni'] if stats['consumazioni'] > 0 else 0
            tasso_medio_drink = sum(stats['tassi']) / len(stats['tassi']) if stats['tassi'] else 0
            percentuale_positivi = (stats['positivi'] / stats['consumazioni'] * 100) if stats['consumazioni'] > 0 else 0
            
            dettaglio_drink.append({
                'nome': drink_name,
                'consumazioni': stats['consumazioni'],
                'media_sorsi': media_sorsi,
                'tasso_medio': tasso_medio_drink,
                'percentuale_positivi': percentuale_positivi
            })
        
        # Prepara i dati per il grafico della distribuzione BAC
        bac_ranges = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0), (1.0, float('inf'))]
        bac_labels = ['0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0', '>1.0']
        bac_data = [0] * len(bac_ranges)
        
        for bac in bac_values:
            for i, (min_bac, max_bac) in enumerate(bac_ranges):
                if min_bac <= bac < max_bac:
                    bac_data[i] += 1
                    break
        
        return render_template('statistica.html',
                             totale_consumazioni=totale_consumazioni,
                             drink_popolari=drink_labels[:5],
                             media_sorsi_per_drink=media_sorsi_per_drink,
                             tasso_medio=tasso_medio,
                             drink_labels=drink_labels,
                             drink_data=drink_data,
                             bac_labels=bac_labels,
                             bac_data=bac_data,
                             dettaglio_drink=dettaglio_drink)
                             
    except Exception as e:
        logger.error(f"Errore nella pagina statistiche: {str(e)}")
        flash('Si è verificato un errore nel caricamento delle statistiche', 'danger')
        return redirect(url_for('home'))

@app.route('/set_selected_bar', methods=['POST'])
@login_required
def set_selected_bar():
    """Salva il bar selezionato nella sessione"""
    try:
        data = request.get_json()
        bar_id = data.get('bar_id')
        
        if not bar_id:
            return jsonify({'success': False, 'error': 'Bar ID non fornito'}), 400
            
        # Salva il bar nella sessione
        SessionManager.set_bar_id(bar_id)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore nel salvataggio del bar selezionato: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)