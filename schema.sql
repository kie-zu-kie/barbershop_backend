-- Reference schema for a fresh cj_barbershop database.
-- Do not run this against a database whose tables have already been created.
-- This application schema intentionally omits the optional notifications and
-- reviews tables.

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(30),
    member_since DATE,
    avatar_initials VARCHAR(10),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    description TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE barbers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    initials VARCHAR(10),
    specialty VARCHAR(150),
    rating NUMERIC(2, 1),
    review_count INTEGER,
    years_experience INTEGER,
    bio TEXT,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    phone VARCHAR(30),
    color VARCHAR(50),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE barber_services (
    barber_id INTEGER NOT NULL REFERENCES barbers(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    PRIMARY KEY (barber_id, service_id)
);

CREATE TABLE barber_working_hours (
    id SERIAL PRIMARY KEY,
    barber_id INTEGER NOT NULL REFERENCES barbers(id),
    day_of_week SMALLINT NOT NULL,
    is_day_off BOOLEAN DEFAULT FALSE,
    start_time TIME WITHOUT TIME ZONE,
    end_time TIME WITHOUT TIME ZONE
);

CREATE TABLE barber_breaks (
    id SERIAL PRIMARY KEY,
    barber_id INTEGER NOT NULL REFERENCES barbers(id),
    day_of_week SMALLINT NOT NULL,
    start_time TIME WITHOUT TIME ZONE NOT NULL,
    end_time TIME WITHOUT TIME ZONE NOT NULL
);

CREATE TABLE barber_vacations (
    id SERIAL PRIMARY KEY,
    barber_id INTEGER NOT NULL REFERENCES barbers(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    label VARCHAR(150)
);

CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    barber_id INTEGER NOT NULL REFERENCES barbers(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    appointment_date DATE NOT NULL,
    appointment_time TIME WITHOUT TIME ZONE NOT NULL,
    status VARCHAR(20) DEFAULT 'Pending',
    notes TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Additive tables for barber sign-in and public haircut portfolios.
-- These can also be created on an existing database with:
--   python -m flask --app backend.app barber-portal-init
CREATE TABLE barber_accounts (
    id SERIAL PRIMARY KEY,
    barber_id INTEGER NOT NULL UNIQUE REFERENCES barbers(id) ON DELETE CASCADE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE haircuts (
    id SERIAL PRIMARY KEY,
    barber_id INTEGER NOT NULL REFERENCES barbers(id) ON DELETE CASCADE,
    title VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    image_filename VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
