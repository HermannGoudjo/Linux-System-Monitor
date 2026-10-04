import subprocess
import os

def get_disk_usage_linux(path, top_n=10):
    """
    Obtient les N plus gros fichiers/dossiers pour un chemin donné en utilisant
    la commande `du`, qui est très rapide sur Linux.
    """
    try:
        # Exécute la commande `du` pour lister les tailles et `sort` pour les trier.
        # `du -a` : Affiche les fichiers et les dossiers.
        # `--max-depth=1` : Limite l'analyse au premier niveau du `path`.
        # `sort -rh` : Trie par taille lisible par l'homme, en ordre décroissant.
        # `head -n {top_n}` : Prend les N premiers résultats.
        command = f"du -ah --max-depth=1 {path} | sort -rh | head -n {top_n}"
        
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        lines = result.stdout.strip().split('\n')
        
        top_files = []
        for line in lines:
            if not line:
                continue
            # Sépare la taille (ex: "1.2G") du chemin
            size, file_path = line.split('\t', 1)
            top_files.append({"size": size.strip(), "path": file_path.strip()})
            
        return top_files

    except subprocess.CalledProcessError as e:
        # Gère les erreurs si la commande `du` échoue
        error_message = e.stderr.strip()
        print(f"Erreur avec la commande 'du': {error_message}")
        return {"error": "La commande 'du' a échoué.", "details": error_message}
    except Exception as e:
        # Gère les autres erreurs inattendues
        print(f"Erreur inattendue lors du scan des dossiers : {e}")
        return {"error": "Une erreur inattendue est survenue.", "details": str(e)}

def get_disk_usage_cross_platform(path, top_n=10):
    """
    Obtient les N plus gros fichiers/dossiers pour un chemin donné en utilisant
    des modules Python. C'est plus lent mais multiplateforme.
    """
    try:
        dir_sizes = {}
        # Liste les éléments à la racine du chemin donné
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            total_size = 0
            
            # Si c'est un dossier, on parcourt son contenu
            if os.path.isdir(full_path):
                for dirpath, dirnames, filenames in os.walk(full_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            # Ajoute la taille du fichier au total
                            total_size += os.path.getsize(fp)
                        except OSError:
                            # Ignore les fichiers qu'on ne peut pas lire (permissions, etc.)
                            pass
                dir_sizes[full_path] = total_size
            # Si c'est un fichier, on prend sa taille directement
            elif os.path.isfile(full_path):
                try:
                    dir_sizes[full_path] = os.path.getsize(full_path)
                except OSError:
                    pass

        # Trie les répertoires/fichiers par taille (décroissant)
        sorted_dirs = sorted(dir_sizes.items(), key=lambda item: item[1], reverse=True)

        # Formate le top N pour l'affichage
        top_files = []
        for i, (path, size_bytes) in enumerate(sorted_dirs):
            if i >= top_n:
                break
            
            # Formate la taille pour être lisible
            if size_bytes > 1024 * 1024 * 1024:
                size_formatted = f"{size_bytes / (1024**3):.2f} GB"
            elif size_bytes > 1024 * 1024:
                size_formatted = f"{size_bytes / (1024**2):.2f} MB"
            elif size_bytes > 1024:
                size_formatted = f"{size_bytes / 1024:.2f} KB"
            else:
                size_formatted = f"{size_bytes} B"
            
            top_files.append({"size": size_formatted, "path": path})
            
        return top_files

    except Exception as e:
        print(f"Erreur lors du scan des dossiers : {e}")
        return {"error": "Erreur lors du scan des dossiers", "details": str(e)}

def search_disk(query, search_path='~'):
    """
    Recherche des fichiers et des dossiers contenant la chaîne de requête dans leur nom.
    Limite la recherche au chemin spécifié (par défaut, le répertoire personnel de l'utilisateur).
    """
    matches = []
    # Étend le chemin '~' au répertoire personnel complet
    abs_search_path = os.path.expanduser(search_path)
    
    # Limite le nombre de résultats pour éviter de surcharger
    MAX_RESULTS = 100 
    
    try:
        for root, dirs, files in os.walk(abs_search_path, topdown=True):
            # Filtre les répertoires à ne pas visiter pour améliorer la performance
            # Par exemple, on pourrait exclure .git, __pycache__, etc.
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for name in files + dirs:
                if len(matches) >= MAX_RESULTS:
                    break
                if query.lower() in name.lower():
                    full_path = os.path.join(root, name)
                    matches.append(full_path)
            
            if len(matches) >= MAX_RESULTS:
                break
                
        return matches

    except Exception as e:
        print(f"Erreur lors de la recherche sur le disque : {e}")
        return {"error": "Erreur lors de la recherche", "details": str(e)}


