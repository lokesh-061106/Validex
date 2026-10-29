"""Collusion graph: faculty, biometric and equipment identities shared across institutions.

Model (Neo4j property graph):
    (:Institution {key, name})-[:EMPLOYS {application}]->(:Faculty {key, masked})
    (:Faculty)-[:HAS_BIOMETRIC]->(:Biometric {key})
    (:Institution)-[:OWNS {application}]->(:Equipment {key, serial})

Identity values are pseudonymised before they reach the graph or the database: PAN numbers and
biometric references become HMAC-SHA256 keys (server secret); officers see masked values only.
Biometric references are IDs issued by an authorised attendance system, not raw biometrics —
this platform does no face or fingerprint matching.

Backends:
    Neo4j      when NEO4J_URI is set — nodes are MERGEd on ingest and collusion is found with Cypher.
    in-process otherwise — the same graph is rebuilt from PostgreSQL and the same queries run in Python.
PostgreSQL stays the system of record either way; Neo4j is a query projection.
"""

import hashlib
import hmac
import logging
import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.document import Document, DocumentType

logger = logging.getLogger(__name__)

PAN_RE = re.compile(r"\b([A-Z]{5})([0-9]{4})([A-Z])\b")

CYPHER_FACULTY = """
MATCH (me:Institution {key: $inst})-[:EMPLOYS]->(f:Faculty)<-[r:EMPLOYS]-(other:Institution)
WHERE other.key <> $inst
RETURN f.key AS key, f.masked AS masked, collect(DISTINCT {institution: other.name, application: r.application}) AS elsewhere
""".strip()
CYPHER_BIOMETRIC = """
MATCH (me:Institution {key: $inst})-[:EMPLOYS]->(f1:Faculty)-[:HAS_BIOMETRIC]->(b:Biometric)<-[:HAS_BIOMETRIC]-(f2:Faculty)
WHERE f1.key <> f2.key
MATCH (holder:Institution)-[r:EMPLOYS]->(f2)
RETURN b.key AS key, f1.masked AS here, f2.masked AS there, collect(DISTINCT {institution: holder.name, application: r.application}) AS elsewhere
""".strip()
CYPHER_EQUIPMENT = """
MATCH (me:Institution {key: $inst})-[:OWNS]->(e:Equipment)<-[r:OWNS]-(other:Institution)
WHERE other.key <> $inst
RETURN e.key AS key, e.serial AS serial, collect(DISTINCT {institution: other.name, application: r.application}) AS elsewhere
""".strip()


def _key(kind: str, value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{kind}:{value.strip().upper()}".encode(), hashlib.sha256).hexdigest()[:32]


def mask_pan(pan: str) -> str:
    m = PAN_RE.fullmatch(pan.strip().upper())
    return f"{m.group(1)}****{m.group(3)}" if m else "****"


def scrub_text(text: str) -> str:
    return PAN_RE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text or "")


def pseudonymise_faculty(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace raw identifiers with keyed hashes + masked display values."""
    out = []
    for m in members:
        row = {k: v for k, v in m.items() if k not in ("pan", "biometric_ref")}
        if m.get("pan"):
            row["pan_key"], row["pan_masked"] = _key("pan", m["pan"]), mask_pan(m["pan"])
        if m.get("biometric_ref"):
            row["biometric_key"] = _key("bio", m["biometric_ref"])
        out.append(row)
    return out


def _inst_key(app: Application) -> str:
    return app.permanent_id or str(app.institution_id)


class GraphService:
    def __init__(self):
        self._driver = None
        self._tried = False

    # ------------------------------------------------------------ backend
    def _neo4j(self):
        if not self._tried:
            self._tried = True
            if settings.NEO4J_URI:
                try:
                    from neo4j import GraphDatabase
                    self._driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
                    self._driver.verify_connectivity()
                    with self._driver.session() as s:
                        for label in ("Institution", "Faculty", "Biometric", "Equipment"):
                            s.run(f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.key IS UNIQUE")
                    logger.info("Collusion graph: Neo4j connected")
                except Exception as e:
                    logger.warning(f"Neo4j unavailable ({e}); using in-process graph")
                    self._driver = None
        return self._driver

    @property
    def backend(self) -> str:
        return "neo4j" if self._neo4j() else "in-process"

    # ------------------------------------------------------------- ingest
    def ingest_document(self, db: Session, doc: Document) -> None:
        """Pseudonymise identities on the document and, with Neo4j, project them into the graph."""
        data = dict(doc.extracted_data or {})
        if data.get("faculty_members") and any("pan" in m for m in data["faculty_members"]):
            data["faculty_members"] = pseudonymise_faculty(data["faculty_members"])
        if data.get("raw_text_snippet"):
            data["raw_text_snippet"] = scrub_text(data["raw_text_snippet"])
        doc.extracted_data = data
        db.commit()
        driver = self._neo4j()
        if not driver:
            return
        app = db.query(Application).filter(Application.id == doc.application_id).first()
        with driver.session() as s:
            s.run("MERGE (i:Institution {key: $k}) SET i.name = $n", k=_inst_key(app), n=app.institution_name)
            for m in data.get("faculty_members") or []:
                if not m.get("pan_key"):
                    continue
                s.run("""MATCH (i:Institution {key: $inst}) MERGE (f:Faculty {key: $k}) SET f.masked = $masked
                         MERGE (i)-[r:EMPLOYS]->(f) SET r.application = $app""",
                      inst=_inst_key(app), k=m["pan_key"], masked=m["pan_masked"], app=app.application_number)
                if m.get("biometric_key"):
                    s.run("MATCH (f:Faculty {key: $f}) MERGE (b:Biometric {key: $b}) MERGE (f)-[:HAS_BIOMETRIC]->(b)",
                          f=m["pan_key"], b=m["biometric_key"])
            for e in data.get("equipment") or []:
                s.run("""MATCH (i:Institution {key: $inst}) MERGE (e:Equipment {key: $k}) SET e.serial = $serial
                         MERGE (i)-[r:OWNS]->(e) SET r.application = $app""",
                      inst=_inst_key(app), k=_key("equipment", e["serial"]), serial=e["serial"], app=app.application_number)

    # ---------------------------------------------------- in-process graph
    @staticmethod
    def _edges(db: Session) -> dict[str, list[dict[str, Any]]]:
        """(identity -> holders) maps rebuilt from the system of record."""
        rows = (db.query(Document, Application).join(Application, Document.application_id == Application.id)
                .filter(Document.is_current.is_(True), Application.status != ApplicationStatus.DRAFT,
                        Document.doc_type.in_([DocumentType.FACULTY_LIST, DocumentType.ASSET_REGISTER])).all())
        faculty, bio, equipment = defaultdict(list), defaultdict(list), defaultdict(list)
        for doc, app in rows:
            holder = {"inst": _inst_key(app), "institution": app.institution_name, "application": app.application_number}
            data = doc.extracted_data or {}
            for m in data.get("faculty_members") or []:
                if m.get("pan_key"):
                    faculty[m["pan_key"]].append({**holder, "masked": m.get("pan_masked")})
                if m.get("biometric_key"):
                    bio[m["biometric_key"]].append({**holder, "pan_key": m.get("pan_key"), "masked": m.get("pan_masked")})
            for e in data.get("equipment") or []:
                equipment[_key("equipment", e["serial"])].append({**holder, "serial": e["serial"]})
        return {"faculty": faculty, "biometric": bio, "equipment": equipment}

    # -------------------------------------------------------------- query
    def collusion_for_application(self, db: Session, app: Application) -> list[dict[str, Any]]:
        inst = _inst_key(app)
        backend = self.backend
        hits: list[dict[str, Any]] = []
        if backend == "neo4j":
            with self._driver.session() as s:
                fac = [r.data() for r in s.run(CYPHER_FACULTY, inst=inst)]
                bio = [r.data() for r in s.run(CYPHER_BIOMETRIC, inst=inst)]
                eq = [r.data() for r in s.run(CYPHER_EQUIPMENT, inst=inst)]
        else:
            g = self._edges(db)
            fac = [{"key": k, "masked": hs[0]["masked"], "elsewhere": [h for h in hs if h["inst"] != inst]}
                   for k, hs in g["faculty"].items() if any(h["inst"] == inst for h in hs) and any(h["inst"] != inst for h in hs)]
            bio = []
            for k, hs in g["biometric"].items():
                mine = [h for h in hs if h["inst"] == inst]
                for h in mine:
                    others = [o for o in hs if o["pan_key"] != h["pan_key"]]
                    if others:
                        bio.append({"key": k, "here": h["masked"], "there": others[0]["masked"], "elsewhere": others})
            eq = [{"key": k, "serial": hs[0]["serial"], "elsewhere": [h for h in hs if h["inst"] != inst]}
                  for k, hs in g["equipment"].items() if any(h["inst"] == inst for h in hs) and any(h["inst"] != inst for h in hs)]

        def where(items):
            return ", ".join(sorted({f"{i['institution']} ({i['application']})" for i in items}))

        for r in fac:
            hits.append({"kind": "shared_faculty", "key": r["key"], "masked": r["masked"], "elsewhere": r["elsewhere"],
                         "finding": f"Faculty with PAN {r['masked']} is also declared by {where(r['elsewhere'])}",
                         "evidence": "Same PAN (keyed hash) on the faculty lists of different institutions: possible proxy/ghost faculty.",
                         "cypher": CYPHER_FACULTY, "backend": backend})
        for r in bio:
            hits.append({"kind": "shared_biometric", "key": r["key"], "masked": r["here"], "elsewhere": r["elsewhere"],
                         "finding": f"Biometric profile of faculty {r['here']} matches a different person ({r['there']}) at {where(r['elsewhere'])}",
                         "evidence": "One biometric reference linked to two different PANs: possible identity substitution.",
                         "cypher": CYPHER_BIOMETRIC, "backend": backend, "confidence": 0.97})
        for r in eq:
            hits.append({"kind": "shared_equipment", "key": r["key"], "serial": r["serial"], "elsewhere": r["elsewhere"],
                         "finding": f"Equipment serial {r['serial']} is also listed by {where(r['elsewhere'])}",
                         "evidence": "Same equipment serial number in the asset registers of different institutions: possible shared or shifted equipment.",
                         "cypher": CYPHER_EQUIPMENT, "backend": backend})
        return hits

    def subgraph(self, db: Session, app: Application) -> dict[str, Any]:
        """Nodes/edges around one institution for the officers' graph view."""
        inst = _inst_key(app)
        links = self.collusion_for_application(db, app)
        nodes = {inst: {"id": inst, "type": "institution", "label": app.institution_name, "focus": True}}
        edges = []
        for link in links:
            nid = f"{link['kind']}:{link['key'][:10]}"
            label = link.get("masked") or link.get("serial")
            nodes[nid] = {"id": nid, "type": link["kind"].split("_")[1], "label": label}
            edges.append({"from": inst, "to": nid, "kind": link["kind"]})
            for e in link["elsewhere"]:
                other = e.get("inst") or e["institution"]
                nodes.setdefault(other, {"id": other, "type": "institution", "label": e["institution"]})
                edges.append({"from": other, "to": nid, "kind": link["kind"], "application": e.get("application")})
        return {"backend": self.backend, "nodes": list(nodes.values()), "edges": edges, "links": links}


graph_service = GraphService()
