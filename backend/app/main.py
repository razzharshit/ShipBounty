from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.auth_routes import router as auth_router
from app.api.tenancy_routes import router as tenancy_router
from app.api.review_routes import router as review_router
from app.api.bounty_routes import router as bounty_router
from app.api.ai_review_routes import router as ai_review_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.payout_integration_routes import router as payout_integration_router
from app.core.config import settings
from app.core.rate_limit import RateLimitMiddleware
from app.github.webhook import router as github_webhook_router


app = FastAPI(title=settings.APP_NAME)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        {
            settings.FRONTEND_URL,
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        }
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(tenancy_router)
app.include_router(review_router)
app.include_router(bounty_router)
app.include_router(ai_review_router)
app.include_router(dashboard_router)
app.include_router(payout_integration_router)
app.include_router(github_webhook_router)
