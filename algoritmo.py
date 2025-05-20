# definiamo l'algoritmo per il calcolo del bac 

from datetime import datetime, timedelta

def calcola_tasso_alcolemico_widmark(peso, genere, volume, gradazione, stomaco, ora_inizio, ora_fine):
    """
    Calcola il tasso alcolemico usando la formula di Widmark per una singola bevanda.
    
    Args:
        peso (float): Peso in kg
        genere (str): 'uomo' o 'donna'
        volume (float): Volume della bevanda in ml
        gradazione (float): Gradazione alcolica in percentuale (es. 0.12, NON LA PERCENTUALE)
        stomaco (str): 'pieno' o 'vuoto'
        ora_inizio (str): Ora di inizio consumo nel formato 'HH:MM'
        ora_fine (str): Ora di fine consumo nel formato 'HH:MM'
        bac_precedente (float): Tasso alcolemico precedente in g/l
    
    Returns:
        float: Tasso alcolemico in g/l
    """
    bac_totale = 0.0
    # Costanti di Widmark
    r = 0.68 if genere == 'uomo' else 0.55  # Fattore di distribuzione
    beta = 0.15  # Tasso di eliminazione dell'alcol (g/l per ora)
    densità_alcol = 0.789  # Densità dell'alcol etilico in g/ml
    
    # Calcolo del tempo di consumo in ore
    inizio = datetime.strptime(ora_inizio, '%H:%M')
    fine = datetime.strptime(ora_fine, '%H:%M')
    if fine < inizio:  # Se il consumo passa la mezzanotte
        fine = fine + timedelta(days=1)
    tempo_consumazione = (fine - inizio).total_seconds() / 3600  # Converti in ore
    
    # Calcolo grammi di alcol puro
    # 1. Calcola il volume di alcol puro in ml
    volume_alcol_ml = volume * gradazione
    # 2. Converti il volume di alcol in grammi usando la densità
    grammi_alcol = volume_alcol_ml * densità_alcol
    
    # Fattore di assorbimento basato sullo stato dello stomaco
    assorbimento = 1.0 if stomaco == 'vuoto' else 0.7
    
    # Calcolo BAC usando la formula di Widmark
    # BAC = (A * assorbimento) / (W * r) - (beta * t)
    # dove:
    # A = grammi di alcol
    # W = peso in kg
    # r = fattore di distribuzione
    # beta = tasso di eliminazione
    # t = tempo in ore
    
    bac_nuovo = (grammi_alcol * assorbimento) / (peso * r) - (beta * tempo_consumazione)
    
    # BAC non negativo
    bac_nuovo = max(0, bac_nuovo)

    bac_totale += bac_nuovo

    return round(bac_totale, 3)

def calcola_alcol_metabolizzato(bac, tempo_ore):
    """
    Calcola quanto alcol è stato metabolizzato in un determinato periodo di tempo.
    
    Args:
        bac (float): Tasso alcolemico iniziale in g/l
        tempo_ore (float): Tempo trascorso in ore
    
    Returns:
        float: Tasso alcolemico dopo il metabolismo
    """
    beta = 0.15  # Tasso di eliminazione dell'alcol (g/l per ora)
    alcol_metabolizzato = beta * tempo_ore
    nuovo_bac = max(0, bac - alcol_metabolizzato)
    return round(nuovo_bac, 3)

def calcola_tempo_trascorso(ora_inizio, ora_fine):
    """
    Calcola il tempo trascorso tra due orari.
    
    Args:
        ora_inizio (str): Ora di inizio nel formato 'HH:MM'
        ora_fine (str): Ora di fine nel formato 'HH:MM'
    
    Returns:
        tuple: (tempo_trascorso, unità_misura) dove:
            - tempo_trascorso è un float
            - unità_misura è 'ore' o 'minuti'
    """
    inizio = datetime.strptime(ora_inizio, '%H:%M')
    fine = datetime.strptime(ora_fine, '%H:%M')
    if fine < inizio:  # Se il tempo passa la mezzanotte
        fine = fine + timedelta(days=1)
    
    tempo_ore = (fine - inizio).total_seconds() / 3600
    
    if tempo_ore < 1:
        tempo_minuti = round(tempo_ore * 60)
        return tempo_minuti, 'minuti'
    else:
        return round(tempo_ore, 2), 'ore'

def calcola_bac_cumulativo(peso, genere, lista_bevande, stomaco):
    """
    Calcola il tasso alcolemico cumulativo per una lista di bevande.
    
    Args:
        peso (float): Peso in kg
        genere (str): 'uomo' o 'donna'
        lista_bevande (list): Lista di dizionari contenenti le informazioni delle bevande
            Ogni dizionario deve contenere:
            - volume (float): Volume in ml
            - gradazione (float): Gradazione alcolica (es. 0.12)
            - ora_inizio (str): Ora di inizio nel formato 'HH:MM'
            - ora_fine (str): Ora di fine nel formato 'HH:MM'
        stomaco (str): 'pieno' o 'vuoto'
    
    Returns:
        dict: Dizionario contenente il BAC finale e la storia del metabolismo
    """
    bac_totale = 0
    storia_metabolismo = []
    
    for i, bevanda in enumerate(lista_bevande):
        # Se non è la prima bevanda, calcola il metabolismo dal drink precedente
        if i > 0:
            bevanda_precedente = lista_bevande[i-1]
            tempo_trascorso, unità = calcola_tempo_trascorso(
                bevanda_precedente['ora_fine'],
                bevanda['ora_inizio']
            )
            # Converti in ore per il calcolo del metabolismo
            tempo_ore = tempo_trascorso / 60 if unità == 'minuti' else tempo_trascorso
            bac_totale += calcola_tasso_alcolemico_widmark(peso, genere, bevanda_precedente['volume'], bevanda_precedente['gradazione'], stomaco, bevanda_precedente['ora_fine'], bevanda_precedente['ora_inizio'])
            
            storia_metabolismo.append({
                'tempo_trascorso': tempo_trascorso,
                'unità': unità,
                'bac_dopo_metabolismo': bac_totale
            })
        
        # Calcola il nuovo BAC aggiungendo la bevanda corrente
        bac_totale += calcola_tasso_alcolemico_widmark(
            peso=peso,
            genere=genere,
            volume=bevanda['volume'],
            gradazione=bevanda['gradazione'],
            stomaco=stomaco,
            ora_inizio=bevanda['ora_inizio'],
            ora_fine=bevanda['ora_fine']
        )
    
    return {
        'bac_finale': bac_totale,
        'storia_metabolismo': storia_metabolismo
    }

def interpreta_tasso_alcolemico(bac):
    """
    Interpreta il tasso alcolemico, fornisce se legale il tasso o meno
    
    Args:
        bac (float): Tasso alcolemico in g/l
    
    Returns:
        dict: Dizionario con interpretazione e livello legale
    """
    if bac == 0:
        return {
            'livello': 'Astemio',
            'legale': True
        }
    elif bac < 0.3:
        return {
            'livello': 'Sobrio',
            'legale': True
        }
    elif bac >= 0.3 and bac < 0.45:
        return {
            'livello': 'Stai quasi raggiungendo il limite legale',
            'legale': True
        }
    elif bac >= 0.45 and bac <= 0.5:
        return {
            'livello': 'Attenzione, sei vicino al limite legale',
            'legale': True
        }
    elif bac > 0.5:
        return {
            'livello': 'Attenzione, non mettersi alla guida',
            'legale': False
        }

def calcola_tempo_sober(bac):
    """
    Calcola il tempo stimato necessario per tornare sobri.
    Se il tempo è inferiore a un'ora, viene restituito in minuti.
    
    Args:
        bac (float): Tasso alcolemico attuale in g/l
    
    Returns:
        str: Tempo stimato in ore o minuti
    """
    beta = 0.15  # Tasso di eliminazione dell'alcol (g/l per ora)
    tempo_ore = bac / beta
    
    if tempo_ore < 1:
        tempo_minuti = round(tempo_ore * 60)
        return f"{tempo_minuti} minuti"
    else:
        return f"{round(tempo_ore, 1)} ore"

# Esempio di utilizzo
if __name__ == "__main__":
    # Esempio di calcolo con multiple bevande
    lista_bevande = [
        {
            'volume': 100,  # Un drink da 100ml
            'gradazione': 0.12,  # 12% di alcol
            'ora_inizio': '20:00',
            'ora_fine': '20:05'
        },
        {
            'volume': 200,  # Un drink completo
            'gradazione': 0.12,  # 12% di alcol
            'ora_inizio': '20:30',
            'ora_fine': '21:00'
        }
    ]
    
    risultato = calcola_bac_cumulativo(
        peso=70,
        genere='uomo',
        lista_bevande=lista_bevande,
        stomaco='pieno'
    )
    
    print(f"\nTasso alcolemico finale: {risultato['bac_finale']} g/l")
    
    print("\nStoria del metabolismo:")
    for i, metabolismo in enumerate(risultato['storia_metabolismo']):
        print(f"Tra il drink {i+1} e {i+2}:")
        print(f"  Tempo trascorso: {metabolismo['tempo_trascorso']} {metabolismo['unità']}")
        print(f"  BAC dopo metabolismo: {metabolismo['bac_dopo_metabolismo']} g/l")
    
    interpretazione = interpreta_tasso_alcolemico(risultato['bac_finale'])
    print(f"\nInterpretazione:")
    print(f"Livello: {interpretazione['livello']}")
    print(f"Legale: {'Sì' if interpretazione['legale'] else 'No'}")
    
    tempo_sober = calcola_tempo_sober(risultato['bac_finale'])
    print(f"\nTempo stimato per tornare sobri: {tempo_sober}")

    
