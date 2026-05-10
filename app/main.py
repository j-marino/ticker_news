from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from datetime import datetime, timedelta, timezone  
from typing import Annotated
from random import randint

import os
import jwt
from fastapi_mail import FastMail, MessageSchema,ConnectionConfig
from fastapi import FastAPI, Request, Form
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlmodel import Field, Session, SQLModel, create_engine, select
from contextlib import asynccontextmanager
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from database import get_all_verdicts

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class User(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(default=None, index=True)
    email: EmailStr = Field(default=None)
    disabled: bool | None


class UserInDB(User, table=True):
    hashed_password: str


class UnverifiedUser(User, table=True):
    hashed_password: str
    creation_time: str 
    generated_code: int


class UserPublic(BaseModel):
    username: str
    email: EmailStr


DB_HOST = os.getenv("DB_HOST", "localhost")
postgres_url = f"postgresql://postgres:myPassword@{DB_HOST}:5432/tickers"
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

conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD"),
    MAIL_FROM = os.getenv("MAIL_FROM"),
    MAIL_PORT = 587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

templates = Jinja2Templates(directory="/home/jman/newsletter/templates")
app.mount("/static", StaticFiles(directory="/home/jman/newsletter/static"), name="static") 

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={"error": None})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
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

    tickers = get_all_verdicts()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tickers": tickers, "username": username}
    )


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


async def send_email_verification(email: EmailStr, code: int):
    template = f"""
        <html>
        <body>
            <h2>Welcome to $tackz 📈</h2>
            <p>Your verification code is:</p>
            <h1 style="letter-spacing: 8px;">{code}</h1>
            <p>This code expires in 10 minutes.</p>
            <p style="color:#888; font-size:12px;">Not financial advice.</p>
        </body>
        </html>
    """

    message = MessageSchema(
        subject="$tackz — verify your account",
        recipients=[email],  # must be a list
        body=template,
        subtype="html"
    )

    fm = FastMail(conf)
    await fm.send_message(message)
    return JSONResponse(status_code=200, content={"message": "email has been sent"})


def generate_code():
    low, high = 100000, 999999 # 6 digit code
    code = randint(low, high)
    return code


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
    email: EmailStr = Form(...),
    password: str = Form(...),
):
    existing = session.exec(select(UserInDB).where(UserInDB.username == username)).first()
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="login.html", 
            context={"error": "Username already taken"}
        )
    
    generated_code = generate_code()

    db_user = UnverifiedUser(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        creation_time=datetime.now().strftime("%X"), # local time version e.g. '17:41:00'
        generated_code=generated_code
    )

    session.add(db_user) 
    session.commit()

    await send_email_verification(email, generated_code)

    # store username in cookie so /verify knows who to look up
    response = RedirectResponse(url="/verify", status_code=302)
    response.set_cookie(key="pending_username", value=username, httponly=True, max_age=600)  # 10 min expiry
    # redirect to email verification tab
    return response 


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request):
    # if no pending registration, redirect home
    if not request.cookies.get("pending_username"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="verify.html",
        context={"error": None}
    )


@app.post("/verify")
async def email_verify(
    request: Request,
    session: SessionDep,
    inputted_code: int = Form(...)
):
    username = request.cookies.get("pending_username")
    if not username:
        return RedirectResponse(url="/")

    unverified = session.exec(
        select(UnverifiedUser).where(UnverifiedUser.username == username)
    ).first()

    if not unverified:
        return templates.TemplateResponse(
            request=request,
            name="verify.html",
            context={"error": "Session expired. Please register again."}
        )

    if inputted_code != unverified.generated_code:
        return templates.TemplateResponse(
            request=request,
            name="verify.html",
            context={"error": "Incorrect code. Try again."}
        )

    # move to real users table
    verified_user = UserInDB(
        username=unverified.username,
        email=unverified.email,
        hashed_password=unverified.hashed_password,
        disabled=False
    )
    session.add(verified_user)
    session.delete(unverified) # delete from unverified users
    session.commit()

    # clear the pending cookie and redirect to login
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("pending_username")
    return response

@app.get("/users/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    return current_user
    