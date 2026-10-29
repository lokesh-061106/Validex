"""Generate synthetic demo documents and seed three applications through the real pipeline.

    cd backend
    python ../scripts/generate_demo_data.py            # seed (skips applications that exist)
    python ../scripts/generate_demo_data.py --reset    # remove all applications first

Writes the generated files to sample_docs/demo/<institution>/ so they can also be uploaded by hand.
For a realistic infrastructure demo, put real computer-lab photos in sample_docs/lab_photos/.
"""

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(BACKEND)
os.environ.setdefault("INLINE_PROCESSING", "true")

from app.core.database import SessionLocal  # noqa: E402
from app.main import init_db  # noqa: E402
from app.models.application import AIRecommendation, Application, ApplicationCategory, ApplicationStatus  # noqa: E402
from app.models.document import DocumentType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.document_service import document_service  # noqa: E402
from app.services.validation_service import validation_service  # noqa: E402

import demo_documents  # noqa: E402


def write_samples(sets: dict) -> None:
    for key, spec in sets.items():
        out = os.path.join(ROOT, "sample_docs", "demo", key)
        os.makedirs(out, exist_ok=True)
        for _, filename, data in spec["docs"]:
            with open(os.path.join(out, filename), "wb") as f:
                f.write(data)


def seed(reset: bool) -> None:
    init_db()
    sets = demo_documents.build()
    write_samples(sets)
    db = SessionLocal()
    try:
        if reset:
            for app in db.query(Application).all():
                db.delete(app)
            db.commit()
            print("Removed existing applications.")

        # Crescent first so its lab photo is the 'original' that Zenith's copy is matched against
        for key in ("crescent", "apex", "zenith"):
            spec = sets[key]
            if db.query(Application).filter(Application.application_number == spec["number"]).first():
                print(f"{spec['number']} exists, skipping")
                continue
            user = db.query(User).filter(User.email == spec["email"]).first()
            app = Application(application_number=spec["number"], institution_id=user.id, institution_name=spec["name"],
                              permanent_id=spec["permanent_id"], requested_intake=spec["intake"],
                              category=ApplicationCategory.EOA, academic_year="2026-2027",
                              status=ApplicationStatus.DRAFT, ai_recommendation=AIRecommendation.PENDING)
            db.add(app)
            db.commit()
            db.refresh(app)
            for doc_type, filename, data in spec["docs"]:
                doc = document_service.create_document(db, app, data, filename, user.id, DocumentType(doc_type))
                document_service.process_document(db, doc.id, user.id)
            app.status = ApplicationStatus.SUBMITTED
            db.commit()
            result = validation_service.validate_application(db, app.id, user.id)
            print(f"{spec['number']} {spec['name']}: risk {result['risk_score']} | AI: {result['ai_recommendation']} | "
                  f"{result['critical_count']} critical, {result['warning_count']} warnings")
    finally:
        db.close()
    if not demo_documents.lab_photos():
        print("\nNote: no real lab photos found in sample_docs/lab_photos/. Placeholders were used, so the "
              "computer-lab rule will ask for better evidence. Add 2+ real lab photos and re-run with --reset.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete all applications before seeding")
    seed(parser.parse_args().reset)
