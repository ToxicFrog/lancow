"""Die roll"""

import re
import random
import math
from madcow.util import Module
from madcow.util.color import ColorLib

class Main(Module):

    _regex = u'^\s*roll\s+(\d*)d(\d+)\s*(?:([-+])(\d+))?\s*$'
    pattern = re.compile(_regex, re.I)
    allow_threading = False
    require_addressing = True
    help = u'roll <dice>d<sides>[+-<modifier>] - roll dice of the specified size'

    def __init__(self, madcow=None):
        if madcow is not None:
            self.colorlib = madcow.colorlib
            self.madcow = madcow
        else:
            self.colorlib = ColorLib(u'ansi')

    def colour(self, text, color):
        return self.colorlib.get_color(color, text=text)
    
    def report(self, rolls):
        rolls = str(rolls)
        
        if len(rolls) > 300:
            return rolls[:300] + "...]"
        
        return rolls
    
    def response(self, nick, args, kwargs):
        dice,sides,sign,mod = args
        
        if dice == "":
            dice = "1"
        
        if int(dice) > 10240:
            return u"Sorry, I don't have that many dice."
        
        rolls = [random.randint(1, int(sides)) for die in range(0, int(dice))]
        total = reduce(lambda x,y: x+y, rolls)
        
        if mod:
            if sign == "+":
                mod = int(mod)
            else:
                mod = -int(mod)
            
            return u'%s: \x02%d\x02  (%sd%s%s%d = %s)' % (nick, total+mod, dice, sides, sign, mod, self.report(rolls))
        else:
            return u'%s: \x02%d\x02  (%sd%s = %s)' % (nick, total, dice, sides, self.report(rolls))
