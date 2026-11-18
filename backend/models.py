from datetime import datetime, timezone

from sqlalchemy import text

from backend import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


barber_services = db.Table(
    "barber_services",
    db.Column("barber_id", db.Integer, db.ForeignKey("barbers.id"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id"), primary_key=True),
)


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    member_since = db.Column(db.Date)
    avatar_initials = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = db.Column(
        db.DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    appointments = db.relationship("Appointment", back_populates="customer")


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, server_default=text("true"))
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = db.Column(
        db.DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    barbers = db.relationship("Barber", secondary=barber_services, back_populates="services")
    appointments = db.relationship("Appointment", back_populates="service")


class Barber(db.Model):
    __tablename__ = "barbers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    initials = db.Column(db.String(10))
    specialty = db.Column(db.String(150))
    rating = db.Column(db.Numeric(2, 1))
    review_count = db.Column(db.Integer, server_default=text("0"))
    years_experience = db.Column(db.Integer)
    bio = db.Column(db.Text)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    color = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = db.Column(
        db.DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    services = db.relationship("Service", secondary=barber_services, back_populates="barbers")
    appointments = db.relationship("Appointment", back_populates="barber")
    working_hours = db.relationship("BarberWorkingHours", back_populates="barber")
    breaks = db.relationship("BarberBreak", back_populates="barber")
    vacations = db.relationship("BarberVacation", back_populates="barber")
    account = db.relationship("BarberAccount", back_populates="barber", uselist=False)
    haircuts = db.relationship(
        "Haircut",
        back_populates="barber",
        cascade="all, delete-orphan",
    )


class BarberAccount(db.Model):
    __tablename__ = "barber_accounts"

    id = db.Column(db.Integer, primary_key=True)
    barber_id = db.Column(
        db.Integer,
        db.ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))

    barber = db.relationship("Barber", back_populates="account")


class Haircut(db.Model):
    __tablename__ = "haircuts"

    id = db.Column(db.Integer, primary_key=True)
    barber_id = db.Column(
        db.Integer,
        db.ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    image_filename = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))

    barber = db.relationship("Barber", back_populates="haircuts")


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    barber_id = db.Column(db.Integer, db.ForeignKey("barbers.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), server_default=text("'Pending'"))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = db.Column(
        db.DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=utcnow,
    )

    customer = db.relationship("Customer", back_populates="appointments")
    barber = db.relationship("Barber", back_populates="appointments")
    service = db.relationship("Service", back_populates="appointments")


class BarberWorkingHours(db.Model):
    __tablename__ = "barber_working_hours"

    id = db.Column(db.Integer, primary_key=True)
    barber_id = db.Column(db.Integer, db.ForeignKey("barbers.id"), nullable=False)
    day_of_week = db.Column(db.SmallInteger, nullable=False)
    is_day_off = db.Column(db.Boolean, server_default=text("false"))
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)

    barber = db.relationship("Barber", back_populates="working_hours")


class BarberBreak(db.Model):
    __tablename__ = "barber_breaks"

    id = db.Column(db.Integer, primary_key=True)
    barber_id = db.Column(db.Integer, db.ForeignKey("barbers.id"), nullable=False)
    day_of_week = db.Column(db.SmallInteger, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    barber = db.relationship("Barber", back_populates="breaks")


class BarberVacation(db.Model):
    __tablename__ = "barber_vacations"

    id = db.Column(db.Integer, primary_key=True)
    barber_id = db.Column(db.Integer, db.ForeignKey("barbers.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    label = db.Column(db.String(150))

    barber = db.relationship("Barber", back_populates="vacations")
