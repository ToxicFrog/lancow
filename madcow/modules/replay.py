"""Replay missing logs"""

import re
import random
import math
from madcow.util import Module
from madcow.util.color import ColorLib

class Main(Module):

    _regex = u'^\s*(replay|tell me what I missed)\.?\s*$'
    #_regex = u'^\s*replay\s*$'
    pattern = re.compile(_regex, re.I)
    allow_threading = False
    require_addressing = True
    help = u'replay - replay all conversation since you last left the channel'

    def __init__(self, madcow=None):
        if madcow is not None:
            self.colorlib = madcow.colorlib
            self.madcow = madcow
        else:
            self.colorlib = ColorLib(u'ansi')

    def colour(self, text, color):
        return self.colorlib.get_color(color, text=text)
    
    def response(self, nick, args, kwargs):
        return "I don't know how to do that...yet."
