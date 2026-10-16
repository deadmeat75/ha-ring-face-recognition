import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

MIGRATIONS = ["""
CREATE TABLE people(id TEXT PRIMARY KEY, name TEXT NOT NULL, trusted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE templates(person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE, vector TEXT NOT NULL);
CREATE TABLE events(id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, local_time TEXT NOT NULL,
 epoch REAL NOT NULL, person_id TEXT REFERENCES people(id) ON DELETE SET NULL, identity TEXT NOT NULL,
 score REAL, status TEXT NOT NULL, face_count INTEGER NOT NULL, snapshot TEXT, trusted INTEGER NOT NULL,
 duration_ms INTEGER NOT NULL, freshness TEXT NOT NULL, error TEXT, attempt INTEGER NOT NULL,
 image_hash TEXT, corrected_identity TEXT, source_event_id TEXT NOT NULL);
CREATE INDEX events_epoch ON events(epoch);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
""", "ALTER TABLE events ADD COLUMN image_metadata TEXT;"]


class Store:
    def __init__(self, data):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.data / "images").mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.data / "visitors.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError("Database is newer than this app; restore a matching backup")
        for i in range(version, len(MIGRATIONS)):
            self.db.executescript("BEGIN IMMEDIATE;" + MIGRATIONS[i] + f"PRAGMA user_version={i+1}; COMMIT;")

    def people(self, vectors=False):
        with self.lock:
            people = [dict(r) for r in self.db.execute("SELECT * FROM people ORDER BY name")]
            for p in people:
                rows = self.db.execute("SELECT vector FROM templates WHERE person_id=?", (p["id"],)).fetchall()
                p["template_count"] = len(rows)
                if vectors:
                    p["vectors"] = [json.loads(r[0]) for r in rows]
            return people

    def person(self, name, trusted, vectors, person_id=None):
        name = str(name).strip()
        if not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Name must be 1–80 printable characters")
        person_id = person_id or uuid.uuid4().hex
        with self.lock, self.db:
            if self.db.execute("SELECT count(*) FROM people").fetchone()[0] >= 50 and not self.db.execute("SELECT 1 FROM people WHERE id=?",(person_id,)).fetchone():
                raise ValueError("Registry limit of 50 people reached")
            self.db.execute("INSERT INTO people VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,trusted=excluded.trusted", (person_id, name, bool(trusted)))
            if vectors is not None:
                self.db.execute("DELETE FROM templates WHERE person_id=?", (person_id,))
                self.db.executemany("INSERT INTO templates VALUES(?,?)", [(person_id, json.dumps(v)) for v in vectors])
        return person_id

    def delete_person(self, person_id):
        with self.lock, self.db:
            # Remove identity traces in visitor records, too; embeddings cascade.
            self.db.execute("UPDATE events SET identity='Deleted person',trusted=0,corrected_identity=NULL WHERE person_id=?", (person_id,))
            self.db.execute("DELETE FROM people WHERE id=?", (person_id,))

    def event(self, event_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return dict(row) if row else None

    def duplicate(self, source_id, epoch):
        with self.lock:
            return self.db.execute("SELECT id FROM events WHERE source_event_id=? OR abs(epoch-?)<10 LIMIT 1", (source_id, epoch)).fetchone() is not None

    def repeated_image(self, digest):
        with self.lock:
            return self.db.execute("SELECT 1 FROM events WHERE image_hash=? LIMIT 1", (digest,)).fetchone() is not None

    def save_event(self, event):
        with self.lock, self.db:
            columns = list(event)
            self.db.execute("INSERT OR REPLACE INTO events (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", tuple(event.values()))

    def latest_event(self):
        with self.lock:
            row = self.db.execute("SELECT * FROM events ORDER BY epoch DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def history(self, person=None, start=None, end=None, include_no_face=True):
        clauses, args = [], []
        if not include_no_face:
            clauses.append("status != 'no_face'")
        for value, clause in [(person,"person_id=?"), (start,"timestamp>=?"), (end,"timestamp<=?")]:
            if value:
                clauses.append(clause)
                args.append(value)
        sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY epoch DESC LIMIT 200"
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def correct(self, event_id, name):
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Correction must be 1–80 characters")
        with self.lock, self.db:
            self.db.execute("UPDATE events SET corrected_identity=? WHERE id=?", (name.strip(), event_id))

    def delete_event(self, event_id):
        with self.lock, self.db:
            e = self.event(event_id)
            if e and e["snapshot"]:
                (self.data / "images" / e["snapshot"]).unlink(missing_ok=True)
            self.db.execute("DELETE FROM events WHERE id=?", (event_id,))

    def retention(self, history_days, image_days):
        now = time.time()
        with self.lock, self.db:
            for e in self.db.execute("SELECT id,snapshot,epoch,status FROM events").fetchall():
                if e["snapshot"] and (image_days == 0 or e["epoch"] < now - image_days * 86400):
                    (self.data / "images" / e["snapshot"]).unlink(missing_ok=True)
                    self.db.execute("UPDATE events SET snapshot=NULL WHERE id=?", (e["id"],))
                if e["epoch"] < now - history_days * 86400:
                    self.delete_event(e["id"])
            # Remove crash-orphaned snapshots, never arbitrary files outside private storage.
            refs = {r[0] for r in self.db.execute("SELECT snapshot FROM events WHERE snapshot IS NOT NULL")}
            for p in (self.data / "images").glob("*.jpg"):
                if p.name not in refs:
                    p.unlink(missing_ok=True)

    def setting(self, key, default):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_retention(self, history, images):
        if type(history) is not int or type(images) is not int or not 1 <= history <= 365 or not 0 <= images <= 30:
            raise ValueError("History 1–365 days; images 0–30 days")
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO settings VALUES(?,?)", [("history_days",str(history)),("image_days",str(images))])
        self.retention(history, images)

    def close(self):
        with self.lock:
            self.db.close()
