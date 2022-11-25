"""
Routes and views for the flask application.
"""


import json
from pickle import NONE
import regex
import hashlib
import requests


from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from flask import render_template, session, url_for, abort, request, redirect
from RasBet import app, db, scheduler, specialized_accounts

from .models import TeamGame, User, Transaction, Game, GameType, UserBet, UserParcialBet, TeamSide, GameState
from math import prod



'''
External API
'''

@scheduler.task('interval', id='get_football_games', seconds=30)
def get_football_games():
    with app.app_context():
        url_football = "http://ucras.di.uminho.pt/v1/games/"

        response = requests.request("GET", url_football)

        games = json.loads(response.text)
        app.logger.info("Requested games in background")

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
                    game_status = GameState.active
                )
                db.session.add(db_game)
                db.session.commit()

                if game['scores']:
                    home_result, away_result = list(map(int, game['scores'].split('x')))
                    db_game.game_status = GameState.closed

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
                    result = result,
                    datetime=datetime.strptime(game['commenceTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
                )
            
                db.session.add(team_game)
                db.session.commit()   
            
            else:
                team_game = db.session.execute(db.select(Game).filter_by(api_id = db_game.id))
                team_game.odd_home = home_odd
                team_game.odd_draw = draw_odd
                team_game.odd_away = away_odd
      
'''
Background Threads
'''

@scheduler.task('interval', id='update_balances', seconds=5)
def update_balances():
    with app.app_context():
        x = bets_from_db()
        for bet, res_list in x.items():
            user_balance = db.session.execute(f"SELECT balance FROM user WHERE id = '{res_list[0][3]}'").scalar()
            if not res_list[0][5]:
                for tup in res_list:
                    if not tup[0] and tup[3] != TeamSide.undefined and tup[4] == GameState.closed:
                        if tup[3] == tup[1]:
                            
                            gains = tup[7] * tup[8]  
                            new_user_balance = user_balance + gains                      
                            db.session.execute(f"UPDATE user SET balance = '{new_user_balance}' WHERE id = '{tup[3]}'")
                            transaction = Transaction(
                                user_id = tup[3],
                                datetime = datetime.now(),
                                value = gains,
                                balance = new_user_balance,
                                description = "Aposta Ganha"
                            )
                            db.session.add(transaction)   
                            db.session.execute(f"UPDATE user_parcial_bet SET paid = 'True' WHERE id = '{tup[10]}'")
            else:
                if len(filter(lambda x: x[4] == GameState.closed and x[3] != TeamSide.undefined and not x[0] and x[3] == x[1])) == len(res_list):
                    gains = res_list[0][8] * prod([x[9] for x in res_list])
                    new_user_balance = user_balance + gains
                    db.session.execute(f"UPDATE user SET balance = '{new_user_balance}' WHERE id = '{res_list[0][3]}'")
                    transaction = Transaction(
                                user_id = res_list[0][3],
                                datetime = datetime.now(),
                                value = gains,
                                balance = new_user_balance,
                                description = "Aposta Ganha"
                            )
                    ids = tuple([x[10] for x in res_list])
                    db.session.add(transaction)
                    db.session.execute(f"UPDATE user_parcial_bet SET paid = 'True' WHERE id IN {ids}")
                    
                    
                    
                
           
    
        db.session.commit()
        
                
            
'''
Utility functions
'''

def bets_from_db():
    result = db.session.execute("SELECT UB.id, UP.paid, UP.bet_team, UB.user_id,TG.result, G.game_status, UB.is_multiple, TG.team_home, TG.team_away, UP.money, Up.odd, UP.id FROM user_parcial_bet UP\
                            INNER JOIN user_bet UB\
                            ON UP.user_bet_id = UB.id\
                            INNER JOIN  game G\
                            ON UP.game_id = G.id\
                            INNER JOIN team_game TG\
                            ON TG.game_id = G.id").all()
    x = {}
        
    for bet, *res in result:
        x.setdefault(bet, []).append(res)
    
    return x
        
    

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
        f"SELECT * FROM {'no_' if not game_type.is_team_game else ''}team_game WHERE game_id IN (SELECT id FROM game WHERE game_type='{enum_game_type.name}' AND datetime >= DATETIME('now') AND game_status != 'closed')").all()

    games = {row.game_id:row for row in _games}

    if 'tmp_bets' not in session:
        session['tmp_bets'] = TmpBets()

    return render_template(f'game_{game_type.value}.html', games=games)

    


@app.route('/')
@app.route('/home/')
def home():
    """Renders the home page."""
    _games = db.session.execute("SELECT * FROM team_game WHERE game_id IN (SELECT id FROM game WHERE date(datetime)=DATE('now') AND game_status != 'closed')").all()

    games = {row.game_id:row for row in _games}
    
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

@app.get('/user/bets')
def user_get_simple_bets():
    
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
    
    bets = bets_from_db()
    bets_simple = {}
    bets_multiple = {}

    for bet, res_list in bets.items():
        new_result = []
        for res in res_list:
            gains = res[8] * res[9]
            team_bet = res[1]
            result = res[3]
            home = res[6]
            away = res[7]
            money = res[8]           
           
            if team_bet == TeamSide.home:
                value = home
            elif team_bet == TeamSide.away:
                value = away
            else:
                value = "Empate"
    
            new_result.append((home,away,result,value,gains,money))
            
        if not res_list[0][6]:
            bets_simple[bet] = new_result
        else:
            gains = res_list[0][8] * prod([x[9] for x in res_list])
            
                
            bets_multiple[bet] = 1
        
    print(bets_simple)
    return render_template(
        'account_bets.html',
        bets_simple = bets_simple,
        bets_multiple = bets_multiple
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
      

    db.session.add(user)
    db.session.commit()
    session['id'] = user.id
    session['name'] = user.name
    session['email'] = user.email
    session['type'] = 'user'
            
    return redirect(url_for('home'))
    

@app.post('/user/login')
def login():
    email = request.form["email"]

    if not check_valid_email(email):
        abort(404, 'Email not valid')
    
    password = get_hashed_passwd(request.form['passwd'])

    for account in specialized_accounts:
        if email == account.get("email"):
            if account.get("password") != password:
                abort(404, "Wrong credentials")
            
            session['email'] = email
            session['type'] = account.get("type")
            session['name'] = account.get("type")
            
            if session['type'] == "admin":
                return redirect(url_for('home')) # pag do admin
            else:
                return redirect(url_for('home')) # pag do especialista
    
    user = db.first_or_404(db.select(User).filter_by(email=email)) # It is already unique

    if user.passwd != password:
        abort(404, "Wrong credentials")

    session['id'] = user.id
    session['name'] = user.name
    session['email'] = user.email
    session['type'] = 'user'
        
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
    if session['type'] == "user":
        session.pop('id')
        session.pop('tmp_bets')

    session.pop('name')
    session.pop('email')
    session.pop('type')
    return redirect(url_for('home')) 

@app.post('/bet/tmp/add/')
def add_tmp_simple_bet():

    tmp_bets = session['tmp_bets'] 
    game_id = int(request.form['game_id'])
    
    game_status = db.session.execute(f"SELECT game_status FROM game WHERE id = '{game_id}'")
    
    if game_status == GameState.suspended:
        abort(501, "Game is suspended")
        
    game = db.get_or_404(TeamGame, game_id)   
    
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
        odd = float(request.form['odd']),
        money = 0.0,
        bet_team = team_side,
        paid = False
    )
    
    tmp_bets.add(game, user_partial_bet)
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
    
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
        
    user_balance = user.balance
    total_spent = tmp_bets.total_spent()
    
    if total_spent > user_balance:
        abort(500, 'Valor de aposta superior ao saldo')
    
    user_bet = UserBet(
        user_id = session['id'],
        is_multiple = tmp_bets.is_multiple_selected,
    )
    
    transaction = Transaction(
        user_id = session['id'],
        datetime = datetime.now(),
        value = total_spent,
        balance = user_balance - total_spent,
        description = "Aposta" 
    )
    db.session.add(transaction)
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

@app.post('/user/balance/deposit')
def deposit():
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
    
    value = float(request.form['value'])
    user.balance += value
    
    transaction = Transaction(
        user_id = session['id'],
        datetime = datetime.now(),
        value = value,
        balance = user.balance,
        description = "Deposito"
    )
    db.session.add(transaction)   
    db.session.commit()
    return redirect(request.referrer)

@app.post('/user/balance/withdraw')
def withdraw():
    user = db.get_or_404(User, session['id'])
    
    if not user:
        abort(404, "User not found")
    
    value = float(request.form['value'])
    if value > user.balance:
        abort(500, 'Não pode levantar mais que o seu balance')
        
    user.balance -= value
    
    transaction = Transaction(
        user_id = session['id'],
        datetime = datetime.now(),
        value = value,
        balance = user.balance,
        description = "Levantamento"
    )
    db.session.add(transaction)    
    db.session.commit()
    return redirect(request.referrer)
    
@app.post('/specialist/<game_id>/<_type>/update')
def change_odd(game_id,_type):
    if session['type'] != 'especialista':
        abort(404, "You must be a specialist!")
        
    team_side = None
    try:
        enum_team_side = TeamSide(int(_type))
    except ValueError:
        try:
            enum_team_side = TeamSide[_type.lower()]
        except KeyError:
            abort(404, "Lado não existente")
    
    team_side = enum_team_side.name
    game_id = int(game_id)
    
    print(f"odd_{team_side}")
  
    print(f"'{game_id}'")
    new_odd = request.form['new_odd']
    print(f"'{new_odd}'")
    db.session.execute(f"UPDATE team_game SET odd_{team_side} = '{new_odd}' WHERE game_id = '{game_id}'")
    db.session.commit()
    return redirect(request.referrer)
 
@app.post('/admin/<game_id>/update/<state>')
def update_game_state(game_id, state):
    
    game_state = None
    try:
        enum_game_state = GameState(int(state))
    except ValueError:
        try:
            enum_game_state = GameState[state.lower()]
        except KeyError:
            abort(404, "Tipo de estado nao existente")
    
    game_state = enum_game_state.name    
    game_status = db.session.execute(f"SELECT game_status FROM game WHERE id = '{int(game_id)}'")
    
    if game_status == game_state:
        abort(404, "Não é possível mudar o estado do jogo para o mesmo")
    
    db.session.execute(f"UPDATE game SET game_status ='{game_state}' WHERE id = '{game_id}'")
    db.session.commit()
    return redirect(request.referrer)


class TmpBets:
    def __init__(self):
        self.simple = []
        self.multiple = []
        self.is_multiple_selected = False
        self.betbutton = []

    def check_simple_submit(self):
        return bool(self.simple) and all(bet.money > 0 for _, bet in self.simple)
    
    def check_multiple_submit(self):
        return bool(self.multiple) and self.multiple[0][1].money > 0

    def total_simple_ammount(self):
        return sum(bet.money for _, bet in self.simple)
    
    def total_spent(self):
        if self.is_multiple_selected:
            if self.multiple:
                return self.multiple[0][1].money
        elif self.simple:
            return sum(bet.money for _, bet in self.simple)
        
        return 0.0

    def total_gains(self):
        if self.is_multiple_selected:
            if self.multiple:
                return self.multiple[0][1].money * prod((bet.odd for _, bet in self.multiple))
        elif self.simple:
            return sum(bet.money * bet.odd for _, bet in self.simple)

        return 0.0

    def has_game_multiple_bet(self, game_id):

        games_bets = self.multiple if self.is_multiple_selected else self.simple
        
        selected_bets_team = [bet.bet_team for _, bet in games_bets if bet.game_id == game_id]

        row_bets = [0, 0, 0]

        for bet_team in selected_bets_team:
            
            if bet_team == TeamSide.home:
                row_bets[0] = 1
            elif bet_team == TeamSide.draw:
                row_bets[1] = 1
            elif bet_team == TeamSide.away:
                row_bets[2] = 1

        if row_bets == [0, 0, 0]:
            row_bets = []

        self.betbutton = row_bets


    def get_bet_team_game_info(self):
        games_bets = self.multiple if self.is_multiple_selected else self.simple
        results = []
        
        
        for game, bet in games_bets:
            
            value_enum = bet.bet_team

            if value_enum == TeamSide.home:
                value = game.team_home
            elif value_enum == TeamSide.away:
                value = game.team_away
            else:
                value = "Empate"
            
            results.append(((game.team_home, game.team_away), value, bet))

        return results


    def add(self, game, bet):
        if self.is_multiple_selected:
            if any(bet.game_id == cached_bet.game_id for _, cached_bet in self.multiple):
                raise Exception('Multiple bet must be unique per game')

            if len(self.multiple) > 0:
                bet.money = self.multiple[0][1].money
            self.multiple.append((game, bet))
        else:
            self.simple.append((game, bet))



    def pop(self, idx):
        if self.is_multiple_selected:
            self.multiple.pop(idx)
        else:
            self.simple.pop(idx)
            

    def set_amount(self, idx, amount):
        if self.is_multiple_selected:
            for _, bet in self.multiple:
                bet.money = amount
        else:
            self.simple[idx][1].money = amount
        

    def flush(self, _id):
        if self.is_multiple_selected:
            for _, bet in self.multiple:
                bet.user_bet_id = _id
                db.session.add(bet)

            self.multiple = []
        else:  
            for _, bet in self.simple:
                bet.user_bet_id = _id
                db.session.add(bet)

            self.simple = []


    def select_simple(self):
        if not self.is_multiple_selected:
            raise Exception('Simple bet is already selected')

        self.is_multiple_selected = False

    def select_multiple(self):
        if self.is_multiple_selected:
            raise Exception('Multiple bet is already selected')

        self.is_multiple_selected = True

        
