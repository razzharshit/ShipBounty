from fastapi import APIRouter, Depends, HTTPException, Request, status
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.authz import authorize_repository, get_current_user
from app.db.session import get_db
from app.models.analysis_run import AnalysisRun
from app.models.authorization import AuthorizationRole
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.webhook_outbox import OutboxState, WebhookOutbox
from app.schemas.pr_metrics import PRMetricsRead
from app.schemas.pull_request import PullRequestCreate, PullRequestRead
from app.schemas.pull_request_file import PullRequestFileRead
from app.schemas.score import AnalysisRunRead, ScoreRead
from app.services.pr_analysis_service import get_pr_metrics_by_pr_id
from app.services.pr_file_service import get_files_by_pr_id
from app.services.pr_service import create_pull_request, list_pull_requests
from app.services.score_service import get_score_by_pr_id, list_score_history



router = APIRouter()


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "API running"}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/prs", response_model=list[PullRequestRead])
def get_prs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PullRequestRead]:
    return list_pull_requests(db, user.id)


@router.post("/prs", response_model=PullRequestRead, status_code=201)
def post_pr(
    payload: PullRequestCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PullRequestRead:
    repository = db.get(Repository, payload.repo_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    authorize_repository(
        db, user, repository, AuthorizationRole.MAINTAINER, request
    )
    return create_pull_request(db, payload, default_author_id=user.id)


def _authorized_pr(
    db: Session,
    user: User,
    pr_id: int,
    request: Request,
    required_role: AuthorizationRole = AuthorizationRole.VIEWER,
) -> PullRequest:
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    authorize_repository(
        db, user, pull_request.repository, required_role, request
    )
    return pull_request


@router.post("/prs/{pr_id}/resync", status_code=status.HTTP_202_ACCEPTED)
def resync_pull_request(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    pull_request = _authorized_pr(
        db,
        user,
        pr_id,
        request,
        required_role=AuthorizationRole.MAINTAINER,
    )
    source = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.repository_pk == pull_request.repo_id,
            WebhookDelivery.event_type == "pull_request",
        )
        .order_by(WebhookDelivery.received_at.desc(), WebhookDelivery.id.desc())
        .first()
    )
    if source is None:
        raise HTTPException(
            status_code=409,
            detail="No authenticated GitHub delivery is available to resynchronize",
        )
    delivery = WebhookDelivery(
        delivery_id=f"operator-resync:{uuid.uuid4()}",
        event_type=source.event_type,
        action="synchronize",
        installation_id=source.installation_id,
        repository_id=source.repository_id,
        repository_full_name=source.repository_full_name,
        repository_owner_login=source.repository_owner_login,
        organization_id=pull_request.repository.organization_id,
        repository_pk=pull_request.repo_id,
        payload=source.payload,
        payload_hash=source.payload_hash,
        status=IngestionState.RECEIVED,
    )
    delivery.outbox_message = WebhookOutbox(status=OutboxState.PENDING)
    db.add(delivery)
    db.commit()
    return {"status": "accepted", "delivery_id": delivery.delivery_id}


@router.get("/scores/{pr_id}", response_model=ScoreRead)
def get_score(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScoreRead:
    pull_request = _authorized_pr(db, user, pr_id, request)
    if not pull_request.file_sync_complete:
        raise HTTPException(
            status_code=409,
            detail=f"Authoritative score unavailable: {pull_request.incomplete_reason or 'file sync incomplete'}",
        )
    score = get_score_by_pr_id(db, pr_id)
    if not score:
        raise HTTPException(
            status_code=404,
            detail="No deterministic score has been produced for this PR",
        )
    return score


@router.get("/prs/{pr_id}/scores", response_model=list[ScoreRead])
def get_score_history(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ScoreRead]:
    _authorized_pr(db, user, pr_id, request)
    return list_score_history(db, pr_id)


@router.get("/prs/{pr_id}/analysis-runs", response_model=list[AnalysisRunRead])
def get_analysis_runs(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AnalysisRunRead]:
    _authorized_pr(db, user, pr_id, request)
    return (
        db.query(AnalysisRun)
        .filter(AnalysisRun.pr_id == pr_id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .all()
    )


@router.get("/prs/{pr_id}/metrics", response_model=PRMetricsRead)
def get_pr_metrics(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PRMetricsRead:
    pull_request = _authorized_pr(db, user, pr_id, request)
    if not pull_request.file_sync_complete:
        raise HTTPException(
            status_code=409,
            detail=f"Authoritative metrics unavailable: {pull_request.incomplete_reason or 'file sync incomplete'}",
        )
    metrics = get_pr_metrics_by_pr_id(db, pr_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="Metrics not found for this PR")
    return metrics


@router.get("/prs/{pr_id}/files", response_model=list[PullRequestFileRead])
def get_pr_files(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PullRequestFileRead]:
    _authorized_pr(db, user, pr_id, request)
    files = get_files_by_pr_id(db, pr_id)
    if not files:
        raise HTTPException(status_code=404, detail=f"No files found for PR {pr_id}")
    return files
