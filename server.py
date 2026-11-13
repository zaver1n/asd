import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "doctors.sqlite3"
PORT = 8000
PASSWORD_ITERATIONS = 310_000
SESSION_LIFETIME = timedelta(days=7)
SPECIALTIES = {
    "Терапевт",
    "Кардиолог",
    "Педиатр",
    "Невролог",
    "Дерматолог",
    "Эндокринолог",
    "Офтальмолог",
    "Другое направление",
}
PATIENT_DOCTORS = {
    "anna-smirnova": {"name": "Анна Смирнова", "specialty": "Терапевт"},
    "mikhail-orlov": {"name": "Михаил Орлов", "specialty": "Кардиолог"},
    "elena-volkova": {"name": "Елена Волкова", "specialty": "Педиатр"},
}
APPOINTMENT_SLOTS = {
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30",
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/login": ("login.html", "text/html; charset=utf-8"),
    "/login.html": ("login.html", "text/html; charset=utf-8"),
    "/cabinet": ("cabinet.html", "text/html; charset=utf-8"),
    "/cabinet.html": ("cabinet.html", "text/html; charset=utf-8"),
    "/patient/register": ("patient-register.html", "text/html; charset=utf-8"),
    "/patient/login": ("patient-login.html", "text/html; charset=utf-8"),
    "/patient/cabinet": ("patient-cabinet.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/login.js": ("login.js", "text/javascript; charset=utf-8"),
    "/cabinet.js": ("cabinet.js", "text/javascript; charset=utf-8"),
    "/patient.js": ("patient.js", "text/javascript; charset=utf-8"),
}


def initialize_database():
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                specialty TEXT NOT NULL,
                phone TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        doctor_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(doctors)")
        }
        if "public_id" not in doctor_columns:
            connection.execute("ALTER TABLE doctors ADD COLUMN public_id TEXT")
        for (email,) in connection.execute(
            "SELECT email FROM doctors WHERE public_id IS NULL OR public_id = ''"
        ).fetchall():
            connection.execute(
                "UPDATE doctors SET public_id = ? WHERE email = ?",
                (secrets.token_urlsafe(18), email),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS doctors_public_id ON doctors(public_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doctor_sessions (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL REFERENCES doctors(email) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS doctor_sessions_expires_at ON doctor_sessions(expires_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_sessions (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL REFERENCES patients(email) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_email TEXT NOT NULL REFERENCES patients(email),
                doctor_slug TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (doctor_slug, appointment_date, appointment_time)
            )
            """
        )
        appointment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(appointments)")
        }
        if "status" not in appointment_columns:
            connection.execute(
                "ALTER TABLE appointments ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
            )
        appointment_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'appointments'"
        ).fetchone()[0]
        legacy_slot_constraint = (
            "UNIQUE (DOCTOR_SLUG, APPOINTMENT_DATE, APPOINTMENT_TIME)"
            in appointment_schema.upper()
        )
        if legacy_slot_constraint:
            connection.execute(
                """
                CREATE TABLE appointments_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_email TEXT NOT NULL REFERENCES patients(email),
                    doctor_slug TEXT NOT NULL,
                    appointment_date TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO appointments_new (
                    id, patient_email, doctor_slug, appointment_date,
                    appointment_time, note, created_at, status
                )
                SELECT id, patient_email, doctor_slug, appointment_date,
                       appointment_time, note, created_at, status
                FROM appointments
                """
            )
            connection.execute("DROP TABLE appointments")
            connection.execute("ALTER TABLE appointments_new RENAME TO appointments")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS appointments_active_slot
            ON appointments (doctor_slug, appointment_date, appointment_time)
            WHERE status IN ('pending', 'confirmed')
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS patient_sessions_expires_at ON patient_sessions(expires_at)"
        )


def patient_doctor_catalog():
    catalog = {
        slug: {**doctor, "is_registered": False}
        for slug, doctor in PATIENT_DOCTORS.items()
    }
    with sqlite3.connect(DATABASE) as connection:
        rows = connection.execute(
            "SELECT public_id, first_name, last_name, specialty FROM doctors "
            "ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE"
        ).fetchall()
    for public_id, first_name, last_name, specialty in rows:
        catalog["doctor-" + public_id] = {
            "name": f"{first_name} {last_name}",
            "specialty": specialty,
            "is_registered": True,
        }
    return catalog


def create_session(email):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_LIFETIME
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            "DELETE FROM doctor_sessions WHERE expires_at <= ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute(
            "INSERT INTO doctor_sessions (token_hash, email, expires_at) VALUES (?, ?, ?)",
            (
                hashlib.sha256(token.encode("ascii")).hexdigest(),
                email,
                expires_at.isoformat(),
            ),
        )
    return token


def create_patient_session(email):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_LIFETIME
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            "DELETE FROM patient_sessions WHERE expires_at <= ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute(
            "INSERT INTO patient_sessions (token_hash, email, expires_at) VALUES (?, ?, ?)",
            (
                hashlib.sha256(token.encode("ascii")).hexdigest(),
                email,
                expires_at.isoformat(),
            ),
        )
    return token


class PortalHandler(BaseHTTPRequestHandler):
    def send_json(self, status, body, headers=None):
        response = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response)

    def read_fields(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Некорректный запрос."})
            return None
        if content_length <= 0 or content_length > 16_384:
            self.send_json(400, {"error": "Некорректный размер формы."})
            return None

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            return {
                key: values[0]
                for key, values in parse_qs(raw_body, keep_blank_values=True).items()
                if values
            }
        except (UnicodeDecodeError, ValueError):
            self.send_json(400, {"error": "Не удалось прочитать данные формы."})
            return None

    def current_doctor(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (ValueError, KeyError):
            return None
        morsel = cookie.get("doctor_session")
        if morsel is None:
            return None
        token_hash = hashlib.sha256(morsel.value.encode("ascii", errors="ignore")).hexdigest()
        with sqlite3.connect(DATABASE) as connection:
            connection.row_factory = sqlite3.Row
            doctor = connection.execute(
                """
                SELECT doctors.email, first_name, last_name, specialty, phone, created_at, public_id
                FROM doctor_sessions
                JOIN doctors ON doctors.email = doctor_sessions.email
                WHERE token_hash = ? AND expires_at > ?
                """,
                (token_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return dict(doctor) if doctor else None

    def current_patient(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (ValueError, KeyError):
            return None
        morsel = cookie.get("patient_session")
        if morsel is None:
            return None
        token_hash = hashlib.sha256(morsel.value.encode("ascii", errors="ignore")).hexdigest()
        with sqlite3.connect(DATABASE) as connection:
            connection.row_factory = sqlite3.Row
            patient = connection.execute(
                """
                SELECT patients.email, first_name, last_name, phone, created_at
                FROM patient_sessions
                JOIN patients ON patients.email = patient_sessions.email
                WHERE token_hash = ? AND expires_at > ?
                """,
                (token_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return dict(patient) if patient else None

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/patient/session":
            self.send_json(200, {"authenticated": self.current_patient() is not None})
            return
        if path == "/api/patient/doctors":
            doctors = patient_doctor_catalog()
            self.send_json(
                200,
                {
                    "doctors": [
                        {"slug": slug, **doctor}
                        for slug, doctor in doctors.items()
                    ]
                },
            )
            return
        if path == "/api/patient/me":
            patient = self.current_patient()
            if patient is None:
                self.send_json(401, {"error": "Войдите в личный кабинет пациента."})
                return
            self.send_json(200, {"patient": patient})
            return
        if path == "/api/patient/appointments":
            patient = self.current_patient()
            if patient is None:
                self.send_json(401, {"error": "Войдите в личный кабинет пациента."})
                return
            with sqlite3.connect(DATABASE) as connection:
                connection.row_factory = sqlite3.Row
                appointments = connection.execute(
                    """
                    SELECT id, doctor_slug, appointment_date, appointment_time, note, created_at, status
                    FROM appointments
                    WHERE patient_email = ?
                    ORDER BY appointment_date, appointment_time
                    """,
                    (patient["email"],),
                ).fetchall()
            doctor_catalog = patient_doctor_catalog()
            self.send_json(
                200,
                {
                    "appointments": [
                        {
                            **dict(appointment),
                            **doctor_catalog.get(
                                appointment["doctor_slug"],
                                {"name": "Врач больше не доступен", "specialty": ""},
                            ),
                        }
                        for appointment in appointments
                    ]
                },
            )
            return
        if path == "/api/me":
            doctor = self.current_doctor()
            if doctor is None:
                self.send_json(401, {"error": "Войдите в личный кабинет."})
                return
            self.send_json(200, {"doctor": doctor})
            return
        if path == "/api/doctor/appointments":
            doctor = self.current_doctor()
            if doctor is None:
                self.send_json(401, {"error": "Войдите в кабинет врача."})
                return
            with sqlite3.connect(DATABASE) as connection:
                connection.row_factory = sqlite3.Row
                appointments = connection.execute(
                    """
                    SELECT appointments.id, patients.first_name AS patient_first_name,
                           patients.last_name AS patient_last_name, patients.phone AS patient_phone,
                           appointments.appointment_date, appointments.appointment_time,
                           appointments.note, appointments.status
                    FROM appointments
                    JOIN patients ON patients.email = appointments.patient_email
                    WHERE appointments.doctor_slug = ?
                    ORDER BY appointments.appointment_date, appointments.appointment_time
                    """,
                    ("doctor-" + doctor["public_id"],),
                ).fetchall()
            self.send_json(
                200,
                {
                    "appointments": [dict(row) for row in appointments],
                    "total": len(appointments),
                    "pending": sum(row["status"] == "pending" for row in appointments),
                },
            )
            return

        entry = STATIC_FILES.get(path)
        if entry is None:
            self.send_json(404, {"error": "Страница не найдена."})
            return

        filename, content_type = entry
        content = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/patient/register":
            self.patient_register()
            return
        if path == "/api/patient/login":
            self.patient_login()
            return
        if path == "/api/patient/logout":
            self.patient_logout()
            return
        if path == "/api/patient/appointments":
            self.create_appointment()
            return
        if path == "/api/login":
            self.login()
            return
        if path == "/api/logout":
            self.logout()
            return
        if path != "/api/register":
            self.send_json(404, {"error": "Маршрут не найден."})
            return

        fields = self.read_fields()
        if fields is None:
            return

        first_name = fields.get("first-name", "")
        last_name = fields.get("last-name", "")
        email = fields.get("email", "").lower()
        phone = fields.get("phone", "")
        specialty = fields.get("specialty", "")
        password = fields.get("password", "")
        first_name = first_name.strip()
        last_name = last_name.strip()
        email = email.strip()
        phone = phone.strip()
        specialty = specialty.strip()

        if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80:
            self.send_json(400, {"error": "Укажите имя и фамилию (не более 80 символов)."})
            return
        if len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            self.send_json(400, {"error": "Укажите корректный адрес электронной почты."})
            return
        if not phone or len(phone) > 40:
            self.send_json(400, {"error": "Укажите корректный номер телефона."})
            return
        if specialty not in SPECIALTIES:
            self.send_json(400, {"error": "Выберите специализацию из списка."})
            return
        if len(password) < 8 or len(password) > 256:
            self.send_json(400, {"error": "Пароль должен содержать от 8 до 256 символов."})
            return
        if fields.get("consent") != "on":
            self.send_json(400, {"error": "Подтвердите согласие на обработку данных."})
            return

        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
        )
        try:
            public_id = secrets.token_urlsafe(18)
            with sqlite3.connect(DATABASE) as connection:
                connection.execute(
                    """
                    INSERT INTO doctors (
                        email, first_name, last_name, specialty, phone,
                        password_salt, password_hash, created_at, public_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        email,
                        first_name,
                        last_name,
                        specialty,
                        phone,
                        salt,
                        password_hash,
                        datetime.now(timezone.utc).isoformat(),
                        public_id,
                    ),
                )
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Этот адрес электронной почты уже зарегистрирован."})
            return

        session_token = create_session(email)
        self.send_json(
            201,
            {"message": f"Кабинет врача создан. Специализация: {specialty}."},
            {"Set-Cookie": self.session_cookie(session_token)},
        )

    def patient_register(self):
        fields = self.read_fields()
        if fields is None:
            return
        first_name = fields.get("first-name", "").strip()
        last_name = fields.get("last-name", "").strip()
        email = fields.get("email", "").strip().lower()
        phone = fields.get("phone", "").strip()
        password = fields.get("password", "")

        if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80:
            self.send_json(400, {"error": "Укажите имя и фамилию (не более 80 символов)."})
            return
        if len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            self.send_json(400, {"error": "Укажите корректный адрес электронной почты."})
            return
        if not phone or len(phone) > 40:
            self.send_json(400, {"error": "Укажите корректный номер телефона."})
            return
        if len(password) < 8 or len(password) > 256:
            self.send_json(400, {"error": "Пароль должен содержать от 8 до 256 символов."})
            return
        if fields.get("consent") != "on":
            self.send_json(400, {"error": "Подтвердите согласие на обработку данных."})
            return

        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
        )
        try:
            with sqlite3.connect(DATABASE) as connection:
                connection.execute(
                    """
                    INSERT INTO patients (
                        email, first_name, last_name, phone,
                        password_salt, password_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        email, first_name, last_name, phone, salt, password_hash,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Этот email уже зарегистрирован."})
            return

        token = create_patient_session(email)
        self.send_json(
            201,
            {"message": "Регистрация прошла успешно."},
            {"Set-Cookie": self.patient_session_cookie(token)},
        )

    def patient_login(self):
        fields = self.read_fields()
        if fields is None:
            return
        email = fields.get("email", "").strip().lower()
        password = fields.get("password", "")
        with sqlite3.connect(DATABASE) as connection:
            patient = connection.execute(
                "SELECT email, password_salt, password_hash FROM patients WHERE email = ?",
                (email,),
            ).fetchone()
        if patient is None:
            self.send_json(401, {"error": "Неверный email или пароль."})
            return
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), patient[1], PASSWORD_ITERATIONS
        )
        if not hmac.compare_digest(password_hash, patient[2]):
            self.send_json(401, {"error": "Неверный email или пароль."})
            return
        token = create_patient_session(patient[0])
        self.send_json(
            200,
            {"message": "Вы вошли в кабинет пациента."},
            {"Set-Cookie": self.patient_session_cookie(token)},
        )

    @staticmethod
    def patient_session_cookie(token, max_age=604800):
        return (
            f"patient_session={token}; Path=/; Max-Age={max_age}; "
            "HttpOnly; SameSite=Lax"
        )

    def patient_logout(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (ValueError, KeyError):
            cookie = SimpleCookie()
        morsel = cookie.get("patient_session")
        if morsel is not None:
            token_hash = hashlib.sha256(morsel.value.encode("ascii", errors="ignore")).hexdigest()
            with sqlite3.connect(DATABASE) as connection:
                connection.execute(
                    "DELETE FROM patient_sessions WHERE token_hash = ?",
                    (token_hash,),
                )
        self.send_json(
            200,
            {"message": "Вы вышли из кабинета пациента."},
            {"Set-Cookie": self.patient_session_cookie("", max_age=0)},
        )

    def create_appointment(self):
        patient = self.current_patient()
        if patient is None:
            self.send_json(401, {"error": "Войдите в личный кабинет пациента."})
            return
        fields = self.read_fields()
        if fields is None:
            return
        doctor_slug = fields.get("doctor_slug", "").strip()
        appointment_date = fields.get("appointment_date", "").strip()
        appointment_time = fields.get("appointment_time", "").strip()
        note = fields.get("note", "").strip()
        doctor_catalog = patient_doctor_catalog()
        if doctor_slug not in doctor_catalog:
            self.send_json(400, {"error": "Выберите врача из списка."})
            return
        try:
            selected_date = date.fromisoformat(appointment_date)
        except ValueError:
            self.send_json(400, {"error": "Укажите корректную дату приёма."})
            return
        if selected_date < date.today() or selected_date > date.today() + timedelta(days=365):
            self.send_json(400, {"error": "Выберите дату в течение ближайшего года."})
            return
        if appointment_time not in APPOINTMENT_SLOTS:
            self.send_json(400, {"error": "Выберите время из доступных интервалов."})
            return
        if len(note) > 500:
            self.send_json(400, {"error": "Комментарий не должен превышать 500 символов."})
            return
        try:
            with sqlite3.connect(DATABASE) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO appointments (
                        patient_email, doctor_slug, appointment_date,
                        appointment_time, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        patient["email"], doctor_slug, appointment_date, appointment_time,
                        note, datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Это время уже занято. Выберите другое."})
            return
        self.send_json(201, {"message": "Вы записаны на приём.", "id": cursor.lastrowid})

    @staticmethod
    def session_cookie(token, max_age=604800):
        return (
            f"doctor_session={token}; Path=/; Max-Age={max_age}; "
            "HttpOnly; SameSite=Lax"
        )

    def login(self):
        fields = self.read_fields()
        if fields is None:
            return
        email = fields.get("email", "").strip().lower()
        password = fields.get("password", "")
        with sqlite3.connect(DATABASE) as connection:
            doctor = connection.execute(
                """
                SELECT email, password_salt, password_hash
                FROM doctors WHERE email = ?
                """,
                (email,),
            ).fetchone()
        if doctor is None:
            self.send_json(401, {"error": "Неверный email или пароль."})
            return

        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), doctor[1], PASSWORD_ITERATIONS
        )
        if not hmac.compare_digest(password_hash, doctor[2]):
            self.send_json(401, {"error": "Неверный email или пароль."})
            return

        session_token = create_session(doctor[0])
        self.send_json(
            200,
            {"message": "Вы вошли в личный кабинет."},
            {"Set-Cookie": self.session_cookie(session_token)},
        )

    def logout(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (ValueError, KeyError):
            cookie = SimpleCookie()
        morsel = cookie.get("doctor_session")
        if morsel is not None:
            token_hash = hashlib.sha256(morsel.value.encode("ascii", errors="ignore")).hexdigest()
            with sqlite3.connect(DATABASE) as connection:
                connection.execute(
                    "DELETE FROM doctor_sessions WHERE token_hash = ?",
                    (token_hash,),
                )
        self.send_json(
            200,
            {"message": "Вы вышли из личного кабинета."},
            {"Set-Cookie": self.session_cookie("", max_age=0)},
        )

    def do_PUT(self):
        path = urlsplit(self.path).path
        appointment_prefix = "/api/doctor/appointments/"
        if path.startswith(appointment_prefix):
            self.update_doctor_appointment(path[len(appointment_prefix):])
            return
        if path == "/api/patient/profile":
            self.update_patient_profile()
            return
        if path != "/api/profile":
            self.send_json(404, {"error": "Маршрут не найден."})
            return
        doctor = self.current_doctor()
        if doctor is None:
            self.send_json(401, {"error": "Войдите в личный кабинет."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 16_384:
                self.send_json(400, {"error": "Некорректный размер данных."})
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Не удалось прочитать данные профиля."})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "Некорректные данные профиля."})
            return

        profile_fields = ("first_name", "last_name", "phone", "specialty")
        if any(not isinstance(payload.get(field), str) for field in profile_fields):
            self.send_json(400, {"error": "Некорректные данные профиля."})
            return
        first_name = payload.get("first_name", "").strip()
        last_name = payload.get("last_name", "").strip()
        phone = payload.get("phone", "").strip()
        specialty = payload.get("specialty", "").strip()
        if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80:
            self.send_json(400, {"error": "Укажите имя и фамилию (не более 80 символов)."})
            return
        if not phone or len(phone) > 40:
            self.send_json(400, {"error": "Укажите корректный номер телефона."})
            return
        if specialty not in SPECIALTIES:
            self.send_json(400, {"error": "Выберите специализацию из списка."})
            return

        with sqlite3.connect(DATABASE) as connection:
            connection.execute(
                """
                UPDATE doctors
                SET first_name = ?, last_name = ?, phone = ?, specialty = ?
                WHERE email = ?
                """,
                (first_name, last_name, phone, specialty, doctor["email"]),
            )
        self.send_json(200, {"message": "Изменения профиля сохранены."})

    def update_doctor_appointment(self, appointment_id):
        doctor = self.current_doctor()
        if doctor is None:
            self.send_json(401, {"error": "Войдите в кабинет врача."})
            return
        try:
            appointment_id = int(appointment_id)
        except ValueError:
            self.send_json(400, {"error": "Некорректный номер записи."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 4096:
                self.send_json(400, {"error": "Некорректный размер данных."})
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Не удалось прочитать данные записи."})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "Некорректный статус записи."})
            return
        new_status = payload.get("status")
        expected_statuses = {
            "confirmed": ("pending", "Запись подтверждена."),
            "rejected": ("pending", "Запись отклонена."),
            "cancelled": ("confirmed", "Подтверждённая запись отменена."),
        }
        transition = expected_statuses.get(new_status)
        if transition is None:
            self.send_json(400, {"error": "Недопустимый статус записи."})
            return
        expected_status, success_message = transition
        with sqlite3.connect(DATABASE) as connection:
            cursor = connection.execute(
                """
                UPDATE appointments SET status = ?
                WHERE id = ? AND doctor_slug = ? AND status = ?
                """,
                (
                    new_status,
                    appointment_id,
                    "doctor-" + doctor["public_id"],
                    expected_status,
                ),
            )
        if cursor.rowcount == 0:
            with sqlite3.connect(DATABASE) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM appointments WHERE id = ? AND doctor_slug = ?",
                    (appointment_id, "doctor-" + doctor["public_id"]),
                ).fetchone()
            if exists:
                self.send_json(409, {"error": "Эта запись уже обработана."})
            else:
                self.send_json(404, {"error": "Запись не найдена."})
            return
        self.send_json(200, {"message": success_message})

    def update_patient_profile(self):
        patient = self.current_patient()
        if patient is None:
            self.send_json(401, {"error": "Войдите в личный кабинет пациента."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 16_384:
                self.send_json(400, {"error": "Некорректный размер данных."})
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Не удалось прочитать данные профиля."})
            return
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(field), str)
            for field in ("first_name", "last_name", "phone")
        ):
            self.send_json(400, {"error": "Некорректные данные профиля."})
            return
        first_name = payload["first_name"].strip()
        last_name = payload["last_name"].strip()
        phone = payload["phone"].strip()
        if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80:
            self.send_json(400, {"error": "Укажите имя и фамилию (не более 80 символов)."})
            return
        if not phone or len(phone) > 40:
            self.send_json(400, {"error": "Укажите корректный номер телефона."})
            return
        with sqlite3.connect(DATABASE) as connection:
            connection.execute(
                "UPDATE patients SET first_name = ?, last_name = ?, phone = ? WHERE email = ?",
                (first_name, last_name, phone, patient["email"]),
            )
        self.send_json(200, {"message": "Изменения профиля сохранены."})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        prefix = "/api/patient/appointments/"
        if not path.startswith(prefix):
            self.send_json(404, {"error": "Маршрут не найден."})
            return
        patient = self.current_patient()
        if patient is None:
            self.send_json(401, {"error": "Войдите в личный кабинет пациента."})
            return
        try:
            appointment_id = int(path[len(prefix):])
        except ValueError:
            self.send_json(400, {"error": "Некорректный номер записи."})
            return
        with sqlite3.connect(DATABASE) as connection:
            cursor = connection.execute(
                "DELETE FROM appointments WHERE id = ? AND patient_email = ?",
                (appointment_id, patient["email"]),
            )
        if cursor.rowcount == 0:
            self.send_json(404, {"error": "Запись не найдена."})
            return
        self.send_json(200, {"message": "Запись отменена."})

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), PortalHandler)
    print(f"Медицинский портал запущен: http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
    finally:
        server.server_close()
