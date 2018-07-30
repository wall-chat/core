#!/user/bin/env python3
# -*- coding: utf-8 -*-
"""wallaced-core
description:
    This module is the main coordinator between all the modules
    and plugs that make up Wallace. This module's Docker container
    should be started first to avoid registration errors.
"""
import signal
import sys
import json
import time
import threading
import requests
from flask import Flask
from flask import jsonify
from flask import request
from flask import abort

__author__ = "Tai Groot"
__license__ = ["GPLv3", "Commercial"]
__version__ = "0.0.1"
__maintainer__ = "Tai Groot"
__email__ = "dev@wallaced.org"
__status__ = "pre-alpha"
__date__ = "27-07-2018"

state = None
app = Flask(__name__)


class State():
    """
    This object is used to organize Wallace's state.

    A dictionary of keywords and their respective modules,
    debug status, the interactive lock, and other state-ful
    properties are tracked here.

    """
    def __init__(self):
        """
        Set interactive_lock to False, record the initialization time,
        disable debug mode be default.
        """
        self.interactive_lock = False
        self.init_time = int(round(time.time()))
        self.locking_module = None
        self.debug = False
        self.keywords = []

    def is_unlocked(self):
        """
        Checks if any modules have the interactive_lock enabled.
        """
        return not self.interactive_lock

    def lock(self, module):
        """
        Sets the interactive_lock active for a module only if no other
        modules currently have a lock.

        Returns True on success, and False on failure
        """
        if not self.is_unlocked():
            return False
        self.locking_module = module
        return True

    def unlock(self):
        """
        Removes the interactive_lock. Returns False if no
        interactive lock was set.
        """
        if not self.interactive_lock:
            return False
        self.interactive_lock = False
        return True

    def add_keyword(self, phrase, module):
        """
        Adds a dictionary entry to the array of phrases Wallace
        recognizes as commands.
        """
        phrase = {'module': module,
                  'phrase': phrase}
        self.keywords.append(phrase)

    def deregister_all(self, module):
        """
        Removes all keyword entries associated with the given module.

        Returns the number of removed keywords.
        """
        new_phrase_list = []
        removed_phrases = 0
        for phrase in self.keywords:
            if phrase[module] == module:
                removed_phrases += 1
            else:
                new_phrase_list.append(phrase)
        self.keywords = new_phrase_list
        return removed_phrases


def _process_message(message):
    """
    Parses through the message to send it to the correct submodule.

    Args:
        message
    """

    if state.interactive_lock:
        send_message(message)


def signal_handler(sig, frame):
    """
    Enables a clean shutdown for all registered modules
    """
    debug("Received " + sig + frame + ", shutting down.")
    print('\nShutting down...')
    sys.exit(0)


def error(output):
    """
    See warn()!
    """
    debug("Error! " + output)


def warn(output):
    """
    There should be a full-featured debugging module in the future.
    This is merely a placeholder for that later.
    """
    debug("Warning! " + output)


def debug(output):
    """
    Prints debug to STDOUT for now. This will likely integrate with the
    beetlejuice module in the future.
    """
    if state.debug:
        print(output)


@app.route("/is_up", methods=['POST'])
def is_up():
    """
    This is intended to let modules know definitively when this module is ready
    to accept registration requests.

    Returns a JSON paylod containing '{'result': True}'
    """
    if not request.json:
        abort(400)
    return jsonify({'result': True})


@app.route("/enable_interactive", methods=['POST'])
def interactive_lock():
    """
    This locks the interactive_lock to the module specified in the POST's
    'sender' field. That will typically also be the module sending
    the rerquest.

    Args:
        locker
        sender
    """
    if not request.json:
        abort(400)
    body = json.loads(request.json)
    if state.is_unlocked():
        state.lock(body.locker)
        debug("Module " +
              body.sender +
              "has requested interactive lock for " +
              body.locker)
        return jsonify({'result': True})
    warn("Module " +
         body.sender +
         "has requested interactive lock for " +
         body.locker +
         ", but " +
         state.locking_module +
         " has already taken a lock!")
    return jsonify({'result': False})


@app.route("/disable_interactive", methods=['POST'])
def remove_lock():
    """
    Modules must make this API call when they are finished interacting so
    that other modules begin receiving messages. It will always return
    {'result': True}.

    Args:
        sender
    """
    required_args = ["sender"]
    if not request.json:
        abort(400)
    body = json.loads(request.json)
    if not all(x in required_args for x in body):
        """Make sure all the required args have been provided"""
        abort(400)
    was_locked = state.unlock()
    if not was_locked:
        debug(
            "Interactive mode was already unlocked, but" +
            body.sender +
            " tried to unlock it again.")
    return jsonify({'result': True})


@app.route("/register_phrase", methods=['POST'])
def register_keyword():
    """
    This this function passes the request off to the state's internal
    keyword array for matching later. Always returns {'result': True}

    Args:
        sender
        phrase
    """
    if not request.json:
        abort(400)
    body = json.loads(request.json)
    if not body.phrase:
        abort(400)
    state.add_keyword(body.sender, body.phrase)
    return jsonify({'result': True})


@app.route("/request_from", methods=['POST'])
def request_from():
    """
    This function allows modules to request data from other modules
    without being networked to them in the docker-compose configuration.

    Args:
        sender
        module
        func_name
        payload
    """
    if not request.json:
        abort(400)
    body = json.loads(request.json)
    url = "{}:5000/{}".format(body.module, body.func_name)
    data = body.payload
    try:
        r = requests.post(url=url, data=data)
        return r.json()
    except requests.exceptions.RequestException as e:
        error("Cross-call error: " + str(e))
        return jsonify({'result': False,
                        'error': True})


@app.route("/get_message", methods=['POST'])
def accept_message():
    """
    This is the function that accepts messages from Plugs and filters them
    down to the correct modules.

    Args:
        sender
        people
        message
        timestamp
    """
    if not request.json:
        abort(400)
    body = json.loads(request.json)
    thread = threading.Thread(target=_process_message(body), args=())
    thread.daemon = True
    thread.start()
    return jsonify({'result': True})


@app.route("/post_message", methods=['POST'])
def send_message(message=None):
    """
    Standardized function is used both for sending
    chat messages between modules

    Args:
        message
    """
    if message is None:
        if not request.json:
            abort(400)
        message = json.loads(request.json)

    data = {'text': message.text,
            'sender': message.sender}
    url = "{}/get_message".format(message.dest)
    try:
        r = requests.post(url=url, data=data)
        return r.json()
    except requests.exceptions.RequestException as e:
        error("Something happened sending a message to " +
              message.dest +
              ", see error: " +
              str(e))


if __name__ == "__main__":
    state = State()
    signal.signal(signal.SIGINT, signal_handler)
    app.run(threaded=True, host='0.0.0.0')
