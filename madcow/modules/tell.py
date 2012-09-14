"""Asynchronous tells for offline people"""
# :tabSize=4:

import re
import time
import os
from madcow.util import Module
from madcow.util.text import *

try:
    import dbm
except ImportError:
    import anydbm as dbm

class Main(Module):

    pattern = Module._any
    priority = 1
    terminate = False
    allow_threading = False
    require_addressing = False
    help = u'pm <nick> <message> - tell someone something when they come online'
    tell = re.compile(u'^\s*(memo|pm)\s+(\S+)\s+(.+)$', re.I)

    def init(self):
        self.dbfile = os.path.join(self.madcow.base, 'db', 'tell')

    def dbm(self):
        return dbm.open(self.dbfile, u'c', 0640)

    def get(self, nick):
        db = self.dbm()
        try:
            nick = encode(nick.lower())
            packed = db[nick]
            packed = decode(packed)

            return packed.strip()
        except:
            return u""
        finally:
            db.close()

    def set(self, nick, message):
        packed = u'%s' % message.strip()
        db = self.dbm()
        try:
            nick = encode(nick.lower())
            packed = encode(packed)
            db[nick] = packed
        finally:
            db.close()
            
    def send_tells(self, nick, req):
        """Send all pending tells for a nick to that person."""
        tells = self.get(nick)
        if tells:
            self.set(nick, u"")
            req.sendto = nick
            return tells
        return u""

    def record(self, nick, user, message):
        tells = self.get(user)
        self.set(user, u"%s\n%s: %s said: %s" % (tells, user, nick, message))

    def response(self, nick, args, kwargs):
        channel = kwargs[u'channel']
        line = args[0]

        reply = self.send_tells(nick, kwargs[u'req'])
        
        match = self.tell.search(line)
        if not match or not kwargs[u'req'].addressed:
            return reply
        
        user = match.group(1)
        message = match.group(2)
        self.record(nick, user, message)
        return (u"%s\n%s" % (u"Ok, I'll tell %s next time they're active." % user, reply)).strip()
