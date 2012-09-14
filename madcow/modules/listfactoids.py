# :tabSize=4:

import itertools
import re
import time
import os
import sys
import traceback
from madcow.util import Module
from madcow.util.text import *

try:
    import dbm
except ImportError:
    import anydbm as dbm

class Main(Module):
    pattern = re.compile(r'^\s*listfactoids\s*(.*)\s*$', re.I)
    require_addressing = True
    priority = 99
    allow_threading = False
    terminate = False
    help = u'listfactoids [pattern] - list all factoid keys. If pattern is specified, list only those for which the key (or value) matches the patternl.'

    def get_dbm(self, dbname):
        dbfile = os.path.join(self.madcow.base, 'db', dbname.lower())
        return dbm.open(dbfile, u'c', 0640)

    def response(self, nick, args, kwargs):
        kwargs[u'req'].sendto = nick
        
        if args[0]:
            pattern = re.compile(args[0])
        else:
            pattern = re.compile('.*')
        
        try:
            is_db = self.get_dbm('is')
            are_db = self.get_dbm('are')
            is_keys = [(key, is_db[key]) for key in is_db]
            are_keys = [(key, are_db[key]) for key in are_db]
            content = [(key,value) for key,value in itertools.chain(is_keys, are_keys)]
        except:
            return u'Sorry, there was an error reading the database (%s)' % traceback.format_exc()
        finally:
            is_db.close()
            are_db.close()

        result = u' \x16|\x16 '.join([key for (key, value) in content])
        return result
