"""
The flask application package.
"""

import os

from dotenv import load_dotenv
from datetime import timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from flask_apscheduler import APScheduler


app = Flask(__name__)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=1)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

load_dotenv()

app.secret_key = os.getenv('RASBET_SESSIONS_KEY')
app.crypto_salt = os.getenv('RASBET_CRYPTO_SALT')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../tmp/project.db'
db = SQLAlchemy(app)

scheduler = APScheduler()

import RasBet.views as views
import RasBet.models as models
