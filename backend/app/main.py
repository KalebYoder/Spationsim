from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db.database import Base, engine
from .routers import auth, nations, territories, facilities, military, probes
from . import models  # noqa: F401 - registers all ORM models with Base.metadata

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Spationsim API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:80"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(nations.router)
app.include_router(territories.router)
app.include_router(facilities.router)
app.include_router(military.router)
app.include_router(probes.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
