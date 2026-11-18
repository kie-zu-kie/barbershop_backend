import click
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from backend import db


def create_portal_tables(tables=None):
    try:
        db.metadata.create_all(bind=db.engine, tables=tables)
    except SQLAlchemyError as error:
        db.session.rollback()
        raise click.ClickException(
            "Could not create barber portal tables. The database role needs "
            "CREATE permission on the public schema and, if not already "
            f"granted, REFERENCES permission on barbers. Database error: {error.orig}"
        ) from error


def register_admin_commands(app):
    @app.cli.command("local-db-init")
    def local_db_init():
        """Create and seed the explicitly selected local SQLite database."""
        if not app.config.get("USE_LOCAL_DATABASE"):
            raise click.ClickException(
                "Set USE_LOCAL_DATABASE=1 before initializing the local database."
            )

        from backend.seed import seed_demo_data

        db.create_all()
        seed_demo_data()
        click.echo("Local SQLite database is ready. Register a customer account in the app.")

    @app.cli.command("barber-portal-init")
    def barber_portal_init():
        """Create only the additive barber portal tables."""
        from backend.models import BarberAccount, Haircut

        create_portal_tables(tables=[BarberAccount.__table__, Haircut.__table__])
        click.echo("Barber portal tables are ready.")

    @app.cli.command("db-check")
    def db_check():
        """Check that the configured PostgreSQL database is reachable."""
        db.session.execute(text("SELECT 1"))
        click.echo("Database connection is healthy.")

    @app.cli.command("barber-setup")
    def barber_setup():
        """Create the haircut table and set a barber sign-in password."""
        from backend.models import Barber, BarberAccount, Haircut

        name = click.prompt("Barber name").strip()
        email = click.prompt("Barber email").strip().lower()
        password = click.prompt(
            "Create barber password",
            hide_input=True,
            confirmation_prompt=True,
        )
        if not name or len(name) > 100:
            raise click.ClickException("Barber name must be between 1 and 100 characters.")
        if len(email) > 255 or "@" not in email:
            raise click.ClickException("Enter a valid email address.")
        if len(password) < 8 or len(password) > 1024:
            raise click.ClickException("Password must contain 8 to 1024 characters.")

        create_portal_tables(tables=[BarberAccount.__table__, Haircut.__table__])
        barber = db.session.scalar(select(Barber).where(Barber.email == email))
        if barber is not None and (barber.password_hash or barber.account is not None):
            raise click.ClickException("A barber account already exists for that email.")
        if barber is None:
            initials = "".join(part[0] for part in name.split()[:2]).upper()
            barber = Barber(name=name, email=email, initials=initials)
            db.session.add(barber)
        barber.password_hash = generate_password_hash(password)
        db.session.commit()
        click.echo(f"Barber sign-in created for {email}.")
