from flask import Flask, jsonify, render_template, request, redirect, url_for, session
import psutil
import platform
import os
import sqlite3
import atexit
import hmac
import json
import smtplib
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from werkzeug.security import check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from disk_utils import get_disk_usage_linux, get_disk_usage_cross_platform, search_disk
import subprocess
from dotenv import load_dotenv # Importation de load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# --- Configuration de la base de données et du planificateur ---
DATABASE = 'monitor.db'
DEFAULT_SETTINGS = {'cpu_threshold': 85, 'memory_threshold': 85, 'disk_threshold': 90, 'retention_days': 30, 'alert_cooldown_minutes': 60}

def disk_summary():
    ignored = {'tmpfs','devtmpfs','proc','sysfs','overlay','squashfs','cgroup','cgroup2','devpts'}
    parts = []
    for p in psutil.disk_partitions(all=False):
        if p.fstype.lower() in ignored: continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            parts.append({'name':p.mountpoint,'device':p.device,'total_gb':round(u.total/1024**3,2),'used_gb':round(u.used/1024**3,2),'percent':u.percent})
        except OSError: pass
    if not parts:
        u=psutil.disk_usage('/'); parts=[{'name':'/','device':'/','total_gb':round(u.total/1024**3,2),'used_gb':round(u.used/1024**3,2),'percent':u.percent}]
    total=sum(p['total_gb'] for p in parts); used=sum(p['used_gb'] for p in parts)
    return parts, round(total,2), round(used,2)


def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            timestamp DATETIME PRIMARY KEY,
            cpu_percent REAL,
            memory_percent REAL,
            disk_percent REAL
        )
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS alert_log (metric TEXT PRIMARY KEY, last_sent DATETIME NOT NULL)')
    for key,value in DEFAULT_SETTINGS.items(): cursor.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(key,str(value)))
    conn.commit()
    conn.close()

def get_settings():
    conn=sqlite3.connect(DATABASE); rows=conn.execute('SELECT key,value FROM settings').fetchall(); conn.close()
    data=DEFAULT_SETTINGS.copy(); data.update({k:int(v) for k,v in rows if k in data}); return data

def notify(subject, message):
    sent=False; hook=os.environ.get('DISCORD_WEBHOOK_URL')
    if hook:
        try:
            req=urllib.request.Request(hook,data=json.dumps({'content':f'**{subject}**\n{message}'}).encode(),headers={'Content-Type':'application/json'},method='POST'); urllib.request.urlopen(req,timeout=10).close(); sent=True
        except Exception as e: print(f'Discord alert error: {e}')
    host,to=os.environ.get('SMTP_HOST'),os.environ.get('ALERT_EMAIL_TO')
    if host and to:
        try:
            m=EmailMessage(); m['Subject']=subject;m['From']=os.environ.get('ALERT_EMAIL_FROM',to);m['To']=to;m.set_content(message)
            with smtplib.SMTP(host,int(os.environ.get('SMTP_PORT','587')),timeout=10) as s:
                if os.environ.get('SMTP_STARTTLS','true').lower()=='true':s.starttls()
                if os.environ.get('SMTP_USERNAME') and os.environ.get('SMTP_PASSWORD'):s.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD'])
                s.send_message(m)
            sent=True
        except Exception as e: print(f'Email alert error: {e}')
    return sent

def log_metrics():
    """Fonction pour collecter et enregistrer les métriques système."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    _, total, used = disk_summary()
    disk = round(used / total * 100, 1) if total else 0
    settings = get_settings()
    
    cursor.execute(
        "INSERT INTO metrics (timestamp, cpu_percent, memory_percent, disk_percent) VALUES (?, ?, ?, ?)",
        (datetime.now(), cpu, mem, disk)
    )
    cursor.execute('DELETE FROM metrics WHERE timestamp < ?', (datetime.now()-timedelta(days=settings['retention_days']),))
    for name,value,key in [('CPU',cpu,'cpu_threshold'),('Mémoire',mem,'memory_threshold'),('Disque',disk,'disk_threshold')]:
        if value >= settings[key] and notify(f'⚠️ Alerte {name}',f'{name} est à {value}% (seuil : {settings[key]}%).'):
            cursor.execute('INSERT OR REPLACE INTO alert_log VALUES (?,?)',(name,datetime.now().isoformat()))
    conn.commit()
    conn.close()
    print(f"Logged metrics at {datetime.now()}: CPU {cpu}%, Mem {mem}%, Disk {disk}%")

# Initialise le planificateur pour exécuter log_metrics toutes les 5 minutes
init_db()
scheduler = BackgroundScheduler()
scheduler.add_job(func=log_metrics, trigger="interval", minutes=5)
scheduler.start()

# S'assure que le planificateur s'arrête proprement à la sortie de l'application
atexit.register(lambda: scheduler.shutdown())
# --- Fin de la configuration ---


app = Flask(__name__)
app.config['SECRET_KEY']=os.environ.get('FLASK_SECRET_KEY',os.urandom(32))
app.config['PERMANENT_SESSION_LIFETIME']=timedelta(hours=8)
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'
app.config['SESSION_COOKIE_SECURE']=os.environ.get('SESSION_COOKIE_SECURE','false').lower()=='true'
AUTH_REQUIRED=os.environ.get('AUTH_REQUIRED','true').lower()=='true'

def _safe_next_path(path):
    """N'autorise que les chemins internes relatifs, pour éviter une redirection ouverte."""
    if path and path.startswith('/') and not path.startswith('//') and '\\' not in path:
        return path
    return '/'

@app.before_request
def auth_guard():
    if not AUTH_REQUIRED or request.endpoint in {'login','logout','health','static'}: return None
    if not (os.environ.get('FLASK_SECRET_KEY') and os.environ.get('ADMIN_USERNAME') and (os.environ.get('ADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD_HASH'))): return render_template('login.html',configuration_error=True),503
    return None if session.get('authenticated') else redirect(url_for('login',next=request.full_path))

# Le reste de votre code Flask...
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login',methods=['GET','POST'])
def login():
    user=os.environ.get('ADMIN_USERNAME',''); raw=os.environ.get('ADMIN_PASSWORD'); hashed=os.environ.get('ADMIN_PASSWORD_HASH')
    next_url=_safe_next_path(request.values.get('next',''))
    if request.method=='POST':
        password=request.form.get('password',''); valid=check_password_hash(hashed,password) if hashed else bool(raw) and hmac.compare_digest(raw,password)
        if hmac.compare_digest(request.form.get('username',''),user) and valid:
            session.clear();session.permanent=True;session['authenticated']=True;return redirect(_safe_next_path(request.form.get('next','')))
        return render_template('login.html',error='Identifiant ou mot de passe incorrect.',next=next_url)
    return render_template('login.html',configuration_error=not bool(user and (raw or hashed) and os.environ.get('FLASK_SECRET_KEY')),next=next_url)

@app.route('/logout',methods=['POST'])
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/health')
def health(): return jsonify({'status':'ok','timestamp':datetime.now().isoformat()})

@app.route('/settings',methods=['GET','POST'])
def settings():
    if request.method=='GET': return jsonify(get_settings())
    data=request.get_json() or {}; conn=sqlite3.connect(DATABASE)
    try:
        for key in DEFAULT_SETTINGS:
            if key in data:
                value=int(data[key]); maximum=3650 if key=='retention_days' else 1440 if key=='alert_cooldown_minutes' else 100
                if not 1<=value<=maximum: raise ValueError
                conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,str(value)))
        conn.commit(); return jsonify(get_settings())
    except (TypeError,ValueError): return jsonify({'error':'Valeur invalide'}),400
    finally: conn.close()

@app.route('/data')
def system_data():
    # ... (code existant)
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_info = psutil.virtual_memory()
    disk_partitions, disk_total, disk_used = disk_summary()
    net_io = psutil.net_io_counters()

    data = {
        'cpu_percent': cpu_percent,
        'memory_percent': memory_info.percent,
        'memory_total_gb': round(memory_info.total / (1024**3), 2),
        'memory_used_gb': round(memory_info.used / (1024**3), 2),
        'disk_percent': round(disk_used / disk_total * 100,1) if disk_total else 0,
        'disk_total_gb': disk_total,
        'disk_used_gb': disk_used,
        'disk_partitions': disk_partitions,
        'net_bytes_sent_gb': round(net_io.bytes_sent / (1024**3), 2),
        'net_bytes_recv_gb': round(net_io.bytes_recv / (1024**3), 2),
        'platform': platform.system(), # Ajout de la plateforme
    }
    return jsonify(data)

@app.route('/drives')
def get_drives():
    """Retourne la liste des partitions de disque disponibles."""
    partitions = psutil.disk_partitions()
    # On ne retourne que le point de montage (ex: 'C:\\', '/boot')
    drive_paths = [p.mountpoint for p in partitions]
    return jsonify(drive_paths)


@app.route('/disk-usage-details')
def disk_usage_details():
    path_to_scan = request.args.get('path', os.path.expanduser('~'))
    
    current_os = platform.system()
    if current_os == "Linux":
        # Pour Linux, on continue de scanner le répertoire personnel par défaut pour la rapidité
        data = get_disk_usage_linux(os.path.expanduser('~'))
    else:
        # Pour les autres OS (Windows), on utilise le chemin fourni
        data = get_disk_usage_cross_platform(path_to_scan)
        
    if isinstance(data, dict) and "error" in data:
        return jsonify(data), 500
    return jsonify(data)

@app.route('/processes')
def top_processes():
    # ... (code existant)
    processes = []
    attrs = ['pid', 'name', 'username', 'cpu_percent', 'memory_percent']
    for p in psutil.process_iter(attrs=attrs):
        try:
            p.info['cpu_percent'] = p.cpu_percent(interval=0.1)
            processes.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    top_processes = sorted(processes, key=lambda p: p['cpu_percent'], reverse=True)[:10]
    for p in top_processes:
        p['memory_percent'] = round(p['memory_percent'], 2)
    return jsonify(top_processes)

def _get_top_apps_linux():
    """Interroge dpkg (Debian/Ubuntu) puis rpm (Fedora/RHEL/openSUSE) en repli."""
    try:
        command = ['dpkg-query', '-Wf', '${Installed-Size}\t${Package}\t${Description}\n']
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        apps = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t', 2)
            if len(parts) < 2:
                continue
            try:
                size_kb = int(parts[0])
            except ValueError:
                continue
            apps.append({'name': parts[1], 'size_kb': size_kb, 'description': parts[2].strip() if len(parts) > 2 else ''})
        return apps, None
    except FileNotFoundError:
        pass
    except subprocess.CalledProcessError as e:
        return [], f"Échec de dpkg-query : {e.stderr}"

    try:
        command = ['rpm', '-qa', '--queryformat', '%{SIZE}\t%{NAME}\t%{SUMMARY}\n']
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        apps = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t', 2)
            if len(parts) < 2:
                continue
            try:
                size_kb = int(parts[0]) // 1024
            except ValueError:
                continue
            apps.append({'name': parts[1], 'size_kb': size_kb, 'description': parts[2].strip() if len(parts) > 2 else ''})
        return apps, None
    except FileNotFoundError:
        return [], "Aucun gestionnaire de paquets supporté (dpkg-query ou rpm) n'a été trouvé sur ce système Linux."
    except subprocess.CalledProcessError as e:
        return [], f"Échec de rpm -qa : {e.stderr}"


def _get_top_apps_windows():
    """Lit les tailles estimées des programmes installés depuis le registre Windows."""
    try:
        import winreg
    except ImportError:
        return [], "Le module winreg n'est pas disponible sur ce système."

    apps = []
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in hives:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                subkey_name = winreg.EnumKey(key, i)
                with winreg.OpenKey(key, subkey_name) as subkey:
                    try:
                        name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                    except OSError:
                        continue
                    try:
                        size_kb = winreg.QueryValueEx(subkey, "EstimatedSize")[0]
                    except OSError:
                        continue
                    try:
                        publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
                    except OSError:
                        publisher = ''
                    apps.append({'name': name, 'size_kb': int(size_kb), 'description': publisher})
            except OSError:
                continue
    if not apps:
        return [], "Aucune application avec taille estimée n'a été trouvée dans le registre Windows."
    return apps, None


def _get_top_apps_macos():
    """Mesure la taille de chaque bundle .app dans /Applications et ~/Applications."""
    apps = []
    search_dirs = ['/Applications', os.path.expanduser('~/Applications')]
    found_any_dir = False
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        found_any_dir = True
        for entry in os.listdir(d):
            if not entry.endswith('.app'):
                continue
            full_path = os.path.join(d, entry)
            try:
                result = subprocess.run(['du', '-sk', full_path], capture_output=True, text=True, check=True)
                size_kb = int(result.stdout.split()[0])
                apps.append({'name': entry[:-4], 'size_kb': size_kb, 'description': full_path})
            except (subprocess.CalledProcessError, ValueError, IndexError):
                continue
    if not found_any_dir:
        return [], "Aucun dossier d'applications (/Applications) n'a été trouvé."
    return apps, None


@app.route('/top-apps')
def top_apps():
    """
    Retourne les 10 applications les plus volumineuses du système complet.
    Linux : paquets installés (dpkg, repli sur rpm).
    Windows : programmes listés dans le registre (Uninstall / EstimatedSize).
    macOS : bundles .app dans /Applications et ~/Applications.
    """
    current_os = platform.system()
    try:
        if current_os == 'Linux':
            apps, error = _get_top_apps_linux()
        elif current_os == 'Windows':
            apps, error = _get_top_apps_windows()
        elif current_os == 'Darwin':
            apps, error = _get_top_apps_macos()
        else:
            return jsonify({'error': f"Plateforme non supportée : {current_os}."}), 400

        if error:
            return jsonify({'error': error}), 500

        # Déduplique par nom (garde la plus grande taille rencontrée)
        dedup = {}
        for a in apps:
            if a['name'] not in dedup or a['size_kb'] > dedup[a['name']]['size_kb']:
                dedup[a['name']] = a
        apps_list = sorted(dedup.values(), key=lambda a: a['size_kb'], reverse=True)
        top = apps_list[:10]

        max_kb = top[0]['size_kb'] if top else 1
        for a in top:
            size_kb = a['size_kb']
            if size_kb >= 1024 * 1024:
                a['size'] = f"{size_kb / 1024 / 1024:.2f} GB"
            elif size_kb >= 1024:
                a['size'] = f"{size_kb / 1024:.1f} MB"
            else:
                a['size'] = f"{size_kb} KB"
            a['percent_of_top'] = round(size_kb / max_kb * 100, 1)

        return jsonify(top)

    except Exception as e:
        return jsonify({'error': f"Une erreur inattendue est survenue: {str(e)}"}), 500

# Nouvelle route API pour l'historique
@app.route('/history')
def get_history():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Récupérer les données des dernières 24 heures
    time_threshold = datetime.now() - timedelta(hours=24)
    cursor.execute("SELECT * FROM metrics WHERE timestamp >= ? ORDER BY timestamp", (time_threshold,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Formater pour Chart.js
    history_data = {
        'timestamps': [row[0] for row in rows],
        'cpu': [row[1] for row in rows],
        'memory': [row[2] for row in rows],
        'disk': [row[3] for row in rows],
    }
    return jsonify(history_data)

@app.route('/services_status')
def services_status():
    """
    Returns a list of system services and their status on Linux.
    """
    if os.name != 'posix':
        return jsonify({'error': 'This feature is only available on Linux systems.'}), 400

    try:
        command = ['systemctl', 'list-units', '--type=service', '--all', '--no-pager']
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        output_lines = result.stdout.splitlines()

        services = []
        header_found = False
        for line in output_lines:
            if line.strip().startswith('UNIT'):
                header_found = True
                continue
            if not header_found:
                continue
            if not line.strip() or line.strip().startswith('●') or 'loaded units listed' in line:
                continue

            parts = line.split(maxsplit=4)
            if len(parts) >= 4:
                unit = parts[0]
                load = parts[1]
                active = parts[2]
                sub = parts[3]
                description = parts[4] if len(parts) > 4 else ''
                
                services.append({
                    'unit': unit,
                    'load': load,
                    'active': active,
                    'sub': sub,
                    'description': description.strip()
                })

        return jsonify(services)

    except FileNotFoundError:
        return jsonify({'error': 'systemctl command not found. This server might not be using systemd or systemctl is not in PATH.'}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Failed to list services: {e.stderr}'}), 500
    except Exception as e:
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return redirect(url_for('index'))

    results = {
        'query': query,
        'processes': [],
        'services': [],
        'disk': []
    }

    # Search processes
    try:
        attrs = ['pid', 'name', 'username', 'cpu_percent', 'memory_percent']
        for p in psutil.process_iter(attrs=attrs):
            if query.lower() in p.info['name'].lower():
                results['processes'].append(p.info)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    # Search services
    if os.name == 'posix':
        try:
            command = ['systemctl', 'list-units', '--type=service', '--all', '--no-pager']
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            output_lines = result.stdout.splitlines()
            for line in output_lines:
                if query.lower() in line.lower():
                    parts = line.split(maxsplit=4)
                    if len(parts) >= 4:
                        results['services'].append({
                            'unit': parts[0],
                            'load': parts[1],
                            'active': parts[2],
                            'sub': parts[3],
                            'description': parts[4] if len(parts) > 4 else ''
                        })
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass # Ignore errors if systemctl is not available or fails

    # Search disk
    disk_results = search_disk(query)
    if isinstance(disk_results, list):
        results['disk'] = disk_results

    return render_template('search_results.html', results=results)

# --- Configuration de l'IA Gemini ---
# IMPORTANT: Remplacez "VOTRE_CLE_API_GEMINI" par votre véritable clé API Gemini.
# Vous pouvez l'obtenir sur le site de Google AI Studio.
# Pour plus de sécurité, utilisez des variables d'environnement en production.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Si la clé API n'est pas définie, nous ne chargerons pas le modèle IA et afficherons un avertissement.
# Cela permet à l'application de démarrer même sans la clé, mais la fonctionnalité IA sera désactivée.
if not GEMINI_API_KEY:
    model = None
    print("Avertissement: La variable d'environnement GEMINI_API_KEY n'est pas définie. Les fonctionnalités d'IA seront désactivées.")
else:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('models/gemini-flash-latest') # Correction du nom du modèle
        print("Modèle Gemini Flash (latest) chargé avec succès.")
    except ImportError:
        model = None
        print("Avertissement: La bibliothèque google-generativeai n'est pas installée. `pip install google-generativeai` pour activer les fonctionnalités d'IA.")
    except Exception as e:
        model = None
        print(f"Erreur lors de la configuration de Gemini: {e}")


@app.route('/analyze', methods=['POST'])
def analyze_item():
    # Vérifie si le modèle Gemini est bien configuré
    if not model:
        return jsonify({'error': "Le modèle d'IA n'est pas configuré. Veuillez vérifier la clé API et l'installation."}), 500

    # Récupère les données envoyées par le frontend
    data = request.get_json()
    item_type = data.get('type')
    item_data = data.get('data')
    
    # Détermine le système d'exploitation du serveur pour contextualiser le prompt de l'IA
    system_os = platform.system()

    # Vérifie si les données essentielles sont présentes
    if not item_type or not item_data:
        return jsonify({'error': 'Données d\'analyse manquantes.'}), 400

    # Initialise le prompt pour l'IA avec un contexte général
    prompt = f"En tant qu'expert système pour {system_os}, analyse l'élément suivant et réponds de manière concise en français:\n\n"

    # Construit le prompt spécifique en fonction du type d'élément
    if item_type == 'process':
        # Gère les cas où le nom d'utilisateur pourrait être absent
        username = item_data.get('username', 'N/A')
        prompt += f"""
        **Élément à analyser :** Processus
        - **Nom :** {item_data.get('name')}
        - **PID :** {item_data.get('pid')}
        - **Utilisateur :** {username}
        - **% CPU :** {item_data.get('cpu_percent')}
        - **% Mémoire :** {item_data.get('memory_percent')}

        **Tâches :**
        1.  **Identifier le processus :** Quel est son rôle principal ?
        2.  **Analyser l'impact :** Quelles sont les conséquences si je l'arrête ? (Critique pour le système, application spécifique, sans danger ?)
        3.  **Proposer une action :** Fournis la commande exacte et sûre pour l'arrêter sur {system_os}. Si l'arrêt est déconseillé, dis-le clairement.
        **Formule ta réponse entièrement en Markdown.**
        """
    elif item_type == 'service':
        prompt += f"""
        **Élément à analyser :** Service
        - **Unité :** {item_data.get('unit')}
        - **État :** {item_data.get('active')} / {item_data.get('sub')}
        - **Description :** {item_data.get('description')}
        
        **Tâches :**
        1.  **Identifier le service :** À quoi sert ce service ?
        2.  **Analyser l'impact :** Qu'arrive-t-il si je le désactive ou l'arrête ? Est-ce risqué pour la stabilité ou la sécurité du système ?
        3.  **Proposer une action :** Fournis les commandes (`systemctl` pour Linux, `net` ou `sc` pour Windows, `launchctl` pour macOS) pour l'arrêter, le redémarrer et vérifier son statut.
        **Formule ta réponse entièrement en Markdown.**
        """
    elif item_type == 'disk':
        prompt += f"""
        **Élément à analyser :** Fichier ou Répertoire
        - **Chemin :** {item_data.get('path')}
        - **Taille :** {item_data.get('size')}
        
        **Tâches :**
        1.  **Estimer le contenu et la criticité :** Que pourrait contenir cet élément en se basant sur son chemin ? Fais une estimation basée sur les conventions de nommage des systèmes {system_os} (ex: fichiers journaux, fichiers temporaires, données utilisateur, fichiers système).
        2.  **Évaluer le risque :** Est-il généralement sûr de le supprimer ? Indique si c'est un fichier système critique, un cache d'application, un fichier utilisateur, etc.
        3.  **Proposer une action :** Suggérer s'il est plausible de supprimer le contenu pour libérer de l'espace, et inclure un avertissement sur les précautions à prendre.
        **Formule ta réponse entièrement en Markdown.**
        """
    elif item_type == 'app':
        prompt += f"""
        **Élément à analyser :** Application installée
        - **Nom :** {item_data.get('name')}
        - **Taille installée :** {item_data.get('size')}
        - **Détail :** {item_data.get('description', 'N/A')}

        **Tâches :**
        1.  **Identifier l'application :** À quoi sert-elle ? S'agit-il d'une application utilisateur, d'une bibliothèque système ou d'une dépendance ?
        2.  **Analyser l'impact :** Est-elle probablement utilisée activement, ou pourrait-elle être un résidu, une dépendance orpheline ou un doublon ?
        3.  **Proposer une action :** Fournis la commande exacte et sûre pour la désinstaller proprement sur {system_os} (ex : `sudo apt remove --purge nom-paquet && sudo apt autoremove` sous Debian/Ubuntu, `sudo dnf remove nom-paquet` sous Fedora/RHEL, le Panneau de configuration ou `winget uninstall` sous Windows, ou déplacer le bundle `.app` vers la corbeille sous macOS). Indique clairement si la désinstallation est risquée pour la stabilité du système.
        **Formule ta réponse entièrement en Markdown.**
        """
    else:
        # Renvoie une erreur si le type d'analyse n'est pas supporté
        return jsonify({'error': 'Type d\'analyse non supporté.'}), 400

    try:
        # Appelle le modèle Gemini pour générer l'analyse
        response = model.generate_content(prompt)
        # Renvoie la réponse de l'IA au frontend
        return jsonify({'analysis': response.text})
    except Exception as e:
        # Gère les erreurs lors de l'appel à l'API Gemini
        print(f"Erreur lors de l'appel à l'API Gemini: {e}")
        return jsonify({'error': f"Une erreur est survenue lors de la communication avec l'IA: {str(e)}"}), 500

if __name__ == '__main__':
    init_db()  # Initialise la base de données au démarrage
    log_metrics() # Log initial
    app.run(debug=True)

