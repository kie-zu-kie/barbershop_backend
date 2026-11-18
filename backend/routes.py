from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
import secrets
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash

from backend import db
from backend.models import (
    Appointment,
    Barber,
    BarberAccount,
    BarberBreak,
    BarberVacation,
    BarberWorkingHours,
    Customer,
    Haircut,
    Service,
)

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__)
MAX_HAIRCUT_IMAGE_BYTES = 5 * 1024 * 1024
MAX_HAIRCUT_IMAGE_PIXELS = 25_000_000
IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def api_error(message, status):
    return jsonify(error=message), status


def current_customer():
    customer_id = session.get("customer_id")
    if customer_id is None:
        return None
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        session.clear()
    return customer


def current_barber():
    barber_id = session.get("barber_id")
    if barber_id is None:
        return None
    barber = db.session.get(Barber, barber_id)
    if barber is None or (not barber.password_hash and barber.account is None):
        session.clear()
        return None
    return barber


def serialize_customer(customer):
    avatar_url = profile_photo_url(customer.id, "customer")
    return {
        "id": str(customer.id),
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone or "",
        "memberSince": customer.member_since.isoformat() if customer.member_since else "",
        "avatarInitials": customer.avatar_initials or "",
        "avatarUrl": avatar_url,
    }


def serialize_service(service):
    return {
        "id": str(service.id),
        "name": service.name,
        "duration": service.duration_minutes,
        "price": float(service.price),
        "description": service.description or "",
    }


def serialize_barber(barber):
    avatar_url = profile_photo_url(barber.id, "barber")
    return {
        "id": str(barber.id),
        "name": barber.name,
        "initials": barber.initials or "".join(part[0] for part in barber.name.split()[:2]).upper(),
        "specialty": barber.specialty or "",
        "rating": float(barber.rating or 0),
        "reviews": barber.review_count or 0,
        "years": barber.years_experience or 0,
        "bio": barber.bio or "",
        "color": barber.color or "bg-gold/90",
        "avatarUrl": avatar_url,
        "services": [str(service.id) for service in barber.services if service.active],
    }


def serialize_barber_account(barber):
    return {
        **serialize_barber(barber),
        "email": barber.email or "",
        "phone": barber.phone or "",
    }


def serialize_haircut(haircut):
    return {
        "id": str(haircut.id),
        "barberId": str(haircut.barber_id),
        "title": haircut.title,
        "description": haircut.description or "",
        "imageUrl": url_for("pages.haircut_image", filename=haircut.image_filename),
        "createdAt": haircut.created_at.isoformat() if haircut.created_at else "",
    }


def profile_photo_url(profile_id, role):
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    for extension in IMAGE_EXTENSIONS.values():
        filename = f"profile-{role}-{profile_id}{extension}"
        if (upload_folder / filename).is_file():
            return url_for("pages.haircut_image", filename=filename)
    return ""


def normalize_profile_photo(image):
    image_data = image.stream.read(MAX_HAIRCUT_IMAGE_BYTES + 1)
    if not image_data or len(image_data) > MAX_HAIRCUT_IMAGE_BYTES:
        return None, None, "Choose an image smaller than 5 MB."
    try:
        with Image.open(BytesIO(image_data)) as uploaded_image:
            image_format = uploaded_image.format
            if image_format not in IMAGE_EXTENSIONS:
                return None, None, "Upload a valid JPG, PNG, or WebP image."
            if uploaded_image.width * uploaded_image.height > MAX_HAIRCUT_IMAGE_PIXELS:
                return None, None, "Photo dimensions must not exceed 25 megapixels."
            uploaded_image.load()
            if image_format == "JPEG":
                uploaded_image = uploaded_image.convert("RGB")
            elif image_format == "WEBP" and uploaded_image.mode not in ("RGB", "RGBA"):
                uploaded_image = uploaded_image.convert("RGBA")
            normalized_image = BytesIO()
            uploaded_image.save(normalized_image, format=image_format, optimize=True)
            image_data = normalized_image.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None, None, "Upload a valid JPG, PNG, or WebP image."
    if len(image_data) > MAX_HAIRCUT_IMAGE_BYTES:
        return None, None, "Processed photo must be smaller than 5 MB."
    return image_data, IMAGE_EXTENSIONS[image_format], None


def save_profile_photo(profile, serializer, role):
    image = request.files.get("photo")
    if image is None or not image.filename:
        return api_error("Choose a profile photo to upload.", 400)
    image_data, image_extension, error = normalize_profile_photo(image)
    if error:
        return api_error(error, 400)

    image_filename = f"profile-{role}-{profile.id}{image_extension}"
    image_path = Path(current_app.config["UPLOAD_FOLDER"]) / image_filename
    temp_path = image_path.with_name(f".{image_filename}.{secrets.token_hex(8)}.tmp")
    try:
        image_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(image_data)
        temp_path.replace(image_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        current_app.logger.exception("Could not store %s profile photo", role)
        return api_error("Photo could not be stored. Please try again.", 500)

    for extension in IMAGE_EXTENSIONS.values():
        previous_path = Path(current_app.config["UPLOAD_FOLDER"]) / f"profile-{role}-{profile.id}{extension}"
        if previous_path != image_path:
            try:
                previous_path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.exception("Could not remove previous %s profile photo", role)
    return jsonify(**{role: serializer(profile)})


def serialize_appointment(appointment):
    return {
        "id": str(appointment.id),
        "customerId": str(appointment.customer_id),
        "customerName": appointment.customer.name,
        "barberId": str(appointment.barber_id),
        "serviceId": str(appointment.service_id),
        "date": appointment.appointment_date.isoformat(),
        "time": appointment.appointment_time.strftime("%H:%M"),
        "status": appointment.status,
        "notes": appointment.notes or "",
    }


def load_catalog():
    services = db.session.scalars(
        select(Service).where(Service.active.is_(True)).order_by(Service.name)
    ).all()
    barbers = db.session.scalars(
        select(Barber).options(selectinload(Barber.services)).order_by(Barber.name)
    ).all()
    return {
        "services": [serialize_service(service) for service in services],
        "barbers": [serialize_barber(barber) for barber in barbers],
        "appointments": [],
    }


def parse_service_input(data):
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    raw_duration = data.get("duration")
    raw_price = data.get("price")
    if not name or len(name) > 100:
        return None, "Enter a service name up to 100 characters."
    try:
        duration = int(raw_duration)
    except (TypeError, ValueError):
        return None, "Enter a valid service duration."
    valid_duration = (
        not isinstance(raw_duration, bool)
        and (
            isinstance(raw_duration, int)
            or isinstance(raw_duration, float) and raw_duration.is_integer()
            or isinstance(raw_duration, str) and raw_duration.strip().isdigit()
        )
    )
    if (
        not valid_duration
        or duration < 5
        or duration > 600
    ):
        return None, "Service duration must be between 5 and 600 minutes."
    try:
        price = Decimal(str(raw_price))
    except (InvalidOperation, TypeError, ValueError):
        return None, "Enter a valid service price."
    if not price.is_finite() or price <= 0 or price > Decimal("99999999.99"):
        return None, "Service price must be greater than zero and within the supported range."
    if len(description) > 500:
        return None, "Description must be 500 characters or fewer."
    return {
        "name": name,
        "duration_minutes": duration,
        "price": price,
        "description": description or None,
    }, None


def parse_appointment_input(data):
    try:
        barber_id = int(data.get("barberId"))
        service_id = int(data.get("serviceId"))
        appointment_date = date.fromisoformat(data.get("date", ""))
        appointment_time = time.fromisoformat(data.get("time", ""))
    except (TypeError, ValueError):
        return None, api_error("Choose a valid barber, service, date, and time.", 400)

    if appointment_date <= date.today():
        return None, api_error("Appointments must be booked for a future date.", 400)
    if appointment_time.tzinfo is not None or appointment_time.second or appointment_time.microsecond:
        return None, api_error("Choose a time in hours and minutes.", 400)

    barber = db.session.get(Barber, barber_id)
    service = db.session.get(Service, service_id)
    if barber is None or service is None or not service.active:
        return None, api_error("The selected barber or service is unavailable.", 404)
    if service not in barber.services:
        return None, api_error("This barber does not offer the selected service.", 400)

    notes = str(data.get("notes") or "").strip()
    if len(notes) > 2000:
        return None, api_error("Notes must be 2,000 characters or fewer.", 400)

    return {
        "barber": barber,
        "service": service,
        "date": appointment_date,
        "time": appointment_time,
        "notes": notes or None,
    }, None


def load_slot_context(selection, exclude_appointment_id=None):
    barber = selection["barber"]
    day = selection["date"]
    weekday = day.weekday()
    vacation = db.session.scalar(
        select(BarberVacation.id).where(
            BarberVacation.barber_id == barber.id,
            BarberVacation.start_date <= day,
            BarberVacation.end_date >= day,
        )
    )
    all_hours = db.session.scalars(
        select(BarberWorkingHours).where(BarberWorkingHours.barber_id == barber.id)
    ).all()
    breaks = db.session.scalars(
        select(BarberBreak).where(
            BarberBreak.barber_id == barber.id,
            BarberBreak.day_of_week == weekday,
        )
    ).all()
    statement = (
        select(Appointment)
        .options(selectinload(Appointment.service))
        .where(
            Appointment.barber_id == barber.id,
            Appointment.appointment_date == day,
            Appointment.status.in_(("Pending", "Confirmed")),
        )
    )
    if exclude_appointment_id is not None:
        statement = statement.where(Appointment.id != exclude_appointment_id)
    appointments = db.session.scalars(statement).all()
    return {
        "vacation": vacation is not None,
        "hours": all_hours,
        "breaks": breaks,
        "appointments": appointments,
    }


def appointment_slot_error(selection, exclude_appointment_id=None, context=None):
    service = selection["service"]
    day = selection["date"]
    start = datetime.combine(day, selection["time"])
    end = start + timedelta(minutes=service.duration_minutes)
    if end.date() != day:
        return "The selected service does not fit within this day."
    context = context or load_slot_context(selection, exclude_appointment_id)
    if context["vacation"]:
        return "The barber is unavailable on that date."

    hours = [row for row in context["hours"] if row.day_of_week == day.weekday()]
    if context["hours"] and not any(
        not row.is_day_off
        and row.start_time is not None
        and row.end_time is not None
        and row.start_time <= selection["time"]
        and end.time() <= row.end_time
        for row in hours
    ):
        return "The selected time is outside this barber's working hours."

    if any(
        row.start_time < end.time() and row.end_time > selection["time"]
        for row in context["breaks"]
    ):
        return "The selected time overlaps the barber's break."

    for existing in context["appointments"]:
        existing_start = datetime.combine(day, existing.appointment_time)
        existing_end = existing_start + timedelta(minutes=existing.service.duration_minutes)
        if start < existing_end and end > existing_start:
            return "That time is already booked. Choose another time."
    return None


@pages.get("/")
def home():
    try:
        bootstrap = load_catalog()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not load catalog for homepage")
        bootstrap = {"services": [], "barbers": [], "appointments": []}
    return jsonify({"status": "ok", "service": "barbershop backend"})


@pages.get("/login")
def login():
    return render_template("admin/login.html")


@pages.get("/admin")
def admin_dashboard():
    return render_template("admin/dashboard.html")


@pages.get("/uploads/<path:filename>")
def haircut_image(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@api.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database="connected")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Database health check failed")
        return jsonify(status="degraded", database="unavailable"), 503


@api.post("/auth/register")
def register_customer():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = data.get("password")
    phone = str(data.get("phone") or "").strip() or None

    if not name or len(name) > 100:
        return api_error("Enter a name between 1 and 100 characters.", 400)
    if len(email) > 255 or "@" not in email:
        return api_error("Enter a valid email address.", 400)
    if not isinstance(password, str) or len(password) < 8:
        return api_error("Password must contain at least 8 characters.", 400)
    if len(password) > 1024:
        return api_error("Password is too long.", 400)
    if phone and len(phone) > 30:
        return api_error("Phone number must be 30 characters or fewer.", 400)
    if db.session.scalar(select(Customer.id).where(Customer.email == email)):
        return api_error("An account with that email already exists.", 409)

    initials = "".join(part[0] for part in name.split()[:2]).upper()
    customer = Customer(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        phone=phone,
        member_since=date.today(),
        avatar_initials=initials,
    )
    db.session.add(customer)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("An account with that email already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not register customer")
        return api_error("Account registration failed. Please try again.", 500)

    session.clear()
    session["customer_id"] = customer.id
    return jsonify(customer=serialize_customer(customer)), 201


@api.post("/auth/login")
def login_customer():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    email = str(data.get("email") or "").strip().lower()
    password = data.get("password")
    if not email or not isinstance(password, str):
        return api_error("Enter your email and password.", 400)

    customer = db.session.scalar(select(Customer).where(Customer.email == email))
    if customer is None or not check_password_hash(customer.password_hash, password):
        return api_error("Email or password is incorrect.", 401)

    session.clear()
    session["customer_id"] = customer.id
    return jsonify(customer=serialize_customer(customer))


@api.get("/auth/me")
def auth_me():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    return jsonify(customer=serialize_customer(customer))


@api.post("/auth/logout")
def logout_customer():
    session.clear()
    return jsonify(status="ok")


@api.post("/barber/auth/login")
def login_barber():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    email = str(data.get("email") or "").strip().lower()
    password = data.get("password")
    if not email or len(email) > 255 or not isinstance(password, str):
        return api_error("Enter your email and password.", 400)

    barber = db.session.scalar(select(Barber).where(Barber.email == email))
    password_hash = barber.password_hash if barber is not None else None
    if barber is not None and not password_hash and barber.account is not None:
        password_hash = barber.account.password_hash
    if barber is None or not password_hash or not check_password_hash(password_hash, password):
        return api_error("Email or password is incorrect.", 401)

    session.clear()
    session["barber_id"] = barber.id
    return jsonify(barber=serialize_barber_account(barber))


@api.post("/barber/auth/register")
def register_barber():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = data.get("password")
    if not name or len(name) > 100:
        return api_error("Enter a name between 1 and 100 characters.", 400)
    if len(email) > 255 or "@" not in email:
        return api_error("Enter a valid email address.", 400)
    if not isinstance(password, str) or len(password) < 8:
        return api_error("Password must contain at least 8 characters.", 400)
    if len(password) > 1024:
        return api_error("Password is too long.", 400)

    barber = db.session.scalar(select(Barber).where(Barber.email == email))
    if barber is not None and (barber.password_hash or barber.account is not None):
        return api_error("A barber account with that email already exists.", 409)
    if barber is None:
        initials = "".join(part[0] for part in name.split()[:2]).upper()
        barber = Barber(name=name, email=email, initials=initials)
        db.session.add(barber)
    barber.password_hash = generate_password_hash(password)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("A barber account with that email already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not register barber account")
        return api_error("Barber account could not be created. Please try again.", 500)

    session.clear()
    session["barber_id"] = barber.id
    return jsonify(barber=serialize_barber_account(barber)), 201


@api.get("/barber/auth/me")
def barber_auth_me():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to continue.", 401)
    return jsonify(barber=serialize_barber_account(barber))


@api.patch("/barber/profile")
def update_barber_profile():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to continue.", 401)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)

    name = str(data.get("name", barber.name) or "").strip()
    specialty = str(data.get("specialty", barber.specialty or "") or "").strip() or None
    bio = str(data.get("bio", barber.bio or "") or "").strip() or None
    email = str(data.get("email", barber.email or "") or "").strip().lower()
    phone = str(data.get("phone", barber.phone or "") or "").strip() or None
    if not name or len(name) > 100:
        return api_error("Enter a name between 1 and 100 characters.", 400)
    if specialty and len(specialty) > 150:
        return api_error("Specialty must be 150 characters or fewer.", 400)
    if bio and len(bio) > 5000:
        return api_error("Bio must be 5,000 characters or fewer.", 400)
    if len(email) > 255 or "@" not in email:
        return api_error("Enter a valid email address.", 400)
    if phone and len(phone) > 30:
        return api_error("Phone number must be 30 characters or fewer.", 400)

    barber.name = name
    barber.initials = "".join(part[0] for part in name.split()[:2]).upper()
    barber.specialty = specialty
    barber.bio = bio
    barber.email = email
    barber.phone = phone
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("A barber account with that email already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update barber profile")
        return api_error("Profile could not be saved. Please try again.", 500)
    return jsonify(barber=serialize_barber_account(barber))


@api.post("/barber/profile/photo")
def upload_barber_profile_photo():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to continue.", 401)
    return save_profile_photo(barber, serialize_barber_account, "barber")


@api.get("/barbers/<int:barber_id>/haircuts")
def list_haircuts(barber_id):
    if db.session.get(Barber, barber_id) is None:
        return api_error("Barber not found.", 404)
    haircuts = db.session.scalars(
        select(Haircut)
        .where(Haircut.barber_id == barber_id)
        .order_by(Haircut.created_at.desc(), Haircut.id.desc())
    ).all()
    return jsonify([serialize_haircut(haircut) for haircut in haircuts])


@api.get("/haircuts")
def public_haircuts():
    haircuts = db.session.scalars(
        select(Haircut)
        .join(Barber, Haircut.barber_id == Barber.id)
        .options(selectinload(Haircut.barber))
        .order_by(Haircut.created_at.desc(), Haircut.id.desc())
    ).all()
    return jsonify(
        [
            {**serialize_haircut(haircut), "barberName": haircut.barber.name}
            for haircut in haircuts
        ]
    )


@api.get("/barber/haircuts")
def barber_haircuts():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to view your haircuts.", 401)
    haircuts = db.session.scalars(
        select(Haircut)
        .where(Haircut.barber_id == barber.id)
        .order_by(Haircut.created_at.desc(), Haircut.id.desc())
    ).all()
    return jsonify([serialize_haircut(haircut) for haircut in haircuts])


@api.post("/barber/haircuts")
def create_haircut():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to add a haircut.", 401)

    title = str(request.form.get("title") or "").strip()
    description = str(request.form.get("description") or "").strip()
    image = request.files.get("image")
    if not title or len(title) > 100:
        return api_error("Enter a haircut title up to 100 characters.", 400)
    if len(description) > 500:
        return api_error("Description must be 500 characters or fewer.", 400)
    if image is None or not image.filename:
        return api_error("Choose a haircut photo to upload.", 400)

    image_data = image.stream.read(MAX_HAIRCUT_IMAGE_BYTES + 1)
    if not image_data or len(image_data) > MAX_HAIRCUT_IMAGE_BYTES:
        return api_error("Choose an image smaller than 5 MB.", 400)
    try:
        with Image.open(BytesIO(image_data)) as uploaded_image:
            image_format = uploaded_image.format
            if image_format not in IMAGE_EXTENSIONS:
                return api_error("Upload a valid JPG, PNG, or WebP image.", 400)
            if uploaded_image.width * uploaded_image.height > MAX_HAIRCUT_IMAGE_PIXELS:
                return api_error("Photo dimensions must not exceed 25 megapixels.", 400)
            uploaded_image.load()
            if image_format == "JPEG":
                uploaded_image = uploaded_image.convert("RGB")
            elif image_format == "WEBP" and uploaded_image.mode not in ("RGB", "RGBA"):
                uploaded_image = uploaded_image.convert("RGBA")
            normalized_image = BytesIO()
            uploaded_image.save(normalized_image, format=image_format, optimize=True)
            image_data = normalized_image.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return api_error("Upload a valid JPG, PNG, or WebP image.", 400)
    if len(image_data) > MAX_HAIRCUT_IMAGE_BYTES:
        return api_error("Processed photo must be smaller than 5 MB.", 400)
    image_extension = IMAGE_EXTENSIONS[image_format]

    image_filename = f"{secrets.token_hex(16)}{image_extension}"
    image_path = Path(current_app.config["UPLOAD_FOLDER"]) / image_filename
    try:
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_data)
        haircut = Haircut(
            barber_id=barber.id,
            title=title,
            description=description or None,
            image_filename=image_filename,
        )
        db.session.add(haircut)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        image_path.unlink(missing_ok=True)
        current_app.logger.exception("Could not save haircut")
        return api_error("Haircut could not be saved. Please try again.", 500)
    except OSError:
        image_path.unlink(missing_ok=True)
        current_app.logger.exception("Could not store haircut image")
        return api_error("Photo could not be stored. Please try again.", 500)
    return jsonify(haircut=serialize_haircut(haircut)), 201


@api.delete("/barber/haircuts/<int:haircut_id>")
def delete_haircut(haircut_id):
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to remove a haircut.", 401)
    haircut = db.session.scalar(
        select(Haircut).where(
            Haircut.id == haircut_id,
            Haircut.barber_id == barber.id,
        )
    )
    if haircut is None:
        return api_error("Haircut not found.", 404)

    image_path = Path(current_app.config["UPLOAD_FOLDER"]) / haircut.image_filename
    db.session.delete(haircut)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not delete haircut")
        return api_error("Haircut could not be deleted. Please try again.", 500)
    try:
        image_path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("Could not remove deleted haircut image")
    return jsonify(status="ok")


@api.get("/profile")
def get_profile():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    return jsonify(customer=serialize_customer(customer))


@api.patch("/profile")
def update_profile():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip() or None
    if not name or len(name) > 100:
        return api_error("Enter a name between 1 and 100 characters.", 400)
    if phone and len(phone) > 30:
        return api_error("Phone number must be 30 characters or fewer.", 400)
    customer.name = name
    customer.phone = phone
    customer.avatar_initials = "".join(part[0] for part in name.split()[:2]).upper()
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update customer profile")
        return api_error("Profile could not be saved. Please try again.", 500)
    return jsonify(customer=serialize_customer(customer))


@api.post("/profile/photo")
def upload_customer_profile_photo():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    return save_profile_photo(customer, serialize_customer, "customer")


@api.get("/appointments")
def appointments():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    rows = db.session.scalars(
        select(Appointment)
        .options(
            selectinload(Appointment.customer),
            selectinload(Appointment.service),
            selectinload(Appointment.barber),
        )
        .where(Appointment.customer_id == customer.id)
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
    ).all()
    return jsonify([serialize_appointment(row) for row in rows])


@api.get("/barber/appointments")
def barber_appointments():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to view appointments.", 401)
    rows = db.session.scalars(
        select(Appointment)
        .options(
            selectinload(Appointment.customer),
            selectinload(Appointment.service),
            selectinload(Appointment.barber),
        )
        .where(Appointment.barber_id == barber.id)
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
    ).all()
    return jsonify([serialize_appointment(row) for row in rows])


@api.patch("/barber/appointments/<int:appointment_id>")
def update_barber_appointment(appointment_id):
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to update appointments.", 401)
    appointment = db.session.scalar(
        select(Appointment)
        .options(
            selectinload(Appointment.customer),
            selectinload(Appointment.service),
            selectinload(Appointment.barber),
        )
        .where(
            Appointment.id == appointment_id,
            Appointment.barber_id == barber.id,
        )
    )
    if appointment is None:
        return api_error("Appointment not found.", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    next_status = data.get("status")
    allowed_transitions = {
        "Pending": {"Confirmed", "Cancelled"},
        "Confirmed": {"Completed", "No-show", "Cancelled"},
    }
    if (
        set(data) != {"status"}
        or not isinstance(next_status, str)
        or next_status not in allowed_transitions.get(appointment.status, set())
    ):
        return api_error("This appointment status cannot be set.", 409)

    appointment.status = next_status
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update barber appointment")
        return api_error("Appointment could not be updated. Please try again.", 500)
    return jsonify(appointment=serialize_appointment(appointment))


@api.get("/availability")
def availability():
    if current_customer() is None:
        return api_error("Sign in to continue.", 401)
    selection, error = parse_appointment_input(
        {
            "barberId": request.args.get("barberId"),
            "serviceId": request.args.get("serviceId"),
            "date": request.args.get("date", ""),
            "time": "09:00",
        }
    )
    if error:
        return error

    context = load_slot_context(selection)
    all_hours = context["hours"]
    day_hours = [row for row in all_hours if row.day_of_week == selection["date"].weekday()]
    if all_hours:
        windows = [
            (row.start_time, row.end_time)
            for row in day_hours
            if not row.is_day_off and row.start_time is not None and row.end_time is not None
        ]
    else:
        weekday = selection["date"].weekday()
        defaults = {
            0: (time(9), time(19)),
            1: (time(9), time(19)),
            2: (time(9), time(19)),
            3: (time(9), time(20)),
            4: (time(9), time(20)),
            5: (time(8), time(17)),
        }
        windows = [defaults[weekday]] if weekday in defaults else []

    duration = timedelta(minutes=selection["service"].duration_minutes)
    candidates = set()
    for window_start, window_end in windows:
        cursor = datetime.combine(selection["date"], window_start)
        closing = datetime.combine(selection["date"], window_end)
        while cursor + duration <= closing:
            candidates.add(cursor.time())
            cursor += timedelta(minutes=30)

    slots = []
    for candidate_time in sorted(candidates):
        candidate = {**selection, "time": candidate_time}
        if appointment_slot_error(candidate, context=context) is None:
            slots.append(candidate_time.strftime("%H:%M"))
    return jsonify(slots=slots)


@api.post("/appointments")
def create_appointment():
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to book an appointment.", 401)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    selection, error = parse_appointment_input(data)
    if error:
        return error
    db.session.execute(
        select(Barber.id).where(Barber.id == selection["barber"].id).with_for_update()
    )
    slot_error = appointment_slot_error(selection)
    if slot_error:
        return api_error(slot_error, 409)

    appointment = Appointment(
        customer_id=customer.id,
        barber_id=selection["barber"].id,
        service_id=selection["service"].id,
        appointment_date=selection["date"],
        appointment_time=selection["time"],
        status="Pending",
        notes=selection["notes"],
    )
    db.session.add(appointment)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not create appointment")
        return api_error("Booking could not be saved. Please try again.", 500)
    return jsonify(appointment=serialize_appointment(appointment)), 201


@api.patch("/appointments/<int:appointment_id>")
def update_appointment(appointment_id):
    customer = current_customer()
    if customer is None:
        return api_error("Sign in to continue.", 401)
    appointment = db.session.scalar(
        select(Appointment)
        .options(
            selectinload(Appointment.customer),
            selectinload(Appointment.service),
            selectinload(Appointment.barber),
        )
        .where(
            Appointment.id == appointment_id,
            Appointment.customer_id == customer.id,
        )
    )
    if appointment is None:
        return api_error("Appointment not found.", 404)
    if appointment.status not in ("Pending", "Confirmed"):
        return api_error("This appointment can no longer be changed.", 409)

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    if data.get("status") == "Cancelled" and set(data) == {"status"}:
        appointment.status = "Cancelled"
    elif "date" in data or "time" in data:
        selection, error = parse_appointment_input(
            {
                "barberId": appointment.barber_id,
                "serviceId": appointment.service_id,
                "date": data.get("date", appointment.appointment_date.isoformat()),
                "time": data.get("time", appointment.appointment_time.strftime("%H:%M")),
                "notes": appointment.notes,
            }
        )
        if error:
            return error
        db.session.execute(
            select(Barber.id).where(Barber.id == appointment.barber_id).with_for_update()
        )
        slot_error = appointment_slot_error(selection, exclude_appointment_id=appointment.id)
        if slot_error:
            return api_error(slot_error, 409)
        appointment.appointment_date = selection["date"]
        appointment.appointment_time = selection["time"]
        appointment.status = "Pending"
    else:
        return api_error("Only cancellation or rescheduling is supported.", 400)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update appointment")
        return api_error("Appointment could not be updated. Please try again.", 500)
    return jsonify(appointment=serialize_appointment(appointment))


@api.get("/services")
def services():
    rows = db.session.scalars(
        select(Service).where(Service.active.is_(True)).order_by(Service.name)
    ).all()
    return jsonify([serialize_service(service) for service in rows])


@api.get("/barber/services")
def barber_services():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to manage services.", 401)
    rows = db.session.scalars(
        select(Service)
        .join(Service.barbers)
        .where(Barber.id == barber.id, Service.active.is_(True))
        .order_by(Service.name)
    ).all()
    return jsonify([serialize_service(service) for service in rows])


@api.post("/barber/services")
def create_barber_service():
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to add a service.", 401)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    fields, error = parse_service_input(data)
    if error:
        return api_error(error, 400)

    service = Service(**fields, active=True)
    service.barbers.append(barber)
    db.session.add(service)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not create barber service")
        return api_error("Service could not be added. Please try again.", 500)
    return jsonify(service=serialize_service(service)), 201


@api.patch("/barber/services/<int:service_id>")
def update_barber_service(service_id):
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to update a service.", 401)
    service = db.session.scalar(
        select(Service)
        .join(Service.barbers)
        .where(Service.id == service_id, Barber.id == barber.id)
    )
    if service is None:
        return api_error("Service not found.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Provide a JSON object.", 400)
    fields, error = parse_service_input(data)
    if error:
        return api_error(error, 400)

    for field, value in fields.items():
        setattr(service, field, value)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update barber service")
        return api_error("Service could not be updated. Please try again.", 500)
    return jsonify(service=serialize_service(service))


@api.delete("/barber/services/<int:service_id>")
def delete_barber_service(service_id):
    barber = current_barber()
    if barber is None:
        return api_error("Sign in as a barber to remove a service.", 401)
    service = db.session.scalar(
        select(Service)
        .join(Service.barbers)
        .where(Service.id == service_id, Barber.id == barber.id)
    )
    if service is None:
        return api_error("Service not found.", 404)

    service.barbers.remove(barber)
    if not service.barbers:
        service.active = False
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not delete barber service")
        return api_error("Service could not be removed. Please try again.", 500)
    return jsonify(status="ok")


@api.get("/barbers")
def barbers():
    rows = db.session.scalars(
        select(Barber).options(selectinload(Barber.services)).order_by(Barber.name)
    ).all()
    return jsonify([serialize_barber(barber) for barber in rows])
