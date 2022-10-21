"""
This script runs the RasBet application using a development server.
"""

from distutils.debug import DEBUG
from distutils.log import debug
from os import environ
from pickle import TRUE
from RasBet import app

if __name__ == '__main__':
    HOST = environ.get('SERVER_HOST', 'localhost')
    try:
        PORT = int(environ.get('SERVER_PORT', '5555'))
    except ValueError:
        PORT = 5555
    app.run(HOST, PORT, debug=True)
