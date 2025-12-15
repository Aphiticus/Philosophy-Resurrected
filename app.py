"""
Philosophy Resurrected - Minimal Flask app with SQLite backend.
Provides:
 - Dynamic homepage (index)
 - Admin dashboard to add albums, tracks, videos, images
 - Upload endpoint that saves files to uploads/
 - Simple ordering and homepage layout editing
 - Uses inline templates for index and admin for simplicity (single Python file)
"""


import os
import sqlite3
from flask import (
    Flask, g, render_template, render_template_string, request, redirect, url_for, jsonify, send_from_directory, abort
)
from werkzeug.utils import secure_filename
from pathlib import Path
import datetime
from cryptography.fernet import Fernet


BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "site.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"  
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_IMAGE = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_VIDEO = {"mp4", "webm", "mov", "ogg"}

# Encryption key setup
KEY_PATH = BASE_DIR / "filekey.key"
if not KEY_PATH.exists():
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as keyfile:
        keyfile.write(key)
else:
    with open(KEY_PATH, "rb") as keyfile:
        key = keyfile.read()
fernet = Fernet(key)


# Require admin pin to be set in environment for security
ADMIN_PIN = os.environ.get("PR_ADMIN_PIN")
if not ADMIN_PIN:
    raise RuntimeError("PR_ADMIN_PIN environment variable must be set for admin access. Do not hardcode passwords in code.")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder="static")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  


ADMIN_LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta charset="utf-8">
</head>
<body>
    <h1>Admin Login</h1>
    <form method="get" action="/admin">
        <label for="pin">Enter PIN:</label>
        <input type="password" name="pin" id="pin" required>
        <button type="submit">Login</button>
    </form>
</body>
</html>
"""

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        need_init = not DB_PATH.exists()
        db = g._database = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        try:
            db.execute("SELECT 1 FROM homepage_layout LIMIT 1")
        except sqlite3.OperationalError:
            if SCHEMA_PATH.exists():
                init_db(db)
            else:
                print(f"SCHEMA FILE NOT FOUND: {SCHEMA_PATH}")
        if need_init and SCHEMA_PATH.exists():
            init_db(db)
    return db

def init_db(db):
    db.row_factory = sqlite3.Row  
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()
    cur = db.cursor()
    cur.execute("SELECT COUNT(1) as c FROM albums")
    if cur.fetchone()["c"] == 0:
        now = datetime.datetime.utcnow().isoformat()
        cur.execute("INSERT INTO albums (title, description, cover_path, position, created_at) VALUES (?,?,?, ?, ?)",
                    ("Genesis (sample)", "A demo album to get you started.", "", 0, now))
    db.commit()

@app.teardown_appcontext
def close_connection(exc):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def allowed_file(filename, kind):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind == "image":
        return ext in ALLOWED_IMAGE
    if kind == "audio":
        return ext in ALLOWED_AUDIO
    if kind == "video":
        return ext in ALLOWED_VIDEO
    return False

def save_upload(file_storage):
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None
    save_path = Path(app.config["UPLOAD_FOLDER"]) / filename
    base, ext = os.path.splitext(filename)
    counter = 1
    while save_path.exists():
        filename = f"{base}_{counter}{ext}"
        save_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        counter += 1
    # Encrypt file data before saving
    file_data = file_storage.read()
    encrypted_data = fernet.encrypt(file_data)
    with open(save_path, "wb") as f:
        f.write(encrypted_data)
    file_storage.stream.seek(0)  # Reset stream in case needed elsewhere
    return filename

def delete_file_if_exists(filename):
    if not filename:
        return
    path = Path(app.config["UPLOAD_FOLDER"]) / filename
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        print(f"Failed to delete file {path}: {e}")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    safe = os.path.normpath(filename)
    if ".." in safe:
        abort(404)
    file_path = Path(app.config["UPLOAD_FOLDER"]) / safe
    if not file_path.exists():
        abort(404)
    try:
        with open(file_path, "rb") as f:
            encrypted_data = f.read()
        decrypted_data = fernet.decrypt(encrypted_data)
        # Guess mimetype from extension
        import mimetypes
        mime, _ = mimetypes.guess_type(str(file_path))
        from flask import Response
        return Response(decrypted_data, mimetype=mime or "application/octet-stream")
    except Exception as e:
        print(f"Failed to decrypt or send file: {e}")
        abort(500)

@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()  
    cur.execute("SELECT * FROM homepage_layout ORDER BY position ASC")
    layout = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT * FROM albums ORDER BY position ASC")
    albums = []
    for row in cur.fetchall():
        alb = dict(row)
        cur.execute("SELECT * FROM tracks WHERE album_id = ? ORDER BY position ASC", (alb["id"],))
        alb["tracks"] = [dict(t) for t in cur.fetchall()]
        albums.append(alb)
    cur.execute("SELECT * FROM videos ORDER BY position ASC")
    videos = [dict(v) for v in cur.fetchall()]
    cur.execute("SELECT * FROM media ORDER BY position ASC")
    media = [dict(m) for m in cur.fetchall()]
    return render_template("index.html", albums=albums, videos=videos, layout=layout, media=media)
def check_pin():
    provided = request.args.get("pin") or request.form.get("pin") or request.headers.get("X-Admin-Pin")
    return provided == ADMIN_PIN

@app.route("/admin", methods=["GET"])
def admin_page():
    if not check_pin():
        return render_template_string(ADMIN_LOGIN_TEMPLATE), 401
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM albums ORDER BY position ASC")
    albums = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM videos ORDER BY position ASC")
    videos = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM media ORDER BY position ASC")
    media = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM homepage_layout ORDER BY position ASC")
    layout = [dict(r) for r in cur.fetchall()]
    return render_template("admin.html", albums=albums, videos=videos, media=media, layout=layout, admin_pin=ADMIN_PIN)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    if "file" not in request.files:
        print("No file provided in request.files") 
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    kind = request.form.get("kind", "image")
    print(f"Upload received: filename={f.filename}, kind={kind}") 
    if f.filename == "":
        print("Empty filename")  
        return jsonify({"error": "empty filename"}), 400
    if not allowed_file(f.filename, kind):
        print(f"File type not allowed: {f.filename} for kind {kind}") 
        return jsonify({"error": f"file type not allowed for kind '{kind}'"}), 400
    filename = save_upload(f)
    if not filename:
        print("Save failed") 
        return jsonify({"error": "save failed"}), 500
    url = url_for("uploaded_file", filename=filename)
    db = get_db()
    now = datetime.datetime.utcnow().isoformat()
    cur = db.cursor()
    cur.execute("INSERT INTO media (title, file_path, kind, position, created_at) VALUES (?,?,?,?,?)",
                (f.filename, filename, kind, 0, now))
    db.commit()
    media_id = cur.lastrowid
    print(f"Upload success: {filename}, media_id={media_id}")  
    return jsonify({"success": True, "filename": filename, "url": url, "media_id": media_id})

@app.route("/api/add_album", methods=["POST"])
def api_add_album():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    cover_file = request.files.get("image")
    cover = ""
    if cover_file and allowed_file(cover_file.filename, "image"):
        cover = save_upload(cover_file)
    if not title:
        return jsonify({"error": "title required"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM albums")
    pos = cur.fetchone()["pos"]
    now = datetime.datetime.utcnow().isoformat()
    cur.execute("INSERT INTO albums (title, description, cover_path, position, created_at) VALUES (?,?,?,?,?)",
                (title, description, cover, pos, now))
    db.commit()
    return jsonify({"success": True, "album_id": cur.lastrowid})

@app.route("/api/add_track", methods=["POST"])
def api_add_track():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    album_id = request.form.get("album_id")
    title = request.form.get("title", "").strip()
    file = request.form.get("file", "").strip()
    if not album_id or not title or not file:
        return jsonify({"error": "album_id, title and file required"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM tracks WHERE album_id = ?", (album_id,))
    pos = cur.fetchone()["pos"]
    now = datetime.datetime.utcnow().isoformat()
    cur.execute("INSERT INTO tracks (album_id, title, file_path, position, created_at) VALUES (?,?,?,?,?)",
                (album_id, title, file, pos, now))
    db.commit()
    return jsonify({"success": True, "track_id": cur.lastrowid})

@app.route("/api/add_video", methods=["POST"])
def api_add_video():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    video_file = request.files.get("video")
    file = ""
    if video_file and allowed_file(video_file.filename, "video"):
        file = save_upload(video_file)
    thumbnail = request.form.get("thumbnail", "").strip()
    if not title or not file:
        return jsonify({"error": "title and file required"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM videos")
    pos = cur.fetchone()["pos"]
    now = datetime.datetime.utcnow().isoformat()
    cur.execute("INSERT INTO videos (title, file_path, thumbnail_path, description, position, created_at) VALUES (?,?,?,?,?,?)",
                (title, file, thumbnail, description, pos, now))
    db.commit()
    return jsonify({"success": True, "video_id": cur.lastrowid})

@app.route("/api/albums", methods=["GET"])
def api_get_albums():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM albums ORDER BY position ASC")
    albums = []
    for row in cur.fetchall():
        alb = dict(row)
        alb["image"] = url_for("uploaded_file", filename=alb["cover_path"]) if alb["cover_path"] else ""
        cur.execute("SELECT * FROM tracks WHERE album_id = ? ORDER BY position ASC", (alb["id"],))
        tracks = []
        for t in cur.fetchall():
            track = dict(t)
            track["path"] = url_for("uploaded_file", filename=track["file_path"])
            track["track_number"] = track.get("position", 0) + 1
            tracks.append(track)
        alb["tracks"] = tracks
        albums.append(alb)
    return jsonify(albums)

@app.route("/api/videos", methods=["GET"])
def api_get_videos():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM videos ORDER BY position ASC")
    videos = []
    for v in cur.fetchall():
        video = dict(v)
        video["path"] = url_for("uploaded_file", filename=video["file_path"])
        video["thumbnail"] = url_for("uploaded_file", filename=video["thumbnail_path"]) if video["thumbnail_path"] else ""
        video["description"] = video.get("description", "")
        videos.append(video)
    return jsonify(videos)

@app.route("/api/media", methods=["GET"])
def api_get_media():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM media ORDER BY position ASC")
    media = []
    for m in cur.fetchall():
        item = dict(m)
        item["path"] = url_for("uploaded_file", filename=item["file_path"])
        media.append(item)
    return jsonify(media)

@app.route("/api/homepage", methods=["GET"])
def api_get_homepage():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM homepage_layout ORDER BY position ASC")
    layout = []
    for row in cur.fetchall():
        item = dict(row)
        title = ""
        if item["type"] == "album" and item["reference_id"]:
            cur.execute("SELECT title FROM albums WHERE id = ?", (item["reference_id"],))
            r = cur.fetchone()
            if r: title = r["title"]
        elif item["type"] in {"video", "featured_video"} and item["reference_id"]:
            cur.execute("SELECT title FROM videos WHERE id = ?", (item["reference_id"],))
            r = cur.fetchone()
            if r: title = r["title"]
        elif item["type"] == "media" and item["reference_id"]:
            cur.execute("SELECT title FROM media WHERE id = ?", (item["reference_id"],))
            r = cur.fetchone()
            if r: title = r["title"]
        item["title"] = title
        layout.append(item)
    return jsonify(layout)

@app.route("/api/reorder", methods=["POST"])
def api_reorder():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json() or {}
    typ = payload.get("type")
    order = payload.get("order", [])
    album_id = payload.get("album_id")
    if typ not in {"albums", "tracks", "videos", "media", "homepage_layout"}:
        return jsonify({"error": "invalid type"}), 400
    db = get_db()
    cur = db.cursor()
    if typ == "tracks" and album_id is None:
        return jsonify({"error": "album_id required for tracks"}), 400
    table_map = {
        "albums": ("albums", None),
        "tracks": ("tracks", "album_id"),
        "videos": ("videos", None),
        "media": ("media", None),
        "homepage_layout": ("homepage_layout", None)
    }
    table, fk = table_map[typ]
    for pos, item_id in enumerate(order):
        if fk and typ == "tracks":
            cur.execute(f"UPDATE {table} SET position = ? WHERE id = ? AND album_id = ?", (pos, item_id, album_id))
        else:
            cur.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (pos, item_id))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/delete", methods=["POST"])
def api_delete():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    typ = request.form.get("type")
    item_id = request.form.get("id")
    if not typ or not item_id:
        return jsonify({"error": "type and id required"}), 400
    db = get_db()
    cur = db.cursor()
    if typ == "album":
        cur.execute("SELECT cover_path FROM albums WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row:
            delete_file_if_exists(row["cover_path"])
        cur.execute("SELECT file_path FROM tracks WHERE album_id = ?", (item_id,))
        for r in cur.fetchall():
            delete_file_if_exists(r["file_path"])
        cur.execute("DELETE FROM tracks WHERE album_id = ?", (item_id,))
        cur.execute("DELETE FROM albums WHERE id = ?", (item_id,))
    elif typ == "track":
        cur.execute("SELECT file_path FROM tracks WHERE id = ?", (item_id,))
        r = cur.fetchone()
        if r:
            delete_file_if_exists(r["file_path"])
        cur.execute("DELETE FROM tracks WHERE id = ?", (item_id,))
    elif typ == "video":
        cur.execute("SELECT file_path, thumbnail_path FROM videos WHERE id = ?", (item_id,))
        r = cur.fetchone()
        if r:
            delete_file_if_exists(r["file_path"])
            delete_file_if_exists(r["thumbnail_path"])
        cur.execute("DELETE FROM videos WHERE id = ?", (item_id,))
    elif typ == "media":
        cur.execute("SELECT file_path FROM media WHERE id = ?", (item_id,))
        r = cur.fetchone()
        if r:
            delete_file_if_exists(r["file_path"])
        cur.execute("DELETE FROM media WHERE id = ?", (item_id,))
    elif typ == "layout":
        cur.execute("DELETE FROM homepage_layout WHERE id = ?", (item_id,))
    else:
        return jsonify({"error": "unknown type"}), 400
    db.commit()
    return jsonify({"success": True})

@app.route("/api/update_album", methods=["POST"])
def api_update_album():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    album_id = request.form.get("id")
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    cover_file = request.files.get("image")
    db = get_db()
    cur = db.cursor()
    if not album_id or not title:
        return jsonify({"error": "id and title required"}), 400
    if cover_file and allowed_file(cover_file.filename, "image"):
        cover = save_upload(cover_file)
        cur.execute("UPDATE albums SET title=?, description=?, cover_path=? WHERE id=?",
                    (title, description, cover, album_id))
    else:
        cur.execute("UPDATE albums SET title=?, description=? WHERE id=?",
                    (title, description, album_id))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/update_video", methods=["POST"])
def api_update_video():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    video_id = request.form.get("id")
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    thumbnail = request.form.get("thumbnail", "").strip()
    video_file = request.files.get("video")
    if not video_id or not title:
        return jsonify({"error": "id and title required"}), 400
    if video_file and not allowed_file(video_file.filename, "video"):
        return jsonify({"error": "invalid video type"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
    if not cur.fetchone():
        return jsonify({"error": "video not found"}), 404
    if video_file:
        file_path = save_upload(video_file)
        cur.execute("UPDATE videos SET title=?, description=?, file_path=?, thumbnail_path=? WHERE id=?",
                    (title, description, file_path, thumbnail, video_id))
    else:
        cur.execute("UPDATE videos SET title=?, description=?, thumbnail_path=? WHERE id=?",
                    (title, description, thumbnail, video_id))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/add_layout_block", methods=["POST"])
def api_add_layout_block():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    block_type = request.form.get("block_type")
    ref_id = request.form.get("ref_id") 
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM homepage_layout")
    pos = cur.fetchone()["pos"]
    now = datetime.datetime.utcnow().isoformat()
    cur.execute("INSERT INTO homepage_layout (type, reference_id, position, created_at) VALUES (?,?,?,?)",
                (block_type, ref_id or None, pos, now))
    db.commit()
    return jsonify({"success": True, "block_id": cur.lastrowid})
@app.route("/generator")
def generator_page():
    return render_template("generator.html")

@app.route("/api/set_featured_video", methods=["POST"])
def api_set_featured_video():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    video_id = request.form.get("video_id")
    if not video_id:
        return jsonify({"error": "video_id required"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
    if not cur.fetchone():
        return jsonify({"error": "video not found"}), 404
    cur.execute("SELECT id FROM homepage_layout WHERE type = 'featured_video'")
    row = cur.fetchone()
    now = datetime.datetime.utcnow().isoformat()
    if row:
        cur.execute("UPDATE homepage_layout SET reference_id = ? WHERE id = ?", (video_id, row["id"]))
    else:
        cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM homepage_layout")
        pos = cur.fetchone()["pos"]
        cur.execute("INSERT INTO homepage_layout (type, reference_id, position, created_at) VALUES (?,?,?,?)",
                    ("featured_video", video_id, pos, now))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/add_album_bundle", methods=["POST"])
def api_add_album_bundle():
    if not check_pin():
        return jsonify({"error": "unauthorized"}), 401
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    cover_file = request.files.get("cover")
    track_files = request.files.getlist("tracks")
    if not title or not track_files:
        return jsonify({"error": "title and at least one track required"}), 400
    cover = ""
    if cover_file and allowed_file(cover_file.filename, "image"):
        cover = save_upload(cover_file)
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 as pos FROM albums")
    pos = cur.fetchone()["pos"]
    now = datetime.datetime.utcnow().isoformat()
    cur.execute("INSERT INTO albums (title, description, cover_path, position, created_at) VALUES (?,?,?,?,?)",
                (title, description, cover, pos, now))
    album_id = cur.lastrowid
    for idx, f in enumerate(track_files):
        if not allowed_file(f.filename, "audio"):
            continue
        saved = save_upload(f)
        cur.execute("INSERT INTO tracks (album_id, title, file_path, position, created_at) VALUES (?,?,?,?,?)",
                    (album_id, f.filename.rsplit(".", 1)[0], saved, idx, now))
    db.commit()
    return jsonify({"success": True, "album_id": album_id, "tracks_added": len(track_files)})

if __name__ == "__main__":
    if not DB_PATH.exists() and SCHEMA_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        init_db(conn)
        conn.close()
    app.run(debug=True, port=5000)
