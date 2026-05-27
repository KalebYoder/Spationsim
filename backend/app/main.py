from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db.database import Base, engine
from .routers import auth, nations, territories, facilities, military, probes, economy, chat, mail, diplomacy, events
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
app.include_router(economy.router)
app.include_router(chat.router)
app.include_router(mail.router)
app.include_router(diplomacy.router)
app.include_router(events.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
