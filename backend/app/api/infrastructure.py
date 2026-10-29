"""Infrastructure CV: ad-hoc analysis studio for officials and the current equipment norms."""

from typing import Annotated
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_official
from app.ml.infrastructure_cv import infrastructure_cv
from app.models.user import User
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service
from app.services.document_service import sniff
from app.services.rule_engine import infra_norms

router = APIRouter(prefix="/infrastructure", tags=["Infrastructure Computer Vision"])


@router.get("/norms")
def get_norms(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)]):
    """Equipment minimums currently configured in the rule engine."""
    return infra_norms(compliance_service.active_rules(db))


@router.post("/analyze")
async def analyze_photo(file: Annotated[UploadFile, File()], db: Annotated[Session, Depends(get_db)],
                        current_user: Annotated[User, Depends(require_official)]):
    """Analyse a lab photo or walkthrough video without attaching it to an application (CV studio).
    Institutions submit lab evidence through the document upload with doc_type=lab_photo."""
    data = await file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    kind, _ = sniff(data)
    if kind == "pdf":
        raise HTTPException(status_code=415, detail="Upload a photo (JPEG/PNG) or video (MP4)")
    report = infrastructure_cv.analyze(data, infra_norms(compliance_service.active_rules(db)), file.filename or "")
    audit_service.log_event(db=db, action="INFRASTRUCTURE_CV_STUDIO", user_id=current_user.id,
                            details={"status": report.status, "counts": report.equipment_counts})
    return report.to_dict()
