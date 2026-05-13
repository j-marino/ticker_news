from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from datetime import datetime, timedelta, timezone  
from typing import Annotated
from random import randint

import os
import jwt
import string
import re
import asyncio
import resend
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded


load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class User(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(default=None, index=True)
    email: EmailStr = Field(default=None, index=True)
    disabled: bool | None


class UserInDB(User, table=True):
    hashed_password: str


class UnverifiedUser(User, table=True):
    hashed_password: str
    creation_time: datetime
    generated_code: int


class UserPublic(BaseModel):
    username: str
    email: EmailStr


DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummypassword")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


async def run_populate():
    from cron_populate_db import populate
    await asyncio.to_thread(populate)  # run blocking code in thread


async def populate_background():
    from cron_populate_db import populate
    print("imported cron populate")
    try:
        print("Background db population starting...")
        await asyncio.to_thread(populate)
        print("Background populate complete")
    except Exception as e:
        print(f"Background populate failed: {e}")


async def run_depopulate():
    from cron_depopulate_db import depopulate
    await asyncio.to_thread(depopulate)


async def delete_unverified_user():
    with Session(engine) as session:
        cutoff = datetime.now() - timedelta(minutes=10)
        users = session.exec(select(UnverifiedUser).where(UnverifiedUser.creation_time < cutoff)).all()
        for user in users:
            session.delete(user)
        session.commit()


async def run_delete_unverified_user():
    await asyncio.to_thread(delete_unverified_user)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()

    # prevent startup block
    asyncio.create_task(populate_background())

    # depopulate first 
    # weekdays 6:45am UTC
    scheduler.add_job(run_depopulate, CronTrigger(hour=6, minute=45, day_of_week='mon-fri'))
    # weekdays 7am UTC
    scheduler.add_job(run_populate, CronTrigger(hour=7, minute=0, day_of_week='mon-fri'))
    # delete unverified users every minute
    scheduler.add_job(run_delete_unverified_user, CronTrigger(minute='*'))
    
    scheduler.start()
    yield
    scheduler.shutdown()

# rate limiting + app setup  
limiter = Limiter(key_func=get_remote_address)
scheduler = AsyncIOScheduler()
resend.api_key = os.getenv("RESEND_API_KEY")
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler) 

SessionDep = Annotated[Session, Depends(get_session)]

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static") 

#redirect root to login
@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.get("/register", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={"error": None})


@app.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def dashboard(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return RedirectResponse(url="/login")
    except InvalidTokenError:
        return RedirectResponse(url="/login")

    tickers = get_all_verdicts()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tickers": tickers, "username": username}
    )


@app.post("/login")
@limiter.limit("5/minute")
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
    response.set_cookie(key="access_token", value=access_token, secure=True, httponly=True)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response


def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)


# prevent client side circumventing the password limits
def validate_password(password: str) -> bool:
    return (
        len(password) >= 8 and
        bool(re.search(r'[A-Z]', password)) and
        bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', password))
    )


def validate_username(username: str) -> bool:
    valid_characters = f"{string.ascii_letters}_0123456789" 
    invalid_name = False
    for letter in username:
        if letter not in valid_characters:
            invalid_name = True

    return (
        len(username) >= 4 and  len(username) <= 12 and 
        not(invalid_name)
    )


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


async def send_email_verification(recipient: EmailStr, code: int):
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

    params: resend.Emails.SendParams = {
        "from": "stackz <onboarding@resend.dev>",       
        "to": [recipient],
        "subject": "$tackz — verify your account",
        "html": template,
    }

    email: resend.Emails.SendResponse = resend.Emails.send(params)
    return email

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
@limiter.limit("5/minute")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    request: Request
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
@limiter.limit("5/minute")
async def create_user(
    session: SessionDep, 
    request: Request, 
    username: str = Form(...),
    email: EmailStr = Form(...),
    password: str = Form(...),
):
    if not validate_password(password):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "password must be 8+ chars with 1 uppercase and 1 symbol"}
        )
    
    if not validate_username(username):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "username can only contain underscores and numbers and ASCII characters"}
        )


    existing_username = session.exec(select(UserInDB).where(UserInDB.username == username)).first()
    existing_email = session.exec(select(UserInDB).where(UserInDB.email == email)).first()
    if existing_username:
        return templates.TemplateResponse(
            request=request,
            name="login.html", 
            context={"error": "Username already taken"}
        )
    
    if existing_email:
        return templates.TemplateResponse(
            request=request,
            name="login.html", 
            context={"error": "Email already in use"}
        )
    
    
    generated_code = generate_code()

    db_user = UnverifiedUser(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        creation_time=datetime.now(), 
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
@limiter.limit("5/minute")
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
@limiter.limit("10/minute") # more generous rate limiting on inputting code
async def email_verify(
    request: Request,
    session: SessionDep,
    inputted_code: int = Form(...)
):
    username = request.cookies.get("pending_username")
    # will not work if the cookie expires.
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
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("pending_username")
    return response

@app.get("/users/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    return current_user
    