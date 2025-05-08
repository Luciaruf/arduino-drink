# definiamo l'algoritmo per il calcolo del bac 

from datetime import datetime, timedelta

def calcola_tasso_alcolemico_widmark(peso, genere, volume, gradazione, stomaco, ora_inizio, ora_fine):
    """
    Calcola il tasso alcolemico usando la formula di Widmark per una singola bevanda.
    
    Args:
        peso (float): Peso in kg
        genere (str): 'uomo' o 'donna'
        volume (float): Volume della bevanda in ml, N.B. è da passare la variazione di volume in ml
        gradazione (float): Gradazione alcolica in percentuale (es. 0.12, NON LA PERCENTUALE)
        stomaco (str): 'pieno' o 'vuoto'
        ora_inizio (str): Ora di inizio consumo nel formato 'HH:MM'
        ora_fine (str): Ora di fine consumo nel formato 'HH:MM'
    
    Returns:
        float: Tasso alcolemico in g/l
    """
    # Costanti di Widmark
    r = 0.68 if genere == 'uomo' else 0.55  # Fattore di distribuzione
    beta = 0.15  # Tasso di eliminazione dell'alcol (g/l per ora)
    
    # Calcolo del tempo di consumo in ore
    inizio = datetime.strptime(ora_inizio, '%H:%M')
    fine = datetime.strptime(ora_fine, '%H:%M')
    if fine < inizio:  # Se il consumo passa la mezzanotte
        fine = fine + timedelta(days=1)
    tempo_consumazione = (fine - inizio).total_seconds() / 3600  # Converti in ore
    
    # Calcolo grammi di alcol puro
    grammi_alcol = volume * (gradazione) * 0.789  # 0.789 è la densità dell'alcol
    
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
    
    bac = (grammi_alcol * assorbimento) / (peso * r) - (beta * tempo_consumazione)
    
    # BAC non negativo
    bac = max(0, bac)
    
    return round(bac, 3)

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
    elif bac >=0.3 and bac < 0.45:
        return {
            'livello': 'Stai quasi raggiungendo il limite legale',
            'legale': True
        }
    elif bac >=0.45 and bac < 0.5:
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
    # Esempio di calcolo con una singola bevanda
    bac = calcola_tasso_alcolemico_widmark(
        peso=70,
        genere='uomo',
        volume=200,  # ml
        gradazione=0.12,  # 12%
        stomaco='pieno',
        ora_inizio='20:00',
        ora_fine='21:00'
    )
    
    print(f"Tasso alcolemico: {bac} g/l")
    
    interpretazione = interpreta_tasso_alcolemico(bac)
    print(f"\nInterpretazione:")
    print(f"Livello: {interpretazione['livello']}")
    print(f"Legale: {'Sì' if interpretazione['legale'] else 'No'}")
    
    tempo_sober = calcola_tempo_sober(bac)
    print(f"\nTempo stimato per tornare sobri: {tempo_sober}")

    
