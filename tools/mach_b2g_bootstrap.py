# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import print_function, unicode_literals

import imp
import os
import platform
import subprocess
import sys
import time


STATE_DIR_FIRST_RUN = '''
mach and the build system store shared state in a common directory on the
filesystem. The following directory will be created:

  {userdir}

If you would like to use a different directory, hit CTRL+c and set the
MOZBUILD_STATE_PATH environment variable to the directory you would like to
use and re-run mach. For this change to take effect forever, you'll likely
want to export this environment variable from your shell's init scripts.
'''.lstrip()

MACH_NOT_FOUND = '''
The mach module could not be found on your system. Either configure the B2G
repo, so the copy in gecko can be used, or install it from the Python package
index.

To install mach from pypi, run:

    $ sudo apt-get install python-pip
    $ pip install mach
'''.lstrip()

# TODO Bug 794506 Integrate with the in-tree virtualenv configuration.
SEARCH_PATHS = [
    'python/mach',
]

# Individual files providing mach commands.
MACH_MODULES = [
    'python/mach/mach/commands/commandinfo.py',
]

CATEGORIES = {
    'build': {
        'short': 'Build Commands',
        'long': 'Interact with the build system',
        'priority': 80,
    },
    'post-build': {
        'short': 'Post-build Commands',
        'long': 'Common actions performed after completing a build.',
        'priority': 70,
    },
    'testing': {
        'short': 'Testing',
        'long': 'Run tests.',
        'priority': 60,
    },
    'devenv': {
        'short': 'Development Environment',
        'long': 'Set up and configure your development environment.',
        'priority': 50,
    },
    'build-dev': {
        'short': 'Low-level Build System Interaction',
        'long': 'Interact with specific parts of the build system.',
        'priority': 20,
    },
    'misc': {
        'short': 'Potpourri',
        'long': 'Potent potables and assorted snacks.',
        'priority': 10,
    }
}

def _find_xulrunner_sdk(gaia_dir):
    # TODO This should use the XULRUNNER_DIRECTORY variable in the gaia
    # Makefile, but there is currently no easy way to extract it.
    xulrunner_sdks = [d for d in os.listdir(gaia_dir)
                      if d.startswith('xulrunner-sdk')]
    if not xulrunner_sdks:
        raise Exception("Could not find a copy of the xulrunner-sdk. " + \
                        "Run 'make' in your gaia profile")

    # Use the most recent xulrunner sdk found
    sdk = sorted(xulrunner_sdks,
                 key=lambda x: int(x[len(x.rstrip('0123456789')):] or 0),
                 reverse=True)[0]
    return os.path.join(gaia_dir, sdk)

def bootstrap(b2g_home):
    # Ensure we are running Python 2.7+. We put this check here so we generate a
    # user-friendly error message rather than a cryptic stack trace on module
    # import.
    if sys.version_info[0] != 2 or sys.version_info[1] < 7:
        print('Python 2.7 or above (but not Python 3) is required to run mach.')
        print('You are running Python', platform.python_version())
        sys.exit(1)

    # Global build system and mach state is stored in a central directory. By
    # default, this is ~/.mozbuild. However, it can be defined via an
    # environment variable. We detect first run (by lack of this directory
    # existing) and notify the user that it will be created. The logic for
    # creation is much simpler for the "advanced" environment variable use
    # case. For default behavior, we educate users and give them an opportunity
    # to react. We always exit after creating the directory because users don't
    # like surprises.
    state_user_dir = os.path.expanduser('~/.mozbuild')
    state_env_dir = os.environ.get('MOZBUILD_STATE_PATH', None)
    if state_env_dir:
        if not os.path.exists(state_env_dir):
            print('Creating global state directory from environment variable: %s'
                % state_env_dir)
            os.makedirs(state_env_dir, mode=0o770)
            print('Please re-run mach.')
            sys.exit(1)
        state_dir = state_env_dir
    else:
        if not os.path.exists(state_user_dir):
            print(STATE_DIR_FIRST_RUN.format(userdir=state_user_dir))
            try:
                for i in range(20, -1, -1):
                    time.sleep(1)
                    sys.stdout.write('%d ' % i)
                    sys.stdout.flush()
            except KeyboardInterrupt:
                sys.exit(1)

            print('\nCreating default state directory: %s' % state_user_dir)
            os.mkdir(state_user_dir)
            print('Please re-run mach.')
            sys.exit(1)
        state_dir = state_user_dir

    # If a gecko source tree is detected, its mach modules are are also
    # loaded.
    gecko_dir = os.environ.get('GECKO_PATH', os.path.join(b2g_home, 'gecko'))
    gecko_bootstrap_dir = os.path.join(gecko_dir, 'build')
    if os.path.isdir(gecko_bootstrap_dir):
        path = os.path.join(gecko_bootstrap_dir, 'mach_bootstrap.py')
        with open(path, 'r') as fh:
            imp.load_module('mach_bootstrap', fh, path,
                ('.py', 'r', imp.PY_SOURCE))

        import mach_bootstrap

        global SEARCH_PATHS
        global MACH_MODULES
        relpath = os.path.relpath(gecko_dir)
        SEARCH_PATHS += [os.path.join(relpath, p)
                            for p in mach_bootstrap.SEARCH_PATHS]
        MACH_MODULES += [os.path.join(relpath, p)
                            for p in mach_bootstrap.MACH_MODULES]

    try:
        import mach.main
    except ImportError:
        sys.path[0:0] = [os.path.join(b2g_home, path) for path in SEARCH_PATHS]
        try:
            import mach.main
        except ImportError:
            print(MACH_NOT_FOUND)
            sys.exit(1)

    # Load the configuration created by the build system.
    # This is the equivalent of sourcing load-config.sh
    config_paths = [os.path.join(b2g_home, '.config'),
                    os.path.join(b2g_home, '.userconfig'),]
    for config_path in config_paths:
        if os.path.isfile(config_path):
            with open(config_path, 'r') as fh:
                for line in fh.readlines():
                    key, value = line.split('=', 1)
                    os.environ[key] = value
    # The build system doesn't provide a mechanism to use
    # a different mozconfig.
    os.environ['MOZCONFIG'] = os.path.join(b2g_home, 'gonk-misc',
                                           'default-gecko-config')

    xre_path = None
    gaia_dir = os.path.join(b2g_home, 'gaia')
    if os.path.isdir(gaia_dir):
        xre_path = os.path.join(_find_xulrunner_sdk(gaia_dir), 'bin')
        if sys.platform.startswith('darwin'):
            xre_path = os.path.join(xre_path, 'XUL.framework', 'Versions', 'Current')

    def populate_context(context):
        context.state_dir = state_dir
        context.topdir = gecko_dir
        context.b2g_home = b2g_home
        context.xre_path = xre_path
        # device name is set from load configuration step above
        context.device_name = os.environ.get('DEVICE_NAME', '').rstrip()

    mach = mach.main.Mach(b2g_home)
    mach.populate_context_handler = populate_context
    mach.require_conditions = True

    for category, meta in CATEGORIES.items():
        mach.define_category(category, meta['short'], meta['long'],
            meta['priority'])

    for path in MACH_MODULES:
        module = os.path.join(b2g_home, path)
        if os.path.isfile(module):
            mach.load_commands_from_file(os.path.join(b2g_home, path))

    return mach
