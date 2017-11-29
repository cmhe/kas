# kas - setup tool for bitbake based projects
#
# Copyright (c) Siemens AG, 2017
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
    This module contain common commands used by kas plugins.
"""

import tempfile
import logging
import shutil
import os
from .libkas import (ssh_cleanup_agent, ssh_setup_agent, ssh_no_host_key_check,
                     get_build_environ, repos_fetch, repo_checkout)

__license__ = 'MIT'
__copyright__ = 'Copyright (c) Siemens AG, 2017'


class Macro:
    """
        Contains commands and provide method to run them.
    """
    def __init__(self):
        self.commands = []

    def add(self, command):
        """
            Appends commands to the command list.
        """
        self.commands.append(command)

    def run(self, context, skip=None):
        """
            Runs command from the command list respective to the configuration.
        """
        skip = skip or []
        for command in self.commands:
            command_name = str(command)
            if command_name in skip:
                continue
            logging.debug('execute %s', command_name)
            command.execute(context)


class Command:
    """
        An abstract class that defines the interface of a command.
    """

    def execute(self, context):
        """
            This method executes the command.
        """
        pass


class SetupHome(Command):
    """
        Setups the home directory of kas.
    """

    def __init__(self):
        super().__init__()
        self.tmpdirname = tempfile.mkdtemp()

    def __del__(self):
        shutil.rmtree(self.tmpdirname)

    def __str__(self):
        return 'setup_home'

    def execute(self, context):
        with open(self.tmpdirname + '/.wgetrc', 'w') as fds:
            fds.write('\n')
        with open(self.tmpdirname + '/.netrc', 'w') as fds:
            fds.write('\n')
        context.update_environment({'HOME': self.tmpdirname})


class SetupDir(Command):
    """
        Creates the build directory.
    """

    def __str__(self):
        return 'setup_dir'

    def execute(self, context):
        os.chdir(context.kas_work_dir)
        if not os.path.exists(context.build_dir):
            os.mkdir(context.build_dir)


class SetupSSHAgent(Command):
    """
        Setup the ssh agent configuration.
    """

    def __str__(self):
        return 'setup_ssh_agent'

    def execute(self, context):
        ssh_setup_agent(context)
        ssh_no_host_key_check(context)


class CleanupSSHAgent(Command):
    """
        Remove all the identities and stop the ssh-agent instance.
    """

    def __str__(self):
        return 'cleanup_ssh_agent'

    def execute(self, context):
        ssh_cleanup_agent(context)


class SetupEnviron(Command):
    """
        Setups the kas environment.
    """

    def __str__(self):
        return 'setup_environ'

    def execute(self, context):
        context.set_build_environment(get_build_environ(context,
                                                        context.build_dir))


class WriteConfig(Command):
    """
        Writes bitbake configuration files into the build directory.
    """

    def __str__(self):
        return 'write_config'

    def execute(self, context):
        def _write_bblayers_conf(context):
            filename = context.build_dir + '/conf/bblayers.conf'
            with open(filename, 'w') as fds:
                fds.write(context.get_bblayers_conf_header())
                fds.write('BBLAYERS ?= " \\\n    ')
                fds.write(' \\\n    '.join(
                    sorted(layer for repo in context.get_repos()
                           for layer in repo.layers)))
                fds.write('"\n')

        def _write_local_conf(context):
            filename = context.build_dir + '/conf/local.conf'
            with open(filename, 'w') as fds:
                fds.write(context.get_local_conf_header())
                fds.write('MACHINE ?= "{}"\n'.format(context.get_machine()))
                fds.write('DISTRO ?= "{}"\n'.format(context.get_distro()))
                fds.write('BBMULTICONFIG ?= "{}"\n'.format(
                    context.get_multiconfig()))

        _write_bblayers_conf(context)
        _write_local_conf(context)


class ReposFetch(Command):
    """
        Fetches repositories defined in the configuration
    """

    def __str__(self):
        return 'repos_fetch'

    def execute(self, context):
        repos_fetch(context, context.get_repos())


class ReposCheckout(Command):
    """
        Ensures that the right revision of each repo is check out.
    """

    def __str__(self):
        return 'repos_checkout'

    def execute(self, context):
        for repo in context.get_repos():
            repo_checkout(context, repo)
