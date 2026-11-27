"""Exploratory non-English examples; labels are not native-speaker verified."""
import json
import re
from pathlib import Path

sets = {
    "es": [
        ("¡Dios, la puerta está cerrada!", "Dios", "deity", 1), ("Rezamos a Dios antes del viaje.", "Dios", "deity", 0),
        ("El tornillo sujeta la placa de metal.", "tornillo", "profanity", 0), ("¡Maldita sea, perdimos el mapa!", "Maldita", "profanity", 1),
        ("La perra cuidó a sus cachorros.", "perra", "profanity", 0), ("Eres un idiota, deja de mentir.", "idiota", "profanity", 1),
        ("Jesús predicó la paz en el pueblo.", "Jesús", "deity", 0), ("¡Jesús, qué explosión tan fuerte!", "Jesús", "deity", 1),
        ("El infierno aparece en la leyenda.", "infierno", "profanity", 0), ("Vete al infierno, traidor.", "infierno", "profanity", 1),
        ("El asno llevó las cajas al mercado.", "asno", "profanity", 0), ("El capitán llamó bastardo al ladrón.", "bastardo", "profanity", 1),
        ("La señora Dick vive junto al puente.", "Dick", "profanity", 0), ("¡Dios mío, el motor se apagó!", "Dios", "deity", 1),
        ("El sacerdote habló del Señor.", "Señor", "deity", 0), ("Señor, olvidé las llaves.", "Señor", "deity", 1),
        ("La perra blanca duerme junto al fuego.", "perra", "profanity", 0), ("¡Maldito guardia, abre la puerta!", "Maldito", "profanity", 1),
        ("El tornillo cayó debajo de la mesa.", "tornillo", "profanity", 0), ("El idiota rompió la radio.", "idiota", "profanity", 1),
    ],
    "fr": [
        ("Mon Dieu, le pont vient de tomber !", "Dieu", "deity", 1), ("Ils prient Dieu chaque matin.", "Dieu", "deity", 0),
        ("La vis tient la plaque au mur.", "vis", "profanity", 0), ("Merde, la porte est bloquée !", "Merde", "profanity", 1),
        ("La chienne protège ses petits.", "chienne", "profanity", 0), ("Espèce d'idiot, recule !", "idiot", "profanity", 1),
        ("Jésus enseignait la compassion.", "Jésus", "deity", 0), ("Jésus, quelle détonation !", "Jésus", "deity", 1),
        ("Le prêtre décrit l'enfer dans son sermon.", "enfer", "profanity", 0), ("Va en enfer, traître !", "enfer", "profanity", 1),
        ("L'âne tire la charrette jusqu'au village.", "âne", "profanity", 0), ("Le capitaine l'a traité de salaud.", "salaud", "profanity", 1),
        ("Dick habite près du vieux moulin.", "Dick", "profanity", 0), ("Bon Dieu, le moteur est arrêté !", "Dieu", "deity", 1),
        ("Le Seigneur veille sur les voyageurs.", "Seigneur", "deity", 0), ("Seigneur, j'ai perdu la carte !", "Seigneur", "deity", 1),
        ("La chienne blanche dort près du feu.", "chienne", "profanity", 0), ("Maudit voleur, rends la clé !", "Maudit", "profanity", 1),
        ("La vis est tombée sous la table.", "vis", "profanity", 0), ("Quel imbécile a coupé le câble ?", "imbécile", "profanity", 1),
    ],
    "de": [
        ("Gott, die Brücke ist eingestürzt!", "Gott", "deity", 1), ("Sie beten zu Gott vor der Reise.", "Gott", "deity", 0),
        ("Die Schraube hält die Platte fest.", "Schraube", "profanity", 0), ("Verdammt, die Tür ist verriegelt!", "Verdammt", "profanity", 1),
        ("Die Hündin bewacht ihre Welpen.", "Hündin", "profanity", 0), ("Du Idiot, geh aus dem Weg!", "Idiot", "profanity", 1),
        ("Jesus predigte Frieden im Dorf.", "Jesus", "deity", 0), ("Jesus, was für eine Explosion!", "Jesus", "deity", 1),
        ("Der Priester spricht von der Hölle.", "Hölle", "profanity", 0), ("Fahr zur Hölle, Verräter!", "Hölle", "profanity", 1),
        ("Der Esel trägt die Kisten zum Markt.", "Esel", "profanity", 0), ("Der Hauptmann nannte ihn einen Bastard.", "Bastard", "profanity", 1),
        ("Dick wohnt neben der alten Mühle.", "Dick", "profanity", 0), ("Mein Gott, der Motor ist ausgefallen!", "Gott", "deity", 1),
        ("Der Herr beschützt die Reisenden.", "Herr", "deity", 0), ("Herr, ich habe den Schlüssel verloren!", "Herr", "deity", 1),
        ("Die Hündin schläft am warmen Feuer.", "Hündin", "profanity", 0), ("Verdammter Dieb, gib den Schlüssel zurück!", "Verdammter", "profanity", 1),
        ("Eine Schraube lag unter dem Tisch.", "Schraube", "profanity", 0), ("Der Idiot hat das Funkgerät zerstört.", "Idiot", "profanity", 1),
    ],
}

out = []
for language, rows in sets.items():
    for sentence, word, category, label in rows:
        m = re.search(re.escape(word), sentence, re.I)
        out.append({"language": language, "sentence": sentence, "target_word": word,
                    "start": m.start(), "end": m.end(), "category": category,
                    "label": label, "confidence_note": "unverified non-native label"})
dest = Path(r"C:\scratch\asr50\WP23\labels\multilingual.json")
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {len(out)} exploratory cases")
