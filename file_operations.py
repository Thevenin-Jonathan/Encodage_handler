import os
import json
import subprocess
import sys
from constants import debug_mode, dossier_encodage_manuel, dossier_sortie
from utils import horodatage

# Définir le chemin du fichier en fonction de l'exécution en tant que script ou exécutable
if hasattr(sys, "_MEIPASS"):
    THIS_FILEPATH = os.path.dirname(sys.executable)
else:
    THIS_FILEPATH = os.path.dirname(__file__)

fichier_encodage_manuel = os.path.join(THIS_FILEPATH, "Encodage_manuel.txt")


def obtenir_pistes(filepath):
    """
    Exécute HandBrakeCLI pour scanner le fichier spécifié et obtenir des informations sur les pistes
    sous forme de JSON.

    Arguments:
    filepath -- Chemin du fichier à analyser.

    Retourne:
    Un dictionnaire contenant les informations des pistes si réussi, None sinon.
    """
    commande = ["HandBrakeCLI", "-i", filepath, "--scan", "--json"]
    result = subprocess.run(commande, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erreur lors de l'exécution de HandBrakeCLI: {result.stderr}")
        return None
    if not result.stdout.strip():  # Vérification supplémentaire
        print("Erreur : la sortie de HandBrakeCLI est vide.")
        return None
    try:
        # Extraire uniquement la partie JSON correcte de la sortie
        json_start = result.stdout.find("{", result.stdout.find("JSON Title Set:"))
        json_end = result.stdout.rfind("}") + 1
        json_str = result.stdout[json_start:json_end]
        info_pistes = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Erreur de décodage JSON: {e}")
        return None
    return info_pistes


def verifier_dossiers():
    """
    Vérifie si les dossiers de sortie et d'encodage manuel existent, et les crée sinon.
    """
    if not os.path.exists(dossier_sortie):
        os.makedirs(dossier_sortie)
    if not os.path.exists(dossier_encodage_manuel):
        os.makedirs(dossier_encodage_manuel)


def ajouter_fichier_a_liste_encodage_manuel(filepath):
    """
    Ajoute le nom du fichier spécifié dans une liste dans un document .txt à la racine du projet.

    Arguments:
    filepath -- Chemin du fichier à ajouter.
    """
    base_name = os.path.basename(filepath)
    liste_fichiers_path = fichier_encodage_manuel

    # Instructions de débogage
    if debug_mode:
        print(f"Chemin du fichier d'encodage manuel : {liste_fichiers_path}")

    try:
        if not os.path.exists(liste_fichiers_path):
            open(liste_fichiers_path, "w").close()
            print(f"Fichier créé : {liste_fichiers_path}")
        with open(liste_fichiers_path, "a") as file:
            file.write(base_name + "\n")
            print(
                f"{horodatage()} 📁 Nom du fichier ajouté à la liste d'encodage manuel : {base_name}"
            )
    except Exception as e:
        print(f"Erreur lors de l'écriture dans le fichier : {e}")
