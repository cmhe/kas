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
    This module contains the implementation of the kas configuration.
"""

import os
import logging
import pprint

try:
    import distro

    def get_distro_id_base():
        """
            Returns a compatible distro id.
        """
        return distro.like() or distro.id()

except ImportError:
    import platform

    def get_distro_id_base():
        """
            Wrapper around platform.dist to simulate distro.id
            platform.dist is deprecated and will be removed in python 3.7
            Use the 'distro' package instead.
        """
        # pylint: disable=deprecated-method
        return platform.dist()[0]

from .repos import Repo
from .libkas import run_cmd, repos_fetch, repo_checkout

__license__ = 'MIT'
__copyright__ = 'Copyright (c) Siemens AG, 2017'

def get_locale_environ():
    """
        Sets the environment variables for process that are
        started by kas.
    """
    distro_base = get_distro_id_base().lower()

    if distro_base in ['fedora', 'suse', 'opensuse']:
        return {'LC_ALL': 'en_US.utf8',
                'LANG': 'en_US.utf8',
                'LANGUAGE': 'en_US'}

    if distro_base in ['debian', 'ubuntu']:
        return {'LC_ALL': 'en_US.UTF-8',
                'LANG': 'en_US.UTF-8',
                'LANGUAGE': 'en_US:en'}

    logging.warning('kas: "%s" is not a supported distro. '
                    'No default locales set.', distro_base)
    return {}

def get_proxy_environ(os_environ):
    return {var_name: os_environ.get[var_name]
            for var_name in os_environ.keys() & set(['http_proxy',
                                                     'https_proxy',
                                                     'ftp_proxy',
                                                     'no_proxy'])}

def get_repo_dict(context):
    """
        Returns a dictionary containing the repositories with
        their name (as it is defined in the config file) as key
        and the `Repo` instances as value.
    """
    repo_config_dict = context.get_repos_raw()
    repo_dict = {}
    for repo in repo_config_dict:

        repo_config_dict[repo] = repo_config_dict[repo] or {}
        layers_dict = repo_config_dict[repo].get('layers', {})
        layers = list(filter(lambda x, laydict=layers_dict:
                             str(laydict[x]).lower() not in
                             ['disabled', 'excluded', 'n', 'no', '0',
                              'false'],
                             layers_dict))
        url = repo_config_dict[repo].get('url', None)
        name = repo_config_dict[repo].get('name', repo)
        refspec = repo_config_dict[repo].get('refspec', None)
        path = repo_config_dict[repo].get('path', None)

        if url is None:
            # No git operation on repository
            if path is None:
                # In-tree configuration
                path = os.path.dirname(self.filename)
                (ret, output) = run_cmd(['git',
                                         'rev-parse',
                                         '--show-toplevel'],
                                        cwd=path,
                                        env=context.get_environment(),
                                        fail=False,
                                        liveupdate=False)
                if ret == 0:
                    path = output.strip()
                logging.info('Using %s as root for repository %s', path,
                             name)

            url = path
            rep = Repo(url=url,
                       path=path,
                       layers=layers)
            rep.disable_git_operations()
        else:
            path = path or os.path.join(context.kas_work_dir, name)
            rep = Repo(url=url,
                       path=path,
                       refspec=refspec,
                       layers=layers)
        repo_dict[repo] = rep
    return repo_dict

def load_configuration_file(context, filepath):
    from .includehandler import GlobalIncludes, IncludeException
    filepath = os.path.abspath(filepath)
    handler = GlobalIncludes(filepath)

    repo_paths = {}
    missing_repo_names_old = []
    (config, missing_repo_names) = \
        handler.get_config(repos=repo_paths)

    while missing_repo_names:
        if missing_repo_names == missing_repo_names_old:
            raise IncludeException('Could not fetch all repos needed by '
                                   'includes.')

        logging.debug('Missing repos for complete config:\n%s',
                      pprint.pformat(missing_repo_names))

        repo_dict = self.get_repo_dict()
        missing_repos = [repo_dict[repo_name]
                         for repo_name in missing_repo_names
                         if repo_name in repo_dict]

        repos_fetch(self, missing_repos)

        for repo in missing_repos:
            repo_checkout(self, repo)

        repo_paths = {r: repo_dict[r].path for r in repo_dict}

        missing_repo_names_old = missing_repo_names
        (self._config, missing_repo_names) = \
            self.handler.get_config(repos=repo_paths)

    logging.debug('Configuration from config file:\n%s',
                  pprint.pformat(self._config))

def create_context(filename, os_environ=None, work_dir='', **qwargs):
    os_environ = os_environ or os.environ
    work_dir = work_dir or os_environ.get('KAS_WORK_DIR', os.getcwd())

    environ = get_locale_environ()
    environ.update(get_proxy_environ(os_environ))

    # Preliminary empty context:
    context = Context(work_dir=work_dir, os_environ=os_environ, environ=environ,
                      config_override=qwargs)

    context = load_configuration_file(context, filename)

class Context:
    """
        Represents the kas application context.
    """
    def __init__(self, work_dir='', os_environ=None, environ=None, config=None,
                 config_override=None):
        self._work_dir = work_dir
        self._os_environ = os_environ or {}
        self._environ = environ or {}

        self._config_override = config_override or {}
        self.set_config(config or {})

    def set_config(self, config):
        self._config = config
        self._config.update(self._config_override)

    @property
    def build_dir(self):
        """
            The path of the build directory.
        """
        return os.path.join(self._work_dir, 'build')

    @property
    def kas_work_dir(self):
        """
            The path to the kas work directory.
        """
        return self._work_dir

    def get_repo_ref_dir(self):
        """
            The path to the directory that contains the repository references.
        """
        # pylint: disable=no-self-use

        return self._os_environ.get('KAS_REPO_REF_DIR', None)

    def get_environment(self):
        """
            Returns the context environment variables from the configuration,
            with possible overwritten values from the shell environment.
        """
        env = self._config.get('env', {})
        env = {var: self._os_environ.get(var, env[var]) for var in env}
        env.update(self._environ)
        return env

    def get_repos_raw(self):
        return self._config.get('repos', {})

    def get_repos(self):
        """
            Returns the list of repos.
        """
        # pylint: disable=no-self-use

        return list(self.get_repo_dict().values())

    def get_bitbake_targets(self):
        """
            Returns a list of bitbake targets
        """
        environ_targets = [i
                           for i in os.environ.get('KAS_TARGET', '').split()
                           if i]
        if environ_targets:
            return environ_targets
        target = self._config.get('target', 'core-image-minimal')
        if isinstance(target, str):
            return [target]
        return target

    def get_bitbake_task(self):
        """
            Return the bitbake task
        """
        return os.environ.get('KAS_TASK',
                              self._config.get('task', 'build'))

    def _get_conf_header(self, header_name):
        """
            Returns the local.conf header
        """
        header = ''
        for key, value in sorted(self._config.get(header_name, {}).items()):
            header += '# {}\n{}\n'.format(key, value)
        return header

    def get_bblayers_conf_header(self):
        """
            Returns the bblayers.conf header
        """
        return self._get_conf_header('bblayers_conf_header')

    def get_local_conf_header(self):
        """
            Returns the local.conf header
        """
        return self._get_conf_header('local_conf_header')

    def get_machine(self):
        """
            Returns the machine
        """
        return os.environ.get('KAS_MACHINE',
                              self._config.get('machine', 'qemu'))

    def get_distro(self):
        """
            Returns the distro
        """
        return os.environ.get('KAS_DISTRO',
                              self._config.get('distro', 'poky'))

    def get_multiconfig(self):
        """
            Returns the multiconfig array as bitbake string
        """
        return ' '.join(set(i.split(':')[1]
                            for i in
                            self.get_bitbake_targets()
                            if i.startswith('multiconfig')))

    def get_gitlabci_config(self):
        """
            Returns the GitlabCI configuration
        """
        return self._config.get('gitlabci_config', '')
