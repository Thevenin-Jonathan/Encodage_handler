import threading
import os
import subprocess
import re
import time
from tqdm import tqdm
from audio_selection import selectionner_pistes_audio
from subtitle_selection import selectionner_sous_titres
from constants import (
    dossier_sortie,
    debug_mode,
    fichier_presets,
)
from utils import horodatage, tronquer_nom_fichier
from file_operations import (
    obtenir_pistes,
    verifier_dossiers,
    ajouter_fichier_a_liste_encodage_manuel,
)
from command_builder import construire_commande_handbrake
from notifications import (
    notifier_encodage_lancement,
    notifier_encodage_termine,
    notifier_erreur_encodage,
)
from logger import setup_logger

# Configuration du logger
logger = setup_logger(__name__)

# Verrou pour synchroniser l'accès à la console
console_lock = threading.Lock()


def read_output(pipe, process_output):
    """
    Lit les sorties standard (stdout) et les erreurs (stderr) d'un processus en cours
    et les affiche dans la console tout en les ajoutant à une liste.

    Arguments:
    pipe -- Flux de sortie ou d'erreur du processus.
    process_output -- Liste pour stocker les sorties lues.
    """
    for line in iter(pipe.readline, ""):
        with console_lock:
            print(line, end="")
        process_output.append(line)
    pipe.close()


def lancer_encodage(dossier, fichier, preset, file_encodage):
    """
    Lance l'encodage d'un fichier en utilisant HandBrakeCLI avec le preset spécifié.
    Gère les options audio et sous-titres, et met à jour la console et les notifications.

    Arguments:
    dossier -- Chemin du dossier contenant le fichier à encoder.
    fichier -- Nom du fichier à encoder.
    preset -- Preset HandBrakeCLI à utiliser pour l'encodage.
    file_encodage -- Queue pour la file d'attente d'encodage.
    """

    # Ajouter ces vérifications avant de lancer l'encodage

    # Vérifier si le fichier existe et est accessible
    if not os.path.exists(fichier) or not os.access(fichier, os.R_OK):
        logger.error(
            f"Le fichier {fichier} n'existe pas ou n'est pas accessible en lecture"
        )
        return False

    # Vérifier si le fichier est vide ou trop petit
    file_size = os.path.getsize(fichier)
    if file_size < 1024 * 1024:  # Moins de 1 MB
        logger.warning(
            f"Le fichier {fichier} est trop petit ({file_size} octets), pourrait être corrompu"
        )

    # Récupérer uniquement le nom du fichier à partir du chemin complet
    nom_fichier = os.path.basename(fichier)
    # Créer le nom du fichier de sortie
    base_nom, extension = os.path.splitext(nom_fichier)
    fichier_sortie = f"{base_nom}_encoded{extension}"
    chemin_sortie = os.path.join(dossier_sortie, fichier_sortie)
    logger.info(f"Fichier de sortie sera enregistré à: {chemin_sortie}")

    # Tronquer le nom du fichier pour l'affichage
    short_fichier = tronquer_nom_fichier(nom_fichier)

    input_path = os.path.join(dossier, fichier)
    logger.info(f"Début du processus d'encodage pour: {input_path}")

    # Vérifier si le fichier a déjà été encodé pour éviter les encodages en boucle
    if "_encoded" in nom_fichier:
        logger.warning(f"Le fichier {nom_fichier} a déjà été encodé, il est ignoré.")
        print(
            f"{horodatage()} 🔄 Le fichier {nom_fichier} a déjà été encodé, il est ignoré."
        )
        return

    # Assurez-vous que le chemin de sortie est correctement défini
    output_path = os.path.join(
        dossier_sortie, os.path.splitext(nom_fichier)[0] + "_encoded.mkv"
    )  # Modifier l'extension de sortie en .mkv et le chemin
    logger.debug(f"Chemin de sortie: {output_path}")

    # Obtenir les informations des pistes du fichier
    logger.debug(f"Récupération des informations de pistes pour {input_path}")
    info_pistes = obtenir_pistes(input_path)
    if info_pistes is None:
        logger.error(
            f"Erreur lors de l'obtention des informations des pistes pour {input_path}"
        )
        print(
            f"{horodatage()} ❌ Erreur lors de l'obtention des informations des pistes audio."
        )
        ajouter_fichier_a_liste_encodage_manuel(input_path)
        return

    # Sélectionner les pistes audio en fonction du preset
    logger.debug(f"Sélection des pistes audio pour {input_path} avec preset {preset}")
    pistes_audio = selectionner_pistes_audio(info_pistes, preset)
    if pistes_audio is None:
        logger.warning(
            f"Aucune piste audio sélectionnée pour {input_path}, ajout à l'encodage manuel"
        )
        ajouter_fichier_a_liste_encodage_manuel(input_path)
        return

    # Sélectionner les sous-titres en fonction du preset
    logger.debug(f"Sélection des sous-titres pour {input_path} avec preset {preset}")
    sous_titres, sous_titres_burn = selectionner_sous_titres(info_pistes, preset)
    if sous_titres is None:
        logger.warning(
            f"Problème avec les sous-titres pour {input_path}, ajout à l'encodage manuel"
        )
        ajouter_fichier_a_liste_encodage_manuel(input_path)
        return

    options_audio = f'--audio={",".join(map(str, pistes_audio))}'
    options_sous_titres = f'--subtitle={",".join(map(str, sous_titres))}'
    options_burn = (
        f"--subtitle-burned={sous_titres.index(sous_titres_burn) + 1}"
        if sous_titres_burn is not None
        else ""
    )

    logger.debug(f"Options audio: {options_audio}")
    logger.debug(f"Options sous-titres: {options_sous_titres}")
    logger.debug(f"Option burn: {options_burn}")

    # Construire la commande HandBrakeCLI
    commande = construire_commande_handbrake(
        input_path,
        output_path,
        preset,
        options_audio,
        options_sous_titres,
        options_burn,
    )

    if debug_mode:
        logger.debug(f"Commande d'encodage: {' '.join(commande)}")
        print(f"{horodatage()} 🔧 Commande d'encodage : {' '.join(commande)}")

    with console_lock:
        logger.info(
            f"Lancement de l'encodage pour {short_fichier} avec preset {preset}, pistes audio {pistes_audio}, sous-titres {sous_titres}, burn {sous_titres_burn}"
        )
        print(
            f"{horodatage()} � Lancement de l'encodage pour {short_fichier} avec le preset {preset}, pistes audio {pistes_audio}, et sous-titres {sous_titres} - burn {sous_titres_burn}"
        )
        notifier_encodage_lancement(short_fichier, file_encodage)

    # Dans encoding.py, avant de lancer HandBrake
    logger.info(f"Début de l'encodage de {fichier} avec preset {preset}")
    logger.info(f"Dossier de sortie configuré: {dossier_sortie}")
    logger.info(f"Chemin complet du fichier de sortie: {output_path}")
    logger.info(f"Exécution de la commande: {' '.join(commande)}")

    try:
        if debug_mode:
            # En mode debug, capturer les sorties stdout et stderr
            process = subprocess.Popen(
                commande, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

            stdout = []
            stderr = []

            stdout_thread = threading.Thread(
                target=read_output, args=(process.stdout, stdout)
            )
            stderr_thread = threading.Thread(
                target=read_output, args=(process.stderr, stderr)
            )

            stdout_thread.start()
            stderr_thread.start()

            stdout_thread.join()
            stderr_thread.join()
        else:
            # En mode standard, capturer seulement stdout et combiner stderr avec stdout
            process = subprocess.Popen(
                commande, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )

        last_percent_complete = -1
        percent_pattern = re.compile(r"Encoding:.*?(\d+\.\d+)\s?%")
        with tqdm(
            total=100,
            desc=f"Encodage de {short_fichier}",
            position=0,
            leave=True,
            dynamic_ncols=True,
        ) as pbar:
            while True:
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
                    break
                if output:
                    if debug_mode:
                        with console_lock:
                            print(output.strip())
                    match = percent_pattern.search(output)
                    if match:
                        percent_complete = float(match.group(1))
                        if percent_complete != last_percent_complete:
                            pbar.n = percent_complete
                            pbar.refresh()
                            last_percent_complete = percent_complete
                            # Log l'avancement tous les 10%
                            if int(percent_complete) % 10 == 0 and int(
                                percent_complete
                            ) > int(last_percent_complete):
                                logger.debug(
                                    f"Progression de l'encodage de {short_fichier}: {int(percent_complete)}%"
                                )
            # Forcer la barre de progression à atteindre 100% à la fin
            pbar.n = 100
            pbar.refresh()

        process.wait()
        with console_lock:
            if process.returncode == 0:
                logger.info(f"Encodage terminé avec succès pour {short_fichier}")
                print(
                    f"\n{horodatage()} ✅ Encodage terminé pour {short_fichier} avec le preset {preset}, pistes audio {pistes_audio}, et sous-titres {sous_titres}"
                )
                notifier_encodage_termine(nom_fichier, file_encodage)
            else:
                logger.error(
                    f"Échec de l'encodage pour {nom_fichier} avec code de retour {process.returncode}"
                )
                print(f"\n{horodatage()} ❌ Erreur lors de l'encodage de {nom_fichier}")
                notifier_erreur_encodage(nom_fichier)
                if debug_mode:
                    # Affichage des erreurs en mode débogage
                    logger.error(f"Erreurs d'encodage: {stderr}")
                    print(f"{horodatage()} ⚠️ Erreurs: {stderr}")
        # Ajoutez à la fin de la fonction d'encodage dans encoding.py
        if os.path.exists(output_path):
            taille = os.path.getsize(output_path) / (1024 * 1024)  # En MB
            logger.info(f"Fichier encodé avec succès: {output_path} ({taille:.2f} MB)")
        else:
            logger.error(f"Le fichier encodé n'a pas été trouvé: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Exception lors de l'encodage de {nom_fichier}: {str(e)}", exc_info=True
        )
        with console_lock:
            print(
                f"\n{horodatage()} ❌ Erreur lors de l'encodage de {nom_fichier}: {e}"
            )
            print(f"\n{horodatage()} ⚠️ Erreur de la commande : {e.stderr}")
            notifier_erreur_encodage(nom_fichier)
    except Exception as e:
        logger.error(
            f"Exception inattendue lors de l'encodage de {nom_fichier}: {str(e)}",
            exc_info=True,
        )
        with console_lock:
            print(
                f"\n{horodatage()} ❌ Erreur inattendue lors de l'encodage de {nom_fichier}: {e}"
            )
            notifier_erreur_encodage(nom_fichier)


def normaliser_chemin(chemin):
    return chemin.replace("\\", "/")


def lancer_encodage_avec_gui(
    fichier, preset, dossier, signals=None, control_flags=None
):
    logger = setup_logger(__name__)

    # Normaliser les chemins (remplacer les antislash par des slash)
    fichier = fichier.replace("\\", "/")

    # Récupérer uniquement le nom du fichier
    nom_fichier = os.path.basename(fichier)
    base_nom, extension = os.path.splitext(nom_fichier)
    fichier_sortie = f"{base_nom}_encoded{extension}"
    chemin_sortie = os.path.join(dossier_sortie, fichier_sortie).replace("\\", "/")

    logger.info(f"Fichier de sortie sera enregistré à: {chemin_sortie}")

    try:
        # Analyse des pistes du fichier
        info_pistes = obtenir_pistes(fichier)
        # Sélection des pistes audio selon la langue préférée
        audio_tracks = selectionner_pistes_audio(info_pistes, fichier)
        # Sélection des sous-titres selon la langue préférée
        subtitle_tracks, burn_track = selectionner_sous_titres(info_pistes, fichier)

        # Préparer les options audio et sous-titres
        audio_option = (
            f"--audio={','.join(map(str, audio_tracks))}" if audio_tracks else ""
        )
        subtitle_option = (
            f"--subtitle={','.join(map(str, subtitle_tracks))}"
            if subtitle_tracks
            else ""
        )
        burn_option = (
            f"--subtitle-burned={burn_track}" if burn_track is not None else ""
        )

        # Construire la commande complète comme celle qui a fonctionné
        handbrake_cmd = [
            "HandBrakeCLI",
            "--preset-import-file",
            fichier_presets,
            "-i",
            fichier,
            "-o",
            chemin_sortie,
            "--preset",
            preset,
        ]

        # Ajouter les options audio et sous-titres si disponibles
        if audio_option:
            handbrake_cmd.append(audio_option)
        if subtitle_option:
            handbrake_cmd.append(subtitle_option)
        if burn_option:
            handbrake_cmd.append(burn_option)

        # Ajouter les paramètres d'encodage audio qui ont fonctionné précédemment
        handbrake_cmd.extend(["--aencoder=aac", "--ab=192", "--mixdown=5point1"])

        logger.info(f"Exécution de la commande: {' '.join(handbrake_cmd)}")

        # Exécuter HandBrake
        process = subprocess.Popen(
            handbrake_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            text=True,
        )

        # Traiter la sortie de HandBrake pour suivre la progression
        # [Code de suivi de progression existant...]

    except Exception as e:
        logger.error(f"Erreur pendant l'encodage: {str(e)}")


def traitement_file_encodage(file_encodage, signals=None, control_flags=None):
    """
    Fonction qui traite la file d'attente des fichiers à encoder
    Avec support pour l'interface graphique
    """
    logger = setup_logger(__name__)
    logger.info("Thread de traitement de la file d'encodage démarré")

    while True:
        # Vérifier si on doit arrêter complètement
        if control_flags and control_flags.get("stop_all", False):
            logger.info("Arrêt de tous les encodages demandé")
            control_flags["stop_all"] = False
            # Envoyer un signal pour mettre à jour l'interface
            if signals:
                signals.encoding_done.emit()
                signals.update_queue.emit([])
            time.sleep(1)
            continue

        # Attendre qu'un fichier soit disponible dans la file
        if file_encodage.empty():
            time.sleep(1)
            continue

        # Extraire le prochain fichier à traiter
        tache = file_encodage.get()

        if isinstance(tache, dict):
            fichier = tache.get("file")
            preset = tache.get("preset")
            dossier = tache.get("folder", "")
        else:
            # Fallback au cas où c'est un tuple
            fichier = tache[0] if len(tache) > 0 else ""
            preset = tache[1] if len(tache) > 1 else ""
            dossier = ""

        # Mettre à jour la file d'attente dans l'interface
        if signals and hasattr(signals, "update_queue"):
            queue_items = []
            if not file_encodage.empty():
                queue_items = list(file_encodage.queue)
            signals.update_queue.emit(queue_items)

        # Encodage avec gestion GUI
        logger.info(f"Début de l'encodage de {fichier} avec le preset {preset}")
        lancer_encodage_avec_gui(fichier, preset, dossier, signals, control_flags)
        logger.info(f"Encodage de {fichier} terminé")
