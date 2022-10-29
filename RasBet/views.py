"""
Routes and views for the flask application.
"""

import json
import regex
import hashlib
import requests


from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from flask import render_template, session, url_for, abort, request, redirect
from RasBet import app, db
from .models import TeamGame, User, Transaction, Game, GameType, UserBet, UserParcialBet, TeamSide




'''
External API
'''



@app.before_first_request
def before_first_request():
    url_football = "http://ucras.di.uminho.pt/v1/games/"

    response = requests.request("GET", url_football)


    games = json.loads(response.text)
    app.logger.info("before_first_request")

    for game in games:
        db_game = db.session.execute(db.select(Game).filter_by(api_id = game['id'])).scalar()
        odds = game['bookmakers'][0]['markets'][0]['outcomes']
        home_odd = [x['price'] for x in odds if x['name'] == game['homeTeam']][0]
        away_odd = [x['price'] for x in odds if x['name'] == game['awayTeam']][0]
        draw_odd = [x['price'] for x in odds if x['name'] == 'Draw'][0]
        
        if not db_game:
            db_game = Game(api_id = game['id'], game_type = GameType.Football, datetime = datetime.strptime(game['commenceTime'], "%Y-%m-%dT%H:%M:%S.%fZ"))
            
            team_game = TeamGame(
                game_id = game['id'], 
                team_home = game['homeTeam'], 
                team_away = game['awayTeam'],
                odd_home = home_odd,
                odd_draw = draw_odd,
                odd_away = away_odd,
                result = game['scores']
            )
            db.session.add(db_game)
            db.session.add(team_game)   
        else:
            team_game = db.session.execute(db.select(Game).filter_by(api_id = db_game.id))
            team_game.odd_home = home_odd
            team_game.odd_draw = draw_odd
            team_game.odd_away = away_odd
        
       
        db.session.commit()


'''
WEB
'''

@app.route('/')
@app.route('/home/')
def home():
    """Renders the home page."""
    games = db.session.execute("SELECT * FROM team_game WHERE game_id IN (SELECT api_id FROM game WHERE date(datetime) = DATE('now'))").all()
    return render_template(
        'index.html',
        title='Home Page',
        year=datetime.now().year,
        games = games
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


@app.get('/login/')
@app.get('/register/')
@app.get('/account_access/')
def account_access():
    """Renders the login page."""
    return render_template(
        'account_access.html',
        title='Login',
        year=datetime.now().year,
        message='Your login page'
    )


@app.get('/user/')
def edit_account():
    
    user = db.get_or_404(User, session['id'])

    
    if not user:
        abort(404, "User not found")
    
        
    return render_template(
        'account_page.html',
        balance = user.balance
    )


@app.get('/user/transactions')
def user_transactions():
    
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
    
    transactions = db.session.execute(db.select(Transaction).filter_by(user_id = session['id'])).scalars()
    
    return render_template(
        'account_transactions.html',
        transactions = transactions,
        balance = user.balance
    )
    


'''
API
'''

EMAIL_REGEX = regex.compile('^[\w-\.]+@([\w-]+\.)+[\w-]{2,4}$')

def check_valid_email(email):
    return bool(EMAIL_REGEX.match(email))

def check_valid_birthdate(birthdate):
    legal_birthdate = date.today() - relativedelta(years=18)

    return birthdate <= legal_birthdate
    
def get_hashed_passwd(passwd):
    return hashlib.sha256(passwd.encode()).hexdigest()

@app.post('/user/register')
def register():
    email = request.form["email"]

    if not check_valid_email(email):
        abort(404, 'Email not valid')

    birthdate = datetime.strptime(request.form['birthdate'], "%Y-%m-%d").date()

    if not check_valid_birthdate(birthdate):
        abort(404, 'Birthdate doesn\'t meet legal conditions')
    
    
    user = User(
        email = email,
        name = request.form['name'],
        passwd = get_hashed_passwd(request.form['passwd']),
        birthdate = birthdate
    )
    session['id'] = user.id
    session['name'] = user.name
    session['email'] = user.email

    db.session.add(user)
    db.session.commit()

            
    return redirect(url_for('home'))
    

@app.post('/user/login')
def login():
    email = request.form["email"]

    if not check_valid_email(email):
        abort(404, 'Email not valid')

    user = db.first_or_404(db.select(User).filter_by(email=email)) # It is already unique

    if user.passwd != get_hashed_passwd(request.form['passwd']):
        abort(404, "Wrong credentials")

    session['id'] = user.id
    session['name'] = user.name
    session['email'] = user.email
            
    return redirect(url_for('home'))

@app.post('/user/')
def edit():
    
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
    
    new_name = request.form['name']
    new_email = request.form['email']
    if new_name:
        user.name = new_name
        session['name'] = new_name
    
    if new_email:
        user.email = new_email
        session['email'] = new_email
        
    if request.form['password']:
        user.passwd = get_hashed_passwd(request.form['password'])
    
    db.session.commit()
    return redirect(url_for('edit_account'))

@app.post('/logout/')
def log_out():
    session.pop('id')
    session.pop('name')
    session.pop('email')
    session.pop('simple_bets')
    session.pop('simple_bets_info')
    return redirect(url_for('home')) 

@app.post('/user/temporary_bet_simple')
def temp_bet():

    if 'simple_bets' not in session:
        session['simple_bets'] = []
    
    if 'simple_bets_info' not in session:
        session['simple_bets_info'] = []
        
    bets_list = session['simple_bets']
    info_list = session['simple_bets_info']
    
    game = db.get_or_404(TeamGame, request.form['game_id'])    
    
    team_side = request.form['bet_team']
    if team_side == "home":
        team_side = TeamSide.home
        team_name = game.team_home
    elif team_side == "draw":
        team_side = TeamSide.draw
        team_name = "draw"
    else:
        team_side = TeamSide.away
        team_name = game.team_away

    
    user_partial_bet = UserParcialBet(
        game_id = request.form['game_id'],
        odd = request.form['odd'],
        money = 0,
        bet_team = team_side
    )
    
    bets_list.append(user_partial_bet)
    session['simple_bets'] = bets_list
    
    info_list.append((user_partial_bet.odd, team_name))
    session['simple_bets_info'] = info_list
    
    return redirect(url_for('home'))

@app.post('/user/bet_multiple')
def bet_multiple():
    
    user_bet = UserBet(
        user_id = session['id'],
        is_multiple = True
    )
    
    for partial in session['simple_bets']:
        partial.user_bet_id = user_bet.id ## TODO: change this because it doesnt work
        partial.money = 10

    db.session.add(user_bet)
    db.session.add_all(session['simple_bets'])
    db.session.commit()
    session.pop('simple_bets_info')
    
    return redirect(url_for('home'))