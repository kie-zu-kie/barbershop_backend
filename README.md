# barbershop_backend

Barbershop backend API. This folder is a standalone Flask JSON API repository
and does not serve the frontend.

## Local setup

1. Copy `.env.example` to `.env` and set `DATABASE_URL` and `SECRET_KEY`.
2. Install and start the API from this folder:

```powershell
python -m pip install -r requirements.txt
python app.py
```

The API listens at <http://127.0.0.1:5000>. The basic health endpoint is
<http://127.0.0.1:5000/health>; <http://127.0.0.1:5000/api/health> also checks
the database connection.

Generate a session secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Set `PUBLIC_API_URL` to the backend's public origin, without `/api`. Set
`FRONTEND_ORIGINS` to the comma-separated, exact origin(s) where the browser
frontend is hosted. `PUBLIC_API_URL` is used for profile and gallery image
links; `FRONTEND_ORIGINS` enables credentialed CORS for browser API requests.
For production, use HTTPS and set `SESSION_COOKIE_SECURE=true`.

## Deployment

The included `Procfile` starts Gunicorn on the provider-assigned port. Use
`pip install -r requirements.txt` as the build command and the Procfile as the
start command. Configure a basic health check at `/health`; use `/api/health`
to include the database connection check. Set `DATABASE_URL`, `SECRET_KEY`,
`PUBLIC_API_URL`, `FRONTEND_ORIGINS`, and
`SESSION_COOKIE_SECURE=true` in the host's environment settings.

PostgreSQL connection strings starting with `postgres://` or `postgresql://`
are automatically adapted to the installed `psycopg` driver. Uploaded images
are written to `uploads/`; configure durable storage for that directory on
hosts with ephemeral filesystems.

The frontend sends session cookies with API requests. Hosting the frontend and
API on subdomains of the same site (for example, `www.example.com` and
`api.example.com`) avoids third-party-cookie restrictions.
