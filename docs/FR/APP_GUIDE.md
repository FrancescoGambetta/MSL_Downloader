# Guide MSL Image Downloader (FR)

Ce guide s'adresse à une personne qui télécharge le projet depuis GitHub et souhaite :
1) installer l'application, 2) la lancer, 3) comprendre ce qui s'affiche à l'écran, 4) l'utiliser pour filtrer et télécharger/traiter des images.

> **Remarque importante**
> - Ce projet a été développé et utilisé principalement avec **Anaconda/Conda**.
> - La procédure avec `python -m venv` + `pip` est incluse comme alternative, mais **n'a peut-être pas encore été testée en profondeur** sur toutes les machines.

## 1) Qu'est-ce que MSL Image Downloader
MSL Image Downloader est une application pour rechercher, télécharger et organiser les images de la mission Mars Science Laboratory (Curiosity) de la NASA. À l'ouverture, on commence par un écran où l'on saisit son nom, puis on arrive dans l'application elle-même, divisée en deux sections que l'on choisit en haut à tout moment :

- **Downloader** : recherche, filtre et télécharge les images.
- **Catalogues (Catalog Manager)** : gère le catalogue local sur lequel repose la recherche du Downloader (état, mises à jour depuis la NASA, vérification, etc.).

Le catalogue se télécharge automatiquement au premier lancement, aucune étape manuelle n'est nécessaire.

## 2) Prérequis
- **Python** : **3.11 ou 3.12** recommandé
- **Conda** : recommandé (réduit les problèmes avec les bibliothèques « binaires » comme `pyarrow`)
- Connexion internet : nécessaire pour le téléchargement/la mise à jour du catalogue et pour récupérer certains fichiers externes (le cas échéant)

> **Remarque technique** : `numpy` est limité à `<2` pour la compatibilité avec `pyarrow` sur certains environnements.

## 3) Installation (étape par étape) — Windows

> Cette section concerne l'installation **sous Windows**.

### 3.1 Récupérer le projet
Option A (Git) :
```bash
mkdir NOM_DOSSIER
cd NOM_DOSSIER
git clone <URL_DU_DEPOT> .
```

Option B (ZIP depuis GitHub) :
- téléchargez le ZIP
- extrayez-le dans un dossier (ex. `C:\Users\...\dwnapp`)
- ouvrez un terminal dans le dossier extrait

### 3.2 Créer l'environnement (Conda recommandé)
Depuis la racine du dépôt :
```bash
conda env create -f environment.yml
conda activate dwnapp
```

Note sur `environment.yml` :
- `environment.yml` crée l'environnement (Python + pip) puis installe les bibliothèques via `pip -r requirements.txt`.
- Autrement dit : **la liste des dépendances se trouve dans `requirements.txt`**, tandis que le fichier YAML sert à créer un environnement propre et cohérent.

Alternative (venv + pip) :
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 4) Lancer l'application
Pour simplifier le lancement, un fichier unique a été créé : il suffit de l'ouvrir (double-clic, sous Windows) et l'application démarre toute seule.

Double-clic sur `launchers/Avvia_MSL_App.bat` : il ouvre le navigateur sur `http://localhost:5173` une fois que tout est prêt.

## 5) Ce que vous voyez dans l'interface (tour rapide)
Après la connexion, la section **Catalogues** s'ouvre en premier, pour télécharger et éventuellement personnaliser le catalogue local. Une fois la procédure d'installation guidée terminée, on passe au **Downloader** via le sélecteur en haut.

Dans le Downloader, l'interface est divisée en zones :
- **Barre latérale** (à gauche) : filtres, sélection en cours, boutons de contrôle
- **Zone centrale** : résultats de la recherche
- **Aperçu/Métadonnées** : aperçu de l'image et métadonnées associées
- **Journal en direct** : affiche la progression et les messages pendant le téléchargement

Le dossier de sortie se choisit depuis les Paramètres, en haut à droite.

## 6) Utiliser l'application (flux type)
Un flux type :
1) Définir le dossier de sortie/téléchargement
2) Appliquer des filtres (sol, caméra, etc.)
3) Vérifier la sélection (combien d'images, ce qu'elle contient)
4) Lancer le **téléchargement** ou le **traitement**

### 6.1 Définir le dossier de sortie
Si l'application signale que le dossier de sortie est manquant :
- utilisez l'option pour choisir le dossier (boîte de dialogue) ou définissez un chemin manuel (voir exemples ci-dessous)
- puis relancez le téléchargement/traitement

### 6.2 Filtrer le catalogue
Vous pouvez filtrer par :
- **sol** (plage ou valeur unique)
- **caméra**
- (facultatif) taille minimale, variantes, tokens et autres filtres disponibles

### 6.3 Télécharger ou traiter
Comportement général :
- **Téléchargement** : enregistre les fichiers bruts (généralement `.IMG` + `.LBL`) dans le dossier de sortie
- **Traitement/Conversion** : produit la sortie finale (généralement `.jpg` + `.meta.json`) dans le dossier de sortie
