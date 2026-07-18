from fastapi import APIRouter

from datariver.interfaces.http.routes import (
    admin,
    auth,
    catalog,
    chat,
    classification_access_admin,
    governance,
    health,
    inference_admin,
    knowledge,
    manual_registration,
    operations,
    registration,
    retention,
    sharing,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(classification_access_admin.router)
api_router.include_router(health.router)
api_router.include_router(inference_admin.router)
api_router.include_router(catalog.router)
api_router.include_router(governance.router)
api_router.include_router(registration.router)
api_router.include_router(manual_registration.router)
api_router.include_router(retention.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(operations.router)
api_router.include_router(sharing.router)
