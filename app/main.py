from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime, timedelta, timezone  
from typing import Annotated

import os
import jwt
import redis 
import json
from fastapi import FastAPI, Request, Form
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlmodel import Field, Session, SQLModel, create_engine, select
from contextlib import asynccontextmanager
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv


load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr | None
    full_name: str | None
    password: str


class User(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(default=None, index=True)
    email: str | None = Field(unique=True)
    full_name: str | None = Field()
    disabled: bool | None = Field()


class UserInDB(User, table=True):
    hashed_password: str


class UserPublic(BaseModel):
    username: str
    email: EmailStr


DB_HOST = os.getenv("DB_HOST", "localhost")
postgres_url = f"postgresql://postgres:myPassword@{DB_HOST}:5432/eccommerce"
engine = create_engine(postgres_url) 

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummypassword")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)
SessionDep = Annotated[Session, Depends(get_session)]


templates = Jinja2Templates(directory="/home/jman/newsletter/templates")
# app.mount("/static", StaticFiles(directory="/home/jman/newsletter/static"), name="static") for when i decide to use a real css stylesheet (never xD)


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    # token comes from cookie, not header, for browser requests
    token = request.cookies.get("access_token")
    if not token: 
        return RedirectResponse(url="/")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return RedirectResponse(url="/")
    except InvalidTokenError:
        return RedirectResponse(url="/")

    # get verdicts from Redis
    all_data = r.hgetall("verdicts")
    tickers = {ticker: json.loads(verdict) for ticker, verdict in all_data.items()}

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tickers": tickers, "username": username}
    )

# login endpoint that sets a cookie instead of returning JSON
@app.post("/login")
async def login(request: Request, session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"}
        )
    
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token")
    return response

def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password):
    return password_hash.hash(password)


def get_user(session: Session, username: str):
    return session.exec(select(UserInDB).where(UserInDB.username == username)).first()


def authenticate_user(session: Session, username: str, password: str):
    user = get_user(session, username)
    if not user:
        verify_password(password, DUMMY_HASH)
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(session, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

    
@app.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep
) -> Token:
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

@app.post("/register")
async def create_user(
    session: SessionDep, 
    request: Request, 
    username: str = Form(...),
    password: str = Form(...)
):
    existing = session.exec(select(UserInDB).where(UserInDB.username == username)).first()
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="login.html", 
            context={"error": "Username already taken"}
        )
    db_user = UserInDB(
        username=username,
        hashed_password=get_password_hash(password)
    )
    session.add(db_user)
    session.commit()
    return RedirectResponse(url="/", status_code=302)

@app.get("/users/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    return current_user
    