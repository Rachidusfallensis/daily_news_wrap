import os
import re
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime, timezone

NOTES_DIR = "/Users/aronafall/Desktop/Ph.D./thesis-ai-lab/bibliography/notes"
API_URL = "http://localhost/api/notes/sync"
# The user's env has AUTH_PASSWORD. Let's authenticate first.
# Auth is cookie based.
AUTH_URL = "http://localhost/auth/login"
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "etB004YyR0seFWB2VOM")

def login():
    data = json.dumps({"password": AUTH_PASSWORD, "remember": True}).encode("utf-8")
    req = urllib.request.Request(AUTH_URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        cookie = resp.headers.get("Set-Cookie")
        if cookie:
            # simple cookie extraction
            return cookie.split(";")[0]
        return None
    except Exception as e:
        print(f"Login failed: {e}")
        return None

def parse_note(filepath, filename):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Try to extract title, bibtex_key, theme
    title = None
    bibtex_key = None
    theme = None
    
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        
    bibtex_match = re.search(r"\*\*BibTeX key\*\*:\s*(.+)$", content, re.MULTILINE)
    if bibtex_match:
        bibtex_key = bibtex_match.group(1).strip()
        
    theme_match = re.search(r"\*\*Theme\*\*:\s*(.+)$", content, re.MULTILINE)
    if theme_match:
        theme = theme_match.group(1).strip()
        
    cluster = None
    cluster_match = re.search(r"\|\s*cluster:\s*([a-zA-Z0-9\-_]+)", content)
    if cluster_match:
        cluster = cluster_match.group(1).strip()
        
    stat = os.stat(filepath)
    last_modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    
    return {
        "filename": filename,
        "title": title,
        "bibtex_key": bibtex_key,
        "theme": theme,
        "cluster": cluster,
        "content_md": content,
        "last_modified": last_modified
    }

def main():
    if not os.path.exists(NOTES_DIR):
        print(f"Notes directory not found: {NOTES_DIR}")
        return
        
    notes_payload = []
    for filename in os.listdir(NOTES_DIR):
        if filename.endswith(".md"):
            filepath = os.path.join(NOTES_DIR, filename)
            notes_payload.append(parse_note(filepath, filename))
            
    if not notes_payload:
        print("No markdown files found.")
        return
        
    print(f"Found {len(notes_payload)} notes. Syncing to {API_URL}...")
    
    cookie = login()
    if not cookie:
        print("Could not authenticate.")
        return
        
    data = json.dumps({"notes": notes_payload}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json", "Cookie": cookie}, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode("utf-8"))
        print(f"Sync complete: {result}")
    except Exception as e:
        print(f"Sync failed: {e}")
        if hasattr(e, "read"):
            print(e.read().decode("utf-8"))

if __name__ == "__main__":
    main()
