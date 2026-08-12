import os, sqlite3, requests
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "smart-tourism-demo-key")
DB = "tourism.db"

# EXACTLY 10 places. Images are found by the exact place name using Wikimedia Commons,
# so one generic image is never reused for all cards.
PLACES = [
("Dassam Falls","Ranchi","Jharkhand","Waterfall,Nature,Photography","Kanchi River waterfall near Taimara.","October to January",350,"23.3437,85.4311","Dassam Falls Ranchi Jharkhand"),
("Hundru Falls","Ranchi","Jharkhand","Waterfall,Nature,Photography","Famous waterfall on the Subarnarekha River.","October to February",400,"23.4542,85.6027","Hundru Falls Ranchi Jharkhand"),
("Betla National Park","Latehar","Jharkhand","Wildlife,Nature,Forest,Adventure","Wildlife destination in the Palamu Tiger Reserve.","November to March",1200,"23.8700,84.1900","Betla National Park Jharkhand"),
("Netarhat","Latehar","Jharkhand","Hill Station,Nature,Sunset,Photography","Hill station known for sunrise, sunset and forests.","October to March",1000,"23.4720,84.2670","Netarhat Jharkhand Magnolia Point"),
("Baba Baidyanath Dham","Deoghar","Jharkhand","Religious,Temple,Spiritual,Family","Major Shiva pilgrimage temple in Deoghar.","October to March",900,"24.4852,86.6948","Baidyanath Temple Deoghar Jharkhand"),
("Patratu Valley","Ramgarh","Jharkhand","Nature,Hills,Adventure,Photography","Scenic winding roads through green hills.","October to February",600,"23.6500,85.3000","Patratu Valley Jharkhand"),
("Jagannath Temple Ranchi","Ranchi","Jharkhand","Religious,Temple,Photography","Historic hilltop Jagannath temple in Ranchi.","October to February",300,"23.3338,85.3157","Jagannath Temple Ranchi Jharkhand"),
("Dimna Lake","Jamshedpur","Jharkhand","Lake,Nature,Family,Photography","Scenic lake surrounded by hills near Jamshedpur.","October to February",500,"22.8100,86.2500","Dimna Lake Jamshedpur Jharkhand"),
("Dalma Wildlife Sanctuary","Jamshedpur","Jharkhand","Wildlife,Nature,Forest,Adventure","Elephant habitat and forest sanctuary in Dalma Hills.","October to March",900,"22.9000,86.2000","Dalma Wildlife Sanctuary Jamshedpur Jharkhand"),
("Naulakha Mandir","Deoghar","Jharkhand","Religious,Temple,Architecture,Photography","Historic temple with distinctive architecture in Deoghar.","October to March",400,"24.4700,86.6900","Naulakha Mandir Deoghar Jharkhand"),
]

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS places(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE, city TEXT, state TEXT, category TEXT,
      description TEXT, best_time TEXT, budget INTEGER,
      latlng TEXT, image_url TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
      email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS reviews(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, place_id INTEGER,
      rating INTEGER, comment TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
      interest TEXT, city TEXT, budget TEXT, season TEXT, created_at TEXT
    );
    """)
    for p in PLACES:
        c.execute("""INSERT OR IGNORE INTO places
        (name,city,state,category,description,best_time,budget,latlng)
        VALUES (?,?,?,?,?,?,?,?)""", p[:8])
    # Keep the database limited to the requested 10 places.
    names = tuple(p[0] for p in PLACES)
    marks = ",".join("?" for _ in names)
    c.execute(f"DELETE FROM places WHERE name NOT IN ({marks})", names)
    # Verified exact image for Naulakha Temple, Deoghar.
    c.execute("UPDATE places SET image_url=? WHERE name=?",
              ("https://commons.wikimedia.org/wiki/Special:Redirect/file/Naulakha%20Temple%2C%20Deoghar%2C%20Jharkhand.jpg", "Naulakha Mandir"))
    c.execute("""INSERT OR IGNORE INTO users(name,email,password,is_admin)
                 VALUES(?,?,?,1)""",
              ("Administrator","admin@smarttourism.com",
               generate_password_hash("admin123")))
    c.commit()
    c.close()

def find_wikimedia_image(search_term):
    """Search Wikimedia Commons for a place-specific image."""
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action":"query","generator":"search","gsrsearch":search_term,
                "gsrnamespace":6,"gsrlimit":1,
                "prop":"imageinfo","iiprop":"url","iiurlwidth":1000,
                "format":"json"
            },
            headers={"User-Agent":"SmartTourismStudentProject/1.0"},
            timeout=8
        )
        data = r.json()
        pages = data.get("query",{}).get("pages",{})
        if pages:
            page = next(iter(pages.values()))
            info = page.get("imageinfo",[{}])[0]
            return info.get("thumburl") or info.get("url") or ""
    except Exception:
        pass
    return ""

def refresh_images():
    c = db()
    for name, city, state, category, desc, best, budget, latlng, search_term in PLACES:
        row = c.execute("SELECT image_url FROM places WHERE name=?",(name,)).fetchone()
        if not row or not row["image_url"]:
            image = find_wikimedia_image(search_term)
            if image:
                c.execute("UPDATE places SET image_url=? WHERE name=?",(image,name))
    c.commit()
    c.close()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return f(*a,**kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get("is_admin"):
            flash("Admin access required.")
            return redirect(url_for("home"))
        return f(*a,**kw)
    return w

def recommend(interest="", city="", budget="", season=""):
    c=db(); rows=c.execute("SELECT * FROM places").fetchall(); c.close()
    if not rows: return []
    docs=[]
    for r in rows:
        docs.append(f"{r['name']} {r['category']} {r['description']} {r['city']} {r['best_time']}")
    vector=TfidfVectorizer(stop_words="english")
    matrix=vector.fit_transform(docs)
    query=vector.transform([f"{interest} {city} {budget} {season}"])
    scores=cosine_similarity(query,matrix).flatten()
    out=[]
    for r,s in zip(rows,scores):
        score=float(s)
        if city and r["city"].lower()==city.lower(): score+=0.30
        if interest and interest.lower() in r["category"].lower(): score+=0.40
        out.append({**dict(r),"score":score})
    return sorted(out,key=lambda x:x["score"],reverse=True)

@app.route("/")
def home():
    c=db()
    places=c.execute("SELECT * FROM places ORDER BY id").fetchall()
    cities=[x[0] for x in c.execute("SELECT DISTINCT city FROM places ORDER BY city")]
    c.close()
    return render_template("index.html",places=places,cities=cities)

@app.route("/recommend",methods=["POST"])
def recommendations():
    interest=request.form.get("interest","")
    city=request.form.get("city","")
    budget=request.form.get("budget","")
    season=request.form.get("season","")
    results=recommend(interest,city,budget,season)
    if session.get("user_id"):
        c=db(); c.execute("""INSERT INTO history(user_id,interest,city,budget,season,created_at)
        VALUES(?,?,?,?,?,?)""",(session["user_id"],interest,city,budget,season,datetime.now().isoformat())); c.commit(); c.close()
    return render_template("results.html",results=results,interest=interest,city=city,budget=budget,season=season)

@app.route("/place/<int:place_id>")
def place(place_id):
    c=db()
    p=c.execute("SELECT * FROM places WHERE id=?",(place_id,)).fetchone()
    reviews=c.execute("""SELECT reviews.*,users.name FROM reviews
        JOIN users ON users.id=reviews.user_id WHERE place_id=? ORDER BY reviews.id DESC""",(place_id,)).fetchall()
    avg=c.execute("SELECT AVG(rating) FROM reviews WHERE place_id=?",(place_id,)).fetchone()[0] or 0
    c.close()
    return render_template("place.html",place=p,reviews=reviews,avg=round(avg,1))

@app.route("/weather/<city>")
def weather(city):
    """Live weather with Open-Meteo. No API key required."""
    try:
        geo=requests.get("https://geocoding-api.open-meteo.com/v1/search",
            params={"name":city,"count":1,"language":"en","format":"json"},timeout=8).json()
        if not geo.get("results"): return jsonify(ok=False,message="Location not found")
        g=geo["results"][0]
        data=requests.get("https://api.open-meteo.com/v1/forecast",
            params={"latitude":g["latitude"],"longitude":g["longitude"],
                    "current":"temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
                    "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone":"auto","forecast_days":5},timeout=8).json()
        return jsonify(ok=True,city=g["name"],current=data.get("current",{}),daily=data.get("daily",{}))
    except Exception:
        return jsonify(ok=False,message="Weather service unavailable")

@app.route("/search")
def search():
    q=request.args.get("q","").strip()
    c=db()
    rows=c.execute("""SELECT * FROM places WHERE name LIKE ? OR city LIKE ? OR
                      category LIKE ? OR description LIKE ? ORDER BY name""",
                   (f"%{q}%",f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    c.close()
    return render_template("search.html",results=rows,q=q)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        try:
            c=db(); c.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",
              (request.form["name"],request.form["email"].lower(),generate_password_hash(request.form["password"])))
            c.commit(); c.close(); flash("Registered successfully."); return redirect(url_for("login"))
        except sqlite3.IntegrityError: flash("Email already registered.")
    return render_template("auth.html",mode="register")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(request.form["email"].lower(),)).fetchone(); c.close()
        if u and check_password_hash(u["password"],request.form["password"]):
            session.update(user_id=u["id"],name=u["name"],is_admin=bool(u["is_admin"]))
            return redirect(url_for("home"))
        flash("Invalid email or password.")
    return render_template("auth.html",mode="login")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/profile")
@login_required
def profile():
    c=db(); user=c.execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone()
    history=c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    c.close(); return render_template("profile.html",user=user,history=history)

@app.route("/review/<int:place_id>",methods=["POST"])
@login_required
def review(place_id):
    c=db(); c.execute("""INSERT INTO reviews(user_id,place_id,rating,comment,created_at)
    VALUES(?,?,?,?,?)""",(session["user_id"],place_id,int(request.form["rating"]),
                            request.form["comment"],datetime.now().isoformat()))
    c.commit(); c.close(); return redirect(url_for("place",place_id=place_id))

@app.route("/admin")
@admin_required
def admin():
    c=db(); places=c.execute("SELECT * FROM places ORDER BY name").fetchall()
    users=c.execute("SELECT id,name,email FROM users ORDER BY id").fetchall(); c.close()
    return render_template("admin.html",places=places,users=users)

if __name__=="__main__":
    init_db()
    refresh_images()
    app.run(debug=True)
