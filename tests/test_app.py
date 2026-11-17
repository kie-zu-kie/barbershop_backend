from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

import pytest
from datetime import date, time, timedelta
from PIL import Image
from werkzeug.security import generate_password_hash

from backend import create_app, db
from backend.config import normalize_database_url
from backend.models import (
    Appointment,
    Barber,
    BarberAccount,
    BarberWorkingHours,
    Customer,
    Haircut,
    Service,
)


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-key",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "CORS_ORIGINS": ["http://localhost:8000"],
            "PUBLIC_API_URL": "https://api.example.test",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_backend_root_and_api_base_redirect_to_frontend(client):
    for path in ("/", "/api"):
        response = client.get(path)

        assert response.status_code == 302
        assert response.headers["Location"] == "http://localhost:8000/"

    assert client.get("/static/css/styles.css").status_code == 404


@pytest.mark.parametrize(
    ("database_url", "expected_url"),
    [
        ("postgres://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("postgresql://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("postgresql+psycopg://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        (None, None),
    ],
)
def test_database_url_uses_installed_postgres_driver(database_url, expected_url):
    assert normalize_database_url(database_url) == expected_url


def test_app_rejects_placeholder_session_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(
            {
                "SECRET_KEY": "replace-with-a-unique-random-value",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_app_requires_database_configuration():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(
            {
                "SECRET_KEY": "test-key",
                "SQLALCHEMY_DATABASE_URI": None,
            }
        )


def test_standalone_flask_cli_loads_app_from_repository_root():
    backend_directory = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "SECRET_KEY": "standalone-cli-test-secret",
            "DATABASE_URL": "sqlite://",
            "FRONTEND_ORIGINS": "http://localhost:8000",
            "FLASK_DEBUG": "false",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "routes"],
        cwd=backend_directory,
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )

    assert "api.health" in result.stdout


def test_catalog_api_returns_database_records(client, app):
    with app.app_context():
        db.session.add(Service(name="Classic Cut", duration_minutes=30, price=25))
        db.session.commit()

    response = client.get("/api/services")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "id": "1",
            "name": "Classic Cut",
            "duration": 30,
            "price": 25.0,
            "description": "",
        }
    ]


def test_barbers_api_includes_assigned_services(client, app):
    with app.app_context():
        service = Service(name="Classic Cut", duration_minutes=30, price=25)
        barber = Barber(name="Jordan Barber", initials="JB", rating=4.8)
        barber.services.append(service)
        db.session.add(barber)
        db.session.commit()

    response = client.get("/api/barbers")

    assert response.status_code == 200
    assert response.get_json()[0]["services"] == ["1"]


def test_health_endpoint_checks_database(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "connected"}


def test_root_health_endpoint_reports_app_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_api_allows_configured_frontend_origin_with_credentials(client):
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8000"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/missing")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found"}


def register(client, email="alex@example.com"):
    return client.post(
        "/api/auth/register",
        json={"name": "Alex Rivera", "email": email, "password": "secure-pass-123"},
    )


def create_bookable_catalog(app):
    with app.app_context():
        service = Service(name="Classic Cut", duration_minutes=30, price=25, active=True)
        barber = Barber(name="Jordan Barber", initials="JB")
        barber.services.append(service)
        db.session.add(barber)
        db.session.commit()
        return str(barber.id), str(service.id)


def make_test_jpeg():
    image = BytesIO()
    Image.new("RGB", (2, 2), color=(30, 60, 90)).save(image, format="JPEG")
    return image.getvalue()


def test_customer_registration_login_and_profile_are_persisted(client, app):
    response = register(client)

    assert response.status_code == 201
    customer_data = response.get_json()["customer"]
    assert customer_data["email"] == "alex@example.com"
    assert "password" not in customer_data
    assert client.get("/api/auth/me").get_json()["customer"]["id"] == customer_data["id"]

    with app.app_context():
        customer = db.session.get(Customer, int(customer_data["id"]))
        assert customer.password_hash != "secure-pass-123"

    updated = client.patch("/api/profile", json={"name": "Alex R.", "phone": "555-0123"})
    assert updated.status_code == 200
    assert updated.get_json()["customer"]["name"] == "Alex R."
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/profile").status_code == 401

    assert client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "wrong-password"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "secure-pass-123"},
    ).status_code == 200


def test_customer_can_upload_and_see_profile_photo(client, app):
    assert client.post(
        "/api/profile/photo",
        data={"photo": (BytesIO(make_test_jpeg()), "profile.jpg")},
        content_type="multipart/form-data",
    ).status_code == 401
    assert register(client).status_code == 201

    uploaded = client.post(
        "/api/profile/photo",
        data={"photo": (BytesIO(make_test_jpeg()), "profile.jpg")},
        content_type="multipart/form-data",
    )

    assert uploaded.status_code == 200
    customer = uploaded.get_json()["customer"]
    assert customer["avatarUrl"].startswith("https://api.example.test/api/uploads/profile-")
    assert client.get(urlparse(customer["avatarUrl"]).path).status_code == 200
    assert client.get("/api/auth/me").get_json()["customer"]["avatarUrl"] == customer["avatarUrl"]


def test_barber_can_upload_and_see_profile_photo(client):
    assert client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jamie Barber",
            "email": "jamie@example.com",
            "password": "secure-pass-123",
        },
    ).status_code == 201

    uploaded = client.post(
        "/api/barber/profile/photo",
        data={"photo": (BytesIO(make_test_jpeg()), "profile.jpg")},
        content_type="multipart/form-data",
    )

    assert uploaded.status_code == 200
    barber = uploaded.get_json()["barber"]
    assert barber["avatarUrl"].startswith("https://api.example.test/api/uploads/profile-")
    assert client.get(urlparse(barber["avatarUrl"]).path).status_code == 200
    assert client.get("/api/barber/auth/me").get_json()["barber"]["avatarUrl"] == barber["avatarUrl"]


def test_profile_photo_upload_rejects_non_image_files(client):
    assert register(client).status_code == 201
    response = client.post(
        "/api/profile/photo",
        data={"photo": (BytesIO(b"not an image"), "profile.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Upload a valid JPG, PNG, or WebP image."


def test_registration_rejects_duplicate_email_and_short_password(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    assert client.post(
        "/api/auth/register",
        json={"name": "Sam", "email": "sam@example.com", "password": "short"},
    ).status_code == 400


def test_registration_limits_match_database_columns(client):
    assert client.post(
        "/api/auth/register",
        json={
            "name": "A" * 101,
            "email": "long-name@example.com",
            "password": "secure-pass-123",
        },
    ).status_code == 400
    assert client.post(
        "/api/auth/register",
        json={
            "name": "Sam",
            "email": "long-phone@example.com",
            "password": "secure-pass-123",
            "phone": "1" * 31,
        },
    ).status_code == 400


def test_appointments_are_saved_listed_and_protected(client, app):
    barber_id, service_id = create_bookable_catalog(app)
    assert register(client).status_code == 201
    appointment_date = date.today() + timedelta(days=7)
    response = client.post(
        "/api/appointments",
        json={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": appointment_date.isoformat(),
            "time": "10:00",
            "notes": "Short on the sides",
        },
    )

    assert response.status_code == 201
    saved = response.get_json()["appointment"]
    assert saved["status"] == "Pending"
    assert saved["customerName"] == "Alex Rivera"
    assert client.get("/api/appointments").get_json() == [saved]
    available = client.get(
        "/api/availability",
        query_string={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": appointment_date.isoformat(),
        },
    )
    assert available.status_code == 200
    assert "10:00" not in available.get_json()["slots"]
    assert "10:30" in available.get_json()["slots"]
    with app.app_context():
        assert db.session.scalar(db.select(Appointment)).notes == "Short on the sides"

    assert client.post(
        "/api/appointments",
        json={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": appointment_date.isoformat(),
            "time": "10:00",
        },
    ).status_code == 409

    client.post("/api/auth/logout")
    assert client.get("/api/appointments").status_code == 401
    assert client.patch(f"/api/appointments/{saved['id']}", json={"status": "Cancelled"}).status_code == 401


def test_barbers_can_view_and_update_only_their_appointments(client, app):
    with app.app_context():
        service = Service(name="Classic Cut", duration_minutes=30, price=25, active=True)
        barber = Barber(name="Jordan Barber", email="jordan@example.com", initials="JB")
        other_barber = Barber(name="Casey Barber", email="casey@example.com", initials="CB")
        barber.services.append(service)
        other_barber.services.append(service)
        db.session.add_all([barber, other_barber])
        db.session.flush()
        db.session.add_all(
            [
                BarberAccount(
                    barber_id=barber.id,
                    password_hash=generate_password_hash("secure-pass-123"),
                ),
                BarberAccount(
                    barber_id=other_barber.id,
                    password_hash=generate_password_hash("secure-pass-123"),
                ),
            ]
        )
        db.session.commit()
        barber_id = barber.id
        other_barber_id = other_barber.id
        service_id = service.id

    assert register(client).status_code == 201
    appointment_date = date.today() + timedelta(days=7)
    barber_booking = client.post(
        "/api/appointments",
        json={
            "barberId": str(barber_id),
            "serviceId": str(service_id),
            "date": appointment_date.isoformat(),
            "time": "10:00",
        },
    ).get_json()["appointment"]
    other_booking = client.post(
        "/api/appointments",
        json={
            "barberId": str(other_barber_id),
            "serviceId": str(service_id),
            "date": appointment_date.isoformat(),
            "time": "10:00",
        },
    ).get_json()["appointment"]
    assert client.get("/api/barber/appointments").status_code == 401
    client.post("/api/auth/logout")

    login = client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "secure-pass-123"},
    )
    assert login.status_code == 200
    assert client.get("/api/barber/appointments").get_json() == [barber_booking]

    confirmed = client.patch(
        f"/api/barber/appointments/{barber_booking['id']}",
        json={"status": "Confirmed"},
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["appointment"]["status"] == "Confirmed"
    assert client.patch(
        f"/api/barber/appointments/{barber_booking['id']}",
        json={"status": "Pending"},
    ).status_code == 409

    client.post("/api/auth/logout")
    client.post(
        "/api/barber/auth/login",
        json={"email": "casey@example.com", "password": "secure-pass-123"},
    )
    assert client.get("/api/barber/appointments").get_json() == [other_booking]
    assert client.patch(
        f"/api/barber/appointments/{barber_booking['id']}",
        json={"status": "Cancelled"},
    ).status_code == 404


def test_customer_can_reschedule_and_cancel_only_their_appointment(client, app):
    barber_id, service_id = create_bookable_catalog(app)
    assert register(client).status_code == 201
    first_date = date.today() + timedelta(days=8)
    created = client.post(
        "/api/appointments",
        json={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": first_date.isoformat(),
            "time": "10:00",
        },
    ).get_json()["appointment"]
    changed = client.patch(
        f"/api/appointments/{created['id']}",
        json={"date": (first_date + timedelta(days=1)).isoformat(), "time": "11:00"},
    )
    assert changed.status_code == 200
    assert changed.get_json()["appointment"]["status"] == "Pending"
    assert changed.get_json()["appointment"]["time"] == "11:00"

    assert client.patch(
        f"/api/appointments/{created['id']}", json={"status": "Cancelled"}
    ).status_code == 200
    assert client.patch(
        f"/api/appointments/{created['id']}", json={"status": "Cancelled"}
    ).status_code == 409


def test_barber_can_publish_and_remove_haircuts(client, app):
    with app.app_context():
        barber = Barber(name="Jordan Barber", email="jordan@example.com", initials="JB")
        db.session.add(barber)
        db.session.flush()
        db.session.add(
            BarberAccount(
                barber_id=barber.id,
                password_hash=generate_password_hash("secure-pass-123"),
            )
        )
        other_barber = Barber(name="Alex Barber", email="alex@example.com", initials="AB")
        db.session.add(other_barber)
        db.session.flush()
        db.session.add(
            BarberAccount(
                barber_id=other_barber.id,
                password_hash=generate_password_hash("other-pass-123"),
            )
        )
        db.session.commit()
        barber_id = barber.id

    assert client.post(
        "/api/barber/haircuts",
        data={"title": "Low fade", "image": (BytesIO(b"\xff\xd8\xfftest"), "cut.jpg")},
        content_type="multipart/form-data",
    ).status_code == 401
    assert client.get("/api/barber/haircuts").status_code == 401
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "wrong-password"},
    ).status_code == 401
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "secure-pass-123"},
    ).status_code == 200
    assert client.get("/api/barber/auth/me").get_json()["barber"]["id"] == str(barber_id)
    assert client.get("/api/barber/haircuts").get_json() == []

    invalid_image = client.post(
        "/api/barber/haircuts",
        data={
            "title": "Invalid upload",
            "image": (BytesIO(b"not an image"), "fake.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert invalid_image.status_code == 400

    created = client.post(
        "/api/barber/haircuts",
        data={
            "title": "Low fade",
            "description": "Clean blend with texture on top.",
            "image": (BytesIO(make_test_jpeg()), "customer-upload.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert created.status_code == 201
    haircut = created.get_json()["haircut"]
    assert haircut["title"] == "Low fade"
    assert haircut["description"] == "Clean blend with texture on top."
    assert "/" in haircut["imageUrl"]
    assert client.get("/api/barber/haircuts").get_json() == [haircut]

    public_gallery = client.get(f"/api/barbers/{barber_id}/haircuts")
    assert public_gallery.status_code == 200
    assert public_gallery.get_json() == [haircut]
    image = client.get(urlparse(haircut["imageUrl"]).path)
    assert image.status_code == 200
    with Image.open(BytesIO(image.data)) as uploaded_image:
        assert uploaded_image.format == "JPEG"
        assert uploaded_image.size == (2, 2)

    assert client.post("/api/auth/logout").status_code == 200
    assert client.delete(f"/api/barber/haircuts/{haircut['id']}").status_code == 401
    with app.app_context():
        assert db.session.scalar(db.select(Haircut)) is not None

    assert client.post(
        "/api/barber/auth/login",
        json={"email": "alex@example.com", "password": "other-pass-123"},
    ).status_code == 200
    assert client.get("/api/barber/haircuts").get_json() == []
    assert client.delete(f"/api/barber/haircuts/{haircut['id']}").status_code == 404
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "secure-pass-123"},
    ).status_code == 200
    assert client.delete(f"/api/barber/haircuts/{haircut['id']}").status_code == 200
    assert client.get(f"/api/barbers/{barber_id}/haircuts").get_json() == []


def test_barber_added_services_are_persisted_and_bookable(client, app):
    with app.app_context():
        barber = Barber(name="Jordan Barber", email="jordan@example.com", initials="JB")
        db.session.add(barber)
        db.session.flush()
        db.session.add(
            BarberAccount(
                barber_id=barber.id,
                password_hash=generate_password_hash("secure-pass-123"),
            )
        )
        other_barber = Barber(name="Alex Barber", email="alex@example.com", initials="AB")
        db.session.add(other_barber)
        db.session.flush()
        db.session.add(
            BarberAccount(
                barber_id=other_barber.id,
                password_hash=generate_password_hash("other-pass-123"),
            )
        )
        db.session.commit()
        barber_id = barber.id

    assert client.get("/api/barber/services").status_code == 401
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "secure-pass-123"},
    ).status_code == 200
    assert client.get("/api/barber/services").get_json() == []

    created = client.post(
        "/api/barber/services",
        json={
            "name": "Textured Crop",
            "duration": 35,
            "price": 32,
            "description": "A textured crop with a clean taper.",
        },
    )
    assert created.status_code == 201
    service = created.get_json()["service"]
    assert service == {
        "id": "1",
        "name": "Textured Crop",
        "duration": 35,
        "price": 32.0,
        "description": "A textured crop with a clean taper.",
    }
    assert client.get("/api/barber/services").get_json() == [service]
    assert client.get("/api/services").get_json() == [service]
    barber_catalog = client.get("/api/barbers").get_json()
    assert next(item for item in barber_catalog if item["id"] == str(barber_id))["services"] == [service["id"]]

    assert client.patch(
        f"/api/barber/services/{service['id']}",
        json={"name": "Textured Crop & Taper", "duration": 40, "price": 38, "description": ""},
    ).status_code == 200
    assert client.get("/api/services").get_json()[0]["name"] == "Textured Crop & Taper"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "alex@example.com", "password": "other-pass-123"},
    ).status_code == 200
    assert client.patch(
        f"/api/barber/services/{service['id']}",
        json={"name": "Other Barber Cut", "duration": 30, "price": 25},
    ).status_code == 404
    assert client.delete(f"/api/barber/services/{service['id']}").status_code == 404

    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/barber/auth/login",
        json={"email": "jordan@example.com", "password": "secure-pass-123"},
    ).status_code == 200
    assert client.delete(f"/api/barber/services/{service['id']}").status_code == 200
    assert client.get("/api/barber/services").get_json() == []
    assert client.get("/api/services").get_json() == []
    with app.app_context():
        saved = db.session.get(Service, int(service["id"]))
        assert saved is not None
        assert saved.active is False
        assert saved.barbers == []


def test_barber_service_creation_validates_fields(client):
    client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jordan Barber",
            "email": "jordan@example.com",
            "password": "secure-pass-123",
        },
    )
    invalid = client.post(
        "/api/barber/services",
        json={"name": "Bad duration", "duration": 4.5, "price": 25},
    )

    assert invalid.status_code == 400
    assert invalid.get_json()["error"] == "Service duration must be between 5 and 600 minutes."


def test_barber_setup_cli_creates_additive_tables_and_account(app):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["barber-setup"],
        input="Jordan Barber\njordan@example.com\nsecure-pass-123\nsecure-pass-123\n",
    )

    assert result.exit_code == 0, result.output
    assert "Barber sign-in created" in result.output
    with app.app_context():
        barber = db.session.scalar(db.select(Barber).where(Barber.email == "jordan@example.com"))
        assert barber is not None
        assert barber.password_hash is not None
        assert barber.password_hash != "secure-pass-123"
        assert barber.account is None
        assert db.session.scalar(db.select(Haircut.id)) is None


def test_barber_can_create_an_account_and_sign_in(client, app):
    registration = client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jamie Barber",
            "email": "jamie@example.com",
            "password": "secure-pass-123",
        },
    )
    assert registration.status_code == 201
    barber = registration.get_json()["barber"]
    assert barber["name"] == "Jamie Barber"
    assert barber["email"] == "jamie@example.com"
    assert client.get("/api/barber/auth/me").get_json()["barber"]["id"] == barber["id"]
    with app.app_context():
        saved_barber = db.session.scalar(db.select(Barber).where(Barber.email == "jamie@example.com"))
        assert saved_barber.password_hash != "secure-pass-123"
        assert saved_barber.account is None

    client.post("/api/auth/logout")
    assert client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jamie Barber",
            "email": "jamie@example.com",
            "password": "secure-pass-123",
        },
    ).status_code == 409
    assert client.post(
        "/api/barber/auth/register",
        json={
            "name": "Casey Barber",
            "email": "casey@example.com",
            "password": "secure-pass-123",
        },
    ).status_code == 201


def test_barber_can_save_profile_and_public_listing_updates(client, app):
    registration = client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jamie Barber",
            "email": "jamie@example.com",
            "password": "secure-pass-123",
        },
    )
    assert registration.status_code == 201
    barber_id = registration.get_json()["barber"]["id"]

    updated = client.patch(
        "/api/barber/profile",
        json={
            "name": "Jamie Rivera",
            "specialty": "Fades",
            "bio": "A barber with a decade of experience.",
            "email": "jamie.rivera@example.com",
            "phone": "555-0123",
        },
    )

    assert updated.status_code == 200
    saved = updated.get_json()["barber"]
    assert saved["id"] == barber_id
    assert saved["name"] == "Jamie Rivera"
    assert saved["initials"] == "JR"
    assert saved["specialty"] == "Fades"
    assert saved["bio"] == "A barber with a decade of experience."
    assert saved["email"] == "jamie.rivera@example.com"
    assert saved["phone"] == "555-0123"
    with app.app_context():
        barber = db.session.get(Barber, int(barber_id))
        assert barber.phone == "555-0123"

    public_barber = next(
        item for item in client.get("/api/barbers").get_json()
        if item["id"] == barber_id
    )
    assert public_barber["name"] == "Jamie Rivera"
    assert public_barber["specialty"] == "Fades"
    assert public_barber["bio"] == "A barber with a decade of experience."


def test_barber_profile_requires_authentication_and_valid_fields(client, app):
    assert client.patch("/api/barber/profile", json={"name": "Jamie"}).status_code == 401

    registration = client.post(
        "/api/barber/auth/register",
        json={
            "name": "Jamie Barber",
            "email": "jamie@example.com",
            "password": "secure-pass-123",
        },
    )
    assert registration.status_code == 201
    assert client.patch(
        "/api/barber/profile",
        json={"name": "", "email": "jamie@example.com"},
    ).status_code == 400
    assert client.patch(
        "/api/barber/profile",
        json={"name": "Jamie Barber", "email": "invalid"},
    ).status_code == 400


def test_barber_account_registration_validates_input(client):
    assert client.post(
        "/api/barber/auth/register",
        json={"name": "Jamie", "email": "bad-email", "password": "secure-pass-123"},
    ).status_code == 400
    assert client.post(
        "/api/barber/auth/register",
        json={"name": "Jamie", "email": "jamie@example.com", "password": "short"},
    ).status_code == 400


def test_availability_uses_barber_working_hours_and_closed_days(client, app):
    barber_id, service_id = create_bookable_catalog(app)
    assert register(client).status_code == 201
    saturday = date.today() + timedelta(days=(5 - date.today().weekday()) % 7 or 7)
    saturday_slots = client.get(
        "/api/availability",
        query_string={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": saturday.isoformat(),
        },
    ).get_json()["slots"]
    assert saturday_slots[0] == "08:00"
    assert saturday_slots[-1] == "16:30"

    with app.app_context():
        db.session.add(
            BarberWorkingHours(
                barber_id=int(barber_id),
                day_of_week=5,
                is_day_off=True,
                start_time=time(8),
                end_time=time(17),
            )
        )
        db.session.commit()

    closed_slots = client.get(
        "/api/availability",
        query_string={
            "barberId": barber_id,
            "serviceId": service_id,
            "date": saturday.isoformat(),
        },
    ).get_json()["slots"]
    assert closed_slots == []


def test_orm_matches_database_column_sizes_and_omits_optional_tables():
    assert Customer.__table__.c.name.type.length == 100
    assert Customer.__table__.c.email.type.length == 255
    assert Customer.__table__.c.password_hash.type.length == 255
    assert Customer.__table__.c.phone.type.length == 30
    assert Service.__table__.c.name.type.length == 100
    assert Service.__table__.c.price.type.precision == 10
    assert Service.__table__.c.price.type.scale == 2
    assert Barber.__table__.c.rating.type.precision == 2
    assert Barber.__table__.c.rating.type.scale == 1
    assert Barber.__table__.c.password_hash.type.length == 255
    assert Barber.__table__.c.password_hash.nullable is True
    assert Appointment.__table__.c.status.type.length == 20
    assert set(db.metadata.tables) == {
        "customers",
        "services",
        "barbers",
        "barber_services",
        "barber_working_hours",
        "barber_breaks",
        "barber_vacations",
        "appointments",
        "barber_accounts",
        "haircuts",
    }
    assert Customer.__table__.c.email.unique is True
    assert Barber.__table__.c.email.unique is True


def test_optional_notification_and_review_routes_are_not_exposed(client):
    assert client.get("/api/notifications").status_code == 404
    assert client.get("/api/reviews").status_code == 404
