import hmac
import secrets
from datetime import date
from pathlib import Path
import numpy as np
from flask import Flask, abort, jsonify, request, send_file
from .images import decode


def create_app(settings, store, engine, service):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    csrf = secrets.token_urlsafe(32)

    @app.before_request
    def authenticate():
        # Check the actual TCP peer, NEVER X-Forwarded-For or user headers.
        if request.remote_addr != "172.30.32.2":
            abort(403)
        if request.method not in {"GET","HEAD","OPTIONS"}:
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf):
                abort(403)

    @app.after_request
    def security(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        return response

    @app.errorhandler(OSError)
    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(RuntimeError)
    @app.errorhandler(TimeoutError)
    def unavailable(error):
        return jsonify(error=str(error)), 503

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/session")
    def session():
        return jsonify(csrf=csrf, health=service.health, engine_peak_rss_kib=engine.peak_rss_kib,
                       history_days=store.setting("history_days",settings.history_days),image_days=store.setting("image_days",settings.image_days))

    @app.get("/api/people")
    def people():
        return jsonify(store.people())

    @app.post("/api/people")
    def enroll():
        photos = request.files.getlist("photos")
        if not 3 <= len(photos) <= 8:
            raise ValueError("Upload 3–8 different photos, each with exactly one face")
        vectors, warnings = [], []
        for photo in photos:
            raw = decode(photo.read(6 * 1024 * 1024 + 1))
            result = engine.analyze(raw)
            if len(result["features"]) != 1 or result["features"][0] is None:
                raise ValueError("Every enrollment photo must contain exactly one sufficiently large face")
            vectors.append(result["features"][0])
            warnings.extend(result["warnings"])
        matrix = np.asarray(vectors, dtype=np.float32)
        similarities = matrix @ matrix.T
        if any(similarities[i,j] < 0.45 for i in range(len(vectors)) for j in range(i)):
            raise ValueError("Enrollment photos are inconsistent; use clear photos of the same person")
        if any(similarities[i,j] > 0.999 for i in range(len(vectors)) for j in range(i)):
            warnings.append("Near-identical photos; varied lighting and angles are recommended")
        # No source photos or filenames are stored. Replacement is atomic after validation.
        person_id = request.form.get("person_id") or None
        if person_id and not any(p["id"] == person_id for p in store.people()):
            abort(404)
        person_id = store.person(request.form.get("name", ""),request.form.get("trusted") == "true",vectors,person_id)
        return jsonify(id=person_id,warnings=warnings)

    @app.patch("/api/people/<person_id>")
    def update(person_id):
        current = next((p for p in store.people() if p["id"] == person_id),None)
        if not current:
            abort(404)
        data = request.get_json()
        if type(data.get("trusted",bool(current["trusted"]))) is not bool:
            raise ValueError("Trusted must be a boolean")
        store.person(data.get("name",current["name"]),data.get("trusted",current["trusted"]),None,person_id)
        return jsonify(ok=True)

    @app.delete("/api/people/<person_id>")
    def delete_person(person_id):
        store.delete_person(person_id)
        return jsonify(ok=True)

    @app.get("/api/history")
    def history():
        start,end = request.args.get("start"),request.args.get("end")
        for value in (start,end):
            if value:
                date.fromisoformat(value)
        return jsonify(store.history(request.args.get("person"),start,end + "T23:59:59.999999+00:00" if end else None))

    @app.patch("/api/history/<event_id>")
    def correct(event_id):
        store.correct(event_id,request.get_json().get("identity"))
        return jsonify(ok=True)

    @app.delete("/api/history/<event_id>")
    def delete_event(event_id):
        store.delete_event(event_id)
        return jsonify(ok=True)

    @app.get("/api/history/<event_id>/image")
    def image(event_id):
        event = store.event(event_id)
        if not event or not event["snapshot"]:
            abort(404)
        return send_file(settings.data / "images" / event["snapshot"], mimetype="image/jpeg")

    @app.post("/api/retention")
    def retention():
        data = request.get_json()
        store.set_retention(data.get("history_days"),data.get("image_days"))
        return jsonify(ok=True)

    return app
