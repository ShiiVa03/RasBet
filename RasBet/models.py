import enum

from RasBet import app, db


class TeamSide(enum.Enum):
    home = 1
    draw = 2
    away = 3

class GameType(enum.Enum):
    Football = 1
    Tennis = 2
    Basketball = 3
    MotoGP = 4



class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    passwd = db.Column(db.String, nullable=False)
    birthdate = db.Column(db.TEXT, nullable=False)
    balance = db.Column(db.Float, nullable=False)

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
    datetime = db.Column(db.DateTime, nullable=False)


class TeamGame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.ForeignKey(Game.id))
    team_home = db.Column(db.String(75), nullable=False)
    team_away = db.Column(db.String(75), nullable=False)
    odd_home = db.Column(db.Float)
    odd_draw = db.Column(db.Float)
    odd_away = db.Column(db.Float)
    result = db.Column(db.Enum(TeamSide))

class NoTeamGame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.ForeignKey(Game.id))
    description = db.Column(db.String(200), nullable=False)

class NoTeamGamePlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    no_team_game_id = db.Column(db.ForeignKey(NoTeamGame.id))
    name = db.Column(db.String(100), nullable=False)
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
