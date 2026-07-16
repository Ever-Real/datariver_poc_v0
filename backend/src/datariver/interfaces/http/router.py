from fastapi import APIRouter

from datariver.interfaces.http.routes import (
    admin,
    catalog,
    chat,
    governance,
    health,
    knowledge,
    operations,
    registration,
    sharing,
)

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(health.router)
api_router.include_router(catalog.router)
api_router.include_router(governance.router)
api_router.include_router(registration.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(operations.router)
api_router.include_router(sharing.router)
