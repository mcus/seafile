#!/usr/bin/env python

import os
import sys
import re
import termcolor
import glob
import logging
from pexpect import spawn
from os.path import abspath, basename, exists, expanduser, join
from contextlib import contextmanager
from subprocess import check_call

TOPDIR = abspath(join(os.getcwd(), '..'))
PREFIX = expanduser('~/opt/local')
SRCDIR = '/tmp/src'
INSTALLDIR = '/tmp/haiwen'
THIRDPARTDIR = expanduser('~/thirdpart')

ADMIN_PASSWORD = 'adminadmin'
ADMIN_USERNAME = 'admin@seafiletest.com'

logger = logging.getLogger(__file__)
seafile_version = ''

def _color(s, color):
    return s if not os.isatty(sys.stdout.fileno()) \
        else termcolor.colored(str(s), color)

def green(s):
    return _color(s, 'green')

def red(s):
    return _color(s, 'red')

def debug(fmt, *a):
    logger.debug(green(fmt), *a)

def info(fmt, *a):
    logger.info(green(fmt), *a)

def warning(fmt, *a):
    logger.warn(red(fmt), *a)

def shell(cmd, **kw):
    kw['shell'] = not isinstance(cmd, list)
    info('calling "%s" in %s', cmd, kw.get('cwd', os.getcwd()))
    check_call(cmd, **kw)

@contextmanager
def cd(path):
    olddir = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(olddir)

def chdir(func):
    def wrapped(self, *w, **kw):
        with cd(self.projectdir):
            return func(self, *w, **kw)
    return wrapped

def make_build_env():
    env = dict(os.environ)
    libsearpc_dir = abspath(join(TOPDIR, 'libsearpc'))
    ccnet_dir = abspath(join(TOPDIR, 'ccnet'))

    def _env_add(*a, **kw):
        kw['env'] = env
        return prepend_env_value(*a, **kw)

    _env_add('CPPFLAGS',
             '-I%s' % join(PREFIX, 'include'),
             seperator=' ')

    _env_add('LDFLAGS',
             '-L%s' % os.path.join(PREFIX, 'lib'),
             seperator=' ')

    _env_add('LDFLAGS',
             '-L%s' % os.path.join(PREFIX, 'lib64'),
             seperator=' ')

    _env_add('PATH', os.path.join(PREFIX, 'bin'))
    _env_add('PATH', THIRDPARTDIR)
    _env_add('PKG_CONFIG_PATH', os.path.join(PREFIX, 'lib', 'pkgconfig'))
    _env_add('PKG_CONFIG_PATH', os.path.join(PREFIX, 'lib64', 'pkgconfig'))
    _env_add('PKG_CONFIG_PATH', libsearpc_dir)
    _env_add('PKG_CONFIG_PATH', ccnet_dir)

    for key in ('PATH', 'PKG_CONFIG_PATH', 'CPPFLAGS', 'LDFLAGS', 'PYTHONPATH'):
        info('%s: %s', key, env.get(key, ''))
    return env

def prepend_env_value(name, value, seperator=':', env=None):
    '''append a new value to a list'''
    env = env or os.environ
    current_value = env.get(name, '')
    new_value = value
    if current_value:
        new_value += seperator + current_value

    env[name] = new_value
    return env

class Project(object):
    configure_cmd = './configure'

    def __init__(self, name):
        self.name = name
        self.version = ''

    @property
    def url(self):
        return 'https://www.github.com/haiwen/{}.git'.format(self.name)

    @property
    def projectdir(self):
        return join(TOPDIR, self.name)

    def clone(self):
        shell('git clone --depth=1 {}'.format(self.url))

    @chdir
    def make_dist(self):
        info('making tarball for %s', self.name)
        if exists('./autogen.sh'):
            shell('./autogen.sh')
            shell(self.configure_cmd, env=make_build_env())
        shell('make dist')

    @chdir
    def copy_dist(self):
        self.make_dist()
        tarball = glob.glob('*.tar.gz')[0]
        info('copying %s to %s', tarball, SRCDIR)
        shell('cp {} {}'.format(tarball, SRCDIR))
        m = re.match(
            '{}-(.*).tar.gz'.format(self.name), basename(tarball))
        if m:
            self.version = m.group(1)

    @chdir
    def use_branch(self, branch):
        shell('git checkout {}'.format(branch))

class Seafile(Project):
    configure_cmd = './configure --disable-fuse --enable-client --enable-server'

    def __init__(self):
        super(Seafile, self).__init__('seafile')

    @chdir
    def copy_dist(self):
        super(Seafile, self).copy_dist()
        global seafile_version
        seafile_version = self.version

class Seahub(Project):
    def __init__(self):
        super(Seahub, self).__init__('seahub')

    @chdir
    def make_dist(self):
        cmds = [
            # 'git add -f media/css/*.css',
            # 'git commit -a -m "%s"' % msg,
            './tools/gen-tarball.py --version={} --branch=HEAD >/dev/null'.format(seafile_version),
        ]
        for cmd in cmds:
            shell(cmd, env=make_build_env())

class SeafDAV(Project):
    def __init__(self):
        super(SeafDAV, self).__init__('seafdav')

    @chdir
    def make_dist(self):
        shell('make')

class SeafObj(Project):
    def __init__(self):
        super(SeafObj, self).__init__('seafobj')

    @chdir
    def make_dist(self):
        shell('make dist')

def build_server(libsearpc, ccnet, seafile):
    cmd = [
        'python',
        join(TOPDIR, 'seafile/scripts/build/build-server.py'),
        '--yes',
        '--version=%s' % seafile.version,
        '--libsearpc_version=%s' % libsearpc.version,
        '--ccnet_version=%s' % ccnet.version,
        '--seafile_version=%s' % seafile.version,
        '--thirdpartdir=%s' % THIRDPARTDIR,
        '--srcdir=%s' % SRCDIR,
    ]
    shell(cmd, shell=False, env=make_build_env())

def fetch_and_build():
    libsearpc = Project('libsearpc')
    ccnet = Project('ccnet')
    seafile = Seafile()
    seahub = Seahub()
    seafobj = SeafObj()
    seafdav = SeafDAV()

    for project in (libsearpc, ccnet, seafile, seahub, seafdav, seafobj):
        if project.name != 'seafile':
            project.clone()
        # TODO: switch to proper branch based on current seafile branch being
        # built
        project.copy_dist()

    build_server(libsearpc, ccnet, seafile)

def setup_server():
    '''Setup seafile server with the setup-seafile.sh script. We use pexpect to
    interactive with the setup process of the script.
    '''
    info('uncompressing server tarball')
    shell('tar xf seafile-server_{}_x86-64.tar.gz -C {}'
          .format(seafile_version, INSTALLDIR))
    setup_script = get_script('setup-seafile.sh')

    info('setting up seafile server with pexepct, script %s', setup_script)
    child = spawn(setup_script)
    def autofill(pattern, line):
        child.expect(pattern)
        child.sendline(line)

    answers = [
        (r'\[ENTER\]', ''),
        # server name
        ('server name', 'my-seafile'),
        # ip or domain
        ('ip or domain', '127.0.0.1'),
        # seafile data dir
        ('seafile-data', ''),
        # fileserver port
        ('seafile fileserver', ''),
        (r'\[ENTER\]', ''),
        (r'\[ENTER\]', ''),
    ]
    for k, v in answers:
        autofill(k, v)
    shell('ls -lht')

def get_script(path):
    return join(INSTALLDIR, 'seafile-server-{}/{}'.format(
        seafile_version, path))

def start_server():
    seafile_sh = get_script('seafile.sh')
    shell('{} start'.format(seafile_sh))

    info('starting seahub')
    seahub_sh = get_script('seahub.sh')
    child = spawn('{} start'.format(abspath(seahub_sh)))
    def autofill(pattern, line):
        child.expect(pattern)
        child.sendline(line)
    answers = [
        # admin email/pass
        ('admin email', ADMIN_USERNAME),
        ('admin password', ADMIN_PASSWORD),
        ('admin password again', ADMIN_PASSWORD),
    ]
    for k, v in answers:
        autofill(k, v)
    child.interact()

def run_tests():
    pass

def setup_logging():
    kw = {
        'format': '[%(asctime)s][%(module)s]: %(message)s',
        'datefmt': '%m/%d/%Y %H:%M:%S',
        'level': logging.DEBUG,
        'stream': sys.stdout,
    }

    logging.basicConfig(**kw)
    logging.getLogger(
        'requests.packages.urllib3.connectionpool').setLevel(logging.WARNING)

def _mkdirs(*paths):
    for path in paths:
        if not exists(path):
            os.mkdir(path)

def main():
    _mkdirs(SRCDIR, INSTALLDIR)
    setup_logging()
    fetch_and_build()
    setup_server()
    start_server()
    run_tests()

if __name__ == '__main__':
    os.chdir(TOPDIR)
    main()
