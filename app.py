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
        # Potresti voler sollevare un'eccezione o gestire diversamente
        return None

    # 2. Recupera dati drink (gradazione, alcolico)
    drink_data = get_drink_by_id(drink_id)
    if not drink_data or 'fields' not in drink_data:
        print(f"Errore: Drink {drink_id} non trovato o dati incompleti.")
        return None

    drink_fields = drink_data['fields']
    print(f"DEBUG SIMULA: Dati del drink recuperati da Airtable: {drink_fields}") # DEBUG PRINT
    
    gradazione_drink = drink_fields.get('Gradazione')
    valore_alcolico_da_airtable = drink_fields.get('Alcolico (bool)')
    is_alcolico = True if valore_alcolico_da_airtable == '1' else False
    
    print(f"DEBUG SIMULA: gradazione_drink={gradazione_drink}, tipo={type(gradazione_drink)}") # DEBUG PRINT
    print(f"DEBUG SIMULA: valore_alcolico_da_airtable={valore_alcolico_da_airtable}, tipo={type(valore_alcolico_da_airtable)}") # DEBUG PRINT
    print(f"DEBUG SIMULA: is_alcolico={is_alcolico}, tipo={type(is_alcolico)}") # DEBUG PRINT

    tasso_calcolato = 0.0
    esito_calcolo = 'Negativo'

    # Definisci stomaco_str qui, in base all'input booleano
    stomaco_str = 'Pieno' if stomaco_pieno_bool else 'Vuoto'

    if is_alcolico and gradazione_drink is not None and gradazione_drink > 0:
        # 3. Prepara parametri per l'algoritmo
        volume_ml = float(peso_cocktail_g)
        gradazione_percent = float(gradazione_drink)
        
        genere_str = str(genere_utente).lower()
        if genere_str not in ['uomo', 'donna']:
            print(f"Errore: Genere non valido '{genere_str}' per l'utente {user_id}.")
            return None 

        # stomaco_str è già definito sopra, qui era specifico per l'algoritmo che voleva minuscolo
        # ma ora l'algoritmo riceve già 'pieno' o 'vuoto' e Airtable vuole 'Pieno' o 'Vuoto'
        # quindi la definizione sopra va bene per entrambi se l'algoritmo gestisce maiuscole/minuscole indifferentemente
        # Oppure, per l'algoritmo, usiamo .lower()
        stomaco_per_algoritmo = stomaco_str.lower() # Assicuriamoci sia minuscolo per l'algoritmo
        
        ora_inizio_dt = timestamp_consumazione
        ora_fine_dt = ora_inizio_dt + timedelta(hours=2) # Modificato da 15 minuti a 2 ore

        ora_inizio_str = ora_inizio_dt.strftime('%H:%M')
        ora_fine_str = ora_fine_dt.strftime('%H:%M')
        
        tasso_calcolato = calcola_tasso_alcolemico_widmark(
            peso=float(peso_utente_kg),
            genere=genere_str,
            volume=volume_ml,
            gradazione=gradazione_percent,
            stomaco=stomaco_per_algoritmo, # Passa la versione minuscola all'algoritmo
            ora_inizio=ora_inizio_str,
            ora_fine=ora_fine_str, # Ora include i 15 minuti di consumo
        )
        
        interpretazione = interpreta_tasso_alcolemico(tasso_calcolato)
        # Esito: "Negativo" se legale (<=0.5), "Positivo" se non legale (>0.5)
        esito_calcolo = 'Negativo' if interpretazione['legale'] else 'Positivo'
    else:
        # Drink non alcolico o gradazione zero
        tasso_calcolato = 0.0
        esito_calcolo = 'Negativo' # Considerato "negativo" all'alcol se non c'è alcol o è analcolico

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
    
    consumazione_creata = None
    tasso_visualizzato = None
    esito_visualizzato = None
    livello_messaggio = None
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
                tasso_visualizzato = consumazione_creata['fields'].get("Tasso Calcolato (g/L)")
                esito_visualizzato = consumazione_creata['fields'].get("Risultato")
                
                # Ottieni anche il messaggio di livello per la visualizzazione
                if tasso_visualizzato is not None:
                    try:
                        # Assicurati che tasso_visualizzato sia un float per la funzione dell'algoritmo
                        tasso_float = float(tasso_visualizzato)
                        interpretazione_dettagliata = interpreta_tasso_alcolemico(tasso_float)
                        if interpretazione_dettagliata and 'livello' in interpretazione_dettagliata:
                            livello_messaggio = interpretazione_dettagliata['livello']
                    except ValueError:
                        livello_messaggio = "N/A (tasso non numerico)"
                        
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
                         tasso=tasso_visualizzato,
                         drink_selezionato=drink_selezionato_obj,
                         esito=esito_visualizzato,
                         livello=livello_messaggio,
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
    
    # Recupera i sorsi già registrati
    sorsi_registrati = get_sorsi_by_consumazione(consumazione_id)
    
    if request.method == 'POST':
        volume = float(request.form.get('volume', 50))
        if volume > 0 and volume <= consumazione['fields']['Peso (g)']:
            # Registra il nuovo sorso
            nuovo_sorso = registra_sorso(consumazione_id, volume)
            if nuovo_sorso:
                flash('Sorso registrato con successo', 'success')
                return redirect(url_for('sorsi', consumazione_id=consumazione_id))
            else:
                flash('Errore durante la registrazione del sorso', 'danger')
        else:
            flash('Volume non valido', 'danger')
    
    return render_template('sorsi.html',
                         email=session['user_email'],
                         consumazione_id=consumazione_id,
                         volume_iniziale=consumazione['fields']['Peso (g)'],
                         sorsi_registrati=sorsi_registrati)

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
    """Recupera tutti i sorsi dell'utente per la giornata corrente e/o per una specifica consumazione"""
    url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
    params = {
        'filterByFormula': f"{{Email}}='{email}'"
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
                
                # Filtra per data e opzionalmente per consumazione
                if timestamp.date() == oggi:
                    if consumazione_id is None or sorso['fields'].get('Consumazioni Id', [None])[0] == consumazione_id:
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
        
        # Calcola il BAC cumulativo dei sorsi precedenti
        lista_bevande_precedenti = []
        for sorso in sorsi_giornalieri:
            if 'fields' in sorso and 'Ora inizio' in sorso['fields']:
                # Recupera la consumazione associata al sorso
                consumazione_sorso_id = sorso['fields'].get('Consumazioni Id', [None])[0]
                if consumazione_sorso_id:
                    consumazione_sorso = get_consumazione_by_id(consumazione_sorso_id)
                    if consumazione_sorso and 'Drink' in consumazione_sorso['fields']:
                        drink_sorso_id = consumazione_sorso['fields']['Drink'][0]
                        drink_sorso = get_drink_by_id(drink_sorso_id)
                        if drink_sorso and 'Gradazione' in drink_sorso['fields']:
                            gradazione_sorso = float(drink_sorso['fields']['Gradazione'])
                            
                            timestamp = datetime.fromisoformat(sorso['fields']['Ora inizio'].replace('Z', '+00:00'))
                            timestamp = timestamp.astimezone(TIMEZONE)
                            lista_bevande_precedenti.append({
                                'volume': sorso['fields']['Volume (g)'],
                                'gradazione': gradazione_sorso,
                                'ora_inizio': timestamp.strftime('%H:%M'),
                                'ora_fine': (timestamp + timedelta(minutes=15)).strftime('%H:%M')
                            })

        # Se ci sono sorsi precedenti, calcola il loro BAC cumulativo
        bac_precedente = 0.0
        bac = 0.0
        alcol_metabolizzato = 0.0
        if lista_bevande_precedenti:
            risultato_precedente = calcola_bac_cumulativo(
                peso=float(peso_utente),
                genere=genere,
                lista_bevande=lista_bevande_precedenti,
                stomaco=consumazione['fields']['Stomaco'].lower()
            )
            bac_precedente += risultato_precedente['bac_finale']
            
            # Calcola l'alcol metabolizzato dai sorsi precedenti
            ora_attuale = datetime.now(TIMEZONE)
            for bevanda in lista_bevande_precedenti:
                # Usa direttamente le stringhe orarie dalla lista_bevande_precedenti
                ora_inizio_str = bevanda['ora_inizio']
                ora_fine_str = bevanda['ora_fine']
                
                # Calcola il tempo trascorso in ore
                ora_inizio_dt = datetime.strptime(ora_inizio_str, '%H:%M')
                ora_inizio_dt = TIMEZONE.localize(datetime.combine(ora_attuale.date(), ora_inizio_dt.time()))
                tempo_trascorso = (ora_attuale - ora_inizio_dt).total_seconds() / 3600
                
                # Calcola l'alcol metabolizzato per questa bevanda usando la sua gradazione specifica
                bac += calcola_alcol_metabolizzato(
                    bac=calcola_tasso_alcolemico_widmark(
                        peso=float(peso_utente),
                        genere=genere,
                        volume=bevanda['volume'],  # Usa il volume del sorso precedente
                        gradazione=bevanda['gradazione'],  # Usa la gradazione del sorso precedente
                        stomaco=consumazione['fields']['Stomaco'].lower(),
                        ora_inizio=ora_inizio_str,
                        ora_fine=ora_fine_str
                    ),
                    tempo_ore=tempo_trascorso
                )
                
        # Usa l'ora corrente per il nuovo sorso
        try:
            ora_inizio = datetime.now(TIMEZONE)
            ora_fine = ora_inizio + timedelta(minutes=15)
        except Exception as e:
            print(f"Errore nel calcolo delle date: {str(e)}")
            return None
        
        try:
            # Calcola il BAC per il nuovo sorso
            bac_sorso = calcola_tasso_alcolemico_widmark(
                peso=float(peso_utente),
                genere=genere,
                volume=volume,
                gradazione=float(gradazione),
                stomaco=consumazione['fields']['Stomaco'].lower(),
                ora_inizio=ora_inizio.strftime('%H:%M'),
                ora_fine = ora_inizio.strftime('%H:%M')
            )
        except Exception as e:
            print(f"Errore nel calcolo del BAC: {str(e)}")
            return None
        
        # Registra il sorso in Airtable
        url = f'https://api.airtable.com/v0/{BASE_ID}/Sorsi'
        data = {
            'records': [{
                'fields': {
                    'Consumazioni Id': [consumazione_id],
                    'Volume (g)': volume,
                    'Email': email_utente,
                    'BAC Temporaneo': round(bac + bac_sorso, 3),
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
    
if __name__ == '__main__':
    app.run(debug=True)