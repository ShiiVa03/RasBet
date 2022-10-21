"""
Routes and views for the flask application.
"""

from datetime import datetime

from flask import render_template,request,flash,url_for,redirect
from RasBet import app, models,db
from datetime import datetime



@app.route('/')
@app.route('/home/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Home Page',
        year=datetime.now().year,
    )

@app.route('/contact/')
def contact():
    """Renders the contact page."""
    return render_template(
        'contact.html',
        title='Contact',
        year=datetime.now().year,
        message='Your contact page.'
    )

@app.route('/about/')
def about():
    """Renders the about page."""
    return render_template(
        'about.html',
        title='About',
        year=datetime.now().year,
        message='Your application description page.'
    )

@app.route('/login/')
def login():
    """Renders the login page."""
    return render_template(
        'login.html',
        title='Login',
        year=datetime.now().year,
        message='Your login page'
    )
    
@app.route('/register/', methods=['POST'])
def register():
    email = request.form['email']
    passwd = request.form['password']
    birthdate = request.form['birthdate']
    user = models.User(name = "Joaquim", email= email, passwd=passwd, birthdate=birthdate,balance=0)
    try:
        db.session.add(user)
        db.session.commit()
    except db.IntegrityError:
        flash('Email already in use.')
    else:
        return redirect(url_for('login'))
            
