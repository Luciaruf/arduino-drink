#!/usr/bin/env python3
"""
Script semplice per testare l'invio di dati di peso al server.
Utilizza l'endpoint semplificato /arduino_peso/<peso> per inviare dati.
"""

import requests
import time
import random
import sys

def invia_peso(peso):
    """
    Invia un valore di peso all'applicazione
    
    Args:
        peso: il valore del peso da inviare
    
    Returns:
        True se il peso è stato inviato con successo, False altrimenti
    """
    url = f"http://localhost:5000/arduino_peso/{peso}"
    
    print(f"Invio peso {peso}g a {url}...")
    
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print(f"✅ Peso inviato correttamente: {peso}g")
            print(f"Risposta: {response.json()}")
            return True
        else:
            print(f"❌ Errore nell'invio. Codice: {response.status_code}")
            if response.text:
                print(f"Risposta: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Errore di connessione: {e}")
        return False

def simulazione_consumazione(peso_iniziale=200, durata_simulazione=30):
    """
    Simula una consumazione di un drink, inviando dati di peso che diminuiscono gradualmente
    
    Args:
        peso_iniziale: peso iniziale del drink in grammi
        durata_simulazione: durata della simulazione in secondi
    """
    print(f"Avvio simulazione di consumazione con peso iniziale di {peso_iniziale}g...")
    
    # Invia il peso iniziale
    if not invia_peso(peso_iniziale):
        print("❌ Impossibile inviare il peso iniziale. Interruzione.")
        return
    
    # Attendi un momento per dare tempo all'interfaccia di mostrare il peso iniziale
    time.sleep(2)
    
    # Simula la diminuzione del peso (come se qualcuno stesse bevendo)
    peso_attuale = peso_iniziale
    tempo_inizio = time.time()
    
    while time.time() - tempo_inizio < durata_simulazione and peso_attuale > 0:
        # Diminuisci il peso di una quantità casuale tra 5 e 15 grammi
        diminuzione = random.uniform(5, 15)
        peso_attuale -= diminuzione
        
        # Assicura che il peso non vada sotto zero
        if peso_attuale < 0:
            peso_attuale = 0
            
        # Arrotonda a 1 decimale per una visualizzazione più pulita
        peso_attuale = round(peso_attuale, 1)
        
        # Invia il nuovo peso
        invia_peso(peso_attuale)
        
        # Attendi un po' prima del prossimo invio (tra 1.5 e 3.5 secondi)
        time.sleep(random.uniform(1.5, 3.5))
    
    print(f"Simulazione completata. Peso finale: {peso_attuale}g")

if __name__ == "__main__":
    # Se viene fornito un argomento, usalo come peso
    if len(sys.argv) > 1:
        try:
            peso = float(sys.argv[1])
            invia_peso(peso)
        except ValueError:
            print(f"Errore: '{sys.argv[1]}' non è un valore di peso valido.")
            print("Uso: python test_peso.py [peso]")
            print("     oppure: python test_peso.py sim [peso_iniziale] [durata]")
    elif len(sys.argv) > 2 and sys.argv[1] == "sim":
        # Modalità simulazione
        try:
            peso_iniziale = float(sys.argv[2])
            durata = int(sys.argv[3]) if len(sys.argv) > 3 else 30
            simulazione_consumazione(peso_iniziale, durata)
        except ValueError:
            print("Errore nei parametri della simulazione.")
            print("Uso: python test_peso.py sim [peso_iniziale] [durata]")
    else:
        # Nessun argomento, mostra le istruzioni
        print("Uso: python test_peso.py [peso]")
        print("     oppure: python test_peso.py sim [peso_iniziale] [durata]")
        print("\nEsempi:")
        print("  python test_peso.py 150        # Invia un peso di 150g")
        print("  python test_peso.py sim 200 30 # Simula una consumazione partendo da 200g per 30 secondi")
