# Guide de l’application DWNAPP (FR)

Ce guide s’adresse à une personne qui télécharge le projet depuis GitHub et veut :
1) installer l’app, 2) la lancer, 3) comprendre ce qu’elle voit à l’écran, 4) l’utiliser pour filtrer et télécharger/traiter des images.

Note importante :
- Ce projet a été développé et utilisé principalement avec **Anaconda/Conda**.
- La procédure `python -m venv` + `pip` est proposée en alternative, mais **elle n’a peut‑être pas encore été testée en profondeur** sur toutes les machines.

## 1) C’est quoi DWNAPP (en bref)
DWNAPP est une application Streamlit qui permet de travailler avec un catalogue d’images de la mission MSL (Curiosity) :
- parcourir et filtrer le catalogue (par sol, caméra, etc.)
- créer une sélection d’images
- télécharger et/ou traiter la sélection (sortie dans un dossier sur ton PC)
- mettre à jour le catalogue si nécessaire

## 2) Prérequis
- **Python** : recommandé **3.11 ou 3.12**
- **Conda** : recommandé sous Windows (réduit les problèmes de bibliothèques binaires comme `pyarrow`)
- Connexion internet : nécessaire pour les téléchargements/mises à jour du catalogue et pour récupérer certains fichiers externes (si applicable)

Note technique : `numpy` est limité à `<2` pour compatibilité avec `pyarrow` dans certains environnements.

## 3) Installation (pas à pas)

### 3.1 Télécharger le projet
Option A (Git) :
```bash
mkdir NOM_DOSSIER
cd NOM_DOSSIER
git clone <URL_REPO> .
```

À quoi servent ces commandes :
- `mkdir NOM_DOSSIER` : crée un nouveau dossier pour le projet.
- `cd NOM_DOSSIER` : entre dans le dossier que tu viens de créer.
- `git clone <URL_REPO> .` : clone le dépôt GitHub dans le dossier courant (`.`).

Option B (ZIP depuis GitHub) :
- télécharger le ZIP
- l’extraire dans un dossier (ex. `C:\\Users\\...\\dwnapp`)
- ouvrir un terminal dans le dossier extrait

### 3.2 Créer l’environnement (recommandé : Conda)
Depuis la racine du repo :
```bash
conda env create -f environment.yml
conda activate dwnapp
```

À quoi servent ces commandes :
- `conda env create -f environment.yml` : crée un environnement Conda nommé `dwnapp` avec Python et les dépendances requises.
- `conda activate dwnapp` : active l’environnement `dwnapp` (à partir de là tu utilises ces bibliothèques).

Note sur `environment.yml` :
- `environment.yml` sert à créer l’environnement (Python + pip) puis installe les bibliothèques via `pip -r requirements.txt`.
- Autrement dit : **la liste des dépendances est dans `requirements.txt`**, et le YAML sert à créer un environnement propre et cohérent.

Alternative (venv + pip) :
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

À quoi servent ces commandes :


- `python -m venv .venv` : crée un environnement virtuel local dans le dossier `.venv`.
- `.\.venv\Scripts\activate` : active l’environnement virtuel (Windows PowerShell/cmd).
- `pip install -r requirements.txt` : installe toutes les bibliothèques nécessaires.

## 4) Lancer l’app
Depuis la racine du repo :
```bash
streamlit run app/app.py
```

À quoi sert cette commande :
- `streamlit run app/app.py` : démarre l’app et ouvre une page dans le navigateur (souvent `http://localhost:8501`).

Streamlit ouvre normalement le navigateur automatiquement. Sinon, copie/colle l’URL affichée dans le terminal (souvent `http://localhost:8501`).

### (Windows) Lancer par double‑clic
Si tu ne veux pas utiliser le terminal à chaque fois :
1) une seule fois : exécuter `Create_env.bat` (crée l’environnement conda)
2) pour lancer : double‑cliquer sur `Run_App.bat`

## 5) Que voit‑on dans l’UI (tour rapide)
L’interface est divisée en zones :
- **Sidebar** (à gauche) : commandes/actions, filtres, sélection courante, boutons de contrôle
- **Zone centrale** : réponse/texte d’information et/ou résultats
- **Viewport/Metadata** (si présent) : aperçu image et métadonnées associées
- **Live log** : pendant download/process, affiche l’avancement et les messages

## 6) Utiliser l’app (workflow typique)
Un workflow typique :
1) définir le dossier de sortie/téléchargement (si demandé)
2) appliquer des filtres (sol, caméra, etc.)
3) vérifier la sélection (combien d’images, contenu)
4) lancer **download** ou **process**

### 6.1 Définir le dossier de sortie
Si l’app indique que le dossier de sortie manque :
- choisir un dossier via la commande (dialog) ou définir un chemin manuellement (voir exemples)
- puis relancer download/process

### 6.2 Filtrer le catalogue
Filtres possibles :
- **sol** (intervalle ou valeur unique)
- **caméra**
- (optionnel) taille minimale, variantes, tokens et autres filtres disponibles

### 6.3 Télécharger ou traiter
Comportement général :
- **Download** : enregistre les fichiers bruts (souvent `.IMG` + `.LBL`) dans le dossier de sortie
- **Process/Convert** : produit des sorties finales (souvent `.jpg` + `.meta.json`) dans le dossier de sortie

## 7) Exemples de commandes (copier/coller)
Filtres :
- `sol 3371`
- `sol da 3300 a 3425`
- `camera mastcam, navcam`
- `mostra filtri`
- `report selezione`

Workflow :
- `scarica`
- `elabora`
- `scarica e elabora`

Configuration :
- `show config`
- `show download path`
- `path download = C:\\percorso\\output`

Mise à jour catalogue :
- `aggiorna catalogo sol 3371 a 3380 workers 4`

Pour plus de détails techniques : `docs/IT/TECHNICAL_GUIDE.md`.

## 8) Problèmes fréquents (solutions rapides)
- **Le navigateur ne s’ouvre pas** : utiliser l’URL affichée dans le terminal (ex. `http://localhost:8501`).
- **“Output path required”** : définir un dossier de sortie et réessayer.
- **“Rien à télécharger/traiter”** : vérifier `report selezione` et enlever des filtres trop stricts.
- **L’app semble “bloquée”** : utiliser le bouton/commande stop (si présent) et réessayer avec une sélection plus petite.

## 9) Données locales (normal)
Ces dossiers contiennent des données locales et peuvent rester vides sur Git :
- `cache/` (cache runtime)
- `data/sessions/` (sessions locales)
