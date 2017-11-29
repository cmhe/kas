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

import logging
import os
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

from .libkas import repo_checkout, repos_fetch, run_cmd
from .repos import Repo

__license__ = 'MIT'
__copyright__ = 'Copyright (c) Siemens AG, 2017'


BB_ENV_EXTRAWHITE_ADDITIONALS = ['SSTATE_DIR', 'DL_DIR', 'TMPDIR']


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
    """
        Extracts the proxy configuration from the os_environment.
    """
    return {var_name: os_environ.get[var_name]
            for var_name in os_environ.keys() &
            set(['http_proxy',
                 'https_proxy',
                 'ftp_proxy',
                 'no_proxy',
                 'HTTP_PROXY',
                 'HTTPS_PROXY',
                 'FTP_PROXY',
                 'NO_PROXY'])}


def get_misc_environ(os_environ):
    """
        Extracts the miscellaneous environment variables from the
        os_environment.
    """
    return {var_name: os_environ.get[var_name]
            for var_name in os_environ.keys() &
            set(['SSH_AGENT_PID',
                 'SSH_AUTH_SOCK',
                 'SHELL',
                 'TERM',
                 'GIT_PROXY_COMMAND'] +
                BB_ENV_EXTRAWHITE_ADDITIONALS)}


def load_configuration_file(context, filepath):
    """
        Fills the configuration of the context based on the kas configuration
        file.
    """
    from .includehandler import GlobalIncludes, IncludeException
    filepath = os.path.abspath(filepath)
    handler = GlobalIncludes(filepath)

    repo_paths = {}

    missing_repo_names_old = []
    missing_repo_names = []

    while True:
        (config, missing_repo_names) = \
            handler.get_config(repos=repo_paths)
        context.set_config(config)

        # No missing repo detected, config complete:
        if not missing_repo_names:
            break

        # Last interation could not change the number of missing repos:
        if missing_repo_names == missing_repo_names_old:
            raise IncludeException('Could not fetch all repos needed by '
                                   'includes.')

        logging.debug('Missing repos for complete config:\n%s',
                      pprint.pformat(missing_repo_names))

        repo_dict = context.get_repo_dict()
        missing_repos = [repo_dict[repo_name]
                         for repo_name in missing_repo_names
                         if repo_name in repo_dict]

        repos_fetch(context, missing_repos)

        for repo in missing_repos:
            repo_checkout(context, repo)

        repo_paths = {r: repo_dict[r].path for r in repo_dict}

        missing_repo_names_old = missing_repo_names

    logging.debug('Configuration from config file:\n%s',
                  pprint.pformat(config))


def get_git_base_path(context, dirpath):
    """
        Returns the base path of the git repository that contains the specified
        directory path.
    """
    basepath = None
    (ret, output) = run_cmd(['git',
                             'rev-parse',
                             '--show-toplevel'],
                            cwd=dirpath,
                            env=context.get_environment(),
                            fail=False,
                            liveupdate=False)
    if ret == 0:
        basepath = output.strip()
    return basepath


def create_context(filename, os_environ=None, work_dir='', **qwargs):
    """
        Create the kas context based on the configuration file.
        With the additional argments its possible to overwrite specific entries
        of the configuration file at runtime. Like distro, targets and task.
    """
    os_environ = os_environ or os.environ
    work_dir = work_dir or os_environ.get('KAS_WORK_DIR', os.getcwd())

    environ = get_locale_environ()
    environ.update(get_proxy_environ(os_environ))
    environ.update(get_misc_environ(os_environ))

    # Preliminary empty context:
    context = Context(work_dir=work_dir, os_environ=os_environ,
                      environ=environ, config_override=qwargs)

    # Find repo path of the configuraton file:
    dirpath = os.path.dirname(filename)
    config_repo_path = get_git_base_path(context, dirpath) or dirpath
    context.set_config_repo_path(config_repo_path)

    load_configuration_file(context, filename)

    return context


class Context:
    """
        Represents the kas application context.
    """
    def __init__(self, config_repo_path=None, work_dir='', os_environ=None,
                 environ=None, config=None, config_override=None):
        self._config_repo_path = config_repo_path
        self._work_dir = work_dir
        self._os_environ = os_environ or {}
        self._environ = environ or {}
        self._build_environ = {}
        self._override_environ = {}

        self._config_override = config_override or {}
        self.set_config(config or {})

    def set_config(self, config):
        """
            Sets the internal configuration structure of the context.
        """
        self._config = config
        self._config.update(self._config_override)

    def set_config_repo_path(self, config_repo_path):
        """
            Sets the repository path of the configuration file.
        """
        self._config_repo_path = config_repo_path

    def set_build_environment(self, env):
        self._build_environ = env

    def update_environment(self, env):
        self._environ.update(env)

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

        return self._os_environ.get('KAS_REPO_REF_DIR', None)

    def get_environment(self):
        """
            Returns the context environment variables from the configuration,
            with possible overwritten values from the shell environment.
        """
        config_env = self._config.get('env', {})
        config_env = {var: self._os_environ.get(var, config_env[var])
                      for var in config_env}

        env = self._build_environ.copy()
        env.update(config_env)
        env.update(self._environ)
        return env

    def get_environment_configured_varname_list(self):
        """
            Returns the list of environment variables that are configured
            in the configuration file. For example used to supplement the
            BB_ENV_EXTRAWHITE.
        """
        return list(self._config.get('env', {}).keys()) + \
            BB_ENV_EXTRAWHITE_ADDITIONALS

    def get_repos(self):
        """
            Returns the list of repos.
        """

        return list(self.get_repo_dict().values())

    def get_repo_dict(self):
        """
            Returns a dictionary containing the repositories with
            their name (as it is defined in the config file) as key
            and the `Repo` instances as value.
        """

        repo_config_dict = self._config.get('repos', {})
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
                    path = self._config_repo_path

                url = path
                rep = Repo(url=url,
                           path=path,
                           layers=layers)
                rep.disable_git_operations()
            else:
                path = path or os.path.join(self._work_dir, name)
                rep = Repo(url=url,
                           path=path,
                           refspec=refspec,
                           layers=layers)
            repo_dict[repo] = rep
        return repo_dict

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
