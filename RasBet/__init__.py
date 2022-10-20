"""
The flask application package.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../../tmp/project.db'
db = SQLAlchemy(app)

import RasBet.views
import RasBet.models
