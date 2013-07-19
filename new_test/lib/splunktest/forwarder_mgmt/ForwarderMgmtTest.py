import os
import logging
import random
import socket
import splunk
import pytest
import subprocess
import time
import sys
import tempfile
from helmut.splunk.ssh import SSHSplunk
from helmut.splunk.local import LocalSplunk
from helmut.ssh.connection import SSHConnection
from helmut.connector import SDKConnector
from helmut import splunk_platform
from time import gmtime, strftime
from helmut.splunk_package.nightly import NightlyPackage
from splunk.models.server_config import SplunkdConfig

LOGGER = logging.getLogger('TestForwarderMgmt')


class SplunkInstance(object):

    def __init__(self, request, hosts=None):
        if hosts is None:
            hosts = [socket.gethostbyname(socket.gethostname())]
            LOGGER.info('Hosts was None. Now it is {hosts}'
                        .format(hosts=hosts))

        self._config = request.config
        self._instances = []
        self._hosts = hosts
        self._current_host_index = 0
        #self.new_remotesplunk()

    def new_remotesplunk(self, host_name=None):
        instance = None
        ssh_conn = None
        splunk_home = None
        if host_name is None:
            host_name = self.next_host()
        LOGGER.debug('host_name = {}'.format(host_name))
        #assert host_name is not None
        splunk_home = self.local_ip

        if host_name in ('localhost',
                         socket.gethostname(),
                         "127.0.0.1",
                         self.local_ip):
            LOGGER.debug('Creating LocalSplunk instance')
            tempfile.tempdir = os.environ['HOME']
            splunk_home = os.getenv("HOME") + os.sep + 'tmp'
            #splunk_home = self._config.splunk_home
            instance = LocalSplunk(splunk_home)
        else:
            LOGGER.debug('Creating SSHSplunk instance')
            splunk_home = self._config.remote_splunk_home
            ssh_conn = SSHConnection(host_name,
                                     22,
                                     self._config.ssh_user,
                                     None)
            instance = SSHSplunk(ssh_conn, splunk_home)
            instance.ssh_conn = ssh_conn
        return instance

    def next_host(self):
        '''
        @return: The next host in the list of available hosts
        @rtype: string
        '''
        assert len(self._hosts) > 0
        if self._current_host_index >= len(self._hosts):
            self._current_host_index = 0
        host_name = self._hosts[self._current_host_index]
        self._current_host_index += 1
        return host_name

    @property
    def local_ip(self):
        '''
        @return: IPv4 address of machine running test.
        @rtype: str
        '''
        return socket.gethostbyname(socket.gethostname())
