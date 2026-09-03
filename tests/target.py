from enum import Enum

from fastapi import FastAPI, Form
from pydantic import BaseModel, Field

app = FastAPI()


class Role(str, Enum):
    user = "user"
    staff = "staff"
    admin = "admin"


class Profile(BaseModel):
    avatar_url: str
    birth_date: str
    bio: str = ""


class Account(BaseModel):
    username: str
    age: int
    balance: float
    is_admin: bool = False
    role: Role = Role.user
    org_id: str
    profile: Profile
    tags: list[str] = Field(default_factory=list)


@app.post("/api/account")
def update_account(account: Account):
    return {"ok": True, "user": account.username}


@app.post("/api/form-login")
def form_login(username: str = Form(...), password: str = Form(...), is_admin: bool = Form(False)):
    return {"ok": True, "user": username}


@app.get("/api/search")
def search(q: str, page: int = 1, limit: int = 10, org_id: str = ""):
    return {"q": q, "page": page}


_profile = {"username": "bob", "email": "bob@example.com", "bio": "",
            "is_admin": False, "role": "user"}


class ProfileUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    bio: str | None = None
    is_admin: bool | None = None
    role: Role | None = None


@app.post("/api/profile")
def update_profile(update: ProfileUpdate):
    data = update.model_dump(exclude_none=True)
    data.pop("role", None)
    _profile.update(data)
    return {"ok": True}


@app.get("/api/profile")
def read_profile():
    return dict(_profile)


class SignupWrapper(BaseModel):
    user: Account


@app.post("/api/wrapped-signup")
def wrapped_signup(payload: SignupWrapper):
    return {"ok": True}
