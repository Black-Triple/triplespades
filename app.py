import os
import random
from flask import Flask, jsonify, request, make_response, render_template
from flask_socketio import SocketIO, send, emit
from flask_cors import CORS
from pymongo import MongoClient
import json
from bson import ObjectId
from bson.json_util import dumps
import bcrypt
import util
import datetime
from flask_bcrypt import Bcrypt
from time import sleep
from dotenv import load_dotenv
load_dotenv()


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return json.JSONEncoder.default(self, o)


DB_URI = os.getenv('DB_URI')
BCRYPT_LOG_ROUNDS = 4

selection_started = False
players_list = []
scores = []

# create a instance of class and name is a placeholder for current module
app = Flask(__name__)
io = SocketIO(app, cors_allowed_origins='*')
client = MongoClient(DB_URI)
bcrypt = Bcrypt(app)
CORS(app)

client.CardDeck.blacklist_tokens.create_index(
    'createdAt', expireAfterSeconds=86400)


@io.on('score')
def score(data):
    global scores
    if len(scores) == 1:
        emit('score_final', scores[0] + data, broadcast=True)
    scores.append(data)


@io.on('score_final')
def score_final(data):
    global players_list
    players_list = []
    emit('score_final', data, broadcast=True)


@io.on('playing_end')
def playing_end(data):
    global players_list
    players_list = []
    emit('playing_end', data, broadcast=True)


@io.on('hand_end')
def hand_end(card):
    emit('hand_end', card, broadcast=True)


@io.on('play_card')
def play_card(data):
    emit('play_card', data, broadcast=True)


@io.on('start_playing')
def start_playing(data):
    emit('start_playing', data, broadcast=True)


@io.on('trump_selection')
def trump_selection(data):
    emit('trump_selection', data, broadcast=True)


@io.on('partner_selection')
def partner_selection(data):
    emit('partner_selection', data, broadcast=True)


@io.on('max_bid')
def max_bid(data):
    emit('bid', data, broadcast=True)
    emit('start_selection', broadcast=True)


@io.on('start_selection')
def start_selection(data):
    global selection_started
    print(selection_started)
    if selection_started:
        return
    else:
        emit('start_selection', broadcast=True)
        selection_started = True


@io.on('bid')
def bid(data):
    emit('bid', data, broadcast=True)


@io.on('join')
def join(data):
    global players_list
    if players_list.count(data) == 0 and not len(players_list) == 5:
        players_list.append(data)
        emit('join', data, broadcast=True)
        if len(players_list) == 5:
            deck = list(client.CardDeck.card_deck.find({}, {'_id': False}))
            random.shuffle(deck)
            emit('start_game', {'default_bidder': random.choice(players_list),
                                'cards': [deck[:10], deck[10:20], deck[20:30], deck[30:40], deck[40:50]]}, broadcast=True)


@io.on('leave')
def leave(data):
    emit('leave', data, broadcast=True)


@io.on('end_game')
def end_game(data):
    emit('end_game', broadcast=True)


def default_bidder():
    users = client.CardDeck.users
    users_list = list(users.find())
    previous_bidder = users.find_one({'default_bidder': True})
    default_bidder = users_list[(users_list.index(
        previous_bidder) + 1) % len(users_list)]
    users.update_one(previous_bidder, {
                     '$set': {'default_bidder': False}})
    users.update_one(default_bidder, {'$set': {'default_bidder': True}})
    return default_bidder['name']


@app.route('/game', methods=['POST'])
def post_game():
    data = request.get_json(force=True)
    games = client.CardDeck.games
    games.insert_one({'start_time': data['start_time'], 'end_time': data['end_time'],
                      'max_bid': data['max_bid'], 'bidder_name': data['bidder_name'],
                      'trump_suit': data['trump_suit'], 'partner_card': data['partner_card'], 'score': data['score']})
    return response('INSERTED_GAME', 200)


@app.route('/game', methods=['GET'])
def get_game():
    games = client.CardDeck.games
    bruh = dumps(list(games.find()))
    return bruh


@app.route('/players', methods=['GET'])
def players():
    global players_list
    return jsonify(players_list)


@app.route('/cards', methods=['GET'])
def cards():
    return dumps(list(client.CardDeck.card_deck.find()))


# request body: {email: string, name: string, password: string}
# response body: None
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True)
    users = client.CardDeck.users
    if users.find_one({'email': data['email']}):
        return response('USER_EXISTS', 400)

    password = bcrypt.generate_password_hash(
        data['password'], BCRYPT_LOG_ROUNDS
    ).decode()
    user = users.insert_one(
        {'name': data['name'], 'email': data['email'], 'password': password})
    auth_token = util.encode_auth_token(str(user.inserted_id))
    return jsonify({'token': auth_token.decode(), 'name': data['name']})

# request body: {email: string, password: string}
# response body: {token: string, name: string}
@app.route('/login', methods=['POST'])
def login():
    global players_list
    users = client.CardDeck.users
    data = request.get_json(force=True)
    user = users.find_one({'email': data['email']})
    if players_list.count(user['name']) > 0:
        return response('ALREADY_AUTHENTICATED', 400)
    if not user:
        return response('EMAIL_NOT_FOUND', 400)
    if not bcrypt.check_password_hash(user['password'], data['password']):
        return response('INVALID_PASSWORD', 400)

    auth_token = util.encode_auth_token(str(user['_id']))
    return jsonify({'token': auth_token.decode(), 'name': user['name']})

# request body: {email: string, token: string}
# response body: {message: string}
@app.route('/logout', methods=['POST'])
def logout():
    users = client.CardDeck.users
    data = request.get_json(force=True)
    user = users.find_one({'email': data['email']})
    if not data.get('token'):
        return response('NO_TOKEN_PROVIDED', 403)

    resp = util.decode_auth_token(data['token'], client)
    if resp is not None:
        client.CardDeck.blacklist_tokens.insert_one(
            {'token': data['token'], 'createdAt': datetime.datetime.now()})
        global selection_started, players_list
        selection_started = False
        players_list.remove(data['name'])
        return jsonify({'message': 'success'})

# request body: None
# response body: [{name: string, authenticated: boolean}]
@app.route('/users', methods=['GET'])
def get_authenticated_users():
    users = client.CardDeck.users
    names = list(users.find())
    for i in range(len(names)):
        names[i] = {'name': names[i]['name']}
    return jsonify(names)

# request body: {email: string, authenticated: boolean}
# response body: {message: string}
@app.route('/change-status', methods=['POST'])
def change_status():
    users = client.CardDeck.users
    data = request.get_json(force=True)
    user = users.find_one({'email': data['email']})
    if not user:
        return response('EMAIL_NOT_FOUND', 400)
    if user['authenticated']:
        return response('ALREADY_AUTHENTICATED', 400)
    users.update_one(user, {'$set': {'authenticated': data['authenticated']}})
    return jsonify({'message': 'success'})


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    if path in ['/change-status', '/users', '/logout', '/login', '/register', '/cards', '/players', '/game']:
        print(f'uhhhh... {path}')
    return render_template('index.html')


# @app.route('/<path:path>')
# def static_proxy(path):
#     return render_template('index.html')


def response(message, status_code):
    resp = make_response(message)
    resp.status_code = status_code
    resp.mimetype = 'application/json'
    return resp


# if condition to check name is equal to main to generate a script
if __name__ == '__main__':
    # selection_started = False
    # debug=True is used when we ddnt saved changes by need output to
    app.run(debug=True)
    # running the socketio server
    io.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
