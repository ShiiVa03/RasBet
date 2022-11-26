import enum

from RasBet import app, db

class MetaInfoGame:
    def __init__(self, value, name, is_team_game, has_draws):
        self.value = value
        self.name = name
        self.is_team_game = is_team_game
        self.has_draws = has_draws

    def __int__(self):
        return self.value

    def __repr__(self):
        return self.name


class TeamSide(enum.Enum):
    undefined = 0
    home = 1
    draw = 2
    away = 3

class GameType(enum.Enum):
    football = MetaInfoGame(1, "Football", True, True)
    tennis = MetaInfoGame(2, "Tennis", False, False)
    basketball = MetaInfoGame(3, "BasketBall", True, False)
    motogp = MetaInfoGame(4, "MotoGP", False, False)

class GameState(enum.Enum):
    active = 0
    suspended = 1
    closed = 2


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    passwd = db.Column(db.String(200), nullable=False)
    birthdate = db.Column(db.Date, nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0)
    

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.ForeignKey(User.id))
    datetime = db.Column(db.DateTime, nullable=False)
    value = db.Column(db.Float, nullable=False)
    balance = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=False)

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.String, nullable=False)
    game_type = db.Column(db.Enum(GameType), nullable=False)
    game_status = db.Column(db.Enum(GameState), nullable=False)


class TeamGame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.ForeignKey(Game.id))
    team_home = db.Column(db.String(75), nullable=False)
    team_away = db.Column(db.String(75), nullable=False)
    odd_home = db.Column(db.Float)
    odd_draw = db.Column(db.Float)
    odd_away = db.Column(db.Float)
    result = db.Column(db.Enum(TeamSide))
    datetime = db.Column(db.DateTime, nullable=False)

class NoTeamGame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.ForeignKey(Game.id))
    description = db.Column(db.String(200), nullable=False)
    datetime = db.Column(db.DateTime, nullable=False)

class NoTeamGamePlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    no_team_game_id = db.Column(db.ForeignKey(NoTeamGame.id))
    name = db.Column(db.String(100), nullable=False)
    odd = db.Column(db.Float)
    placement = db.Column(db.Integer, nullable=False)


class UserBet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.ForeignKey(User.id))
    is_multiple = db.Column(db.Boolean, nullable=False)
    

class UserParcialBet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_bet_id = db.Column(db.ForeignKey(UserBet.id))
    game_id = db.Column(db.ForeignKey(Game.id))
    odd = db.Column(db.Float, nullable=False)
    money = db.Column(db.Float, nullable=False)
    bet_team = db.Column(db.Enum(TeamSide))
    bet_no_team = db.Column(db.ForeignKey(NoTeamGamePlayer.id))
    paid = db.Column(db.Boolean)
