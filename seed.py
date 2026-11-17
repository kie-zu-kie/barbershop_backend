from __future__ import annotations

from backend import db
from backend.models import Barber, Customer, Service


def seed_demo_data():
    """Create a small set of sample records for local development/testing."""
    if Service.query.count() > 0:
        return

    services = [
        Service(name="Classic Cut", duration_minutes=30, price=25.00, active=True),
        Service(name="Beard Trim", duration_minutes=20, price=18.00, active=True),
        Service(name="Fade & Style", duration_minutes=45, price=40.00, active=True),
    ]
    db.session.add_all(services)

    barbers = [
        Barber(name="Jordan Miles", initials="JM", specialty="Skin Fade", rating=4.9, review_count=120, years_experience=8, color="bg-gold/90"),
        Barber(name="Alex Park", initials="AP", specialty="Beard Design", rating=4.7, review_count=84, years_experience=6, color="bg-sky-500"),
    ]
    db.session.add_all(barbers)

    for barber in barbers:
        barber.services.extend(services[:2])

    customers = [
        Customer(name="Adrian James", email="adrian@example.com", password_hash="demo-hash", phone="555-0100"),
        Customer(name="Sam Lee", email="sam@example.com", password_hash="demo-hash", phone="555-0101"),
    ]
    db.session.add_all(customers)
    db.session.commit()


if __name__ == "__main__":
    seed_demo_data()
    print("Demo data seeded successfully.")
