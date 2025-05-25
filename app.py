from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import hashlib, os

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

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logger.info(f"[LOGIN] Tentativo di login per email: {email}")
        user = get_user_by_email(email)

        result = False
        if user:
            try:
                # Verifica la password
                result = verify_password(user['fields']['Password'], password)
                logger.info(f"[LOGIN] Verifica hash per email {email}: {result}")
            except Exception as e:
                logger.error(f"[LOGIN] Errore nella verifica dell'hash per email {email}: {e}")
                result = False
        else:
            logger.warning(f"[LOGIN] Utente non trovato per email: {email}")

        if result:
            session['user'] = user['id']
            session['user_email'] = email
            logger.info(f"[LOGIN] Login riuscito per email: {email}")
            # Reindirizza alla home invece che alla dashboard per un caricamento più veloce
            return redirect(url_for('home'))
        else:
            logger.warning(f"[LOGIN] Login fallito per email: {email}")
            flash('Credenziali errate')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    # Prima di eliminare tutto, ottieni il BAC corrente per informare l'utente
    bac_corrente = session.get('bac_cumulativo_sessione', 0.0)
    interpretazione = ''
    if bac_corrente > 0:
        interpretazione = interpreta_tasso_alcolemico(bac_corrente)['livello']
        flash(f'Il tuo tasso alcolemico attuale è: {bac_corrente:.3f} g/L ({interpretazione}). Ricorda di non metterti alla guida se hai bevuto.', 'info')
    
    # Pulisci la sessione
    session.clear()
    flash('Logout effettuato con successo', 'success')
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
        old_bar_id = session.get('bar_id')
        
        # Se stiamo cambiando bar (non è la prima selezione)
        if old_bar_id and old_bar_id != bar_id:
            # Verifica se ci sono consumazioni non completate nel bar attuale
            if 'active_consumazione_id' in session:
                consumazione_id = session['active_consumazione_id']
                consumazione = get_consumazione_by_id(consumazione_id)
                
                if consumazione:
                    # Recupera i dettagli della consumazione
                    sorsi = get_sorsi_by_consumazione(consumazione_id)
                    volume_iniziale = float(consumazione['fields'].get('Peso (g)', 0))
                    volume_consumato = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi) if sorsi else 0.0
                    drink_id = consumazione['fields'].get('Drink', [''])[0] if 'Drink' in consumazione['fields'] else ''
                    drink = get_drink_by_id(drink_id) if drink_id else None
                    drink_name = drink['fields'].get('Name', 'Sconosciuto') if drink else 'Sconosciuto'
                    
                    # Se il drink non è completato, avvisa l'utente
                    if volume_consumato < volume_iniziale:
                        flash(f'Hai lasciato {drink_name} non terminato. Puoi trovarlo nella pagina Drink Master.', 'warning')
            
            # Informa l'utente del BAC corrente
            bac_corrente = session.get('bac_cumulativo_sessione', 0.0)
            if bac_corrente > 0:
                interpretazione = interpreta_tasso_alcolemico(bac_corrente)['livello']
                flash(f'Il tuo tasso alcolemico attuale è: {bac_corrente:.3f} g/L ({interpretazione}).', 'info')
            
            # Resetta le variabili di sessione legate al bar
            if 'active_consumazione_id' in session:
                del session['active_consumazione_id']
            
            # Nota: NON resettiamo bac_cumulativo_sessione, poiché questo dovrebbe persistere tra i bar
            # per il calcolo corretto del tasso alcolemico totale
        
        # Imposta il nuovo bar_id
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
        flash('Devi essere loggato e aver selezionato un bar per simulare.')
        return redirect(url_for('login')) # O seleziona_bar

    bar_id = session['bar_id']
    drinks = get_drinks(bar_id)
    
    consumazione_creata = None # Manteniamo solo la variabile per l'ID della consumazione
    drink_selezionato_obj = None

    # === GESTIONE DATO DA ARDUINO (TEMPORANEAMENTE FISSO PER TEST) ===
    # current_peso_cocktail_g = dato_da_arduino # Commentato: riattivare per lettura da Arduino
    current_peso_cocktail_g = 200.0 # VALORE FISSO PER TEST
    usando_peso_fisso_test = True # Flag per il template
    # La logica di reset di dato_da_arduino e timestamp_dato dopo la consumazione rimane,
    # anche se non direttamente usata per current_peso_cocktail_g in questa modalità di test.

    if request.method == 'POST':
        drink_id = request.form.get('drink')
        stomaco_str = request.form.get('stomaco') # 'pieno' o 'vuoto'

        if not drink_id or not stomaco_str:
            flash('Devi selezionare un drink e lo stato del tuo stomaco.')
            return redirect(url_for('simula'))

        # Non servono più i controlli su current_peso_cocktail_g proveniente da Arduino
        # dato che ora è fisso e valido.
        # if current_peso_cocktail_g is None: ... (rimosso)
        # try: ... float(current_peso_cocktail_g) ... (rimosso, è già float)
        
        peso_da_usare_per_calcolo = float(current_peso_cocktail_g) # Assicuriamoci sia float

        drink_selezionato_obj = next((d for d in drinks if d['id'] == drink_id), None)

        try:
            consumazione_creata = create_consumazione(
                user_id=session['user'], 
                drink_id=drink_id, 
                bar_id=bar_id, 
                peso_cocktail_g=peso_da_usare_per_calcolo, # Usa il peso (fisso per ora)
                stomaco_pieno_bool=(stomaco_str == 'pieno')
            )

            if consumazione_creata and 'fields' in consumazione_creata:
                # Salva l'ID della consumazione nella sessione
                session['active_consumazione_id'] = consumazione_creata['id']
                
                flash('Simulazione registrata con successo!', 'success')
                
                # Resetta dato_da_arduino dopo l'uso
                global dato_da_arduino, timestamp_dato
                dato_da_arduino = None
                timestamp_dato = None
            else:
                flash('Errore durante la registrazione della simulazione o calcolo del tasso.', 'danger')
        
        except Exception as e:
            print(f"Errore imprevisto durante la creazione della consumazione/simulazione: {str(e)}")
            flash(f'Errore imprevisto durante la simulazione: {str(e)}', 'danger')

    bar_details = get_bar_by_id(bar_id) # Per avere il nome del bar aggiornato
    
    # Passiamo anche current_peso_cocktail_g al template per informare l'utente
    return render_template('simula.html', 
                         bar=bar_details,
                         drinks=drinks,
                         drink_selezionato=drink_selezionato_obj,
                         valore_peso_utilizzato=current_peso_cocktail_g,
                         usando_peso_fisso_test=usando_peso_fisso_test,
                         consumazione_id=consumazione_creata['id'] if consumazione_creata else None)

def get_all_consumazioni():
    """Recupera tutte le consumazioni dal sistema"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    response = requests.get(url, headers=get_airtable_headers())
    
    if response.status_code == 200:
        return response.json().get('records', [])
    
    print(f"ERRORE GET_ALL_CONSUMAZIONI: {response.status_code}")
    return []

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))
    
    user_id = session['user']
    bar_id = session.get('bar_id')
    
    # Usa il template originale per la dashboard specifica del bar
    return render_dashboard(user_id, bar_id)

@app.route('/world')
def world():
    """Pagina World con classifiche globali e statistiche"""
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))
    
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
        user_id = session['user']
        
        # Statistiche globali del sistema
        all_consumazioni = get_all_consumazioni()
        all_bars = get_bars()
        all_drinks = get_drinks()
        
        # Calcola statistiche globali
        totale_consumazioni = len(all_consumazioni)
        num_bar = len(all_bars)
        
        # Stima il numero di sorsi (senza richiamare i sorsi reali)
        # Stimiamo una media di 5 sorsi per consumazione per evitare chiamate API lente
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
                # Usiamo la cache locale invece di chiamare get_user_by_id
                user = all_users.get(uid)
                if user and 'fields' in user and 'Email' in user['fields']:
                    user_email = user['fields']['Email']
                else:
                    user_email = f'Utente {uid[:5]}...'
                user_counts[user_email] = user_counts.get(user_email, 0) + 1
        
        classifica = [
            {'nome': email, 'conteggio': count}
            for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ][:20]  # Limitato ai primi 20
        
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
            tassi_utente = [float(c.get('fields', {}).get('Tasso Calcolato (g/L)', 0.0)) 
                           for c in raw_consumazioni_utente 
                           if isinstance(c.get('fields', {}).get('Tasso Calcolato (g/L)'), (int, float))]
            
            tasso_medio_utente = sum(tassi_utente) / len(tassi_utente) if tassi_utente else 0.0
            
            esiti_positivi_utente = sum(1 for c in raw_consumazioni_utente if c.get('fields', {}).get('Risultato') == 'Positivo')
            perc_esiti_positivi_utente = (esiti_positivi_utente / num_consumazioni_utente * 100) if num_consumazioni_utente > 0 else 0
            
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

def render_dashboard(user_id, bar_id):
    """Funzione helper per renderizzare la dashboard originale"""
    # Codice originale della funzione dashboard

    drinks_all = get_drinks() # Per risolvere i nomi dei drink
    bars_all = get_bars()     # Per risolvere i nomi dei bar

    consumazioni_utente_dettagliate = []
    raw_consumazioni_utente = get_user_consumazioni(user_id=user_id, bar_id=bar_id if bar_id else None)

    for cons_fields in raw_consumazioni_utente:
        cons = cons_fields.get('fields', {})
        created_time_str = cons_fields.get('createdTime')

        # Risolvi nomi
        drink_id_list = cons.get('Drink', [])
        bar_id_list = cons.get('Bar', [])
        
        drink_name = 'N/D'
        if drink_id_list:
            drink_info = next((d['fields'].get('Name', 'N/D') for d in drinks_all if d['id'] == drink_id_list[0]), 'N/D')
            drink_name = drink_info

        bar_name = 'N/D'
        if bar_id_list:
            bar_info = next((b['fields'].get('Name', 'N/D') for b in bars_all if b['id'] == bar_id_list[0]), 'N/D')
            bar_name = bar_info
        
        # Formattazione timestamp (dal campo 'timestamp' che abbiamo aggiunto)
        timestamp_consumazione_str = cons.get('Time')
        display_timestamp = 'N/D'
        if timestamp_consumazione_str:
            try:
                dt_obj = datetime.fromisoformat(timestamp_consumazione_str.replace('Z', '+00:00'))
                display_timestamp = dt_obj.strftime('%d/%m/%Y %H:%M')
            except ValueError:
                 # Se il formato non è esattamente ISO o manca Z, prova createdTime da Airtable
                 if created_time_str:
                    try:
                        dt_obj = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))
                        display_timestamp = dt_obj.strftime('%d/%m/%Y %H:%M')
                    except ValueError:
                        display_timestamp = 'Timestamp invalido'                 
                 else:
                    display_timestamp = 'Timestamp mancante'

        consumazioni_utente_dettagliate.append({
            'drink_name': drink_name,
            'bar_name': bar_name,
            'timestamp': display_timestamp,
            'peso_cocktail': cons.get('Peso (g)', 'N/D'),
            'tasso': cons.get('Tasso Calcolato (g/L)', 'N/D'),
            'esito': cons.get('Risultato', 'N/D'),
            'stomaco': cons.get('Stomaco', 'N/D'),
            'id': cons_fields.get('id')
        })

    # La logica per user_drinks (aggregato) e classifica può rimanere o essere adattata
    # Per ora la commento se il template si concentrerà sui dettagli

    if not bar_id:
        # Statistiche globali (la classifica generale potrebbe ancora essere utile)
        # consumazioni = get_user_consumazioni(user_id) # Già prese come raw_consumazioni_utente
        all_consumazioni_altri_utenti = get_user_consumazioni(None) # Per classifica generale
        # drinks = get_drinks() # Già prese come drinks_all
        # bars = get_bars()     # Già prese come bars_all
        # print("DEBUG - consumazioni trovate:", consumazioni)
        # print("DEBUG - all_consumazioni:", all_consumazioni_altri_utenti)
        # print("DEBUG - drinks:", drinks_all)
        # print("DEBUG - bars:", bars_all)

        # Raggruppa per bar e drink (user_drinks esistente)
        user_drinks_aggregated = {}
        for cons_fields in raw_consumazioni_utente: # Usa quelle già filtrate per l'utente
            cons = cons_fields.get('fields', {})
            if 'Bar' not in cons or not cons['Bar'] or 'Drink' not in cons or not cons['Drink']:
                continue
            # Nomi già risolti prima, potremmo riutilizzare bar_name e drink_name da lì se li avessimo strutturati
            # Ma per ora rifacciamo il lookup per coerenza con il codice esistente di questa sezione
            bar_id_cons = cons['Bar'][0]
            drink_id_cons = cons['Drink'][0]
            bar = next((b for b in bars_all if b['id'] == bar_id_cons), None)
            drink = next((d for d in drinks_all if d['id'] == drink_id_cons), None)
            _bar_name = bar['fields']['Name'] if bar else 'Bar Sconosciuto'
            _drink_name = drink['fields']['Name'] if drink else 'Drink Sconosciuto'
            key = f"{_bar_name} - {_drink_name}"
            user_drinks_aggregated[key] = user_drinks_aggregated.get(key, 0) + 1
        user_drinks_list_aggregated = [
            {'nome': k, 'conteggio': v}
            for k, v in user_drinks_aggregated.items()
        ]

        # Classifica generale su tutti i bar
        user_counts = {}
        for cons_fields in all_consumazioni_altri_utenti:
            cons = cons_fields.get('fields', {})
            if 'User' not in cons or not cons['User']:
                continue
            uid = cons['User'][0]
            # Evitiamo di chiamare get_user_by_id per ogni consumazione per efficienza se possibile
            # Airtable non fornisce facilmente i dati utente linkati direttamente in modo aggregabile
            # Per una classifica reale, l'ideale sarebbe aggregare in Airtable o avere un DB separato
            # Qui simuliamo cercando l'email, ma non è efficiente per molti utenti/consumazioni.
            # Consideriamo un approccio semplificato per la classifica per ora.
            # La logica esistente chiama get_user_by_id, la manterrò ma con un commento.
            user = get_user_by_id(uid) # Molto inefficiente per classifiche grandi
            user_email = user['fields']['Email'] if user and 'fields' in user and 'Email' in user['fields'] else f'Utente {uid[:5]}...'
            user_counts[user_email] = user_counts.get(user_email, 0) + 1
        classifica_generale = [
            {'nome': email, 'conteggio': count}
            for email, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ][:10]

        # STATISTICHE UTENTE
        num_consumazioni_utente = len(raw_consumazioni_utente)
        tassi_utente = [float(c.get('fields', {}).get('Tasso Calcolato (g/L)', 0.0)) 
                        for c in raw_consumazioni_utente 
                        if isinstance(c.get('fields', {}).get('Tasso Calcolato (g/L)'), (int, float))]
        tasso_medio_utente = sum(tassi_utente) / len(tassi_utente) if tassi_utente else 0.0
        
        esiti_positivi_utente = sum(1 for c in raw_consumazioni_utente if c.get('fields', {}).get('Risultato') == 'Positivo')
        perc_esiti_positivi_utente = (esiti_positivi_utente / num_consumazioni_utente * 100) if num_consumazioni_utente > 0 else 0
        
        drink_preferito_utente = "N/A"
        if user_drinks_list_aggregated: # user_drinks_list_aggregated è già calcolato per l'utente
            drink_preferito_utente = max(user_drinks_list_aggregated, key=lambda x: x['conteggio'])['nome']

        # STATISTICHE GENERALI (solo se in dashboard globale)
        bar_preferito_utente = "N/A"
        num_consumazioni_totali_sistema = 0
        drink_popolare_sistema = "N/A"
        bar_popolare_sistema = "N/A"

        if not bar_id:
            # Bar preferito dall'utente (conteggio consumazioni per bar per l'utente loggato)
            consumi_utente_per_bar = {}
            for cons_fields in raw_consumazioni_utente:
                cons_data = cons_fields.get('fields', {})
                bar_ids_list = cons_data.get('Bar', [])
                if bar_ids_list:
                    bar_id_cons = bar_ids_list[0]
                    bar_name = next((b['fields'].get('Name', 'N/D') for b in bars_all if b['id'] == bar_id_cons), 'N/D')
                    consumi_utente_per_bar[bar_name] = consumi_utente_per_bar.get(bar_name, 0) + 1
            if consumi_utente_per_bar:
                bar_preferito_utente = max(consumi_utente_per_bar, key=consumi_utente_per_bar.get)

            # Statistiche di sistema (usano all_consumazioni_altri_utenti che sono TUTTE le consumazioni)
            num_consumazioni_totali_sistema = len(all_consumazioni_altri_utenti)

            conteggio_drink_sistema = {}
            conteggio_bar_sistema = {}
            for cons_fields in all_consumazioni_altri_utenti:
                cons_data = cons_fields.get('fields', {})
                drink_ids_list = cons_data.get('Drink', [])
                bar_ids_list = cons_data.get('Bar', [])
                if drink_ids_list:
                    drink_id_cons = drink_ids_list[0]
                    drink_name = next((d['fields'].get('Name', 'N/D') for d in drinks_all if d['id'] == drink_id_cons), 'N/D')
                    conteggio_drink_sistema[drink_name] = conteggio_drink_sistema.get(drink_name, 0) + 1
                if bar_ids_list:
                    bar_id_cons = bar_ids_list[0]
                    bar_name = next((b['fields'].get('Name', 'N/D') for b in bars_all if b['id'] == bar_id_cons), 'N/D')
                    conteggio_bar_sistema[bar_name] = conteggio_bar_sistema.get(bar_name, 0) + 1
            
            if conteggio_drink_sistema:
                drink_popolare_sistema = max(conteggio_drink_sistema, key=conteggio_drink_sistema.get)
            if conteggio_bar_sistema:
                bar_popolare_sistema = max(conteggio_bar_sistema, key=conteggio_bar_sistema.get)
            
            return render_template('dashboard.html',
                                 bar=None, 
                                 consumazioni_dettagliate=consumazioni_utente_dettagliate,
                                 user_drinks_aggregati=user_drinks_list_aggregated, 
                                 classifica=classifica_generale,
                                 # Nuove statistiche utente
                                 num_consumazioni_utente=num_consumazioni_utente,
                                 tasso_medio_utente=round(tasso_medio_utente, 2),
                                 drink_preferito_utente=drink_preferito_utente,
                                 bar_preferito_utente=bar_preferito_utente, # Solo per globale
                                 perc_esiti_positivi_utente=round(perc_esiti_positivi_utente, 1),
                                 # Nuove statistiche sistema (solo per globale)
                                 num_consumazioni_totali_sistema=num_consumazioni_totali_sistema,
                                 drink_popolare_sistema=drink_popolare_sistema,
                                 bar_popolare_sistema=bar_popolare_sistema
                                 )

    # Statistiche per bar selezionato
    # raw_consumazioni_utente sono già filtrate per bar_id se presente
    # drinks = get_drinks(bar_id) # drinks_all già disponibili e filtrati se necessario
    
    # user_drinks aggregati per il bar specifico
    drink_counts_specific_bar = {}
    for cons_fields in raw_consumazioni_utente: # Già filtrate per utente e bar
        cons = cons_fields.get('fields', {})
        if 'Drink' not in cons or not cons['Drink']:
            continue
        drink_id_cons = cons['Drink'][0]
        drink = next((d for d in drinks_all if d['id'] == drink_id_cons), None)
        _drink_name = drink['fields']['Name'] if drink and 'fields' in drink and 'Name' in drink['fields'] else 'Drink Sconosciuto'
        drink_counts_specific_bar[_drink_name] = drink_counts_specific_bar.get(_drink_name, 0) + 1
    user_drinks_list_specific_bar = [
        {'nome': k, 'conteggio': v}
        for k, v in drink_counts_specific_bar.items()
    ]

    # Classifica per il bar specifico
    all_consumazioni_specific_bar = get_user_consumazioni(None, bar_id) # Tutte le consumazioni per questo bar
    user_counts_specific_bar = {}
    for cons_fields in all_consumazioni_specific_bar:
        cons = cons_fields.get('fields', {})
        if 'User' not in cons or not cons['User']:
            continue
        uid = cons['User'][0]
        user = get_user_by_id(uid) # Inefficiente
        user_email = user['fields']['Email'] if user and 'fields' in user and 'Email' in user['fields'] else f'Utente {uid[:5]}...'
        user_counts_specific_bar[user_email] = user_counts_specific_bar.get(user_email, 0) + 1
    classifica_specific_bar = [
        {'nome': email, 'conteggio': count}
        for email, count in sorted(user_counts_specific_bar.items(), key=lambda x: x[1], reverse=True)
    ][:10]
    
    current_bar_details = get_bar_by_id(bar_id)

    # STATISTICHE UTENTE
    num_consumazioni_utente = len(raw_consumazioni_utente)
    tassi_utente = [float(c.get('fields', {}).get('Tasso Calcolato (g/L)', 0.0)) 
                    for c in raw_consumazioni_utente 
                    if isinstance(c.get('fields', {}).get('Tasso Calcolato (g/L)'), (int, float))]
    tasso_medio_utente = sum(tassi_utente) / len(tassi_utente) if tassi_utente else 0.0
    
    esiti_positivi_utente = sum(1 for c in raw_consumazioni_utente if c.get('fields', {}).get('Risultato') == 'Positivo')
    perc_esiti_positivi_utente = (esiti_positivi_utente / num_consumazioni_utente * 100) if num_consumazioni_utente > 0 else 0
    
    drink_preferito_utente = "N/A"
    if user_drinks_list_specific_bar: # user_drinks_list_specific_bar è già calcolato per questo bar
        drink_preferito_utente = max(user_drinks_list_specific_bar, key=lambda x: x['conteggio'])['nome']

    return render_template('dashboard.html',
                         bar=current_bar_details, 
                         consumazioni_dettagliate=consumazioni_utente_dettagliate,
                         user_drinks_aggregati=user_drinks_list_specific_bar, 
                         classifica=classifica_specific_bar,
                         # Nuove statistiche utente (specifiche per questo bar)
                         num_consumazioni_utente=num_consumazioni_utente,
                         tasso_medio_utente=round(tasso_medio_utente, 2),
                         drink_preferito_utente=drink_preferito_utente, # Sarà il preferito in questo bar
                         perc_esiti_positivi_utente=round(perc_esiti_positivi_utente, 1)
                         )

# Il vecchio endpoint /invia_dato non è più necessario, ora usiamo /arduino_peso/<peso>

@app.route('/get_arduino_data')
def get_arduino_data():
    """Ottiene l'ultimo dato inviato da Arduino"""
    global dato_da_arduino, timestamp_dato
    
    return jsonify({
        'peso': dato_da_arduino,
        'timestamp': timestamp_dato
    })

@app.route('/simulatore')
def simulatore():
    """Pagina per simulare l'invio di dati peso da Arduino"""
    return render_template('simulatore.html')

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

# La rotta del simulatore Arduino è stata rimossa perché non necessaria

@app.route('/registra_sorso_ajax/<consumazione_id>', methods=['POST'])
def registra_sorso_ajax(consumazione_id):
    """Endpoint per registrare un sorso via AJAX"""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Utente non autenticato'})
    
    try:
        data = request.get_json()
        volume = float(data.get('volume', 0))
        
        if volume <= 0:
            return jsonify({'success': False, 'error': 'Volume non valido'})
        
        # Registra il sorso
        sorso = registra_sorso(consumazione_id, volume)
        
        if isinstance(sorso, dict) and 'error' in sorso:
            # Errore nella registrazione del sorso
            return jsonify({'success': False, 'error': sorso['error']})
        
        return jsonify({
            'success': True,
            'sorso_id': sorso['id'] if sorso else None,
            'volume': volume,
            'bac': sorso['fields'].get('BAC Temporaneo', 0) if sorso and 'fields' in sorso else 0
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Funzione di utilità interna per verificare la consumazione attiva
def get_active_consumption():
    """Verifica se c'è una consumazione attiva per l'utente corrente e la restituisce"""
    if 'user' not in session:
        return None
    
    try:
        # Ottieni tutte le consumazioni dell'utente
        user_id = session.get('user')
        if not user_id:
            return None
            
        consumazioni = get_consumazioni_by_user(user_id)
        
        # Trova l'ultima consumazione non completata
        for consumazione in consumazioni:
            if consumazione['fields'].get('Completato', '') == 'Non completato':
                return consumazione
        
        return None
    
    except Exception as e:
        print(f"Errore nel recupero della consumazione attiva: {e}")
        return None

@app.route('/check_active_consumption')
def check_active_consumption():
    """API per verificare se c'è una consumazione attiva per l'utente corrente"""
    if 'user' not in session:
        return jsonify({'active': False, 'error': 'Utente non autenticato'})
    
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
def finish_consumption():
    """Completa una consumazione"""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Utente non autenticato'})
    
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
        if consumazione['fields'].get('User', []) and consumazione['fields']['User'][0] != session['user']:
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
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_cities', methods=['GET'])
def api_get_cities():
    """Endpoint API per ottenere l'elenco delle città disponibili"""
    if 'user' not in session:
        return jsonify({'error': 'Non autorizzato'}), 401
        
    cities = get_cities()
    return jsonify({'cities': cities})

@app.route('/get_bars_by_city/<city>', methods=['GET'])
def get_bars_by_city(city):
    """Endpoint API per ottenere i bar in una specifica città"""
    logger.info(f"Richiesta bar per città: {city}")
    
    if 'user' not in session:
        logger.warning("Tentativo di accesso non autorizzato all'endpoint get_bars_by_city")
        return jsonify({'error': 'Non autorizzato'}), 401
        
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
def nuovo_drink():
    # Pagina per selezionare il drink
    if 'user' not in session:
        flash('Devi effettuare il login per monitorare i tuoi drink')
        return redirect(url_for('login'))
    
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
    
    # Inizializza le variabili per i template
    selected_city = None
    bars = []
    selected_bar_id = None
    drinks = []
    
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
            session['selected_bar_id'] = selected_bar_id
            
            # Ottieni tutti i drink prima del filtraggio
            all_drinks = get_drinks()
            # Filtra i drink per questo bar
            drinks = []
            for drink in all_drinks:
                bar_list_drink = drink['fields'].get('Bar', [])
                if selected_bar_id in bar_list_drink:
                    drinks.append(drink)
            logger.info(f"Trovati {len(drinks)} drink per il bar {selected_bar_id}")
    
    # Questo blocco è stato sostituito con il nuovo codice sopra per gestire 'city'
    
    # Gestione del form quando viene inviato
    if request.method == 'POST' and 'drink_id' in request.form and request.form.get('drink_id'):
        # Ottieni i valori selezionati
        drink_id = request.form.get('drink_id')
        bar_id = request.form.get('bar_id')
        
        logger.info(f"Drink ID: {drink_id}, Bar ID: {bar_id}")
        
        if not drink_id or not bar_id:
            flash('Seleziona un drink e un bar prima di iniziare', 'danger')
            logger.warning("Mancano drink_id o bar_id")
        else:
            logger.info(f"Avvio monitoraggio per drink_id: {drink_id}, bar_id: {bar_id}")
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
def monitora_drink():
    # Pagina per monitorare il consumo del drink
    if 'user' not in session:
        flash('Devi effettuare il login per monitorare i tuoi drink', 'danger')
        return redirect(url_for('login'))
    
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
    
    # Verifica che ci sia un drink_id valido
    if not drink_id:
        flash('Nessun drink selezionato', 'danger')
        return redirect(url_for('nuovo_drink'))
    
    # Ottieni i dettagli del drink
    drink_selezionato = get_drink_by_id(drink_id)
    
    if not drink_selezionato:
        flash('Drink non trovato', 'danger')
        return redirect(url_for('nuovo_drink'))
    
    return render_template(
        'monitora_drink.html',
        drink_id=drink_id,
        bar_id=bar_id,
        drink_selezionato=drink_selezionato,
        consumazione_id=consumazione_id
    )

@app.route('/get_drinks_by_bar/<bar_id>', methods=['GET'])
def get_drinks_by_bar(bar_id):
    # Endpoint API per ottenere i drink disponibili per un bar specifico
    if 'user' not in session:
        return jsonify({'error': 'Non autorizzato'}), 401
    
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
def get_drink_details(drink_id):
    """Endpoint API per ottenere i dettagli di un drink specifico"""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Non autorizzato'}), 401
    
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
def create_consumption():
    """Crea una nuova consumazione"""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Utente non autenticato'})
    
    try:
        data = request.get_json()
        peso_iniziale = float(data.get('peso_iniziale', 0))
        drink_id = data.get('drink_id')
        bar_id = data.get('bar_id')  # Ottieni il bar_id direttamente dal form
        
        if peso_iniziale <= 0:
            return jsonify({'success': False, 'error': 'Peso iniziale non valido. Assicurati che il bicchiere sia posizionato sul sottobicchiere.'})
        
        if not drink_id:
            return jsonify({'success': False, 'error': 'Drink non selezionato'})
            
        if not bar_id:
            return jsonify({'success': False, 'error': 'Bar non selezionato'})
        
        # Recupera i dati dell'utente e del drink
        user_id = session['user']  # user_id è direttamente in session['user']
        drink = get_drink_by_id(drink_id)
        
        if not drink:
            return jsonify({'success': False, 'error': 'Drink non trovato'})
        
        # Crea una nuova consumazione in Airtable
        percentuale_alcol = float(drink['fields'].get('Percentuale', 0))
        grammi_alcol = (percentuale_alcol / 100) * peso_iniziale
        
        # Calcola il BAC stimato (molto semplificato per questo esempio)
        # Poiché session['user'] contiene solo l'ID e non info sull'utente, utilizziamo valori di default
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
        # Bar_id è già ottenuto dal form JSON
            
        # Prepara solo i dati essenziali, lasciando che Airtable gestisca i campi calcolati
        data = {
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id],
                'Peso (g)': peso_iniziale,
                'Tasso Calcolato (g/L)': bac,
                'Completato': 'Non completato',
                'Stomaco': 'Pieno'
            }
        }
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code >= 400:
            raise Exception(f"Errore Airtable: {response.status_code} - {response.text}")
            
        consumazione = response.json()
        
        return jsonify({
            'success': True,
            'consumption_id': consumazione['id'],
            'drink_name': drink['fields'].get('Nome', 'Drink sconosciuto'),
            'initial_weight': peso_iniziale,
            'bac': bac
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# La funzione sorsi è stata spostata nella sezione precedente del file
# e ora reindirizza a nuovo_drink


def get_consumazione_by_id(consumazione_id):
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
    sorsi_da_sessione = get_sorsi_by_consumazione_from_session(consumazione_id)
    
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

def get_sorsi_by_consumazione_from_session(consumazione_id):
    """Recupera i sorsi dalla sessione (backup)"""
    # Chiave per memorizzare i sorsi nella sessione
    session_key = f'sorsi_{consumazione_id}'
    
    # Recupera l'elenco dei sorsi dalla sessione (o una lista vuota)
    sorsi = session.get(session_key, [])
    print(f'DEBUG - Trovati {len(sorsi)} sorsi in sessione per consumazione {consumazione_id}')
    return sorsi

def save_sorso_to_session(consumazione_id, sorso):
    """Salva un sorso nella sessione come backup"""
    # Chiave per memorizzare i sorsi nella sessione
    session_key = f'sorsi_{consumazione_id}'
    
    # Recupera l'elenco corrente dei sorsi (o crea una lista vuota)
    sorsi = session.get(session_key, [])
    
    # Aggiungi il nuovo sorso
    sorsi.append(sorso)
    
    # Salva l'elenco aggiornato nella sessione
    session[session_key] = sorsi
    print(f'DEBUG - Salvato sorso in sessione. Ora ci sono {len(sorsi)} sorsi per consumazione {consumazione_id}')

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

def registra_sorso(consumazione_id, volume):
    try:
        # Recupera i dati necessari
        consumazione = get_consumazione_by_id(consumazione_id)
        if not consumazione:
            return None
        
        # Verifica che il volume totale consumato non superi il volume del drink
        volume_drink = float(consumazione['fields']['Peso (g)'])
        sorsi_registrati = get_sorsi_by_consumazione(consumazione_id)
        volume_consumato = sum(float(sorso['fields'].get('Volume (g)', 0)) for sorso in sorsi_registrati) if sorsi_registrati else 0
        
        # Controlla se il nuovo sorso supererebbe il volume totale del drink
        if volume_consumato + float(volume) > volume_drink:
            print(f"Errore: volume richiesto {volume}g, ma rimangono solo {volume_drink - volume_consumato}g")
            # Qui non restituiamo None per permettere alla funzione chiamante di gestire l'errore
            # Creando un dizionario fittizio con un campo 'error'
            return {'error': 'volume_exceeded', 'remaining': volume_drink - volume_consumato}
        
        user_id = consumazione['fields']['User'][0]
        user = get_user_by_id(user_id)
        if not user:
            return None
        
        drink_id = consumazione['fields']['Drink'][0]
        drink = get_drink_by_id(drink_id)
        if not drink:
            return None
        
        # Dati per il calcolo
        # Accesso sicuro ai campi dell'utente e del drink
        peso_utente = user['fields'].get('Peso', 70)  # Valore di default se manca
        genere = user['fields'].get('Genere', 'M').lower()
        gradazione = drink['fields'].get('Gradazione', 0)
        email_utente = user['fields'].get('Email', '')
        
        # Recupera tutti i sorsi dell'utente per la giornata corrente
        sorsi_giornalieri = get_sorsi_giornalieri(email_utente)
        
        # Usa l'ora corrente per il nuovo sorso
        try:
            ora_inizio = datetime.now(TIMEZONE)
            ora_fine = ora_inizio + timedelta(minutes=1)
        except Exception as e:
            print(f"Errore nel calcolo delle date: {str(e)}")
            return None

        # Calcola il BAC per il nuovo sorso usando il volume del sorso
        try:
            bac_sorso = calcola_tasso_alcolemico_widmark(
                peso=float(peso_utente),
                genere=genere,
                volume=float(volume),  # Usa il volume del sorso passato come parametro
                gradazione=float(gradazione),
                stomaco=consumazione['fields'].get('Stomaco', 'Pieno').lower(),
                ora_inizio=ora_inizio.strftime('%H:%M'),
                ora_fine=ora_fine.strftime('%H:%M')
            )
        except Exception as e:
            print(f"Errore nel calcolo del BAC: {str(e)}")
            return None

        # Ottieni l'ultimo BAC cumulativo dalla sessione (questo mantiene la continuità tra i drink)
        session_bac_key = 'bac_cumulativo_sessione'
        bac_sessione = session.get(session_bac_key, 0.0)
        ultima_ora_sessione = session.get('ultima_ora_bac_sessione')
        print(f"DEBUG: BAC sessione precedente = {bac_sessione} g/L")
        
        # Se esiste un BAC di sessione, calcola il metabolismo dall'ultimo sorso
        if bac_sessione > 0 and ultima_ora_sessione:
            try:
                ultima_ora = datetime.fromisoformat(ultima_ora_sessione)
                tempo_trascorso = (ora_inizio - ultima_ora).total_seconds() / 3600
                # Non utilizzare valori negativi di tempo
                tempo_trascorso = max(0, tempo_trascorso)
                bac_metabolizzato = calcola_alcol_metabolizzato(bac_sessione, tempo_trascorso)
                print(f"DEBUG: BAC metabolizzato da {bac_sessione} a {bac_metabolizzato} in {tempo_trascorso} ore")
            except Exception as e:
                print(f"Errore nel calcolo del BAC metabolizzato dalla sessione: {str(e)}")
                bac_metabolizzato = bac_sessione
        else:
            bac_metabolizzato = 0.0
            
        # Se non ci sono sorsi precedenti per questo drink, usa il BAC metabolizzato dalla sessione + il nuovo sorso
        if not sorsi_giornalieri:
            bac_totale = bac_metabolizzato + bac_sorso
        else:
            # Trova il sorso con l'ora di fine più vicina all'ora di inizio del nuovo sorso
            ultimo_sorso = None
            min_diff = float('inf')
            
            for sorso in sorsi_giornalieri:
                if 'fields' in sorso and 'Ora fine' in sorso['fields']:
                    ora_fine_sorso = datetime.fromisoformat(sorso['fields']['Ora fine'].replace('Z', '+00:00'))
                    ora_fine_sorso = ora_fine_sorso.astimezone(TIMEZONE)
                    diff = abs((ora_inizio - ora_fine_sorso).total_seconds())
                    
                    if diff < min_diff:
                        min_diff = diff
                        ultimo_sorso = sorso
            
            if ultimo_sorso:
                bac_precedente = float(ultimo_sorso['fields'].get('BAC Temporaneo', 0.0))
                
                # Calcola il tempo trascorso dall'ultimo sorso
                ora_fine_ultimo = datetime.fromisoformat(ultimo_sorso['fields']['Ora fine'].replace('Z', '+00:00'))
                ora_fine_ultimo = ora_fine_ultimo.astimezone(TIMEZONE)
                tempo_trascorso = (ora_inizio - ora_fine_ultimo).total_seconds() / 3600
                
                # Calcola l'alcol metabolizzato nel tempo trascorso
                bac_vecchio = calcola_alcol_metabolizzato(bac_precedente, tempo_trascorso)
                
                # Il BAC totale è: il massimo tra BAC precedente metabolizzato e BAC sessione + BAC nuovo sorso
                # Usiamo il massimo per evitare di perdere traccia del BAC se cambiamo drink
                bac_totale = max(bac_vecchio, bac_metabolizzato) + bac_sorso
                
                print(f"DEBUG BAC: precedente={bac_precedente}, metabolizzato={bac_vecchio}, sessione={bac_metabolizzato}, nuovo sorso={bac_sorso}, totale={bac_totale}")
            else:
                bac_totale = bac_metabolizzato + bac_sorso
                
        # Limita il BAC a un valore massimo ragionevole
        MAX_BAC = 4.0  # g/L, valore massimo plausibile per un essere umano
        if bac_totale > MAX_BAC:
            print(f"ATTENZIONE: BAC calcolato {bac_totale} g/L eccede il limite massimo, limitato a {MAX_BAC} g/L")
            bac_totale = MAX_BAC
        
        # Aggiorna il BAC di sessione e l'orario
        session[session_bac_key] = bac_totale
        session['ultima_ora_bac_sessione'] = ora_fine.isoformat()
        
        # Registra il sorso in Airtable
        url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
        
        # Ottieni un nuovo ID incrementale per il sorso
        last_id = 0
        sorsi_esistenti = get_sorsi_by_consumazione(consumazione_id)
        if sorsi_esistenti:
            for sorso in sorsi_esistenti:
                if 'fields' in sorso and 'Id' in sorso['fields']:
                    sorso_id = int(sorso['fields']['Id'])
                    if sorso_id > last_id:
                        last_id = sorso_id
        
        new_id = last_id + 1
        
        data = {
            'records': [{
                'fields': {
                    'Id': new_id,
                    'Consumazioni Id': [consumazione_id],
                    'Volume (g)': volume,
                    'Email': email_utente,
                    'BAC Temporaneo': round(bac_totale, 3),
                    'Ora inizio': ora_inizio.isoformat(),
                    'Ora fine': ora_fine.isoformat()
                }
            }]
        }
        
        response = requests.post(url, headers=get_airtable_headers(), json=data)
        
        if response.status_code != 200:
            print(f"Errore Airtable - Status: {response.status_code}")
            return None
        
        # Otteniamo il record creato
        created_record = response.json()['records'][0]
        
        # Salviamo anche in sessione come backup per la visualizzazione
        save_sorso_to_session(consumazione_id, created_record)
            
        return created_record
        
    except Exception as e:
        print(f"Errore durante la registrazione del sorso: {str(e)}")
        return None

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

@app.route('/game')
def game():
    if not session.get('user'):
        flash('Devi effettuare il login per accedere al gioco.')
        return redirect(url_for('login'))
    
    # Get user data
    user = get_user_by_id(session.get('user'))
    
    # Get or create game data
    game_data = get_game_data(session.get('user'))
    if not game_data:
        game_data = create_game_data(session.get('user'))
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
                        'is_current_user': user_id == session.get('user')  # Flag per l'utente corrente
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

@app.route('/sorsi/<consumazione_id>')
def sorsi(consumazione_id):
    """Reindirizza alla pagina nuovo_drink poiché ora utilizziamo un approccio unificato"""
    if 'user' not in session:
        flash('Devi effettuare il login per accedere a questa pagina', 'danger')
        return redirect(url_for('login'))
    
    # Verifica che la consumazione esista
    consumazione = get_consumazione_by_id(consumazione_id)
    if not consumazione:
        flash('Consumazione non trovata', 'danger')
        return redirect(url_for('drink_master'))
    
    # Verifica che la consumazione appartenga all'utente corrente
    user_id = session['user']
    if user_id not in consumazione['fields'].get('User', []):
        flash('Non hai accesso a questa consumazione', 'danger')
        return redirect(url_for('drink_master'))
    
    # Reindirizza alla nuova pagina unificata
    flash('Ora utilizziamo un approccio unificato per il monitoraggio dei drink', 'info')
    return redirect(url_for('nuovo_drink'))

@app.route('/drink_master')
def drink_master():
    """Pagina che mostra tutte le consumazioni dell'utente con relativi sorsi"""
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))
    
    user_id = session['user']
    user_email = session['user_email']
    
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
    bac_corrente = session.get('bac_cumulativo_sessione', 0.0)
    ultima_ora = session.get('ultima_ora_bac_sessione')
    
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
                session['bac_cumulativo_sessione'] = bac_corrente
                session['ultima_ora_bac_sessione'] = ora_attuale.isoformat()
        except Exception as e:
            print(f"Errore nel ricalcolo del BAC: {str(e)}")
    
    interpretazione_bac = interpreta_tasso_alcolemico(bac_corrente)
    
    return render_template('drink_master.html', 
                           email=user_email, 
                           consumazioni=consumazioni_complete,
                           bac_corrente=bac_corrente,
                           interpretazione_bac=interpretazione_bac)

if __name__ == '__main__':
    app.run(debug=True)