import os
import re
import io
import shutil
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageOps, ExifTags

# Permitir sobrescrever o caminho do banco via variável de ambiente
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "cuidabem.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB para fotos
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ACTIVITY_CATEGORIES = [
    ("caminhada", "Caminhada"),
    ("natacao", "Natação"),
    ("ciclismo", "Ciclismo"),
    ("musculacao", "Musculação"),
    ("pilates", "Pilates"),
]
CATEGORY_LABELS = dict(ACTIVITY_CATEGORIES)

# Tipos de diabetes e relações de emergência
DIABETES_TYPES = [
    ("tipo_1", "Tipo 1"),
    ("tipo_2", "Tipo 2"),
    ("pre_diabetes", "Pré-diabetes"),
    ("gestacional", "Gestacional"),
]
DIABETES_TYPE_LABELS = dict(DIABETES_TYPES)
EMERGENCY_RELATIONS = [
    ("pai", "Pai"),
    ("mae", "Mãe"),
    ("cuidador", "Cuidador"),
]
EMERGENCY_RELATION_LABELS = dict(EMERGENCY_RELATIONS)

# Tipos de alerta e dias da semana
ALERT_TYPES = [
    ("medicacao", "Medicação"),
    ("refeicao", "Refeição"),
    ("glicemia", "Medição de Glicemia"),
    ("exercicio", "Exercício físico"),
    ("consulta", "Consulta médica"),
]
ALERT_TYPE_LABELS = dict(ALERT_TYPES)
DAYS_OF_WEEK = [
    ("mon", "Segunda"),
    ("tue", "Terça"),
    ("wed", "Quarta"),
    ("thu", "Quinta"),
    ("fri", "Sexta"),
    ("sat", "Sábado"),
    ("sun", "Domingo"),
]
DAY_LABELS = dict(DAYS_OF_WEEK)
# Momentos da medição de glicemia
MEASUREMENT_CONTEXTS = [
    ("em_jejum", "Em Jejum"),
    ("antes_refeicao", "Antes da Refeição"),
    ("2h_pos_refeicao", "2h após a refeição"),
    ("antes_dormir", "Antes de dormir"),
]
MEASUREMENT_CONTEXT_LABELS = dict(MEASUREMENT_CONTEXTS)

MEAL_TYPES = [
    ("cafe_manha", "Café da Manhã"),
    ("almoco", "Almoço"),
    ("lanche", "Lanche"),
    ("jantar", "Jantar"),
]
MEAL_TYPE_LABELS = dict(MEAL_TYPES)

# Leitor OCR carregado sob demanda (evita download de modelos no boot)
_ocr_reader = None


def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _ocr_reader


# Modelo de classificação de imagens (MobileNetV3 treinado no ImageNet)
_food_model = None
_food_transform = None
_food_categories = None

# Tradução das categorias do ImageNet para português
IMAGE_NET_PT = {
    "apple": "maçã", "banana": "banana", "orange": "laranja", "lemon": "limão",
    "strawberry": "morango", "pineapple": "abacaxi", "fig": "figo", "pomegranate": "romã",
    "carbonara": "carbonara", "pizza": "pizza", "cheeseburger": "cheeseburger",
    "hotdog": "cachorro-quente", "guacamole": "guacamole", "burrito": "burrito",
    "ice cream": "sorvete", "ice lolly": "picolé", "French loaf": "baguete",
    "bagel": "bagel", "pretzel": "pretzel", "potpie": "torta salgada",
    "consomme": "caldo", "hot pot": "fondue", "mashed potato": "purê de batata",
    "chocolate sauce": "calda de chocolate", "dough": "massa", "meat loaf": "rolo de carne",
    "eggnog": "gemada", "corn": "milho", "broccoli": "brócolis",
    "custard apple": "fruta-do-conde", "acorn squash": "abóbora",
    "butternut squash": "abóbora", "strawberry": "morango",
    "bakery": "padaria", "coffee mug": "caneca de café", "coffeepot": "cafeteira",
    "espresso": "café espresso", "espresso maker": "máquina de café",
    "red wine": "vinho tinto", "wine bottle": "garrafa de vinho",
    "beer bottle": "garrafa de cerveja", "beer glass": "copo de cerveja",
    "plate": "prato", "cup": "copo", "soup bowl": "tigela de sopa",
    "mixing bowl": "tigela de mistura", "milk can": "lata de leite",
    "teapot": "bule de chá", "wooden spoon": "colher de pau",
    "dining table": "mesa de jantar", "restaurant": "restaurante",
    "plate rack": "escorredor de pratos", "measuring cup": "xicara de medir",
    "acorn": "bolota", "cornet": "corneta",
    "watermelon": "melancia", "mango": "manga", "avocado": "abacate",
    "peach": "pêssego", "pear": "pera", "cherry": "cereja",
    "grape": "uva", "custard": "pudim", "trifle": "trifle",
    "pudding": "pudim", "chocolate": "chocolate", "candy": "bala",
    "cookie": "biscoito", "cake": "bolo", "muffin": "muffin",
    "doughnut": "rosquinha", "croissant": "croissant", "bread": "pão",
    "cheese": "queijo", "milk": "leite", "butter": "manteiga",
    "egg": "ovo", "rice": "arroz", "noodle": "macarrão",
    "pasta": "massa", "salad": "salada", "soup": "sopa",
    "sandwich": "sanduíche", "burger": "hambúrguer", "hamburger": "hambúrguer",
    "shrimp": "camarão", "fish": "peixe", "chicken": "frango",
    "beef": "carne bovina", "pork": "carne de porco", "meat": "carne",
    "sauce": "molho", "cream": "creme", "sugar": "açúcar",
    "tea": "chá", "coffee": "café", "juice": "suco",
    "beer": "cerveja", "wine": "vinho", "soda": "refrigerante",
    "tomato": "tomate", "potato": "batata", "onion": "cebola",
    "carrot": "cenoura", "cabbage": "repolho", "corn": "milho",
    "broccoli": "brócolis", "cauliflower": "couve-flor",
    "crayfish": "lagosta", "goldfish": "peixe dourado",
    "jellyfish": "água-viva", "starfish": "estrela-do-mar",
}


def translate_label(label):
    if label in IMAGE_NET_PT:
        return IMAGE_NET_PT[label]
    lower = label.lower()
    for en, pt in IMAGE_NET_PT.items():
        if en in lower:
            return pt
    return label.replace("_", " ").capitalize()


def get_food_model():
    global _food_model, _food_transform, _food_categories
    if _food_model is None:
        import torch
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
        weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
        _food_model = mobilenet_v3_small(weights=weights)
        _food_model.eval()
        _food_transform = weights.transforms()
        _food_categories = weights.meta["categories"]
    return _food_model, _food_transform, _food_categories


def digits_only(s):
    return "".join(ch for ch in (s or "") if ch.isdigit())


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.context_processor
def inject_globals():
    return {"AI_ENABLED": AI_ENABLED}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    # Garantir diretório do banco antes de abrir conexão
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    except Exception as e:
        print(f"Erro ao criar diretório do banco: {e}")
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            height REAL,
            weight REAL,
            diabetes_type TEXT,
            phone TEXT,
            emergency_contact_phone TEXT,
            emergency_contact_name TEXT,
            emergency_contact_relation TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Garantir que colunas novas existam mesmo em bancos antigos
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    to_add = [
        ("height", "REAL"),
        ("weight", "REAL"),
        ("diabetes_type", "TEXT"),
        ("phone", "TEXT"),
        ("emergency_contact_phone", "TEXT"),
        ("emergency_contact_name", "TEXT"),
        ("emergency_contact_relation", "TEXT"),
        ("active", "INTEGER NOT NULL DEFAULT 1"),
    ]
    for name, typ in to_add:
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typ}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            measured_at TEXT NOT NULL,
            glucose_level REAL NOT NULL,
            measurement_context TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Garantir que colunas novas existam na tabela measurements
    mcols = {row[1] for row in conn.execute("PRAGMA table_info(measurements)").fetchall()}
    if "measurement_context" not in mcols:
        conn.execute("ALTER TABLE measurements ADD COLUMN measurement_context TEXT")
    if "notes" not in mcols:
        conn.execute("ALTER TABLE measurements ADD COLUMN notes TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_measurements_user_time
        ON measurements(user_id, measured_at DESC);
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            performed_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activities_user_time
        ON activities(user_id, performed_at DESC);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activities_user_category
        ON activities(user_id, category);
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            alert_time TEXT NOT NULL,
            days TEXT NOT NULL,
            alert_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    # Migrar coluna alert_date se faltar
    acols = {row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    if "alert_date" not in acols:
        conn.execute("ALTER TABLE alerts ADD COLUMN alert_date TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            meal_type TEXT NOT NULL,
            meal_at TEXT NOT NULL,
            description TEXT,
            photo_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_meals_user_time
        ON meals(user_id, meal_at DESC);
        """
    )

    conn.commit()
    conn.close()


# Em Flask 3.1, before_first_request foi removido; inicializamos o banco no carregamento
init_db()


def get_user_by_username(username):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user


def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return user


@app.route("/", methods=["GET", "POST"])
def index():
    # Página raiz sempre mostra o formulário de login

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Login de administrador (credenciais fixas: adm/adm)
        if username.lower() == "adm" and password == "adm":
            session.clear()
            session["is_admin"] = True
            session["user_name"] = "Administrador"
            flash("Login de administrador realizado com sucesso!", "success")
            return redirect(url_for("usuarios"))

        # Login de usuário padrão
        user = get_user_by_username(username)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Login ou senha inválidos.", "error")
            return render_template("login.html")

        # Bloquear login se usuário estiver desativado
        try:
            if int(user["active"]) == 0:
                flash("Usuário desativado. Contate o administrador.", "error")
                return render_template("login.html")
        except Exception:
            # Se a coluna não existir por algum motivo, permitir login
            pass

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        flash("Login realizado com sucesso!", "success")
        return redirect(url_for("features"))

    return render_template("login.html")


@app.route("/esqueci_senha", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username:
            flash("Informe o login.", "error")
            return render_template("forgot_password.html", username=username)

        if username.lower() == "adm":
            flash("A conta de administrador não pode ser redefinida por este fluxo.", "error")
            return redirect(url_for("index"))

        user = get_user_by_username(username)
        if not user:
            flash("Login não encontrado.", "error")
            return render_template("forgot_password.html", username=username)

        session["reset_login"] = username
        flash("Login localizado. Informe a nova senha.", "info")
        return redirect(url_for("reset_password"))

    return render_template("forgot_password.html")


@app.route("/redefinir_senha", methods=["GET", "POST"])
def reset_password():
    username = session.get("reset_login")
    if not username:
        flash("Fluxo de redefinição inválido. Informe seu login.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if len(new_password) < 6:
            errors.append("A nova senha deve ter pelo menos 6 caracteres.")
        if new_password != confirm_password:
            errors.append("As senhas não coincidem.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("reset_password.html", username=username)

        password_hash = generate_password_hash(new_password)
        conn = get_db_connection()
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
        conn.commit()
        conn.close()

        session.pop("reset_login", None)
        flash("Senha redefinida com sucesso. Faça login.", "success")
        return redirect(url_for("index"))

    return render_template("reset_password.html", username=username)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        height_str = request.form.get("height", "").strip()
        weight_str = request.form.get("weight", "").strip()
        diabetes_type = request.form.get("diabetes_type", "").strip()
        phone_raw = request.form.get("phone", "").strip()
        emergency_contact_phone_raw = request.form.get("emergency_contact_phone", "").strip()
        emergency_contact_name = request.form.get("emergency_contact_name", "").strip()
        emergency_contact_relation = request.form.get("emergency_contact_relation", "").strip()

        errors = []
        if not name or not email or not username or not password:
            errors.append("Todos os campos são obrigatórios.")
        if len(password) < 6:
            errors.append("A senha deve ter pelo menos 6 caracteres.")
        if get_user_by_email(email):
            errors.append("E-mail já está em uso.")
        if get_user_by_username(username):
            errors.append("Login já está em uso.")
        # Validações dos novos campos
        allowed_diabetes = {slug for slug, _ in DIABETES_TYPES}
        if not diabetes_type or diabetes_type not in allowed_diabetes:
            errors.append("Tipo de diabetes inválido.")
        def digits_only(s):
            return "".join(ch for ch in (s or "") if ch.isdigit())
        phone = digits_only(phone_raw)
        emergency_contact_phone = digits_only(emergency_contact_phone_raw)
        # Telefone principal permanece obrigatório
        if not phone or len(phone) not in (10, 11):
            errors.append("Telefone inválido. Informe DDD + número (10 ou 11 dígitos).")
        # Dados do responsável são opcionais: valide apenas se informados
        if emergency_contact_phone_raw and len(emergency_contact_phone) not in (10, 11):
            errors.append("Telefone do responsável inválido. Informe DDD + número (10 ou 11 dígitos).")
        allowed_rel = {slug for slug, _ in EMERGENCY_RELATIONS}
        if emergency_contact_relation and emergency_contact_relation not in allowed_rel:
            errors.append("Relação de emergência inválida.")

        def parse_float(s):
            if not s:
                return None
            try:
                v = float(s)
                if v <= 0:
                    return None
                return v
            except Exception:
                return None

        height_val = parse_float(height_str)
        if height_str and height_val is None:
            errors.append("Altura deve ser um número maior que zero.")
        weight_val = parse_float(weight_str)
        if weight_str and weight_val is None:
            errors.append("Peso deve ser um número maior que zero.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "register.html",
                name=name,
                email=email,
                username=username,
                height=height_str,
                weight=weight_str,
                diabetes_type=diabetes_type,
                phone=phone,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_relation=emergency_contact_relation,
            )

        password_hash = generate_password_hash(password)
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO users (
                name, email, username, password_hash,
                height, weight, diabetes_type, phone,
                emergency_contact_phone, emergency_contact_name, emergency_contact_relation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                email,
                username,
                password_hash,
                height_val,
                weight_val,
                diabetes_type,
                phone,
                emergency_contact_phone,
                emergency_contact_name,
                emergency_contact_relation,
            ),
        )
        conn.commit()
        conn.close()

        flash("Cadastro realizado! Você já pode fazer login.", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    # Permite selecionar o mês no formato YYYY-MM; padrão mês atual
    month_key = request.args.get("month") or datetime.now().strftime("%Y-%m")

    conn = get_db_connection()
    # Série histórica completa para o gráfico de tendência
    rows_all = conn.execute(
        "SELECT measured_at, glucose_level FROM measurements WHERE user_id = ? ORDER BY measured_at ASC",
        (user_id,),
    ).fetchall()

    labels = [row["measured_at"] for row in rows_all]
    values = [float(row["glucose_level"]) for row in rows_all]

    latest_value = values[-1] if values else None
    count = len(values)

    # Estatísticas dos últimos 7 dias
    from datetime import timedelta
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    def parse_dt(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M")
        except Exception:
            return None
    vals_7d = [v for s, v in zip(labels, values) if (parse_dt(s) and parse_dt(s) >= cutoff)]
    avg_7d = sum(vals_7d) / len(vals_7d) if vals_7d else None
    min_val = min(values) if values else None
    max_val = max(values) if values else None

    # Estatísticas do mês fechado (dias 1 a 30)
    month_rows = conn.execute(
        """
        SELECT measured_at, glucose_level, measurement_context
        FROM measurements
        WHERE user_id = ?
          AND strftime('%Y-%m', measured_at) = ?
          AND CAST(strftime('%d', measured_at) AS INTEGER) BETWEEN 1 AND 30
        ORDER BY measured_at ASC
        """,
        (user_id, month_key),
    ).fetchall()
    month_values = [float(r["glucose_level"]) for r in month_rows]
    month_avg = sum(month_values) / len(month_values) if month_values else None
    month_min = min(month_values) if month_values else None
    month_max = max(month_values) if month_values else None

    # Médias diárias dentro do mês selecionado
    daily_rows = conn.execute(
        """
        SELECT date(measured_at) AS day, AVG(glucose_level) AS avg_val
        FROM measurements
        WHERE user_id = ?
          AND strftime('%Y-%m', measured_at) = ?
          AND CAST(strftime('%d', measured_at) AS INTEGER) BETWEEN 1 AND 30
        GROUP BY day
        ORDER BY day ASC
        """,
        (user_id, month_key),
    ).fetchall()
    daily_labels = [row["day"] for row in daily_rows]
    daily_avgs = [float(row["avg_val"]) for row in daily_rows]

    # Médias por contexto de medição (jejum, antes da refeição, etc.) no mês
    context_rows = conn.execute(
        """
        SELECT measurement_context AS ctx, AVG(glucose_level) AS avg_val
        FROM measurements
        WHERE user_id = ?
          AND strftime('%Y-%m', measured_at) = ?
          AND CAST(strftime('%d', measured_at) AS INTEGER) BETWEEN 1 AND 30
        GROUP BY measurement_context
        ORDER BY ctx ASC
        """,
        (user_id, month_key),
    ).fetchall()
    conn.close()
    context_labels = [MEASUREMENT_CONTEXT_LABELS.get(row["ctx"], row["ctx"] or "—") for row in context_rows]
    context_avgs = [float(row["avg_val"]) for row in context_rows]

    return render_template(
        "dashboard.html",
        name=session.get("user_name"),
        labels=labels,
        values=values,
        latest_value=latest_value,
        count=count,
        avg_7d=avg_7d,
        min_val=min_val,
        max_val=max_val,
        # Dados do mês fechado
        month_key=month_key,
        month_avg=month_avg,
        month_min=month_min,
        month_max=month_max,
        daily_labels=daily_labels,
        daily_avgs=daily_avgs,
        context_labels=context_labels,
        context_avgs=context_avgs,
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "success")
    return redirect(url_for("index"))


@app.route("/usuarios", methods=["GET", "POST"])
def usuarios():
    # Apenas administrador pode acessar
    if not session.get("is_admin"):
        flash("Acesso restrito. Faça login como administrador.", "error")
        return redirect(url_for("index"))

    conn = get_db_connection()
    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id")
        if user_id:
            if action == "delete":
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                if not row:
                    conn.close()
                    flash("Usuário não encontrado.", "error")
                    return redirect(url_for("usuarios"))
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
                conn.close()
                flash("Usuário excluído com sucesso.", "success")
                return redirect(url_for("usuarios"))
            elif action in ("activate", "deactivate", "toggle"):
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                if not row:
                    conn.close()
                    flash("Usuário não encontrado.", "error")
                    return redirect(url_for("usuarios"))
                try:
                    current = int(row["active"]) if row["active"] is not None else 1
                except Exception:
                    current = 1
                if action == "activate":
                    new_active = 1
                elif action == "deactivate":
                    new_active = 0
                else:  # toggle
                    new_active = 0 if current else 1
                conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_active, user_id))
                conn.commit()
                conn.close()
                flash("Usuário ativado." if new_active == 1 else "Usuário desativado.", "success")
                return redirect(url_for("usuarios"))

    users = conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    return render_template(
        "users.html",
        users=users,
        diabetes_labels=DIABETES_TYPE_LABELS,
        relation_labels=EMERGENCY_RELATION_LABELS,
    )


@app.route("/account", methods=["GET", "POST"])
def account():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        session.clear()
        flash("Sessão inválida. Faça login novamente.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        height_str = request.form.get("height", "").strip()
        weight_str = request.form.get("weight", "").strip()
        diabetes_type = request.form.get("diabetes_type", "").strip()
        phone_raw = request.form.get("phone", "").strip()
        emergency_contact_phone_raw = request.form.get("emergency_contact_phone", "").strip()
        emergency_contact_name = request.form.get("emergency_contact_name", "").strip()
        emergency_contact_relation = request.form.get("emergency_contact_relation", "").strip()

        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Normalização dos telefones para apenas dígitos
        phone = digits_only(phone_raw)
        emergency_contact_phone = digits_only(emergency_contact_phone_raw)

        errors = []
        if not name or not email or not username:
            errors.append("Nome, e-mail e login são obrigatórios.")

        if email != user["email"] and get_user_by_email(email):
            errors.append("E-mail já está em uso.")
        if username != user["username"] and get_user_by_username(username):
            errors.append("Login já está em uso.")

        # Validações dos novos campos
        allowed_diabetes = {slug for slug, _ in DIABETES_TYPES}
        if diabetes_type and diabetes_type not in allowed_diabetes:
            errors.append("Tipo de diabetes inválido.")
        allowed_rel = {slug for slug, _ in EMERGENCY_RELATIONS}
        if emergency_contact_relation and emergency_contact_relation not in allowed_rel:
            errors.append("Relação de emergência inválida.")

        # Validação dos telefones (opcionais na edição: validar se informados)
        if phone and len(phone) not in (10, 11):
            errors.append("Telefone inválido. Informe DDD + número (10 ou 11 dígitos).")
        if emergency_contact_phone and len(emergency_contact_phone) not in (10, 11):
            errors.append("Telefone do responsável inválido. Informe DDD + número (10 ou 11 dígitos).")

        def parse_float(s):
            if not s:
                return None
            try:
                v = float(s)
                if v <= 0:
                    return None
                return v
            except Exception:
                return None

        height_val = parse_float(height_str)
        if height_str and height_val is None:
            errors.append("Altura deve ser um número maior que zero.")
        weight_val = parse_float(weight_str)
        if weight_str and weight_val is None:
            errors.append("Peso deve ser um número maior que zero.")

        change_password = False
        if new_password or confirm_password:
            change_password = True
            if len(new_password) < 6:
                errors.append("A nova senha deve ter pelo menos 6 caracteres.")
            if new_password != confirm_password:
                errors.append("A confirmação de senha não confere.")
            if not check_password_hash(user["password_hash"], current_password):
                errors.append("Senha atual incorreta.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template(
                "account.html",
                user=user,
                name=name,
                email=email,
                username=username,
                height=height_str,
                weight=weight_str,
                diabetes_type=diabetes_type,
                phone=phone,
                emergency_contact_phone=emergency_contact_phone,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_relation=emergency_contact_relation,
            )

        if change_password:
            password_hash = generate_password_hash(new_password)
            conn.execute(
                """
                UPDATE users SET
                    name = ?, email = ?, username = ?, password_hash = ?,
                    height = ?, weight = ?, diabetes_type = ?, phone = ?,
                    emergency_contact_phone = ?, emergency_contact_name = ?, emergency_contact_relation = ?
                WHERE id = ?
                """,
                (
                    name,
                    email,
                    username,
                    password_hash,
                    height_val,
                    weight_val,
                    diabetes_type,
                    phone,
                    emergency_contact_phone,
                    emergency_contact_name,
                    emergency_contact_relation,
                    user_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE users SET
                    name = ?, email = ?, username = ?,
                    height = ?, weight = ?, diabetes_type = ?, phone = ?,
                    emergency_contact_phone = ?, emergency_contact_name = ?, emergency_contact_relation = ?
                WHERE id = ?
                """,
                (
                    name,
                    email,
                    username,
                    height_val,
                    weight_val,
                    diabetes_type,
                    phone,
                    emergency_contact_phone,
                    emergency_contact_name,
                    emergency_contact_relation,
                    user_id,
                ),
            )
        conn.commit()
        conn.close()
        session["user_name"] = name
        flash("Dados atualizados com sucesso.", "success")
        return redirect(url_for("account"))

    conn.close()
    return render_template("account.html", user=user)


@app.route("/features")
def features():
    # Página de funcionalidades: mostra links conforme estado de autenticação
    is_logged_in = "user_id" in session or session.get("is_admin")
    return render_template("features.html", is_logged_in=is_logged_in, name=session.get("user_name"))


@app.route("/alerts", methods=["GET", "POST"])
def alerts():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    edit_id = request.args.get("edit")
    conn = get_db_connection()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            alert_type = request.form.get("alert_type", "").strip()
            alert_time = request.form.get("alert_time", "").strip()
            days_selected = request.form.getlist("days")
            alert_date = request.form.get("alert_date", "").strip()

            errors = []
            valid_types = {t for t, _ in ALERT_TYPES}
            if alert_type not in valid_types:
                errors.append("Tipo de alerta inválido.")
            try:
                datetime.strptime(alert_time, "%H:%M")
            except Exception:
                errors.append("Horário inválido.")
            valid_days = {d for d, _ in DAYS_OF_WEEK}
            has_days = bool(days_selected)
            has_date = bool(alert_date)
            if has_days and not set(days_selected).issubset(valid_days):
                errors.append("Seleção de dias inválida.")
            if has_date:
                try:
                    datetime.strptime(alert_date, "%Y-%m-%d")
                except Exception:
                    errors.append("Data inválida.")
            if not (has_days ^ has_date):
                errors.append("Selecione dias da semana OU informe uma data específica.")

            if errors:
                for e in errors:
                    flash(e, "error")
                alerts_rows = conn.execute(
                    "SELECT * FROM alerts WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
                conn.close()
                return render_template(
                    "alerts.html",
                    alert_types=ALERT_TYPES,
                    days_of_week=DAYS_OF_WEEK,
                    alerts=alerts_rows,
                    alert_type_prev=alert_type,
                    alert_time_prev=alert_time,
                    days_prev=days_selected,
                    alert_date_prev=alert_date,
                    alert_type_labels=ALERT_TYPE_LABELS,
                    day_labels=DAY_LABELS,
                    alert_time_default="",
                )

            days_str = ",".join(sorted(days_selected)) if has_days else ""
            alert_date_val = alert_date if has_date else None
            conn.execute(
                "INSERT INTO alerts (user_id, alert_type, alert_time, days, alert_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, alert_type, alert_time, days_str, alert_date_val),
            )
            conn.commit()
            flash("Alerta criado com sucesso.", "success")
            conn.close()
            return redirect(url_for("alerts"))

        elif action == "update":
            alert_id = request.form.get("alert_id")
            alert_type = request.form.get("alert_type", "").strip()
            alert_time = request.form.get("alert_time", "").strip()
            days_selected = request.form.getlist("days")
            alert_date = request.form.get("alert_date", "").strip()

            errors = []
            valid_types = {t for t, _ in ALERT_TYPES}
            if alert_type not in valid_types:
                errors.append("Tipo de alerta inválido.")
            try:
                datetime.strptime(alert_time, "%H:%M")
            except Exception:
                errors.append("Horário inválido.")
            valid_days = {d for d, _ in DAYS_OF_WEEK}
            has_days = bool(days_selected)
            has_date = bool(alert_date)
            if has_days and not set(days_selected).issubset(valid_days):
                errors.append("Seleção de dias inválida.")
            if has_date:
                try:
                    datetime.strptime(alert_date, "%Y-%m-%d")
                except Exception:
                    errors.append("Data inválida.")
            if not (has_days ^ has_date):
                errors.append("Selecione dias da semana OU informe uma data específica.")

            row = conn.execute("SELECT * FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)).fetchone()
            if not row:
                conn.close()
                flash("Alerta não encontrado.", "error")
                return redirect(url_for("alerts"))

            if errors:
                for e in errors:
                    flash(e, "error")
                alerts_rows = conn.execute(
                    "SELECT * FROM alerts WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
                conn.close()
                edit_days = row["days"].split(",") if row["days"] else []
                return render_template(
                    "alerts.html",
                    alert_types=ALERT_TYPES,
                    days_of_week=DAYS_OF_WEEK,
                    alerts=alerts_rows,
                    edit_alert=row,
                    edit_days=edit_days,
                    edit_date=row["alert_date"],
                    alert_type_labels=ALERT_TYPE_LABELS,
                    day_labels=DAY_LABELS,
                    alert_time_default="",
                )

            days_str = ",".join(sorted(days_selected)) if has_days else ""
            alert_date_val = alert_date if has_date else None
            conn.execute(
                "UPDATE alerts SET alert_type = ?, alert_time = ?, days = ?, alert_date = ? WHERE id = ? AND user_id = ?",
                (alert_type, alert_time, days_str, alert_date_val, alert_id, user_id),
            )
            conn.commit()
            conn.close()
            flash("Alerta atualizado com sucesso.", "success")
            return redirect(url_for("alerts"))

    alerts_rows = conn.execute(
        "SELECT * FROM alerts WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    edit_alert = None
    edit_days = []
    if edit_id:
        edit_alert = conn.execute("SELECT * FROM alerts WHERE id = ? AND user_id = ?", (edit_id, user_id)).fetchone()
        if edit_alert:
            edit_days = edit_alert["days"].split(",") if edit_alert["days"] else []
    conn.close()

    return render_template(
        "alerts.html",
        alert_types=ALERT_TYPES,
        days_of_week=DAYS_OF_WEEK,
        alerts=alerts_rows,
        edit_alert=edit_alert,
        edit_days=edit_days,
        edit_date=edit_alert["alert_date"] if edit_alert else None,
        alert_type_labels=ALERT_TYPE_LABELS,
        day_labels=DAY_LABELS,
        alert_time_default="",
    )


@app.route("/alerts/delete/<int:alert_id>", methods=["POST"])
def delete_alert(alert_id):
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))
    user_id = session["user_id"]
    conn = get_db_connection()
    conn.execute("DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id))
    conn.commit()
    conn.close()
    flash("Alerta excluído.", "success")
    return redirect(url_for("alerts"))


@app.route("/alerts_dashboard")
def alerts_dashboard():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]

    conn = get_db_connection()
    alerts_rows = conn.execute(
        "SELECT id, alert_type, alert_time, days, alert_date, created_at FROM alerts WHERE user_id = ? ORDER BY alert_time ASC",
        (user_id,),
    ).fetchall()

    # Contagem por tipo de alerta
    type_counts = {slug: 0 for slug, _ in ALERT_TYPES}
    # Contagem por dia da semana
    day_counts = {slug: 0 for slug, _ in DAYS_OF_WEEK}

    recurring_count = 0
    date_count = 0

    for row in alerts_rows:
        atype = row["alert_type"]
        if atype in type_counts:
            type_counts[atype] += 1
        if row["alert_date"]:
            date_count += 1
        elif row["days"]:
            recurring_count += 1
            for d in row["days"].split(","):
                d = d.strip()
                if d in day_counts:
                    day_counts[d] += 1

    conn.close()

    total_alerts = len(alerts_rows)
    type_labels_order = [label for slug, label in ALERT_TYPES]
    type_slugs_order = [slug for slug, _ in ALERT_TYPES]
    counts_per_type = [type_counts[slug] for slug in type_slugs_order]

    day_labels_order = [label for slug, label in DAYS_OF_WEEK]
    day_slugs_order = [slug for slug, _ in DAYS_OF_WEEK]
    counts_per_day = [day_counts[slug] for slug in day_slugs_order]

    # Tipo mais frequente
    top_idx = counts_per_type.index(max(counts_per_type)) if counts_per_type else None
    top_type_label = type_labels_order[top_idx] if (top_idx is not None and max(counts_per_type) > 0) else None

    # Lista formatada dos alertas
    formatted_alerts = []
    for row in alerts_rows:
        days_list = row["days"].split(",") if row["days"] else []
        days_labels = [DAY_LABELS.get(d, d) for d in days_list]
        formatted_alerts.append({
            "id": row["id"],
            "type_label": ALERT_TYPE_LABELS.get(row["alert_type"], row["alert_type"]),
            "alert_time": row["alert_time"],
            "days_labels": days_labels,
            "alert_date": row["alert_date"],
        })

    return render_template(
        "alerts_dashboard.html",
        name=session.get("user_name"),
        total_alerts=total_alerts,
        recurring_count=recurring_count,
        date_count=date_count,
        top_type_label=top_type_label,
        type_labels=type_labels_order,
        counts_per_type=counts_per_type,
        day_labels=day_labels_order,
        counts_per_day=counts_per_day,
        alerts=formatted_alerts,
    )


@app.route("/alerts/data")
def alerts_data():
    if "user_id" not in session:
        return {"alerts": []}, 401
    user_id = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, alert_type, alert_time, days, alert_date FROM alerts WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    def row_to_obj(r):
        days_list = r["days"].split(",") if r["days"] else []
        return {
            "id": r["id"],
            "alert_type": r["alert_type"],
            "alert_type_label": ALERT_TYPE_LABELS.get(r["alert_type"], r["alert_type"]),
            "alert_time": r["alert_time"],
            "days": days_list,
            "alert_date": r["alert_date"],
        }
    return {"alerts": [row_to_obj(r) for r in rows]}


@app.route("/measurements", methods=["GET", "POST"])
def measurements():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    if request.method == "POST":
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        level_str = request.form.get("level", "").strip()
        context = request.form.get("measurement_context", "").strip()
        notes = request.form.get("notes", "").strip()

        errors = []
        if not date_str or not time_str or not level_str:
            errors.append("Informe data, hora e o nível medido.")
        valid_contexts = {c for c, _ in MEASUREMENT_CONTEXTS}
        if context not in valid_contexts:
            errors.append("Selecione o momento da medição.")

        measured_at = None
        try:
            measured_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            errors.append("Data ou hora inválidas.")

        try:
            level = float(level_str)
            if level <= 0:
                errors.append("O nível deve ser maior que zero.")
        except Exception:
            errors.append("Nível informado não é um número válido.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn = get_db_connection()
            entries = conn.execute(
                "SELECT * FROM measurements WHERE user_id = ? ORDER BY measured_at DESC LIMIT 50",
                (user_id,),
            ).fetchall()
            conn.close()
            return render_template(
                "measurements.html",
                entries=entries,
                date_prev=date_str,
                time_prev=time_str,
                level_prev=level_str,
                context_prev=context,
                notes_prev=notes,
                measurement_contexts=MEASUREMENT_CONTEXTS,
                date_default=datetime.now().strftime("%Y-%m-%d"),
                time_default="",
            )

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO measurements (user_id, measured_at, glucose_level, measurement_context, notes) VALUES (?, ?, ?, ?, ?)",
            (user_id, measured_at.strftime("%Y-%m-%d %H:%M"), level, context, notes or None),
        )
        conn.commit()
        conn.close()
        flash("Medição registrada com sucesso.", "success")
        return redirect(url_for("measurements"))

    conn = get_db_connection()
    entries = conn.execute(
        "SELECT * FROM measurements WHERE user_id = ? ORDER BY measured_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    conn.close()

    now = datetime.now()
    return render_template(
        "measurements.html",
        measurement_contexts=MEASUREMENT_CONTEXTS,
        entries=entries,
        date_default=now.strftime("%Y-%m-%d"),
        time_default="",
    )


@app.route("/measurements/analyze-photo", methods=["POST"])
def analyze_photo():
    if "user_id" not in session and not session.get("is_admin"):
        return jsonify({"error": "Faça login para acessar."}), 401

    if not AI_ENABLED:
        return jsonify({"error": "O reconhecimento automático está desativado neste ambiente. Digite os dados manualmente."}), 403

    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "Nenhuma foto enviada."}), 400

    file_bytes = file.read()
    try:
        img = Image.open(io.BytesIO(file_bytes))
    except Exception:
        return jsonify({"error": "Arquivo de imagem inválido."}), 400

    img = ImageOps.exif_transpose(img)

    # --- Extrair data/hora dos metadados EXIF ---
    date_str = None
    time_str = None
    exif = img.getexif()
    if exif:
        for tag_id, value in exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, tag_id)
            if tag_name in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
                try:
                    dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                    break
                except Exception:
                    continue

    # Fallback: usar data/hora atual
    if not date_str or not time_str:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

    # --- OCR para ler o número da glicemia ---
    level = None
    ocr_debug = []
    try:
        import numpy as np
        reader = get_ocr_reader()
        img_array = np.array(img)
        results = reader.readtext(
            img_array,
            allowlist="0123456789",
            detail=1,
        )

        candidates = []
        for bbox, text, conf in results:
            digits = re.sub(r"\D", "", text)
            if not digits:
                continue
            ocr_debug.append({"text": text, "digits": digits, "confidence": round(float(conf), 3)})
            try:
                val = int(digits)
            except Exception:
                continue
            if 20 <= val <= 600:
                candidates.append((val, float(conf)))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            level = candidates[0][0]
    except Exception as e:
        return jsonify({
            "error": f"Falha no reconhecimento: {e}",
            "date": date_str,
            "time": time_str,
        }), 500

    return jsonify({
        "date": date_str,
        "time": time_str,
        "level": level,
        "ocr_results": ocr_debug,
    })


@app.route("/activities", methods=["GET", "POST"])
def activities():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        duration_str = request.form.get("duration", "").strip()

        errors = []
        valid_categories = {c for c, _ in ACTIVITY_CATEGORIES}
        if category not in valid_categories:
            errors.append("Categoria inválida.")
        if not date_str or not time_str or not duration_str:
            errors.append("Informe categoria, data, hora e tempo.")

        performed_at = None
        try:
            performed_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            errors.append("Data ou hora inválidas.")

        try:
            duration = int(float(duration_str))
            if duration <= 0:
                errors.append("O tempo deve ser maior que zero.")
        except Exception:
            errors.append("Tempo informado não é um número válido.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn = get_db_connection()
            entries = conn.execute(
                "SELECT * FROM activities WHERE user_id = ? ORDER BY performed_at DESC LIMIT 50",
                (user_id,),
            ).fetchall()
            month_key = datetime.now().strftime("%Y-%m")
            summary = conn.execute(
                """
                SELECT category, COUNT(*) AS count, SUM(duration_minutes) AS total
                FROM activities
                WHERE user_id = ? AND strftime('%Y-%m', performed_at) = ?
                GROUP BY category
                """,
                (user_id, month_key),
            ).fetchall()
            conn.close()
            return render_template(
                "activities.html",
                categories=ACTIVITY_CATEGORIES,
                entries=entries,
                summary=summary,
                date_prev=date_str,
                time_prev=time_str,
                duration_prev=duration_str,
                category_prev=category,
                month_key=month_key,
                category_labels=CATEGORY_LABELS,
                date_default=datetime.now().strftime("%Y-%m-%d"),
                time_default="",
            )

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO activities (user_id, category, performed_at, duration_minutes) VALUES (?, ?, ?, ?)",
            (user_id, category, performed_at.strftime("%Y-%m-%d %H:%M"), duration),
        )
        conn.commit()
        conn.close()
        flash("Atividade registrada com sucesso.", "success")
        return redirect(url_for("activities"))

    conn = get_db_connection()
    entries = conn.execute(
        "SELECT * FROM activities WHERE user_id = ? ORDER BY performed_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    month_key = datetime.now().strftime("%Y-%m")
    summary = conn.execute(
        """
        SELECT category, COUNT(*) AS count, SUM(duration_minutes) AS total
        FROM activities
        WHERE user_id = ? AND strftime('%Y-%m', performed_at) = ?
        GROUP BY category
        """,
        (user_id, month_key),
    ).fetchall()
    conn.close()

    now = datetime.now()
    return render_template(
        "activities.html",
        categories=ACTIVITY_CATEGORIES,
        entries=entries,
        summary=summary,
        date_default=now.strftime("%Y-%m-%d"),
        time_default="",
        month_key=month_key,
        category_labels=CATEGORY_LABELS,
    )


@app.route("/activities_dashboard")
def activities_dashboard():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    month_key = request.args.get("month") or datetime.now().strftime("%Y-%m")

    conn = get_db_connection()
    summary_rows = conn.execute(
        """
        SELECT category, COUNT(*) AS count, SUM(duration_minutes) AS total
        FROM activities
        WHERE user_id = ? AND strftime('%Y-%m', performed_at) = ?
        GROUP BY category
        """,
        (user_id, month_key),
    ).fetchall()

    daily_rows = conn.execute(
        """
        SELECT date(performed_at) AS day, SUM(duration_minutes) AS total
        FROM activities
        WHERE user_id = ? AND strftime('%Y-%m', performed_at) = ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (user_id, month_key),
    ).fetchall()
    conn.close()

    # Mapear por categoria seguindo a ordem padrão
    summary_map = {row["category"]: {"count": row["count"], "total": row["total"]} for row in summary_rows}
    category_labels_order = [label for slug, label in ACTIVITY_CATEGORIES]
    category_slugs_order = [slug for slug, _ in ACTIVITY_CATEGORIES]
    counts_per_category = [int(summary_map.get(slug, {}).get("count", 0) or 0) for slug in category_slugs_order]
    durations_per_category = [int(summary_map.get(slug, {}).get("total", 0) or 0) for slug in category_slugs_order]

    # Totais e categoria mais frequente
    total_activities = sum(counts_per_category)
    total_minutes = sum(durations_per_category)
    top_idx = counts_per_category.index(max(counts_per_category)) if counts_per_category else None
    top_category_label = category_labels_order[top_idx] if (top_idx is not None and max(counts_per_category) > 0) else None

    # Evolução diária
    labels_days = [row["day"] for row in daily_rows]
    durations_daily = [int(row["total"]) for row in daily_rows]

    return render_template(
        "activities_dashboard.html",
        name=session.get("user_name"),
        month_key=month_key,
        category_labels=category_labels_order,
        counts_per_category=counts_per_category,
        durations_per_category=durations_per_category,
        labels_days=labels_days,
        durations_daily=durations_daily,
        total_activities=total_activities,
        total_minutes=total_minutes,
        top_category_label=top_category_label,
    )


@app.route("/meals", methods=["GET", "POST"])
def meals():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]

    if request.method == "POST":
        meal_type = request.form.get("meal_type", "").strip()
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        description = request.form.get("description", "").strip()

        errors = []
        valid_types = {t for t, _ in MEAL_TYPES}
        if meal_type not in valid_types:
            errors.append("Tipo de refeição inválido.")
        if not date_str or not time_str:
            errors.append("Informe a data e a hora.")

        meal_at = None
        try:
            meal_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            errors.append("Data ou hora inválidas.")

        photo_filename = None
        file = request.files.get("photo")
        if file and file.filename:
            if not allowed_file(file.filename):
                errors.append("Formato de foto inválido. Use PNG, JPG, JPEG, GIF ou WEBP.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn = get_db_connection()
            entries = conn.execute(
                "SELECT * FROM meals WHERE user_id = ? ORDER BY meal_at DESC LIMIT 50",
                (user_id,),
            ).fetchall()
            conn.close()
            return render_template(
                "meals.html",
                meal_types=MEAL_TYPES,
                entries=entries,
                meal_type_prev=meal_type,
                date_prev=date_str,
                time_prev=time_str,
                description_prev=description,
                date_default=datetime.now().strftime("%Y-%m-%d"),
                time_default="",
            )

        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            photo_filename = f"meal_{user_id}_{ts}_{os.urandom(4).hex()}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, photo_filename))

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO meals (user_id, meal_type, meal_at, description, photo_path) VALUES (?, ?, ?, ?, ?)",
            (user_id, meal_type, meal_at.strftime("%Y-%m-%d %H:%M"), description or None, photo_filename),
        )
        conn.commit()
        conn.close()
        flash("Refeição registrada com sucesso.", "success")
        return redirect(url_for("meals"))

    conn = get_db_connection()
    entries = conn.execute(
        "SELECT * FROM meals WHERE user_id = ? ORDER BY meal_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    conn.close()

    return render_template(
        "meals.html",
        meal_types=MEAL_TYPES,
        entries=entries,
        date_default=datetime.now().strftime("%Y-%m-%d"),
        time_default="",
    )


@app.route("/meals_dashboard")
def meals_dashboard():
    if "user_id" not in session:
        flash("Faça login para acessar.", "error")
        return redirect(url_for("index"))

    user_id = session["user_id"]
    month_key = request.args.get("month") or datetime.now().strftime("%Y-%m")

    conn = get_db_connection()
    # Resumo por tipo de refeição no mês
    summary_rows = conn.execute(
        """
        SELECT meal_type, COUNT(*) AS count
        FROM meals
        WHERE user_id = ? AND strftime('%Y-%m', meal_at) = ?
        GROUP BY meal_type
        """,
        (user_id, month_key),
    ).fetchall()

    # Evolução diária de refeições no mês
    daily_rows = conn.execute(
        """
        SELECT date(meal_at) AS day, COUNT(*) AS total
        FROM meals
        WHERE user_id = ? AND strftime('%Y-%m', meal_at) = ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (user_id, month_key),
    ).fetchall()

    # Total de refeições e dias com registro (para médias)
    totals_row = conn.execute(
        """
        SELECT COUNT(*) AS total, COUNT(DISTINCT date(meal_at)) AS days
        FROM meals
        WHERE user_id = ? AND strftime('%Y-%m', meal_at) = ?
        """,
        (user_id, month_key),
    ).fetchone()
    conn.close()

    # Mapear por tipo de refeição seguindo a ordem padrão
    summary_map = {row["meal_type"]: row["count"] for row in summary_rows}
    meal_labels_order = [label for slug, label in MEAL_TYPES]
    meal_slugs_order = [slug for slug, _ in MEAL_TYPES]
    counts_per_meal_type = [int(summary_map.get(slug, 0) or 0) for slug in meal_slugs_order]

    # Totais e tipo de refeição mais frequente
    total_meals = totals_row["total"] if totals_row else 0
    days_registered = totals_row["days"] if totals_row else 0
    avg_per_day = (total_meals / days_registered) if days_registered > 0 else 0
    top_idx = counts_per_meal_type.index(max(counts_per_meal_type)) if counts_per_meal_type else None
    top_meal_type_label = meal_labels_order[top_idx] if (top_idx is not None and max(counts_per_meal_type) > 0) else None

    # Evolução diária
    labels_days = [row["day"] for row in daily_rows]
    meals_daily = [int(row["total"]) for row in daily_rows]

    return render_template(
        "meals_dashboard.html",
        name=session.get("user_name"),
        month_key=month_key,
        meal_labels=meal_labels_order,
        counts_per_meal_type=counts_per_meal_type,
        labels_days=labels_days,
        meals_daily=meals_daily,
        total_meals=total_meals,
        days_registered=days_registered,
        avg_per_day=avg_per_day,
        top_meal_type_label=top_meal_type_label,
    )


@app.route("/meals/analyze-photo", methods=["POST"])
def analyze_meal_photo():
    if "user_id" not in session and not session.get("is_admin"):
        return jsonify({"error": "Faça login para acessar."}), 401

    if not AI_ENABLED:
        return jsonify({"error": "O reconhecimento automático está desativado neste ambiente. Digite os dados manualmente."}), 403

    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "Nenhuma foto enviada."}), 400

    try:
        img = Image.open(file)
    except Exception:
        return jsonify({"error": "Arquivo de imagem inválido."}), 400

    img = ImageOps.exif_transpose(img)

    # --- Extrair data/hora dos metadados EXIF ---
    date_str = None
    time_str = None
    exif = img.getexif()
    if exif:
        for tag_id, value in exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, tag_id)
            if tag_name in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
                try:
                    dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                    break
                except Exception:
                    continue
    if not date_str or not time_str:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

    # --- Classificação do alimento com IA (MobileNetV3) ---
    food_predictions = []
    try:
        import torch
        import numpy as np
        model, transform, categories = get_food_model()
        img_rgb = img.convert("RGB")
        img_t = transform(img_rgb).unsqueeze(0)
        with torch.no_grad():
            output = model(img_t)
            probs = torch.nn.functional.softmax(output[0], dim=0)
            top_prob, top_catid = torch.topk(probs, 3)
        for i in range(top_prob.size(0)):
            label_en = categories[top_catid[i].item()]
            conf = float(top_prob[i].item())
            food_predictions.append({"label": translate_label(label_en), "label_en": label_en, "confidence": round(conf, 3)})
    except Exception as e:
        pass

    # --- OCR para ler texto de embalagens ---
    ocr_texts = []
    try:
        import numpy as np
        reader = get_ocr_reader()
        img_array = np.array(img)
        ocr_results = reader.readtext(img_array, detail=1)
        for bbox, text, conf in ocr_results:
            txt = text.strip()
            if txt and len(txt) >= 2:
                ocr_texts.append({"text": txt, "confidence": round(float(conf), 3)})
    except Exception:
        pass

    # Determinar a melhor sugestão para o campo descrição
    suggestion = None
    if food_predictions and food_predictions[0]["confidence"] >= 0.20:
        suggestion = food_predictions[0]["label"]

    return jsonify({
        "date": date_str,
        "time": time_str,
        "suggestion": suggestion,
        "food_predictions": food_predictions,
        "ocr_texts": ocr_texts,
    })


@app.route("/admin/db", methods=["GET", "POST"])
def admin_db():
    # Apenas administrador pode acessar
    if not session.get("is_admin"):
        flash("Acesso restrito ao administrador.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        file = request.files.get("dbfile")
        if not file or not file.filename:
            flash("Selecione um arquivo .db para enviar.", "error")
            return render_template("admin_db.html", db_path=DB_PATH)
        fname = file.filename.lower()
        if not fname.endswith(".db"):
            flash("Arquivo inválido. Envie um arquivo com extensão .db.", "error")
            return render_template("admin_db.html", db_path=DB_PATH)

        # Garantir diretório do banco
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        except Exception:
            pass

        backup_path = None
        tmp_path = DB_PATH + ".upload.tmp"
        try:
            # Fazer backup se existir um banco atual
            if os.path.exists(DB_PATH):
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_path = DB_PATH + f".bak-{ts}"
                shutil.copy2(DB_PATH, backup_path)
            # Salvar temporário e substituir
            file.save(tmp_path)
            os.replace(tmp_path, DB_PATH)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            flash(f"Falha ao atualizar banco: {e}", "error")
            return render_template("admin_db.html", db_path=DB_PATH, backup_path=backup_path)

        flash("Banco atualizado com sucesso." + (f" Backup criado em: {backup_path}" if backup_path else ""), "success")
        return redirect(url_for("admin_db"))

    return render_template("admin_db.html", db_path=DB_PATH)


if __name__ == "__main__":
    # Garantir que o banco exista ao iniciar diretamente
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)