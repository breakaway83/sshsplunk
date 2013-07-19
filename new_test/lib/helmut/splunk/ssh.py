'''
Module for dealing with Splunk instances that you're connected to via SSH.

@author: Nicklas Ansman-Giertz
@contact: U{ngiertz@splunk.com<mailto:ngiertz@splunk.com>}
@since: 2011-12-05
'''
import os
import tempfile

from helmut.splunk_package.nightly import NightlyPackage
from helmut.splunk_package.package import UNIVERSAL_FORWARDER
from helmut.splunk_package.release import ReleasedPackage
from .local import LocalSplunk
from helmut import splunk_platform
from helmut.ssh.connection import SSHConnection
from helmut.util import fileutils, archiver


class SSHSplunk(LocalSplunk):
    """
    Represents a remote Splunk instance.

    You communicate with Splunk over SSH.

    @ivar _connection: The SSH connection to Splunk.
    @type _connection: L{SSHConnection}
    """
    def __init__(self, connection, splunk_home, name=None):
        """
        Creates a new instance.

        @param connection: The SSH connection.
        @type connection: L{SSHConnection}
        @param splunk_home: The path to splunk_home on the remote server.
        @type splunk_home: str
        @param connector_factory: The factory to use when creating the default
                                  connection.
        @raise InvalidSSHConnection: If the connection is not of the right type.
        @see: L{LocalSplunk.__init__}
        """
        self._validate_connection(connection)
        self._connection = connection

        super(SSHSplunk, self).__init__(splunk_home, name)

    @classmethod
    def _validate_connection(cls, connection):
        '''
        Validates the connection variable.

        Currently these are the requirements:
          - Must be an L{SSHConnection}

        @raise InvalidSplunkHome: If the splunk_home variable is invalid.
        '''
        if not isinstance(connection, SSHConnection):
            msg = '{0} is not a valid connection'.format(connection)
            raise InvalidSSHConnection(msg)

    @property
    def _str_format(self):
        return '<{cls}@{id} name="{name}" splunk_home="{splunk_home} ' \
               'connection={conn}>'

    # Suppressing errors since this is Nicklas' code and I have not fully
    # gone into how it works. - parhamfh 24/09/12
    # pylint: disable=W0212
    @property
    def _str_format_arguments(self):
        a = super(SSHSplunk, self)._str_format_arguments
        a['conn'] = self._connection
        return a

    @property
    def connection(self):
        """
        The ssh connection that is used.

        @rtype: L{SSHConnection}
        """
        return self._connection

    @property
    def _file_utils(self):
        """
        The file utils of the SSH connection.

        @rtype: L{SSHFileUtils}
        """
        return self._connection.file_utils

    def _binary_exists(self, binary=None):
        binary = self.get_binary_path(binary or self.splunk_binary)
        return self._file_utils.isfile(binary)

    def execute_with_binary(self, binary, command):
        binary = self.get_binary_path(binary)
        self._validate_binary(binary)

        cmd = '{0} {1}'.format(binary, command)

        self.logger.info('Executing command {0}'.format(cmd))
        return self._connection.execute(cmd)

    def stop(self):
        self.logger.info('Stopping Splunk...')
        cmd = 'stop'
        (code, stdout, stderr) = self.execute(cmd)

    def execute(self, command):
        command = '{0} {1}'.format(command, self.COMMON_FLAGS)
        return self.execute_without_common_flags(command)

    def execute_without_common_flags(self, command):
        if not self._binary_exists():
            raise SplunkNotInstalled
        return self.execute_with_binary(self.splunk_binary, command)

    def _binary_exists(self, binary=None):
        binary = self.get_binary_path(binary or self.splunk_binary)
        self.logger.debug('Checking if splunk binary %s exists: %s' %
                          (binary, os.path.isfile(binary or self.splunk_binary)
                           ))
        return self.connection.file_utils.isfile(binary or self.splunk_binary)

    @property
    def splunk_binary(self):
        return self.get_binary_path('splunk')

    def get_binary_path(self, binary):
        #if self.connection.file_utils.isdir(binary):
        #    return binary
        splunk_binary_path = os.path.join(self._splunk_home, 'bin', binary)
        if self.connection.file_utils.isfile(splunk_binary_path):
            return splunk_binary_path
        else:
            splunk_binary_path = os.path.join(self._splunk_home, 'splunk', \
                                 'bin', binary)
            if self.connection.file_utils.isfile(splunk_binary_path):
                return splunk_binary_path
            else:
                return os.path.join(self._splunk_home, 'bin', binary)

    def web_host(self):
        '''
        Returns the web host for Splunk.

        Will be the same as the SSH host.

        @return: The host.
        @rtype: str
        '''
        return self._connection.host

    def splunkd_host(self):
        '''
        Returns the splunkd host.

        Will be the same as the SSH host.

        @return: The host.
        @rtype: str
        '''
        return self._connection.host

    def uninstall(self):
        '''
        Uninstalls splunk by first stopping the instance if it's running and
        then removing the splunk_home directory.

        This executes 'rm -rf <splunk_home>' on the remote server.
        '''
        self.logger.info('Uninstalling Splunk...')
        self._stop_splunk_if_needed()
        self._file_utils.force_remove_tree(self.splunk_home)
        self.logger.info('Splunk has been uninstalled.')

    def install_nightly(self, branch=None, build=None):
        pkg = NightlyPackage(platform=self._get_host_platform(), branch=branch)
        pkg.build = build
        return self.install_from_package(pkg)

    def _get_host_platform(self):
        '''
        Attempts to determine the host platform.

        @return: The platform.
        @rtype: L{SplunkPlatform}
        @raise CouldNotDetermineHostArchitecture: If the architecture could not
                                                  be determined.
        @raise CouldNotDetermineHostOS: If the OS could not be determined.
        '''
        _os = self._get_host_os()
        _arch = self._get_host_architecture()
        return splunk_platform.get_platform((_os, _arch))

    def _get_host_os(self):
        '''
        Returns the OS of the host.

        @return: The OS.
        @rtype: str
        @raise CouldNotDetermineHostOS: If the OS could not be determined.
        '''
        cmd = 'python -c "import sys; sys.stdout.write(sys.platform)"'
        (code, stdout, stderr) = self._connection.execute(cmd)
        if code != 0:
            raise CouldNotDetermineHostOS(stderr)
        return stdout

    def _get_host_architecture(self):
        '''
        Returns the OS of the host.

        @return: The OS.
        @rtype: str
        @raise CouldNotDetermineHostArchitecture: If the architecture could not
                                                  be determined.
        '''
        cmd = 'python -c "import sys, platform; ' \
              'sys.stdout.write(platform.machine())"'
        (code, arch, stderr) = self._connection.execute(cmd)
        if code != 0:
            raise CouldNotDetermineHostArchitecture(stderr)
        return arch

    def install_nightly_forwarder(self, branch=None, build=None):
        pkg = NightlyPackage(platform=self._get_host_platform(), branch=branch)
        pkg.build = build
        pkg.package_type = UNIVERSAL_FORWARDER
        return self.install_from_package(pkg)

    def install_release(self, version=None):
        pkg = ReleasedPackage(platform=self._get_host_platform(),
                              version=version)
        return self.install_from_package(pkg)

    def install_released_forwarder(self, version=None):
        pkg = ReleasedPackage(platform=self._get_host_platform(),
                              version=version)
        pkg.package_type = UNIVERSAL_FORWARDER
        return self.install_from_package(pkg)

    def _move_extracted_splunk_to_splunk_home(self, source):
        self.logger.debug("Sending extracted Splunk source (%s) to SPLUNK_HOME\
                            : %s" % (source, self.splunk_home))
        self._file_utils.send(source, self.splunk_home)

    def has_app(self, name):
        return self.connection.file_utils.isdir(self._path_to_app(name))

    def install_app(self, name, package):
        if not self.has_app(name):
            return False

        path = os.path.join(tempfile.gettempdir(),
                            'ssh_splunk_temp_{0}'.format(name))

        try:
            os.makedirs(path)
            self._install_app_with_tempdir(name, package, path)
            return True
        finally:
            fileutils.force_remove_directory(path)

    def _install_app_with_tempdir(self, name, package, path):
        '''
        Extracts the specified package to the specified path and then installs
        the app by copying the contents over SSH.

        @param name: The name of the app
        @type name: str
        @param package: The path to the package to install.
        @type package: str
        @param path: The temp directory to extract the package to.
        @type path: str
        '''
        archiver.extract(package, path)
        self.connection.file_utils.send(path, self._path_to_app(name))

    def uninstall_app(self, name):
        self.connection.file_utils.force_remove_tree(self._path_to_app(name))


class CouldNotDetermineHostOS(RuntimeError):
    """
    Raised when the remote OS could not be determined.
    """


class CouldNotDetermineHostArchitecture(RuntimeError):
    """
    Raised when the architecture of the host could not be determined.
    """


class InvalidSSHConnection(BaseException):
    """
    Raised when the given SSH connection is not valid.
    """
