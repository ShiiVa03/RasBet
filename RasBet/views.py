"""
Routes and views for the flask application.
"""

from ast import Return
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
            db_game = Game(
                api_id=game['id'],
                game_type=GameType.football,
                datetime=datetime.strptime(game['commenceTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
            )
            db.session.add(db_game)
            db.session.commit()

            if game['scores']:
                home_result, away_result = list(map(int, game['scores'].split('x')))

                if home_result > away_result:
                    result = TeamSide.home
                elif home_result < away_result:
                    result = TeamSide.away
                else:
                    result = TeamSide.draw
            else:
                result = TeamSide.undefined

            team_game = TeamGame(
                game_id = db_game.id, 
                team_home = game['homeTeam'], 
                team_away = game['awayTeam'],
                odd_home = home_odd,
                odd_draw = draw_odd,
                odd_away = away_odd,
                result = result
            )
            
            db.session.add(team_game)
            db.session.commit()   
        else:
            team_game = db.session.execute(db.select(Game).filter_by(api_id = db_game.id))
            team_game.odd_home = home_odd
            team_game.odd_draw = draw_odd
            team_game.odd_away = away_odd
        
      


'''
WEB
'''

@app.route('/games/<_type>/')
def games(_type):
    game_type = None

    try:
        enum_game_type = GameType(int(_type))
    except ValueError:
        try:
            enum_game_type = GameType[_type.lower()]
        except KeyError:
            abort(404, "Jogo não existente")

    game_type = enum_game_type.value
    _games = db.session.execute(
        f"SELECT * FROM {'no_' if not game_type.is_team_game else ''}team_game WHERE game_id IN (SELECT id FROM game WHERE game_type='{enum_game_type.name}')"
    ).all()

    games = {row.game_id:row for row in _games}

    if 'tmp_bets' not in session:
        session['tmp_bets'] = TmpBets()

    return render_template(f'game_{game_type.value}.html', games=games)

    


@app.route('/')
@app.route('/home/')
def home():
    """Renders the home page."""
    games = db.session.execute("SELECT * FROM team_game WHERE game_id IN (SELECT api_id FROM game WHERE date(datetime)=DATE('now'))").all()

    if 'tmp_bets' not in session:
        session['tmp_bets'] = TmpBets()

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
    session.pop('tmp_bets')
    return redirect(url_for('home')) 

@app.post('/bet/tmp/add/')
def add_tmp_simple_bet():

    tmp_bets = session['tmp_bets']
    
    game = db.get_or_404(TeamGame, int(request.form['game_id']))   
    
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
        game_id = int(request.form['game_id']),
        odd = request.form['odd'],
        money = 0,
        bet_team = team_side
    )
    
    tmp_bets.add(user_partial_bet)
    return redirect(request.referrer)
    


@app.post('/bet/tmp/set/')
def set_tmp_bet():
    _index = request.form.get('index', None)
    amount = float(request.form['amount'].replace(",","."))
    print(amount)
    index = _index and int(_index)
    print(index)
    
    session['tmp_bets'].set_amount(index, amount)

    return redirect(request.referrer)

@app.post('/bet/tmp/del/')
def del_tmp_bet():
    index = int(request.form['index'])
    print(index)
    session['tmp_bets'].pop(index)
    return redirect(request.referrer)

    
@app.post('/bet/create/')
def bet_simple():
    tmp_bets = session['tmp_bets']
    
    user_bet = UserBet(
        user_id = session['id'],
        is_multiple = tmp_bets.is_multiple_selected
    )
    db.session.add(user_bet)
    db.session.commit()
    
    
    tmp_bets.flush(user_bet.id)
    db.session.commit()
    return redirect(request.referrer)


@app.post('/bet/tmp/change_context')
def change_context_tmp_bet():
    
    if bool(int(request.form['multiple'])):
        session['tmp_bets'].select_multiple()
    else:
        
        session['tmp_bets'].select_simple()

    return redirect(request.referrer)

    


class TmpBets:
    def __init__(self):
        self.simple = []
        self.multiple = []
        self.is_multiple_selected = False

    def check_multiple_submit(self):
        return all(bet.money > 0 for bet in self.multiple)

    def check_simple_submit(self):
        for bet in self.simple:
            if bet.money == 0:
                return False
        return True

    def total_simple_ammount(self):
        total = 0
        for bet in self.simple:
            total += bet.money
        return total


    def get_bet_team_game_info(self, games):
        bets = self.multiple if self.is_multiple_selected else self.simple
        results = []
        
        
        for bet in bets:
            
            game = games[bet.game_id]
            

            
            value_enum = bet.bet_team

            if value_enum == TeamSide.home:
                value = game[2]
            elif value_enum == TeamSide.away:
                value = game[3]
            else:
                value = "Empate"
            
            results.append(((game[2], game[3]), value, bet))

        return results


    def add(self, bet):
        if self.is_multiple_selected:
            if any(bet.game_id == cached_bet.game_id for cached_bet in self.multiple):
                raise Exception('Multiple bet must be unique per game')

            self.multiple.append(bet)
        else:
            self.simple.append(bet)



    def pop(self, idx):
        if self.is_multiple_selected:
            self.multiple.pop(idx)
        else:
            self.simple.pop(idx)
            

    def set_amount(self, idx, amount):
        if self.is_multiple_selected:
            for bet in self.multiple:
                bet.money = amount
        else:
            self.simple[idx].money = amount
        

    def flush(self, _id):
        if self.is_multiple_selected:
            for bet in self.multiple:
                bet.user_bet_id = _id

            db.session.add_all(self.multiple)
            self.multiple = []
        else:  
            for bet in self.simple:
                bet.user_bet_id = _id

            db.session.add_all(self.simple)
            self.simple = []


    def select_simple(self):
        if not self.is_multiple_selected:
            raise Exception('Simple bet is already selected')

        self.is_multiple_selected = False

    def select_multiple(self):
        if self.is_multiple_selected:
            raise Exception('Multiple bet is already selected')

        self.is_multiple_selected = True

        
