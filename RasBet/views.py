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

from .models import TeamGame, User, Transaction, Game, GameType, UserBet, UserParcialBet, TeamSide, GameState, NoTeamGame, NoTeamGamePlayer, Observer
from math import prod



'''
External API
'''

@scheduler.task('interval', id='get_team_games', seconds=30)
def get_team_games():
    with app.app_context():
        url_football = "http://ucras.di.uminho.pt/v1/games/"
        basket_path = "RasBet/games/basketball.json"
        tennis_path = "RasBet/games/tennis.json"

        response = requests.request("GET", url_football)

        football_games = json.loads(response.text)
        basket_games = json.load(open(basket_path))
        tennis_games = json.load(open(tennis_path))

        parse_jsons(football_games, "football")
        parse_jsons(tennis_games, "tennis")
        parse_jsons(basket_games, "basketball")
     
        
@scheduler.task('interval', id='get_no_team_games', seconds=30)
def get_no_team_games():
    with app.app_context():
        
        motogp_path = "Rasbet/games/motogp.json"
        motogp_games = json.load(open(motogp_path))
        
        parse_jsons(motogp_games, "motogp")
        
      
'''
Background Threads
'''

@scheduler.task('interval', id='update_balances', seconds=60)
def update_balances():
    with app.app_context():
        bets_team = bets_team_game()
        bets_no_team = bets_no_team_game()
        total_bet_dict = {}
        create_total_bet_from_tg(bets_team, total_bet_dict, 1)
        create_total_bet_from_tg(bets_no_team, total_bet_dict, 0)

        for bet, total_bet in total_bet_dict.items():
            user_balance = db.session.execute(f"SELECT balance FROM user WHERE id = '{total_bet.user_id}'").scalar()
 
            if not total_bet.multiple():
                for tup in total_bet.no_team_games:
                    if not tup[0] and tup[3] and tup[4] == GameState.closed.name:
                        if tup[3] == 1:
                            gains = tup[6] * tup[7]  
                            new_user_balance = user_balance + gains                      
                            db.session.execute(f"UPDATE user SET balance = '{new_user_balance}' WHERE id = '{tup[2]}'")
                            
                            transaction = create_transaction(total_bet.user_id, gains, new_user_balance)
                            db.session.add(transaction)   
                            db.session.execute(f"UPDATE user_parcial_bet SET paid = 'True' WHERE id = '{tup[8]}'")
                            
                for tup in total_bet.team_games:
                    if not tup[0] and tup[3] != TeamSide.undefined.name and tup[4] == GameState.closed.name:
                        if tup[3] == tup[1]:
                            gains = tup[8] * tup[9]  
                            new_user_balance = user_balance + gains                      
                            db.session.execute(f"UPDATE user SET balance = '{new_user_balance}' WHERE id = '{tup[2]}'")
                            
                            transaction = create_transaction(total_bet.user_id, gains, new_user_balance)
                            db.session.add(transaction)   
                            db.session.execute(f"UPDATE user_parcial_bet SET paid = 'True' WHERE id = '{tup[10]}'")
            else:
                if len(list(filter(lambda x: x[4] == GameState.closed and x[3] == 1 and not x[0], total_bet.no_team_games))) == len(total_bet.no_team_games) and \
                        len(list(filter(lambda x: x[4] == GameState.closed and x[3] != TeamSide.undefined and not x[0] and x[3] == x[1], total_bet.team_games))) == len(total_bet.team_games):

                    new_user_balance = user_balance + total_bet.gains
                    db.session.execute(f"UPDATE user SET balance = '{new_user_balance}' WHERE id = '{total_bet_dict.user_id}'")
                    
                    transaction = create_transaction(total_bet.user_id, total_bet.gains, new_user_balance)
                    ids_team_game = [x[10] for x in total_bet.team_games]
                    ids_no_team_game = [x[8] for x in total_bet.no_team_games]
                    db.session.add(transaction)
                    db.session.execute(f"UPDATE user_parcial_bet SET paid = 'True' WHERE id IN {tuple(ids_team_game + ids_no_team_game)}")
            db.session.commit()
        
            
'''
Utility functions
'''

class TotalBet():
    def __init__(self, user_id, is_multiple):
        self.team_games = []
        self.no_team_games = []
        self.is_multiple = is_multiple
        self.user_id = user_id
        self.gains = 0
    
    def add_team_game(self, tup):
        if self.is_multiple:
            if not self.gains:
                self.gains = tup[8] * tup[9]
            else:
                self.gains *= tup[9]
        
        self.team_games.append(tup)
    
    def add_no_team_game(self, tup):
        if self.is_multiple:
            if not self.gains:
                self.gains = tup[6] * tup[7]
            else:
                self.gains *= tup[7]
        
        self.no_team_games.append(tup)
        
    def multiple(self):
        return self.is_multiple
        
    
    def get_user_id(self):
        return self.user_id
        

def create_total_bet_from_tg(games, total_bets, team_game):
    for bet, res_list in games.items():
        if not bet in total_bets:
            total_bets[bet] = TotalBet(res_list[0][2], res_list[0][5])
        for tup in res_list:
            if team_game:                    
                total_bets[bet].add_team_game(tup)
            else: 
                total_bets[bet].add_no_team_game(tup)


def create_transaction(user_id, value, new_balance):
    return Transaction(
        user_id = user_id,
        datetime = datetime.now(),
        value = value,
        balance = new_balance,
        description = "Aposta Ganha"
    )
    
def bets_team_game():
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

def bets_no_team_game():
    result = db.session.execute("SELECT UB.id, UP.paid, UP.bet_no_team, UB.user_id, NTGP.placement, G.game_status, UB.is_multiple, UP.money, UP.odd, UP.id, NTGP.name, NTG.description FROM user_parcial_bet UP\
                            INNER JOIN user_bet UB\
                            ON UP.user_bet_id = UB.id\
                            INNER JOIN  game G\
                            ON UP.game_id = G.id\
                            INNER JOIN no_team_game_player NTGP\
                            ON NTGP.id = UP.bet_no_team\
                            INNER JOIN no_team_game NTG\
                            ON NTGP.no_team_game_id = NTG.id").all()
    x = {}
        
    for bet, *res in result:
        x.setdefault(bet, []).append(res)
    
    return x
    
        
def parse_jsons(games, type):
    app.logger.info("Requested games in background")
    
    try:
        enum_game_type = GameType(int(type))
    except ValueError:
        try:
            enum_game_type = GameType[type.lower()]
        except KeyError:
            abort(404, "Jogo não existente")
    game_type = enum_game_type.value

    for game in games:
        db_game = db.session.execute(db.select(Game).filter_by(api_id = game['id'])).scalar()
        if game_type.is_team_game:
            odds = game['bookmakers'][0]['markets'][0]['outcomes']
            home_odd = [x['price'] for x in odds if x['name'] == game['homeTeam']][0]
            away_odd = [x['price'] for x in odds if x['name'] == game['awayTeam']][0]
            if game_type.has_draws:
                draw_odd = [x['price'] for x in odds if x['name'] == 'Draw'][0]
            else:
                draw_odd = None
        else:
            placements = {}
            odds = {}
            
            for player in game['players']:
                odds[player['name']] = player['bookmakers'][0]['price']
                placements[player['name']] =  player['placement']
                
        if not db_game:
            db_game = Game(
                api_id=game['id'],
                game_type=enum_game_type.name,
                game_status = GameState.active
            )
            
            db.session.add(db_game)
            db.session.commit()

            if game_type.is_team_game:
                if game['scores']:
                    home_result, away_result = list(map(int, game['scores'].split('x')))
                    db_game.game_status = GameState.closed

                    if home_result > away_result:
                        result = TeamSide.home
                    elif home_result < away_result:
                        result = TeamSide.away
                    else:
                        if game_type.has_draws:
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
               
            else:
                no_team_game = NoTeamGame(
                    game_id = db_game.id,
                    description = game['description'],
                    datetime = datetime.strptime(game['commenceTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
                )
                db.session.add(no_team_game)
                db.session.commit()

                for player in game['players']:
                    no_team_game_player = NoTeamGamePlayer(
                        no_team_game_id = no_team_game.id,
                        name = player['name'],
                        placement = player['placement'],
                        odd = odds[player['name']]
                    )
                
                    db.session.add(no_team_game_player)
            db.session.commit()       
        else:
            if game_type.is_team_game:
                if game['scores']:
                    home_result, away_result = list(map(int, game['scores'].split('x')))
                    db_game.game_status = GameState.closed

                    if home_result > away_result:
                        result = TeamSide.home
                    elif home_result < away_result:
                        result = TeamSide.away
                    else:
                        if game_type.has_draws:
                            result = TeamSide.draw
                else:
                    result = TeamSide.undefined
            else:
                if game['completed']:
                    no_team_game = db.session.execute(f"SELECT * FROM no_team_game WHERE game_id = '{db_game.id}'").first()
                    no_team_game_players = db.session.execute(f"SELECT * FROM no_team_game_player WHERE no_team_game_id = '{no_team_game.id}'").all()
                
                    for no_team_game_player in no_team_game_players:
                        db.session.execute(f"UPDATE no_team_game_player SET placement = '{placements[no_team_game_player.name]}' WHERE id = '{no_team_game_player.id}'")

            db.session.commit()
    

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

    subscriptions = []
    if 'id' in session:
        user_id = session['id']        
        subs = db.session.execute(f"SELECT * FROM observer WHERE id_user = '{user_id}'").all() 
        subscriptions = [y for (y,_) in subs]
        

    games = {row.game_id:row for row in _games}
    
    for row in _games:
        game = db.get_or_404(Game,row.game_id)
        game_status = None

        if game.game_status == GameState.active:
            game_status = "active"
        else:
            game_status = "suspended"
            
        if not game_type.is_team_game:
            players_list = db.session.execute(
            f"SELECT * FROM no_team_game_player WHERE no_team_game_id = '{row.id}'").all()
            new_tup = (row, players_list, game_status)
        else:
            new_tup = (row, game_status)
        
        games[row.game_id] = new_tup

    if 'tmp_bets' not in session:
        session['tmp_bets'] = TmpBets()

    return render_template(f'game_{game_type.value}.html', games=games, subscriptions = subscriptions)

    


@app.route('/')
@app.route('/home/')
def home():
    """Renders the home page."""
    _games = db.session.execute("SELECT * FROM team_game WHERE game_id IN (SELECT id FROM game WHERE date(datetime)=DATE('now') AND game_status != 'closed' AND game_type = 'football')").all()

    subscriptions = []
    if 'id' in session:
        user_id = session['id']        
        subs = db.session.execute(f"SELECT * FROM observer WHERE id_user = '{user_id}'").all()   
        subscriptions = [y for (y,_) in subs]
        
    games = {row.game_id:row for row in _games}
    for row in _games:
        game = db.get_or_404(Game,row.game_id)
        game_status = None

        if game.game_status == GameState.active:
            game_status = "active"
        else:
            game_status = "suspended"
        games[row.game_id] = (row, game_status)
    
    if 'tmp_bets' not in session:
        session['tmp_bets'] = TmpBets()

    return render_template(
        'index.html',
        title='Home Page',
        year=datetime.now().year,
        games = games,
        subscriptions = subscriptions
        
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
    bets_team = bets_team_game()
    bets_no_team = bets_no_team_game()
    total_bet_dict = {}
    create_total_bet_from_tg(bets_team, total_bet_dict, 1)
    create_total_bet_from_tg(bets_no_team, total_bet_dict, 0)
    
    bets_simple = []
    bets_multiple = []
    
    for bet,total_bet in total_bet_dict.items():
        if total_bet.get_user_id() == user.id:
            for tg in total_bet.team_games:
                team_bet = tg[1]
                result = tg[3]
                home = tg[6]
                away = tg[7]
                money = tg[8]
                gains = "{:.2f}".format(tg[8] * tg[9])
                    
                if team_bet == TeamSide.home.name:
                    value = home
                elif team_bet == TeamSide.away.name:
                    value = away
                else:
                    value = "Empate"
                description = f"{home} - {away}"
                
                if total_bet.multiple():
                    bets_multiple.append((description,result,value,total_bet.gains,money))
                else:
                    bets_simple.append((description,result,value,gains,money))
                
            for tg in total_bet.no_team_games:
                gains = "{:.2f}".format(tg[6] * tg[7])
                value = tg[9]
                result = tg[3]
                money = tg[6]
                description = f"{tg[10]}"
    
                if total_bet.multiple():
                    bets_multiple.append((description,result,value,total_bet.gains,money))
                else:
                    bets_simple.append((description,result,value,gains,money))
    
    
    return render_template(
        'account_bets.html',
        bets_simple = bets_simple,
        bets_multiple = bets_multiple
    )
  

@app.get('/user/notifs')
def user_get_notifs():
    
    user = db.get_or_404(User, session['id'])
    
    notifs = db.session.execute(f"SELECT * FROM notification WHERE user_id = '{user.id}' and read = 0").all()
    print(notifs)
    return render_template(
        'notifs.html',
        notifications = notifs
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
    _type = request.form['type']
    
    team_game = None

    try:
        enum_game_type = GameType(int(_type))
    except ValueError:
        try:
            enum_game_type = GameType[_type.lower()]
        except KeyError:
            abort(404, "Tipo não existente")
    
    team_game = enum_game_type.value.is_team_game
    
    game_status = db.session.execute(f"SELECT game_status FROM game WHERE id = '{game_id}'")
    
    if game_status == GameState.suspended:
        abort(501, "Game is suspended")
    
    team_side = None
    player_bet = None
    
    if team_game:
        game = db.session.execute(f"SELECT * FROM team_game WHERE game_id = '{game_id}'").one() 
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
    else:
        game = db.session.execute(f"SELECT * FROM no_team_game WHERE game_id = '{game_id}'").one()
        player = db.get_or_404(NoTeamGamePlayer, request.form['player_id']) 
        player_bet = player.id
    
    user_partial_bet = UserParcialBet(
        game_id = int(request.form['game_id']),
        odd = float(request.form['odd']),
        money = 0.0,
        bet_team = team_side,
        bet_no_team = player_bet,
        paid = False
    )
    
    tmp_bets.add(game, user_partial_bet)
    return redirect(request.referrer)
    


@app.post('/bet/tmp/set/')
def set_tmp_bet():
    _index = request.form.get('index', None)
    amount = float(request.form['amount'].replace(",","."))
    index = _index and int(_index)

    
    session['tmp_bets'].set_amount(index, amount)

    return redirect(request.referrer)

@app.post('/bet/tmp/del/')
def del_tmp_bet():
    index = int(request.form['index'])
    session['tmp_bets'].pop(index)
    return redirect(request.referrer)

@app.post('/game/<game_id>/subscribe/')
def subscribe(game_id):
    game_id = int(game_id)
    
    observer = Observer(
        id_game = game_id,
        id_user = session['id']
    )
    
    db.session.add(observer)
    db.session.commit()
    return redirect(request.referrer)

@app.post('/game/<game_id>/unsubscribe/')
def unsubscribe(game_id):
    game_id = int(game_id)
    
    user_id = session['id']
    result = db.session.execute(f"SELECT * FROM observer WHERE id_game = {game_id} and id_user = {user_id}").first()
    
    if not result:
        abort(404, "Not subscribed")   
    
    db.session.execute(f"DELETE FROM observer WHERE id_game = {game_id} and id_user = {user_id}")
    db.session.commit() 
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
    
    observers = tmp_bets.get_game_ids()
    
    for observer in observers:
        db.session.execute(f"INSERT OR REPLACE INTO observer ('id_game', 'id_user') VALUES ({observer}, {user.id})")
    
    
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
    
    user.balance -= total_spent
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
    
@app.post('/specialist/<game_id>/update')
def change_odd(game_id):
    if session['type'] != 'especialista':
        abort(404, "You must be a specialist!")

    game_id = int(game_id)
    new_odd = request.form['new_odd']    
    game_type = request.form['game_type']
    
    try:
        enum_game_type = GameType(int(game_type))
    except ValueError:
        try:
            enum_game_type = GameType[game_type.lower()]
        except KeyError:
            abort(404, "Tipo não existente")
    
    team_game = enum_game_type.value.is_team_game
    
    description = ""
    if team_game:
        team_side = None
        try:
            enum_team_side = TeamSide(int(request.form['side']))
        except ValueError:
            try:
                enum_team_side = TeamSide[request.form['side'].lower()]
            except KeyError:
                abort(404, "Lado não existente")
    
        team_side = enum_team_side.name
        team_game = db.session.execute(f"SELECT * FROM team_game WHERE game_id = '{game_id}'").first()
        
        description = f"Jogo entre {team_game.team_home} e {team_game.team_away} alterou de odd"
        db.session.execute(f"UPDATE team_game SET odd_{team_side} = '{new_odd}' WHERE game_id = '{game_id}'")
    else:
        player_id = request.form['player_id']
        
        no_team_game = db.session.execute(f"SELECT * FROM no_team_game WHERE game_id = '{game_id}'")
        description = f"Jogo {no_team_game.description} mudou de odd"

        player = db.get_or_404(NoTeamGamePlayer, player_id)
        player.odd = new_odd
        
    observers = db.session.execute(f"SELECT * FROM observer where id_game='{game_id}'").all()

    for game_id,user_id in observers:
        user = db.get_or_404(User, user_id)
        user.update(description)

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
    
    print(game_id)

    game_state = enum_game_state  
    game = db.get_or_404(Game, game_id)

    if game.game_status == game_state:
        abort(404, "Não é possível mudar o estado do jogo para o mesmo")
    
    game.game_status = game_state
    db.session.commit()
    return redirect(request.referrer)

@app.post('/user/notif/<id>/read')
def read_notif(id):
    user = db.get_or_404(User, session['id'])
    
    db.session.execute(f"UPDATE notification SET read = 1 WHERE user_id = {user.id} and id = {id}")
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

            game_outside = db.get_or_404(Game, game.game_id)

            if game_outside.game_type.value.is_team_game:
                value_enum = bet.bet_team

                if value_enum == TeamSide.home:
                    value = game.team_home
                elif value_enum == TeamSide.away:
                    value = game.team_away
                else:
                    value = "Empate"
                description = f"{game.team_home} - {game.team_away}"
            else:
                player = db.get_or_404(NoTeamGamePlayer, bet.bet_no_team)
                value = player.name
                description = game.description

            results.append((description, value, bet))

        return results
    
    def get_game_ids(self):
        games_id = []
        
        if not self.is_multiple_selected:
            for game, _ in self.simple:
                if game.game_id not in games_id:
                    games_id.append(game.game_id)
        else:
            games_id = [x.game_id for x in self.multiple]
        
        return games_id         
        

    def check_game_present(self, game_id):
        games_bets = self.multiple if self.is_multiple_selected else self.simple
        
        return any(game_id == game.id for game,_ in games_bets)
        
    def check_player_present(self, player_id):
        games_bets = self.multiple if self.is_multiple_selected else self.simple
        
        return any(player_id == cached_bet.bet_no_team for _, cached_bet in games_bets)
        

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

    def check_game_present(self, game_id):
        games_bets = self.multiple if self.is_multiple_selected else self.simple

        return any(game_id == game.id for game, _ in games_bets)

    def check_player_present(self, player_id):
        games_bets = self.multiple if self.is_multiple_selected else self.simple
        
        return any(player_id == cached_bet.bet_no_team for _, cached_bet in games_bets)
        
