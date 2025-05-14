from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
import requests
import time
from algoritmo import calcola_tasso_alcolemico_widmark, interpreta_tasso_alcolemico

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
                'Peso in kg': peso_kg,
                'Genere': genere
            }\
        }]\
    }
    response = requests.post(url, headers=get_airtable_headers(), json=data)
    return response.json()['records'][0]

def create_consumazione(user_id, drink_id, bar_id, peso_cocktail_g, stomaco_pieno_bool, timestamp_consumazione=None):
    if timestamp_consumazione is None:
        timestamp_consumazione = datetime.now()

    # 1. Recupera dati utente (peso, genere)
    user_data = get_user_by_id(user_id)
    if not user_data or 'fields' not in user_data:
        print(f"Errore: Utente {user_id} non trovato o dati incompleti.")
        return None
    
    user_fields = user_data['fields']
    peso_utente_kg = user_fields.get('Peso in kg')
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
    gradazione_drink = drink_fields.get('gradazione') # Assumendo es. 0.05 per 5%
    is_alcolico = drink_fields.get('Alcolico', False) # Default a non alcolico se non specificato

    tasso_calcolato = 0.0
    esito_calcolo = 'Positivo' # Default per non alcolici o errori

    if is_alcolico and gradazione_drink is not None and gradazione_drink > 0:
        # 3. Prepara parametri per l'algoritmo
        volume_ml = float(peso_cocktail_g) # Assumendo 1g = 1ml
        gradazione_percent = float(gradazione_drink) # L'algoritmo si aspetta es. 0.12
        
        genere_str = str(genere_utente).lower() # L'algoritmo si aspetta 'uomo' o 'donna'
        if genere_str not in ['uomo', 'donna']:
            print(f"Errore: Genere non valido '{genere_str}' per l'utente {user_id}.")
            return None # O gestisci un default

        stomaco_str = 'pieno' if stomaco_pieno_bool else 'vuoto'
        
        ora_inizio_dt = timestamp_consumazione
        ora_fine_dt = ora_inizio_dt + timedelta(hours=2) # Modificato da 15 minuti a 2 ore

        ora_inizio_str = ora_inizio_dt.strftime('%H:%M')
        ora_fine_str = ora_fine_dt.strftime('%H:%M')
        
        tasso_calcolato = calcola_tasso_alcolemico_widmark(
            peso=float(peso_utente_kg),
            genere=genere_str,
            volume=volume_ml,
            gradazione=gradazione_percent,
            stomaco=stomaco_str,
            ora_inizio=ora_inizio_str,
            ora_fine=ora_fine_str # Ora include i 15 minuti di consumo
        )
        
        interpretazione = interpreta_tasso_alcolemico(tasso_calcolato)
        esito_calcolo = 'Positivo' if interpretazione['legale'] else 'Negativo'
    else:
        # Drink non alcolico o gradazione zero
        tasso_calcolato = 0.0
        esito_calcolo = 'Positivo' # Non c'è alcol

    # 4. Salva in Airtable
    url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
    data_to_save = {
        'records': [{
            'fields': {
                'User': [user_id],
                'Drink': [drink_id],
                'Bar': [bar_id],
                'timestamp': timestamp_consumazione.isoformat(),
                'Peso (in g) del cocktail ricevuto da arduino': float(peso_cocktail_g),
                "tasso calcolato g/L dall'algoritmo": round(tasso_calcolato, 3),
                'Stomaco (bool se pieno o vuoto)': stomaco_pieno_bool,
                'Risultato (positivo o negativo)': esito_calcolo
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
    
    consumazione_creata = None # Per conservare i dati della consumazione e passarli al template
    tasso_visualizzato = None
    esito_visualizzato = None
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
                tasso_visualizzato = consumazione_creata['fields'].get("tasso calcolato g/L dall'algoritmo")
                esito_visualizzato = consumazione_creata['fields'].get("Risultato (positivo o negativo)")
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
                         # peso_da_arduino=current_peso_cocktail_g, # Vecchia variabile, ora usiamo quella sotto
                         valore_peso_utilizzato=current_peso_cocktail_g, # Passa il valore effettivamente usato
                         usando_peso_fisso_test=usando_peso_fisso_test) # Passa il flag

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Devi essere loggato')
        return redirect(url_for('login'))

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
        timestamp_consumazione_str = cons.get('timestamp')
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
            'peso_cocktail': cons.get('Peso (in g) del cocktail ricevuto da arduino', 'N/D'),
            'tasso': cons.get("tasso calcolato g/L dall'algoritmo", 'N/D'),
            'esito': cons.get("Risultato (positivo o negativo)", 'N/D'),
            'stomaco': 'Pieno' if cons.get('Stomaco (bool se pieno o vuoto)', False) else 'Vuoto'
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

        return render_template('dashboard.html',
                             bar=None, # Indica che siamo in dashboard globale
                             consumazioni_dettagliate=consumazioni_utente_dettagliate,
                             user_drinks_aggregati=user_drinks_list_aggregated, # Passiamo il vecchio aggregato
                             classifica=classifica_generale)

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

    return render_template('dashboard.html',
                         bar=current_bar_details, # Passa i dettagli del bar selezionato
                         consumazioni_dettagliate=consumazioni_utente_dettagliate,
                         user_drinks_aggregati=user_drinks_list_specific_bar, # Aggregati per questo bar
                         classifica=classifica_specific_bar)

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