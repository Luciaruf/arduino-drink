from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
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

def get_drink_by_id(drink_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Drinks/{drink_id}'
    response = requests.get(url, headers=get_airtable_headers())
    if response.status_code == 200:
        return response.json()
    return None

def get_user_by_email(email):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    params = {
        'filterByFormula': f"{{Email}}='{email}'"
    }
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    records = response.json().get('records', [])
    return records[0] if records else None

def create_user(email, password_hash, peso_kg, genere):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Users'
    data = {
        'records': [{\
            'fields': {\
                'Email': email,\
                'Password': password_hash,\
                'Peso': peso_kg,
                'Genere': genere.capitalize()
            }\
        }]\
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

        if not peso_kg_str or not genere:
            flash('Peso e Genere sono campi obbligatori.')
            return redirect(url_for('register'))
        
        try:
            peso_kg = float(peso_kg_str)
            if peso_kg <= 0:
                raise ValueError("Il peso deve essere positivo.")
        except ValueError as e:
            flash(f'Valore del peso non valido: {e}')
            return redirect(url_for('register'))

        if get_user_by_email(email):
            flash('Email già registrata.')
            return redirect(url_for('register'))

        create_user(email, generate_password_hash(password), peso_kg, genere)
        flash('Registrazione avvenuta con successo! Effettua il login.')
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

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

    # Controllo per forzare la vista globale
    view_mode = request.args.get('view_mode')
    if view_mode == 'global':
        session.pop('bar_id', None)

    user_id = session['user']
    bar_id = session.get('bar_id')

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
            'stomaco': cons.get('Stomaco', 'N/D')
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

@app.route('/sorsi/<consumazione_id>', methods=['GET', 'POST'])
def sorsi(consumazione_id):
    if 'user' not in session:
        flash('Devi effettuare il login per accedere a questa pagina', 'danger')
        return redirect(url_for('login'))
    
    # Recupera i dati della consumazione
    consumazione = get_consumazione_by_id(consumazione_id)
    if not consumazione:
        flash('Consumazione non trovata', 'danger')
        return redirect(url_for('simula'))
    
    # Verifica che la consumazione appartenga all'utente corrente
    if consumazione['fields']['User'][0] != session['user']:
        flash('Non hai i permessi per accedere a questa consumazione', 'danger')
        return redirect(url_for('simula'))
    
    # Assicurati che il bar_id sia nella sessione (utile per la navbar e intestazione)
    consumazione_bar_id = consumazione['fields'].get('Bar', [None])[0]
    if consumazione_bar_id and session.get('bar_id') != consumazione_bar_id:
        session['bar_id'] = consumazione_bar_id

    # Recupera i sorsi già registrati
    sorsi_registrati = get_sorsi_by_consumazione(consumazione_id)
    print("\nDEBUG - Sorsi registrati:", len(sorsi_registrati))
    for sorso in sorsi_registrati:
        print("DEBUG - Sorso:", sorso['fields'])

    interpretazione_bac = None
    bac_ultimo_sorso = None
    if sorsi_registrati:
        # Prendi il BAC dell'ultimo sorso registrato
        ultimo_sorso = sorsi_registrati[0]
        print("\nDEBUG - Ultimo sorso:", ultimo_sorso['fields'])
        bac_ultimo_sorso = ultimo_sorso['fields'].get('BAC Temporaneo')
        print("DEBUG - BAC ultimo sorso:", bac_ultimo_sorso)
        if bac_ultimo_sorso is not None:
            try:
                bac_float = float(bac_ultimo_sorso)
                print("DEBUG - BAC convertito in float:", bac_float)
                interpretazione_bac = interpreta_tasso_alcolemico(bac_float)
                print("DEBUG - Interpretazione BAC:", interpretazione_bac)
            except Exception as e:
                print("DEBUG - Errore interpretazione BAC:", str(e))
                interpretazione_bac = None
    else:
        print("\nDEBUG - Nessun sorso registrato")

    if request.method == 'POST':
        volume = float(request.form.get('volume', 50))
        if volume > 0 and volume <= consumazione['fields']['Peso (g)']:
            # Registra il nuovo sorso
            nuovo_sorso = registra_sorso(consumazione_id, volume)
            print("\nDEBUG - Nuovo sorso registrato:", nuovo_sorso['fields'] if nuovo_sorso else None)
            if nuovo_sorso:
                # Aggiungo il flash con il BAC cumulativo e la sua interpretazione
                bac_cumulativo = nuovo_sorso['fields'].get('BAC Temporaneo')
                if bac_cumulativo is not None:
                    try:
                        bac_float = float(bac_cumulativo)
                        interpretazione = interpreta_tasso_alcolemico(bac_float)
                        flash(f'BAC cumulativo attuale: {bac_cumulativo} g/L\nStato: {interpretazione["livello"]}', 'info')
                    except Exception as e:
                        print("DEBUG - Errore interpretazione BAC:", str(e))
                        flash(f'BAC cumulativo attuale: {bac_cumulativo} g/L', 'info')
                return redirect(url_for('sorsi', consumazione_id=consumazione_id))
            else:
                flash('Errore durante la registrazione del sorso', 'danger')
        else:
            flash('Volume non valido', 'danger')

    # DEBUG: Controlla i valori prima di renderizzare il template
    print("\nDEBUG - PRIMA DI RENDERIZZARE TEMPLATE:")
    print("DEBUG - sorsi_registrati:", sorsi_registrati)
    print("DEBUG - bac_ultimo_sorso:", bac_ultimo_sorso)
    print("DEBUG - interpretazione_bac:", interpretazione_bac)

    return render_template('sorsi.html',
                         email=session['user_email'],
                         consumazione_id=consumazione_id,
                         volume_iniziale=consumazione['fields']['Peso (g)'],
                         sorsi_registrati=sorsi_registrati,
                         interpretazione_bac=interpretazione_bac,
                         bac_ultimo_sorso=bac_ultimo_sorso)

def get_consumazione_by_id(consumazione_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni/{consumazione_id}'
    response = requests.get(url, headers=get_airtable_headers())
    if response.status_code == 200:
        return response.json()
    return None

def get_sorsi_by_consumazione(consumazione_id):
    url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
    params = {
        'filterByFormula': f"{{Consumazione}}='{consumazione_id}'"
    }
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    if response.status_code == 200:
        return response.json().get('records', [])
    return []

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
        
        user_id = consumazione['fields']['User'][0]
        user = get_user_by_id(user_id)
        if not user:
            return None
        
        drink_id = consumazione['fields']['Drink'][0]
        drink = get_drink_by_id(drink_id)
        if not drink:
            return None
        
        # Dati per il calcolo
        peso_utente = user['fields']['Peso']
        genere = user['fields']['Genere'].lower()
        gradazione = drink['fields']['Gradazione']
        email_utente = user['fields']['Email']
        
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
                stomaco=consumazione['fields']['Stomaco'].lower(),
                ora_inizio=ora_inizio.strftime('%H:%M'),
                ora_fine=ora_fine.strftime('%H:%M')
            )
        except Exception as e:
            print(f"Errore nel calcolo del BAC: {str(e)}")
            return None

        # Se non ci sono sorsi precedenti, usa solo il BAC del nuovo sorso
        if not sorsi_giornalieri:
            bac_totale = bac_sorso
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
                bac_precedente = ultimo_sorso['fields'].get('BAC Temporaneo', 0.0)
                
                # Calcola il tempo trascorso dall'ultimo sorso
                ora_fine_ultimo = datetime.fromisoformat(ultimo_sorso['fields']['Ora fine'].replace('Z', '+00:00'))
                ora_fine_ultimo = ora_fine_ultimo.astimezone(TIMEZONE)
                tempo_trascorso = (ora_inizio - ora_fine_ultimo).total_seconds() / 3600
                
                # Calcola l'alcol metabolizzato nel tempo trascorso
                bac_vecchio = calcola_alcol_metabolizzato(bac_precedente, tempo_trascorso)
                
                # Il BAC totale è: BAC precedente metabolizzato + BAC nuovo sorso
                bac_totale = bac_vecchio + bac_sorso
                print(bac_precedente, bac_vecchio, bac_sorso)
            else:
                bac_totale = bac_sorso
        
        # Registra il sorso in Airtable
        url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
        data = {
            'records': [{
                'fields': {
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
            
        return response.json()['records'][0]
        
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

if __name__ == '__main__':
    app.run(debug=True)