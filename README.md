# Linux System Monitor

Tableau de bord web Flask pour surveiller CPU, RAM, disques, partitions, réseau, processus, applications installées, services Linux et historique SQLite. Interface **DevOps Pro** (thème sombre, Tailwind CSS), responsive desktop/mobile, avec analyse IA optionnelle (Gemini).

## Fonctionnalités

- **Vue globale** : CPU, RAM installée/utilisée, disque total et partitions colorées selon un code couleur cohérent (cyan = normal, orange = à surveiller, rouge = critique), graphique d'activité 24 h.
- **Historique** : 24 dernières heures stockées en SQLite, visualisées avec Chart.js.
- **Réseau** : octets envoyés/reçus depuis le démarrage du système.
- **Processus** : top 10 par usage CPU, rafraîchi automatiquement.
- **Applications** : top 10 des applications les plus lourdes du système complet — détection automatique selon l'OS (paquets `dpkg`/`rpm` sur Linux, registre Windows, bundles `.app` sur macOS).
- **Services Linux (systemd)** : liste filtrable en direct.
- **Recherche intégrée** : processus, services et fichiers/dossiers, accessible depuis la barre de recherche.
- **Analyse IA** (Gemini, optionnelle) : explique un processus, un service, un fichier ou une application, et propose une commande sûre pour agir dessus.
- **Alertes** par e-mail SMTP et/ou Discord/Telegram selon des seuils configurables (voir [ALERTS_CONFIGURATION.md](ALERTS_CONFIGURATION.md)).
- **Réglages persistants**, conservation automatique des anciennes métriques, endpoint `/health` pour la supervision.
- **Authentification** par session avant accès au dashboard et aux API, avec protection anti *open redirect* et cookies `HttpOnly`/`SameSite` (voir [Sécurité](#sécurité)).
- **Responsive** : navigation adaptée mobile (barre d'onglets défilable) et desktop (sidebar fixe).

## Lancer localement

```bash
python -m venv venv
# Linux/macOS : source venv/bin/activate
# Windows : .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Le serveur de développement Flask démarre sur `http://127.0.0.1:5000`.

## Configuration

Créez un fichier `.env` à la racine du projet :

```env
# Authentification (fortement recommandé dès que le tableau de bord est accessible
# en dehors de votre poste)
AUTH_REQUIRED=true
FLASK_SECRET_KEY=une-cle-longue-aleatoire
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=hash-du-mot-de-passe

# À activer uniquement si l'application est servie en HTTPS (reverse proxy,
# certbot...). Sinon, laissez absent : le navigateur refuserait sinon d'envoyer
# le cookie de session en HTTP simple.
# SESSION_COOKIE_SECURE=true

# Analyse IA (optionnel)
GEMINI_API_KEY=ta_cle_gemini

# Alertes par e-mail (optionnel, voir ALERTS_CONFIGURATION.md)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=monitor@example.com
SMTP_PASSWORD=mot-de-passe-application
ALERT_EMAIL_FROM=monitor@example.com
ALERT_EMAIL_TO=admin@example.com

# Alertes Discord/Telegram (optionnel, voir ALERTS_CONFIGURATION.md)
# DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
# TELEGRAM_BOT_TOKEN=123456:token_du_bot
# TELEGRAM_CHAT_ID=123456789
```

Créer le hash du mot de passe admin :

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('mot-de-passe-fort'))"
```

> `.env` ne doit jamais être commité ni copié dans une image Docker : il est déjà exclu via `.gitignore` et `.dockerignore`.

## Déploiement

| Cible | Guide |
|---|---|
| Ubuntu (Gunicorn + systemd + Nginx, recommandé pour surveiller un serveur réel) | [DEPLOYMENT_UBUNTU.md](DEPLOYMENT_UBUNTU.md) |
| Windows Server (Waitress + Planificateur de tâches) | [DEPLOYMENT_WINDOWS.md](DEPLOYMENT_WINDOWS.md) |
| Docker (démonstration ou supervision d'un conteneur) | [DOCKER_GUIDE.md](DOCKER_GUIDE.md) |
| Alertes (e-mail, Discord, Telegram) | [ALERTS_CONFIGURATION.md](ALERTS_CONFIGURATION.md) |

Docker convient à une démonstration ou au monitoring d'un conteneur : par défaut, il n'observe que les ressources du conteneur, pas celles de l'hôte. Pour surveiller tout un serveur Ubuntu, préférez le déploiement systemd : l'application voit ainsi directement les ressources de l'hôte.

## Structure du projet

```
├── app.py                     # Application Flask + routes API
├── disk_utils.py              # Analyse disque (fichiers/dossiers volumineux)
├── requirements.txt
├── Dockerfile
├── templates/
│   ├── index.html             # Tableau de bord (thème DevOps Pro)
│   ├── login.html             # Page de connexion
│   └── search_results.html    # Résultats de recherche
├── DEPLOYMENT_UBUNTU.md
├── DEPLOYMENT_WINDOWS.md
├── DOCKER_GUIDE.md
├── ALERTS_CONFIGURATION.md
└── EXPLICATIONS.md            # Journal de développement
```

## Sécurité

- Sessions signées via `FLASK_SECRET_KEY`, expirant après 8 h.
- Mots de passe comparés en temps constant (`hmac.compare_digest`) et stockés hachés (`werkzeug.security`), jamais en clair.
- Redirection post-connexion (`next`) validée pour n'accepter que des chemins internes, afin d'éviter toute redirection ouverte.
- Cookies de session `HttpOnly` et `SameSite=Lax` ; `Secure` activable via `SESSION_COOKIE_SECURE=true` derrière HTTPS.
- Aucun identifiant ni secret n'est stocké dans le code ou dans Git — tout passe par `.env` (exclu de `.gitignore`/`.dockerignore`).
- N'exposez jamais ce tableau de bord sur Internet sans authentification (`AUTH_REQUIRED=true`) ni HTTPS.
