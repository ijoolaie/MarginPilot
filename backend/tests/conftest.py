"""Pytest bootstrap. Sets a placeholder DATABASE_URL BEFORE app import so unit
tests never require a real database. Integration tests override it explicitly."""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://marginpilot:placeholder@localhost:5432/marginpilot",
)

# Exercise Secure session cookies on every platform; HTTPX does not treat
# http://localhost as a secure-cookie origin consistently across OSes.
os.environ["CORS_ORIGINS"] = "https://localhost:3000"
