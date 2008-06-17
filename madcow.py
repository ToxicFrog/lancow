#!/usr/bin/env python

"""Madcow infobot"""

import sys
import os
from ConfigParser import ConfigParser
from optparse import OptionParser
import re
from time import sleep, strftime, time as unix_time
import logging as log
from include.authlib import AuthLib
from include.utils import Error
import SocketServer
from select import select
from signal import signal, SIGHUP, SIGTERM
import shutil
from threading import Thread, RLock
from Queue import Queue, Empty
from types import StringTypes, StringType

# STATIC VARIABLES
__version__ = '1.3.2'
__author__ = 'cj_ <cjones@gruntle.org>'
__copyright__ = 'Copyright (C) 2007-2008 Christopher Jones'
__license__ = 'GPL'
__url__ = 'http://madcow.sourceforge.net/'
__all__ = ['Request', 'Madcow', 'Config']
__logformat__ = '[%(asctime)s] %(levelname)s: %(message)s'
__loglevel__ = log.WARN
__charset__ = 'latin1'
__config__ = 'madcow.ini'

class Madcow:
    """Core bot handler, subclassed by protocols"""

    _delim = re.compile(r'\s*[,;]\s*')
    _codecs = ('ascii', 'utf8', 'latin1')
    _botname = 'madcow'
    re_cor1 = None
    re_addrend = None
    re_feedback = None
    re_cor2 = None
    re_addrpre = None

    ### INITIALIZATION FUNCTIONS ###

    def __init__(self, config, prefix):
        """Initialize bot"""
        self.config = config
        self.prefix = prefix
        self.cached_nick = None
        self.namespace = self.config.modules.dbnamespace
        self.running = False

        # parse ignore list
        if self.config.main.ignorelist is not None:
            self.ignore_list = self.config.main.ignorelist
            self.ignore_list = self._delim.split(self.ignore_list)
            self.ignore_list = [nick.lower() for nick in self.ignore_list]
            log.info('Ignoring nicks: %s' % ', '.join(self.ignore_list))
        else:
            self.ignore_list = []

        # create admin instance
        self.admin = Admin(self)

        # set encoding
        if self.config.main.charset:
            self.charset = self.config.main.charset
        else:
            self.charset = __charset__

        # load modules
        self.modules = Modules(self, 'modules', self.prefix)
        self.periodics = Modules(self, 'periodic', self.prefix)
        self.usage_lines = self.modules.help + self.periodics.help
        self.usage_lines.append('help - this screen')
        self.usage_lines.append('version - get bot version')

        # signal handlers
        signal(SIGHUP, self.signal_handler)
        signal(SIGTERM, self.signal_handler)

        # initialize threads
        self.request_queue = Queue()
        self.response_queue = Queue()
        self.lock = RLock()

    def start(self):
        """Start the bot"""
        self.running = True

        # start services
        for service in Service.__subclasses__():
            log.info('starting service: %s' % service.__name__)
            thread = service(self)
            thread.setDaemon(True)
            thread.start()

        # start worker threads
        for i in range(0, self.config.main.workers):
            name = 'ModuleWorker' + str(i + 1)
            thread = Thread(target=self.request_handler, name=name)
            thread.setDaemon(True)
            thread.start()

        self.run()

    def run(self):
        """Runs madcow loop"""
        print 'no protocol implemented'
        while self.running:
            # this is where you do actual stuff
            sleep(1)

    def signal_handler(self, sig, *args):
        """Handles signals"""
        if sig == SIGTERM:
            log.warn('got SIGTERM, signaling shutting down')
            self.running = False
        elif sig == SIGHUP:
            self.reload_modules()

    def reload_modules(self):
        """Reload all modules"""
        log.info('reloading modules')
        self.modules.load_modules()
        self.periodics.load_modules()

    ### OUTPUT FUNCTIONS

    def output(self, message, req=None):
        """Add response to output queue"""
        self.response_queue.put((message, req))

    def check_response_queue(self):
        """Check if there's any message in response queue and process"""
        try:
            response, req = self.response_queue.get_nowait()
        except Empty:
            return
        except Exception, exc:
            log.exception(exc)
            return
        self.handle_response(response, req)
        self.response_queue.task_done()

    def handle_response(self, response, req=None):
        """encode output, lock threads, and call protocol_output"""
        response = self.encode(response)
        try:
            self.lock.acquire()
            try:
                self.protocol_output(response, req)
            except Exception, exc:
                log.error('error in output: %s' % repr(response))
                log.exception(exc)
        finally:
            self.lock.release()

    def encode(self, text):
        """Force output to the bots encoding if possible"""
        if isinstance(text, StringTypes):
            for charset in self._codecs:
                try:
                    text = unicode(text, charset)
                    break
                except:
                    pass

            if isinstance(text, StringType):
                text = unicode(text, 'ascii', 'replace')
        try:
            text = text.encode(self.charset)
        except:
            text = text.encode('ascii', 'replace')
        return text

    def protocol_output(self, message, req=None):
        """Override with protocol-specific output method"""
        print message

    ### MODULE PROCESSING ###

    def request_handler(self):
        """Dispatcher for workers"""
        while self.running:
            request = self.request_queue.get()
            try:
                self.process_module_item(request)
            finally:
                self.request_queue.task_done()

    def process_module_item(self, request):
        """Run module response method and output any response"""
        obj, nick, args, kwargs = request
        try:
            response = obj.response(nick, args, kwargs)
        except Exception, exc:
            log.warn('Uncaught module exception')
            log.exception(exc)
            return

        if response is not None and len(response) > 0:
            self.output(response, kwargs['req'])

    ### INPUT FROM USER ###

    def check_addressing(self, req):
        """Is bot being addressed?"""
        nick = re.escape(self.botname())

        # recompile nick-based regex if it changes
        if nick != self.cached_nick:
            self.cached_nick = nick
            self.re_cor1 = re.compile(r'^\s*no[ ,]+%s[ ,:-]+\s*(.+)$' % nick,
                    re.I)
            self.re_cor2 = re.compile(r'^\s*no[ ,]+(.+)$', re.I)
            self.re_feedback = re.compile(r'^\s*%s[ !]*\?[ !]*$' % nick, re.I)
            self.re_addrend = re.compile(r'^(.+),\s+%s\W*$' % nick, re.I)
            self.re_addrpre = re.compile(r'^\s*%s[-,: ]+(.+)$' % nick, re.I)

        if self.re_feedback.search(req.message):
            req.feedback = req.addressed = True

        try:
            req.message = self.re_addrend.search(req.message).group(1)
            req.addressed = True
        except:
            pass

        try:
            req.message = self.re_addrpre.search(req.message).group(1)
            req.addressed = True
        except:
            pass

        try:
            req.message = self.re_cor1.search(req.message).group(1)
            req.correction = req.addressed = True
        except:
            pass

        if req.addressed:
            try:
                req.message = self.re_cor2.search(req.message).group(1)
                req.correction = True
            except:
                pass

    def process_message(self, req):
        """Process requests"""
        if 'NOBOT' in req.message:
            return
        if self.config.main.logpublic and not req.private:
            self.logpublic(req)
        if req.nick.lower() in self.ignore_list:
            log.info('Ignored "%s" from %s' % (req.message, req.nick))
            return
        if req.feedback:
            self.output('yes?', req)
            return
        if req.addressed and req.message.lower() == 'help':
            self.output(self.usage(), req)
            return
        if req.addressed and req.message.lower() == 'version':
            res = 'madcow %s by %s: %s' % (__version__, __author__, __url__)
            self.output(res, req)
            return
        if req.private:
            response = self.admin.parse(req)
            if response is not None and len(response):
                self.output(response, req)
                return
        if self.config.main.module == 'cli' and req.message == 'reload':
            self.reload_modules()
        for mod_name, obj in self.modules.by_priority():
            log.debug('trying: %s' % mod_name)

            if obj.require_addressing and not req.addressed:
                continue

            try:
                args = obj.pattern.search(req.message).groups()
            except:
                continue

            req.matched = True # module can set this to false to avoid term

            # see if we can filter some of this information..
            kwargs = {'req': req}
            kwargs.update(req.__dict__)
            request = (obj, req.nick, args, kwargs,)

            if self.config.main.module == 'cli' or not obj.allow_threading:
                log.debug('running non-threaded code for module %s' % mod_name)
                self.process_module_item(request)
            else:
                log.debug('launching thread for module: %s' % mod_name)
                self.request_queue.put(request)

            if obj.terminate and req.matched:
                log.debug('terminating because %s matched' % mod_name)
                break

    def logpublic(self, req):
        """Logs public chatter"""
        line = '%s <%s> %s\n' % (strftime('%T'), req.nick, req.message)
        path = os.path.join(
            self.prefix, 'logs',
            '%s-irc-%s-%s' % (self.namespace, req.channel, strftime('%F'))
        )

        logfile = open(path, 'a')
        try:
            logfile.write(line)
        finally:
            logfile.close()

    ### MISC FUNCTIONS ###

    def usage(self):
        """Returns help data as a string"""
        return '\n'.join(sorted(self.usage_lines))

    def stop(self):
        """Stop the bot"""
        self.running = False

    def botname(self):
        """Should return the real name of the bot"""
        return self._botname


class Service(Thread):
    """Service object"""

    def __init__(self, bot):
        self.bot = bot
        Thread.__init__(self, name=self.__class__.__name__)


class GatewayService(Service):
    """Gateway service spawns TCP socket and listens for requests"""

    def run(self):
        """While bot is alive, listen for connections"""
        addr = (self.bot.config.gateway.bind, self.bot.config.gateway.port)
        server = SocketServer.ThreadingTCPServer(addr, ServiceHandler)
        server.daemon_threads = True
        server.bot = self.bot
        while self.bot.running:
            if select([server.socket], [], [], 0.25)[0]:
                server.handle_request()


class ServiceHandler(SocketServer.BaseRequestHandler):
    """This class handles the listener service for message injection"""

    # pre-compiled regex
    re_payload = re.compile(r'^\s*(from|to|message)\s*:\s*(.+?)\s*$', re.I)

    def setup(self):
        """Called when a connection is created"""
        log.info('connection from %s' % repr(self.client_address))

    def handle(self):
        """Handles a TCP connection to gateway service"""
        data = ''
        while self.server.bot.running:
            read = self.request.recv(1024)
            if len(read) == 0:
                break
            data += read
        log.debug('got payload: %s' % repr(data))

        payload = {}
        for line in data.splitlines():
            try:
                key, val = self.re_payload.search(line).groups()
            except:
                continue
            payload[key.lower()] = val

        if len(payload) != 3:
            log.warn('invalid payload')
            return

        # see if we can reverse lookup sender
        modules = self.server.bot.modules.dict()
        dbm = modules['learn'].get_db('email')
        for user, email in dbm.items():
            if payload['from'] == email:
                payload['from'] = user
                break

        output = 'message from %s: %s' % (payload['from'], payload['message'])
        req = Request(output)
        req.colorize = False
        req.sendto = payload['to']
        self.server.bot.output(output, req)

    def finish(self):
        """Called when connection closes"""
        log.info('connection closed by %s' % repr(self.client_address))
        

class PeriodicEvents(Service):
    """Class to manage modules which are periodically executed"""
    _re_delim = re.compile(r'\s*[,;]\s*')
    _ignore_modules = ['__init__', 'template']
    _process_frequency = 1
    last_run = {}

    def run(self):
        """While bot is alive, process periodic event queue"""
        self.last_run = dict.fromkeys(self.bot.periodics.dict().keys(),
                unix_time())
        while self.bot.running:
            self.process_queue()
            sleep(self._process_frequency)

    def process_queue(self):
        """Process queue"""
        now = unix_time()
        for mod_name, obj in self.bot.periodics.dict().items():
            if (now - self.last_run[mod_name]) < obj.frequency:
                continue
            self.last_run[mod_name] = now
            req = Request(None)
            req.sendto = obj.output
            request = (obj, None, None, {'req': req})
            self.bot.request_queue.put(request)


class FileNotFound(Error):
    """Raised when a file is not found"""


class ConfigError(Error):
    """Raised when a required config option is missing"""


class Request:
    """Generic object passed in from protocol handlers for processing"""

    def __init__(self, message):
        self.message = message
        self.sendto = None
        self.private = False
        self.nick = None
        self.matched = False
        self.feedback = False
        self.correction = False
        self.colorize = False
        self.channel = None
        self.addressed = False


class User:
    """This class represents a logged in user"""

    def __init__(self, user, flags):
        self.user = user
        self.flags = flags

    def is_asmin(self):
        """Boolean: user is an admin"""
        return 'a' in self.flags

    def is_registered(self):
        """Boolean: user is registerd"""
        if 'a' in self.flags or 'r' in self.flags:
            return True
        else:
            return False


class Admin:
    """Class to handle admin interface"""

    _reAdminCommand = re.compile(r'^\s*admin\s+(.+?)\s*$', re.I)
    _reRegister = re.compile('^\s*register\s+(\S+)\s*$', re.I)
    _reAuth = re.compile('^\s*(?:log[io]n|auth)\s+(\S+)\s*$', re.I)
    _reFist = re.compile('^\s*fist\s+(\S+)\s+(.+)$', re.I)
    _reHelp = re.compile('^\s*help\s*$', re.I)
    _reLogout = re.compile('^\s*log(?:out|off)\s*$', re.I)
    _reDelUser = re.compile(r'\s*del(?:ete)?\s+(\S+)\s*$', re.I)
    _reListUsers = re.compile(r'\s*list\s+users\s*$', re.I)
    _reChFlag = re.compile(r'\s*chflag\s+(\S+)\s+(\S+)\s*$', re.I)
    _reAddUser = re.compile(r'^\s*add\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s*$', re.I)

    _basic_usage = [
        'help - this screen',
        'register <pass> - register with bot',
        'login <pass> - login to bot',
    ]

    _loggedin_usage = [
        'logout - log out of bot',
    ]

    _admin_usage = [
        'fist <chan> <msg> - make bot say something in channel',
        'add <user> <flags> [pass] - add a user (no pass = no login)',
        'del <user> - delete a user',
        'list users - list users :P',
        'chflag <user> <[+-][aor]> - update user flags',
    ]

    def __init__(self, bot):
        self.bot = bot
        self.authlib = AuthLib('%s/data/db-%s-passwd' % (bot.prefix,
            bot.namespace))
        self.users = {}

    def parse(self, req):
        """Parse request for admin commands and execute, returns output"""
        if not self.bot.config.admin.enabled:
            return
        try:
            command = self._reAdminCommand.search(req.message).group(1)
        except:
            return
        nick = req.nick.lower()

        # register
        try:
            passwd = self._reRegister.search(command).group(1)
            return self.register_user(nick, passwd)
        except:
            pass

        # log in
        try:
            passwd = self._reAuth.search(command).group(1)
            return self.authuser(nick, passwd)
        except:
            pass

        # help
        usage = []
        usage += self._basic_usage
        if nick in self.users:
            usage += self._loggedin_usage
            if self.users[nick].is_asmin():
                usage += self._admin_usage
        if self._reHelp.search(command):
            return '\n'.join(usage)

        # don't pass this point unless we are logged in
        try:
            user = self.users[nick]
        except:
            return

        # logout
        if Admin._reLogout.search(command):
            del self.users[nick]
            return 'You are now logged out.'

        # functions past here require admin
        if not user.is_asmin():
            return

        try:
            adduser, flags, password = self._reAddUser.search(command).groups()
            return self.adduser(adduser, flags, password)
        except:
            pass

        # be the puppetmaster
        try:
            channel, message = Admin._reFist.search(command).groups()
            req.sendto = channel
            return message
        except:
            pass

        # delete a user
        try:
            deluser = self._reDelUser.search(command).group(1)
            self.authlib.delete_user(deluser)
            if self.users.has_key(deluser):
                del self.users[deluser]
            return 'User deleted: %s' % deluser
        except:
            pass

        # list users
        try:
            if self._reListUsers.search(command):
                output = []
                passwd = self.authlib.get_passwd()
                for luser, data in passwd.items():
                    flags = []
                    if 'a' in data['flags']:
                        flags.append('admin')
                    if 'r' in data['flags']:
                        flags.append('registered')
                    if 'o' in data['flags']:
                        flags.append('autoop')
                    if self.users.has_key(luser):
                        flags.append('loggedin')
                    flags = ' '.join(flags)
                    output.append('%s: %s' % (luser, flags))
                return '\n'.join(output)
        except:
            pass

        # update user flags
        try:
            chuser, newflags = self._reChFlag.search(command).groups()
            return self.change_flags(chuser, newflags)
        except:
            pass

    def change_flags(self, user, chflags):
        """Change flags for a user"""
        curflags = self.authlib.get_flags(user)
        curflags = set(curflags)
        args = re.split(r'([+-])', chflags)[1:]
        for i in range(0, len(args), 2):
            action, flags = args[i], args[i+1]
            flags = set(flags)
            if action == '-':
                for flag in flags:
                    curflags.discard(flag)
            elif action == '+':
                for flag in flags:
                    curflags.add(flag)
        curflags = ''.join(curflags)
        self.authlib.change_flags(user, curflags)
        if self.users.has_key(user):
            self.users[user].flags = curflags
        return 'flags for %s changed to %s' % (user, curflags)

    def adduser(self, user, flags, password):
        """Add a new user"""
        if self.authlib.user_exists(user):
            return "User already registered."
        flags = ''.join(set(flags))
        self.authlib.add_user(user, password, flags)
        return 'user added: %s' % user

    def register_user(self, user, passwd):
        """Register with the bot"""
        if not self.bot.config.admin.allowRegistration:
            return "Registration is disabled."
        if self.authlib.user_exists(user):
            return "User already registered."
        flags = self.bot.config.admin.defaultFlags
        if not flags:
            flags = 'r'
        flags = set(flags)
        if user.lower() == self.bot.config.main.owner.lower():
            flags.add('a')
        flags = ''.join(flags)
        self.authlib.add_user(user, passwd, flags)
        return "You are now registered, try logging in: login <pass>"

    def authuser(self, user, passwd):
        """Attempt to log in"""
        if not self.authlib.user_exists(user):
            return "You are not registered: try register <password>."
        if not self.authlib.check_user(user, passwd):
            return 'Nice try.. notifying FBI'
        self.users[user] = User(user, self.authlib.get_flags(user))
        return 'You are now logged in. Message me "admin help" for help'


class Modules:
    """This class dynamically loads plugins and instantiates them"""
    _pyext = re.compile(r'\.py$')
    _ignore_mods = ('__init__', 'template')

    def __init__(self, madcow, subdir, prefix):
        self.madcow = madcow
        self.subdir = subdir
        self.mod_dir = os.path.join(prefix, self.subdir)
        self.modules = {}
        self.help = []
        self.load_modules()

    def load_modules(self):
        """Load/reload modules"""
        disabled = list(self._ignore_mods)
        for mod_name, enabled in self.madcow.config.modules.settings.items():
            if not enabled:
                disabled.append(mod_name)
        log.info('reading modules from %s' % self.mod_dir)
        try:
            filenames = os.walk(self.mod_dir).next()[2]
        except Exception, exc:
            log.warn("Couldn't load modules from %s: %s" % (self.mod_dir, exc))
            return
        for filename in filenames:
            if not self._pyext.search(filename):
                continue
            mod_name = self._pyext.sub('', filename)
            if mod_name in disabled:
                log.debug('skipping %s: disabled' % mod_name)
                continue
            if self.modules.has_key(mod_name):
                mod = self.modules[mod_name]['mod']
                try:
                    reload(mod)
                    log.debug('reloaded module %s' % mod_name)
                except Exception, exc:
                    log.warn("couldn't reload %s: %s" % (mod_name, exc))
                    del self.modules[mod_name]
                    continue
            else:
                try:
                    mod = __import__(
                        '%s.%s' % (self.subdir, mod_name),
                        globals(),
                        locals(),
                        ['Main'],
                    )
                except Exception, exc:
                    log.warn("couldn't load module %s: %s" % (mod_name, exc))
                    continue
                self.modules[mod_name] = {'mod': mod}
            try:
                obj = getattr(mod, 'Main')(self.madcow)
            except Exception, exc:
                log.warn("failure loading %s: %s" % (mod_name, exc))
                del self.modules[mod_name]
                continue
            if not obj.enabled:
                log.debug("skipped loading %s: disabled" % mod_name)
                del self.modules[mod_name]
                continue
            try:
                if obj.help:
                    self.help.append(obj.help)
                else:
                    raise Exception
            except:
                log.debug('no help for module: %s' % mod_name)
            self.modules[mod_name]['obj'] = obj
            log.debug('loaded module: %s' % mod_name)

        # if debug level set, show execution order/details of modules
        if log.root.level <= log.DEBUG:
            try:
                for mod_name, obj in self.by_priority():
                    try:
                        log.debug('%-13s: pri=%3s thread=%-5s stop=%s' % (
                            mod_name, obj.priority, obj.allow_threading,
                            obj.terminate))
                    except:
                        pass
            except:
                pass

    def by_priority(self):
        """Return list of tuples for modules, sorted by priority"""
        modules = self.dict()
        modules = sorted(modules.items(), lambda x, y: cmp(x[1].priority,
            y[1].priority))
        return modules

    def dict(self):
        """Return dict of modules"""
        modules = {}
        for mod_name, mod_data in self.modules.items():
            modules[mod_name] = mod_data['obj']
        return modules

    def __iter__(self):
        return self.dict().iteritems()


class Config:
    """Config class that allows dot-notation namespace addressing"""

    class ConfigSection:
        _isint = re.compile(r'^-?[0-9]+$')
        _isfloat = re.compile(r'^-?\d+\.\d+$')
        _istrue = re.compile('^(?:true|yes|on|1)$', re.I)
        _isfalse = re.compile('^(?:false|no|off|0)$', re.I)

        def __init__(self, settings, name):
            self.name = name
            self.settings = {}
            for key, val in settings:
                if self._isint.search(val):
                    val = int(val)
                elif self._isfloat.search(val):
                    val = float(val)
                elif self._istrue.search(val):
                    val = True
                elif self._isfalse.search(val):
                    val = False
                self.settings[key.lower()] = val

        def __getattr__(self, attr):
            attr = attr.lower()
            if self.settings.has_key(attr):
                return self.settings[attr]
            else:
                raise ConfigError, 'missing setting %s in section %s' % (
                        attr, self.name)


    def __init__(self, filename):
        if not os.path.exists(filename):
            raise FileNotFound, filename
        parser = ConfigParser()
        parser.read(filename)
        self.sections = {}
        for name in parser.sections():
            self.sections[name] = self.ConfigSection(parser.items(name), name)

    def __getattr__(self, attr):
        attr = attr.lower()
        if self.sections.has_key(attr):
            return self.sections[attr]
        else:
            raise ConfigError, "missing section: %s" % attr


def detach():
    """Daemonize on POSIX system"""
    if os.name != 'posix':
        return
    stop_logging('StreamHandler') # kind of pointless if we're daemonized
    if os.fork() != 0:
        sys.exit(0)
    os.setsid()
    if os.fork() != 0:
        sys.exit(0)
    for stream in sys.stdout, sys.stderr:
        stream.flush()
    stdin = file('/dev/null', 'r')
    stdout = file('/dev/null', 'a+')
    stderr = file('/dev/null', 'a+', 0)
    os.dup2(stdin.fileno(), sys.stdin.fileno())
    os.dup2(stdout.fileno(), sys.stdout.fileno())
    os.dup2(stderr.fileno(), sys.stderr.fileno())
    log.info('madcow is launched as a daemon')

def stop_logging(handler_name):
    """
    Stops a specified logging handler by name (e.g. StreamHandler), why
    there's no way to do this in the logging class I do not know.
    """
    logger = log.getLogger('')
    for handler in logger.handlers:
        if handler.__class__.__name__ == handler_name:
            handler.flush()
            handler.close()
            logger.removeHandler(handler)
    log.info('stopped logging to console')

def main():
    """Entry point to set up bot and run it"""

    # where we are being run from
    prefix = os.path.abspath(os.path.dirname(sys.argv[0]))
    sys.path.append(prefix)
    default_config = os.path.join(prefix, __config__)

    # make sure proper subdirs exist
    datadir = os.path.join(prefix, 'data')
    if not os.path.exists(datadir):
        os.mkdir(datadir)
    logdir = os.path.join(prefix, 'logs')
    if not os.path.exists(logdir):
        os.mkdir(logdir)

    # parse commandline options
    parser = OptionParser(version=__version__)
    parser.add_option('-c', '--config', default=default_config,
            help='default: %default', metavar='FILE')
    parser.add_option('-d', '--detach', action='store_true', default=False,
            help='detach when run')
    parser.add_option('-p', '--protocol',
            help='force the use of this output protocol')
    parser.add_option('-D', '--debug', dest='loglevel', action='store_const',
            const=log.DEBUG,help='turn on debugging output')
    parser.add_option('-v', '--verbose', dest='loglevel', action='store_const',
            const=log.INFO, help='increase logging output')
    parser.add_option('-q', '--quiet', dest='loglevel', action='store_const',
            const=log.WARN, help='only show errors')
    parser.add_option('-P', '--pidfile', metavar='<file>',
            help='override pidfile')
    opts = parser.parse_args()[0]

    # read config file
    if not os.path.exists(opts.config):
        if opts.config == default_config:
            shutil.copyfile(default_config + '-sample', opts.config)
            err = 'created config %s - edit and rerun' % __config__
            print >> sys.stderr, err
        else:
            print >> sys.stderr, 'config not found: %s' % opts.config
        return 1

    try:
        config = Config(opts.config)
    except FileNotFound:
        sys.stderr.write('config file not found, see README\n')
        return 1
    except Exception, exc:
        sys.stderr.write('error parsing config: %s\n' % exc)
        return 1

    # init log facility
    try:
        loglevel = getattr(log, config.main.loglevel)
    except:
        loglevel = __loglevel__
    if opts.loglevel is not None:
        loglevel = opts.loglevel
    log.basicConfig(level=loglevel, format=__logformat__)

    # if specified, log to file as well
    try:
        logfile = config.main.logfile
        if logfile is not None and len(logfile):
            handler = log.FileHandler(filename=logfile)
            handler.setLevel(opts.loglevel)
            formatter = log.Formatter(__logformat__)
            handler.setFormatter(formatter)
            log.getLogger('').addHandler(handler)
    except Exception, exc:
        log.warn('unable to log to file: %s' % exc)
        log.exception(exc)

    # load specified protocol
    if opts.protocol:
        protocol = opts.protocol
        config.main.module = protocol
    else:
        protocol = config.main.module

    # daemonize if requested
    if config.main.detach or opts.detach:
        detach()
    
    # determine pidfile to use (commandline overrides config)
    if opts.pidfile:
        pidfile = opts.pidfile
    else:
        pidfile = config.main.pidfile

    # write pidfile
    if pidfile:
        if os.path.exists(pidfile):
            log.warn('removing stale pidfile: %s' % pidfile)
            os.remove(pidfile)
        try:
            pid_fo = open(pidfile, 'wb')
            try:
                pid_fo.write(str(os.getpid()))
            finally:
                pid_fo.close()
        except Exception, exc:
            log.warn('filed to write %s: %s' % pidfile)
            log.exception(exc)

    # run bot
    try:
        bot = __import__('protocols.' + protocol, (), (), ['ProtocolHandler'])
        bot = getattr(bot, 'ProtocolHandler')(config, prefix)
        bot.start()
    finally:
        if pidfile and os.path.exists(pidfile):
            log.info('removing pidfile')
            try:
                os.remove(pidfile)
            except Exception, exc:
                log.warn('failed to remove pidfile %s' % pidfile)
                log.exception(exc)
        bot.stop()

    log.info('madcow is exiting cleanly')
    return 0

if __name__ == '__main__':
    sys.exit(main())
