import os,sqlite3,datetime,mimetypes as mt
from flask import Flask,g,render_template as rt,render_template_string as rts,request as rq,redirect,url_for as uf,jsonify as jy,abort,Response
from werkzeug.utils import secure_filename as sf
from pathlib import Path
from cryptography.fernet import Fernet

B=Path(__file__).parent.resolve()
DB=B/"site.db"
SC=B/"database"/"schema.sql"
UP=Path("/var/data/uploads")
AL={"img":{"png","jpg","jpeg","gif","svg","webp"},"aud":{"mp3","wav","ogg","m4a"},"vid":{"mp4","webm","mov"}}
K=B/"filekey.key"

if not K.exists():
    k=Fernet.generate_key()
    K.write_bytes(k)
else:
    k=K.read_bytes()
fn=Fernet(k)

PN=os.environ.get("PR_ADMIN_PIN")
if not PN: raise RuntimeError("Set PR_ADMIN_PIN")
UP.mkdir(parents=True,exist_ok=True)

app=Flask(__name__,static_folder="static")
app.config["MAX_CONTENT_LENGTH"]=1024**3

def db():
    d=getattr(g,"_db",None)
    if d is None:
        d=g._db=sqlite3.connect(str(DB))
        d.row_factory=sqlite3.Row
        try: d.execute("SELECT 1 FROM albums LIMIT 1")
        except: 
            if SC.exists():
                d.executescript(SC.read_text())
                d.commit()
    return d

@app.teardown_appcontext
def cls(e):
    d=getattr(g,"_db",None)
    if d: d.close()

def ok(n,k):
    e=n.rsplit(".",1)[-1].lower() if "." in n else ""
    return e in AL.get(k,set())

def sv(f):
    n=sf(f.filename)
    if not n: return None
    p=UP/n
    c=1
    while p.exists():
        b,e=os.path.splitext(n)
        n=f"{b}_{c}{e}";p=UP/n;c+=1
    d=f.read()
    p.write_bytes(fn.encrypt(d))
    return n

@app.route("/uploads/<path:n>")
def dl(n):
    p=UP/os.path.normpath(n)
    if not p.exists() or ".." in n: abort(404)
    try:
        d=fn.decrypt(p.read_bytes())
        m,_=mt.guess_type(str(p))
        return Response(d,mimetype=m or "application/octet-stream")
    except: abort(500)

def auth():
    p=rq.args.get("pin") or rq.form.get("pin") or rq.headers.get("X-Admin-Pin")
    return p==PN

@app.route("/")
def idx():
    d=db();c=d.cursor()
    L=[dict(r) for r in c.execute("SELECT * FROM homepage_layout ORDER BY position").fetchall()]
    A=[]
    for r in c.execute("SELECT * FROM albums ORDER BY position").fetchall():
        a=dict(r)
        a["tracks"]=[dict(t) for t in c.execute("SELECT * FROM tracks WHERE album_id=? ORDER BY position",(a["id"],)).fetchall()]
        A.append(a)
    V=[dict(v) for v in c.execute("SELECT * FROM videos ORDER BY position").fetchall()]
    M=[dict(m) for m in c.execute("SELECT * FROM media ORDER BY position").fetchall()]
    return rt("index.html",albums=A,videos=V,layout=L,media=M)

@app.route("/api/upload",methods=["POST"])
def up():
    if not auth(): return jy({"e": "unauth"}),401
    f=rq.files.get("file")
    k=rq.form.get("kind","img")
    if not f or not ok(f.filename,k): return jy({"e":"fail"}),400
    n=sv(f)
    d=db();c=d.cursor()
    c.execute("INSERT INTO media (title,file_path,kind,position,created_at) VALUES (?,?,?,0,?)",(f.filename,n,k,datetime.datetime.utcnow().isoformat()))
    d.commit()
    return jy({"success":True,"id":c.lastrowid})

@app.route("/api/reorder",methods=["POST"])
def reo():
    if not auth(): return jy({"e":1}),401
    p=rq.get_json();t=p.get("type");o=p.get("order",[]);aid=p.get("album_id")
    d=db();c=d.cursor()
    tbl={"albums":"albums","tracks":"tracks","videos":"videos","media":"media","layout":"homepage_layout"}
    m=tbl.get(t)
    for i,v in enumerate(o):
        if t=="tracks": c.execute(f"UPDATE {m} SET position=? WHERE id=? AND album_id=?",(i,v,aid))
        else: c.execute(f"UPDATE {m} SET position=? WHERE id=?",(i,v))
    d.commit()
    return jy({"success":True})

if __name__=="__main__":
    app.run(debug=True,port=5000)
