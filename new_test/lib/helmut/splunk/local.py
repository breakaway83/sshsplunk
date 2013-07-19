'''
Module for dealing with local splunk instances

@author: Nicklas Ansman-Giertz
@contact: U{ngiertz@splunk.com<mailto:ngiertz@splunk.com>}
@since: 2011-11-23
'''

import subprocess
import os
import tempfile
import shlex
import urllib2

import helmut.util.archiver as archiver
from .base import Splunk
from helmut.util import fileutils
from helmut.splunk_package.nightly import NightlyPackage
from helmut.splunk_package.package import UNIVERSAL_FORWARDER
from helmut.splunk_package.release import ReleasedPackage
from helmut.splunk.base import CouldNotRestartSplunk
from helmut.exceptions.command_execution import CommandExecutionFailure


class LocalSplunk(Splunk):
    '''
    Represents a local splunk instance.

    Local means there is access to the Splunk binaries, conf files etc.

    @ivar _splunk_home: The path to the Splunk installations root.
    @type _splunk_home: str
    @ivar _splunkd_port: The port which Splunkd listens to. Will be None if the
                         port is not known.
    @type _splunkd_port: int
    @ivar _web_port: The port which Splunk web listens to. Will be None if the
                     port is not known.
    @type _web_port: int

    @cvar COMMON_FLAGS: The most flags that are most commonly used. They are
                        recommended when using the default Splunk binary as
                        they put it in non interactive mode, otherwise Helmut
                        might lock up when executing commands.
    @type COMMON_FLAGS: str
    '''

    COMMON_FLAGS = '--accept-license --no-prompt --answer-yes'
    _POSSIBLE_ARCHIVE_DIRECTORIES = ['splunk', 'splunkforwarder', 'splunkbeta',
                                     'splunkforwarderbeta']

    def __init__(self, splunk_home, name=None):
        '''
        Creates a new LocalSplunk instance.

        @param splunk_home: The local that splunk is/will be installed.
        @type splunk_home: str
        @raise InvalidSplunkHome: If splunk_home is not a string.
        '''
        self._validate_splunk_home(splunk_home)

        self._splunk_home = os.path.abspath(splunk_home)
        self._splunkd_port = None
        self._web_port = None

        super(LocalSplunk, self).__init__(name)

    @classmethod
    def _validate_splunk_home(cls, splunk_home):
        '''
        Validates the splunk_home variable.

        Currently these are the requirements:
          - Must be a string

        @raise InvalidSplunkHome: If the splunk_home variable is invalid.
        '''
        if not isinstance(splunk_home, str):
            raise InvalidSplunkHome('splunk_home must be a string')

    @property
    def _str_format(self):
        return '<{cls}@{id} name="{name}" splunk_home="{splunk_home}>'

    @property
    def _str_format_arguments(self):
        return {
            'cls': self.__class__.__name__,
            'id': id(self),
            'name': self.name,
            'splunk_home': self.splunk_home
        }

    def update_ports_from_splunk(self):
        '''
        Tries to read the ports that this splunk instance listens too.

        If the ports could not be read they are set to None
        '''
        self._splunkd_port = self._read_splunkd_port()
        self._web_port = self._read_web_port()

    def _read_splunkd_port(self):
        '''
        Returns the splunkd port or returns None if it failed.

        This executes the C{soapport} command

        @return: The port or None
        @rtype: int
        '''
        self.logger.info('Reading splunkd port')
        return self._read_port_from_command('soapport')

    def _read_web_port(self):
        '''
        Returns the splunkweb port or returns None if it failed.

        This executes the C{httpport} command

        @return: The port or None
        @rtype: int
        '''
        self.logger.info('Reading web port')
        return self._read_port_from_command('httpport')

    def _read_port_from_command(self, command):
        '''
        Reads the a port from by executing the specified command via the splunk
        binary.

        The port is assumed to be printed on the very last row of stdout and
        it is also assumed that the command returns 0 on success.

        @param command: The command to execute
        @type command: str
        @return: The port or None if it failed to execute
        @rtype: int
        '''
        if not self._binary_exists():
            return None
        (code, stdout, _) = self.execute(command)
        if code != 0:
            return None
        # pylint: disable=E1103
        return int(stdout.strip().split('\n')[-1])

    def _binary_exists(self, binary=None):
        '''
        Checks if the specified binary exists.

        If the binary is not specified the splunk binary is checked.

        This calls the L{get_binary_path} method.

        @param binary: The binary to look for or None
        @type binary: str
        @return: True if it exists
        @rtype: bool
        '''
        binary = self.get_binary_path(binary or self.splunk_binary)
        self.logger.debug('Checking if splunk binary %s exists: %s' %
                          (binary, os.path.isfile(binary or self.splunk_binary)
                           ))
        return os.path.isfile(binary or self.splunk_binary)

    @property
    def splunk_binary(self):
        '''
        Returns the absolute path to the splunk binary

        @rtype: str
        '''
        return self.get_binary_path('splunk')

    def get_binary_path(self, binary):
        '''
        Returns the absolute path to the specified binary.

        If the path is already absolute it is returned as is.

        Example usage:
            >>> splunk = LocalSplunk('/opt/splunk')
            >>> splunk.get_binary_path('btool')
            '/opt/splunk/bin/btool'
            >>> splunk.get_binary_path('/foo/bar')
            '/foo/bar'

        @param binary: The binary to return the path for
        @type binary: str
        @rtype: str
        @return: The absolute path to the binary
        '''
        if os.path.isabs(binary):
            return binary
        return os.path.join(self._splunk_home, 'bin', binary)

    def is_installed(self):
        '''
        Checks if this Splunk instance is installed.

        It checks if the splunk binary exists.

        @rtype: bool
        @return: True if splunk is installed.
        '''
        self.logger.info('Checking if Splunk is installed...')
        r = self._binary_exists()
        self.logger.info('Splunk is{0} installed'.format('' if r else ' not'))
        return r

    def _splunk_has_started(self):
        '''
        Called after splunk has started.

        Will call L{update_ports_from_splunk} and
        L{_notify_listeners_of_splunk_start}
        '''
        self.logger.info('Splunk has been started.')

        self.update_ports_from_splunk()
        self._notify_listeners_of_splunk_start()

    @property
    def splunk_home(self):
        '''
        Returns the path to splunk_home

        @rtype: str
        '''
        return self._splunk_home

    @splunk_home.setter
    def splunk_home(self, value):
        # Do something if you want
        self._splunk_home = value

    def execute(self, command):
        '''
        Executes the specified command using the splunk binary.

        This will add the L{common flags<COMMON_FLAGS>} to the command.

        See L{execute_without_common_flags} if you don't want them.

        Example:
            >>> splunk.execute('show web-port -auth admin:changeme')
            (0, 'Web port: 8000\\n', '')
            >>> splunk.execute('version')
            (0, 'Splunk 4.3 (build 112175)\\n', '')

        @param command: The command to execute. Remember to quote strings with
                        spaces.
        @type command: str
        @return: (code, stdout, stderr)
        @rtype: tuple(int, str, str)
        @raise SplunkNotInstalled: If the splunk binary doesn't exist
        '''
        command = '{0} {1}'.format(command, self.COMMON_FLAGS)
        return self.execute_without_common_flags(command)

    def execute_without_common_flags(self, command):
        '''
        Executes the specified command using the splunk binary.

        This will not add the L{common flags<COMMON_FLAGS>} to the command.

        See L{execute} for example usage.

        @param command: The command to execute. Remember to quote your strings
                        if the contain spaces.
        @type command: str
        @return: (exit_code, stdout, stderr)
        @rtype: tuple(int, str, str)
        @raise SplunkNotInstalled: If the splunk binary doesn't exist
        '''
        if not self._binary_exists():
            raise SplunkNotInstalled
        return self.execute_with_binary(self.splunk_binary, command)

    def execute_with_binary(self, binary, command):
        '''
        Executes the specified command with the given binary.

        Example:
            >>> splunk.execute_with_binary('btool check')
            (0, '', '')

        @param binary: The binary to execute with. Can be relative to the bin
                       directory or an absolute path.
        @type binary: str
        @param command: The command to execute. Remember to quote your strings
                        if the contain spaces.
        @type command: str
        @return: (exit_code, stdout, stderr)
        @rtype: tuple(int, str, str)
        @raise BinaryMissing: If the binary doesn't exist
        '''
        binary = self.get_binary_path(binary)
        self._validate_binary(binary)

        cmd = [binary]
        cmd.extend(shlex.split(command))

        self.logger.info('Executing command {0}'.format(''.join(cmd)))

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        (stdout, stderr) = process.communicate()
        self.logger.info('Done! Exit code {0}'.format(process.returncode))
        return (process.returncode, stdout, stderr)

    def _validate_binary(self, binary):
        '''
        Checks if the specified binary exists.

        @param binary: The binary
        @type binary: str
        @raise BinaryMissing: If the binary doesn't exist
        '''
        if not self._binary_exists(binary):
            raise BinaryMissing(binary)

    def start(self, auto_ports=False):
        '''
        Starts Splunk.

        Please note that an exception might not be thrown even if the command
        fails. The exception is only thrown if Splunk is not running.

        If you try to start Splunk when it is already started for example. The
        command will return a positive integer but this method will not throw
        an exception since Splunk is running.

        This means that you can be sure that Splunk is running if this command
        does not throw an exception.

        @return: The exit code of the command.
        @rtype: int
        @raise CouldNotStartSplunk: If Splunk is not running after starting it.
        '''
        self.logger.info('Starting splunk...')

        flags = ''
        if auto_ports:
            flags = " --auto-ports"

        cmd = 'start' + flags
        (code, stdout, stderr) = self.execute(cmd)
        #self.logger.info('Splunk has been started')
        self.logger.info('Splunk has been started with version {version}'.format(version=self.version())) 
        self._verify_splunk_is_running(cmd, code, stdout, stderr)
        self._splunk_has_started()
        return code

    def _verify_splunk_is_running(self, command, code, stdout, stderr):
        '''
        Checks if Splunk is running raising an exception if not.

        @param command: The command that was run
        @type command: str
        @param code: The exit code.
        @type code: int
        @param stdout: The stdout that was printed by the command.
        @type stdout: str
        @param stderr: The stderr that was printed by the command.
        @type stderr: str
        @raise CouldNotStartSplunk: If Splunk is not running.
        '''
        self.logger.info('Verifying that Splunk is running...')
        if not self.is_running():
            self.logger.info('Splunk is not running')
            raise CouldNotStartSplunk(command, code, stdout, stderr)
        self.logger.info('Splunk is running')

    def stop(self):
        '''
        Stops Splunk.

        Please note that an exception might not be thrown even if the command
        fails. The exception is only thrown if Splunk is still running.

        If you try to stop Splunk when it is already stopped for example. The
        command will return a positive integer but this method will not throw
        an exception since Splunk is not running.

        This means that you can be sure that Splunk is not running if this
        command does not throw an exception.

        @return: The exit code of the command.
        @rtype: int
        @raise CouldNotStopSplunk: If Splunk is still running after stopping it.
        '''
        self.logger.info('Stopping Splunk...')
        cmd = 'stop'
        (code, stdout, stderr) = self.execute(cmd)
        self.logger.info('Splunk has been stopped')
        self._verify_splunk_is_not_running(cmd, code, stdout, stderr)
        return code

    def _verify_splunk_is_not_running(self, command, code, stdout, stderr):
        '''
        Checks if Splunk is running raising an exception if it is.

        @param command: The command that was run
        @type command: str
        @param code: The exit code.
        @type code: int
        @param stdout: The stdout that was printed by the command.
        @type stdout: str
        @param stderr: The stderr that was printed by the command.
        @type stderr: str
        @raise CouldNotStopSplunk: If Splunk is running.
        '''
        self.logger.info('Verifying that Splunk is not running...')
        if self.is_running():
            self.logger.info('Splunk is running')
            raise CouldNotStopSplunk(command, code, stdout, stderr)
        self.logger.info('Splunk is not running')

    def restart(self):
        '''
        Restarts Splunk.

        Calls L{stop} and then L{start}

        @return: Always 0 (for compatibility with L{start}/L{stop}).
        @rtype: int
        @raise CouldNotRestartSplunk: If Splunk failed to restart.
        '''
        self.logger.info('Restarting Splunk...')
        try:
            self.logger.debug('Stopping Splunk inside .restart()')
            cmd = 'restart'
            (code, stdout, stderr) = self.execute(cmd)
            self._verify_splunk_is_running(cmd, code, stdout, stderr)
            self._splunk_has_started()
        except CommandExecutionFailure, err:
            self.logger.info('Restarting Splunk failed')
            raise CouldNotRestartSplunk(err.command, err.code, err.stdout,
                                        err.stderr)

        self.logger.info('Splunk has been restarted')
        return code

    def is_running(self):
        '''
        Checks to see if Splunk is started.

        It does this by calling C{status} on the Splunk binary.

        @rtype: bool
        @return: True if Splunk is started.
        '''
        is_running = False
        self.logger.info('Checking if Splunk is running...')
        if self.is_installed():
            (_, stdout, _) = self.execute('status')
            is_running = 'splunkd is running' in stdout
        msg = 'Splunk {0} running'.format('is' if is_running else 'is not')
        self.logger.info(msg)
        return is_running

    def web_port(self):
        '''
        Returns the web port for Splunk.

        If the port is unknown it tries to read the port again.

        @rtype: int
        @return: The port or None if it's unknown.
        '''
        if self._web_port is None:
            self.update_ports_from_splunk()
        return self._web_port

    # TODO: TEMPORARY FOR EST-1859
    def set_web_port(self, port):
        self.default_connector.server_settings_endpoint.post(httpport=port)

    def web_host(self):
        '''
        Returns the web host for Splunk.

        Currently hardcoded to 'localhost'

        @rtype: str
        @return: The host
        '''
        return 'localhost'

    def web_scheme(self):
        '''
        Returns the web scheme for Splunk.

        Currently hardcoded to 'http'

        @return: The scheme.
        @rtype: str
        '''
        return 'http'

    def splunkd_port(self):
        '''
        Returns the splunkd port.

        If the splunkd port is unknown it tries to read the port again.

        @return: The port or None if it's unknown.
        @rtype: str
        '''
        if self._splunkd_port is None:
            self.update_ports_from_splunk()
        return self._splunkd_port

    # TODO: TEMPORARY FOR EST-1859
    def set_splunkd_port(self, port):
        self.default_connector.server_settings_endpoint.post(mgmtHostPort=port)

    def splunkd_host(self):
        '''
        Returns the splunkd host.

        Currently hardcoded to 'localhost'

        @return: The host.
        @rtype: str
        '''
        return 'localhost'

    def splunkd_scheme(self):
        '''
        Returns the splunkd host.

        Currently hardcoded to 'https'

        @return: The scheme.
        @rtype: str
        '''
        return 'https'

    def uri_base(self):
        '''
        Returns the splunkd host.

        Currently hardcoded to 'localhost'

        @return: The host.
        @rtype: str
        '''
        return self.splunkd_scheme()+'://'+self.splunkd_host()+':'+str(self.splunkd_port()) 

    def uninstall(self):
        '''
        Uninstalls splunk by first stopping the instance if it's running and
        then removing the splunk_home directory.
        '''
        self.logger.info('Uninstalling Splunk...')
        self._stop_splunk_if_needed()
        fileutils.force_remove_directory(self.splunk_home)
        self.logger.info('Splunk has been uninstalled.')

    def _stop_splunk_if_needed(self):
        '''
        Stops Splunk if it is running.
        '''
        if self.is_running():
            self.logger.debug("Stopping Splunk inside "
                              "._stop_splunk_if_needed()")
            self.stop()

    def install_nightly(self, branch=None, build=None):
        '''
        Installs this instance from the specified nightly branch and build.

        This is just a lazy version of first using the L{splunk_package} to
        download a package and then installing via L{install_from_archive}

        @param branch: The branch to download from. None means default branch
                       (current).
        @type branch: str or None
        @param build: The build to download. None means latest build.
        @type build: str or None
        @see: L{install_from_archive}
        @see: L{splunk_package}
        '''
        pkg = NightlyPackage(branch=branch, build=build)
        return self.install_from_package(pkg)

    def install_from_package(self, package):
        '''
        Installs this instance from the specified package.

        @param package: The package object.
        @type package: L{SplunkPackage}
        @see: L{install_from_archive}
        @see: L{splunk_package}
        '''
        self.logger.info('Trying to install Splunk from {0}'.format(package))
        pkg = package.download()
        try:
            self.install_from_archive(pkg)
        finally:
            self.logger.info('Removing downloaded package {0}'.format(pkg))
            os.remove(pkg)

    def install_nightly_forwarder(self, branch=None, build=None):
        '''
        Installs this instance as a universal forwarder from the specified
        nightly branch and build.

        This is just a lazy version of first using the L{splunk_package} to
        download a package and then installing via L{install_from_archive}

        @param branch: The branch to download from. None means default branch
                       (current).
        @type branch: str or None
        @param build: The build to download. None means latest build.
        @type build: str or None
        @see: L{install_from_archive}
        @see: L{splunk_package}
        '''
        pkg = NightlyPackage(branch=branch)
        pkg.build = build
        pkg.package_type = UNIVERSAL_FORWARDER
        return self.install_from_package(pkg)

    def install_release(self, version=None):
        '''
        Installs this instance from the specified release.

        This is just a lazy version of first using the L{splunk_package} to
        download a package and then installing via L{install_from_archive}

        @param version: Which version to download. Defaults to the latest for
                        this platform.
        @type version: str
        @see: L{install_from_archive}
        @see: L{splunk_package}
        '''
        pkg = ReleasedPackage(version=version)
        return self.install_from_package(pkg)

    def install_released_forwarder(self, version=None):
        '''
        Installs this instance as a forwarder from the specified release.

        This is just a lazy version of first using the L{splunk_package} to
        download a package and then installing via L{install_from_archive}

        @param version: Which version to download. Defaults to the latest for
                        this platform.
        @type version: str
        @see: L{install_from_archive}
        @see: L{splunk_package}
        '''
        pkg = ReleasedPackage(version=version)
        pkg.package_type = UNIVERSAL_FORWARDER
        return self.install_from_package(pkg)

    def install_from_url(self, url):
        """Downloads and installs a package from a URL.

        The URL must point to a valid splunk package (has one of the file
        extensions usually supported by Releases).

        @param url: The URL to the package.
        @type url: str
        """
        self.logger.info("Downloading from={0}".format(url))
        response = urllib2.urlopen(url)
        fd, temp_file = tempfile.mkstemp(suffix=os.path.basename(url))
        try:
            self.logger.info("Downloading to={0}".format(temp_file))
            with os.fdopen(fd, 'wb') as f:
                f.write(response.read())
            self.install_from_archive(temp_file)
        finally:
            fileutils.force_remove_file(temp_file)

    def install_from_archive(self, archive_path):
        '''
        Installs this splunk instance from an archive.

        The archive must be extractable by the L{archiver}

        WARNING: Splunk will be stopped when calling this method and it will
        not be restarted automatically.

        @param archive_path: The path to the archive
        @type archive_path: str
        '''
        msg = 'Installing Splunk from archive={0}'.format(archive_path)
        self.logger.info(msg)
        self._stop_splunk_if_needed()
        directory = tempfile.mkdtemp()
        try:
            self._install_archive_with_temp_directory(archive_path, directory)
        finally:
            msg = 'Removing extracted files from {0}'.format(directory)
            self.logger.info(msg)
            fileutils.force_remove_directory(directory)

        self.logger.info('Splunk has been installed.')

    def _install_archive_with_temp_directory(self, archive_path, directory):
        '''
        Installs this instance from a specified archive by extracting it to
        the specified temp directory

        @param archive_path: The path to the archive
        @type archive_path: str
        @param directory: The temp directory to use
        @type directory: str
        '''
        archiver.extract(archive_path, directory)
        source = self._find_archive_directory_name(directory)
        self._move_extracted_splunk_to_splunk_home(source)

    def _move_extracted_splunk_to_splunk_home(self, source):
        """
        After the archiver has extracted the package this method is called to
        move the extracted folder to splunk_home.

        The source must be the root directory of Splunk. This means you cannot
        just take the directory that the archiver extracts to. This is because
        the package contains a directory called 'splunk', 'splunkforwarder' etc.

        @param source: The directory of the extracted Splunk package.
        @type source: str
        """
        msg = 'Copying extracted Splunk from {source} to {home}'
        self.logger.info(msg.format(source=source, home=self.splunk_home))
        fileutils.force_move_directory(source, self.splunk_home)

    def _find_archive_directory_name(self, directory):
        """
        Tries to find the directory name of an extracted Splunk archive.

        It will iterate over L{_POSSIBLE_ARCHIVE_DIRECTORIES} and see if that
        entry exists.

        @param directory: The directory that the package was extracted to.
        @type directory: str
        @return: The path to the Splunk directory.
        @rtype: str
        @raise CouldNotFindSplunkDirectory: If the directory could not be
                                            guessed.
        """
        self.logger.info('Trying to find extracted directory name')
        entries = os.listdir(directory)
        for name in self._POSSIBLE_ARCHIVE_DIRECTORIES:
            if name in entries:
                self.logger.info("{0} - Exists".format(name))
                return os.path.join(directory, name)
            else:
                self.logger.info("{0} - Doesn't exist".format(name))
        raise CouldNotFindSplunkDirectory

    def version(self):
        '''
        The version in the format: Splunk <version> (build <build>)

        This simple executes 'version' with the Splunk binary

        @rtype: str
        '''
        cmd = 'version'
        (code, stdout, stderr) = self.execute(cmd)
        if code != 0:
            raise CommandExecutionFailure(cmd, code, stdout, stderr)
        # pylint: disable=E1103
        return stdout.strip()

    def has_app(self, name):
        '''
        Checks if the specified app is installed.

        @param name: The name of the app.
        @type name: str
        @return: True if it exists.
        @rtype: bool
        '''
        return os.path.isdir(self._path_to_app(name))

    def _path_to_app(self, name):
        '''
        Returns the path to the specified app.

        @param name: The name of the app.
        @type name: str
        @return: The path
        @rtype: str
        '''
        return os.path.join(self.apps_dir, name)

    @property
    def apps_dir(self):
        '''
        The path to the directory where the apps for this instance is stored.

        @rtype: str
        '''
        return os.path.join(self.splunk_home, 'etc', 'apps')

    # pylint: disable=W0613
    def install_app(self, name, package):
        '''
        Installs the specified app.

        @param name: The name of the app.
        @type name: str
        @param package: The path to the package to install from.
        @type package: str
        '''
        archiver.extract(package, self.apps_dir)

    def uninstall_app(self, name):
        '''
        Uninstall the specified app.

        @param name: The name of the app
        @type name: str
        @return: True if the app was removed and Splunk needs to be restarted.
        @rtype: bool
        '''
        if not self.has_app(name):
            return False
        fileutils.force_remove_directory(self._path_to_app(name))
        return True

    def enable_listen(self, ports):
        self.logger.info("Enabling ports for listening...")

        try:
            for port in ports:
                if self._check_if_valid_port(port):
                    self.logger.info("Enabling port %s for listening." % port)
                    self.execute("enable listen -port %s" % port)
        # Assume it is a single int and not a list of ints
        except TypeError:
            if self._check_if_valid_port(ports):
                self.logger.info("Enabling port %s for listening." % ports)
                self.execute("enable listen -port %s" % ports)

    def disable_listen(self, ports):
        self.logger.info("Disabling ports for listening...")

        try:
            for port in ports:
                if self._check_if_valid_port(port):
                    self.logger.info("Disabling port %s for listening." % port)
                    self.execute("disable listen -port %s" % port)
        # Assume it is a single int and not a list of ints
        except TypeError:
            if self._check_if_valid_port(ports):
                self.logger.info(
                    "Disabling port %s for listening." % ports)
                self.execute("disable listen -port %s" % ports)

    def _check_if_valid_port(self, port):
        try:
            # Since Python versions previous to 3.x allow string to int
            # comparison
            # we must check type explicitly
            if not isinstance(port, int):
                raise TypeError("Port must be specified with an int. "
                                "Port value specified: %s" % port)
            if not 0 <= port <= 65535:
                raise ValueError("The port must be within the range 0 "
                                 "and 65535. Port value specified: %s" % port)
        except TypeError, te:
            self.logger.warn(te)
            return False
        except ValueError, ve:
            self.logger.warn(ve)
            return False

        return True


class InvalidSplunkHome(RuntimeError):
    '''
    Raised when the given splunk_home variable is invalid
    '''
    pass


class SplunkNotInstalled(RuntimeError):
    '''
    Raised when an action that requires splunk to be installed is called but
    Splunk is not installed.
    '''


class BinaryMissing(RuntimeError):
    '''
    Raised when trying to execute a command with a non existent binary.
    '''

    def __init__(self, binary):
        '''
        Creates the exception.

        @param binary: The binary that is missing
        @type binary: str
        '''
        message = "The {0} binary doesn't exist".format(binary)
        super(BinaryMissing, self).__init__(message)


class CouldNotFindSplunkDirectory(RuntimeError):
    """
    Raised when the name of the directory in a Splunk package could not be
    guessed.
    """

    def __init__(self, msg=None):
        msg = msg or 'Could not find the Splunk build inside the archive.'
        RuntimeError.__init__(self, msg)


class CouldNotStartSplunk(CommandExecutionFailure):
    '''
    Raised when a Splunk start fails.
    '''
    pass


class CouldNotStopSplunk(CommandExecutionFailure):
    '''
    Raised when a Splunk stop fails.
    '''
    pass
