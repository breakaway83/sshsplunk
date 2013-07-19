"""
Meta
====
    $Id: //splunk/current/new_test/tests/forwarder_mgmt/conftest.py#4 $
    $DateTime: 2013/07/15 12:57:53 $
    $Author: wma $
    $Change: 171452 $
"""

import tempfile
import logging
import pytest
import time
import os
import shutil
import socket
import yaml

from helmut.splunk.local import LocalSplunk
from helmut.splunk.ssh import SSHSplunk
from helmut.connector.base import Connector
from helmut.util import fileutils
from splunktest.forwarder_mgmt.ForwarderMgmtTest import SplunkInstance

LOGGER = logging.getLogger('TestDeploymentServer')
# Absolute path name to test folder
PATH = os.path.dirname(os.path.abspath(__file__))
# Absolute path name to configuration folder fslaves
YAMLPATH = os.path.join(PATH, '..', '..', 'config', 'forwarder_mgmt')
# Absolute path name to global configuration file
DEFAULT_CONFIG_FILE = os.path.join(YAMLPATH, '_global-conf.yml')

# Dictionary for all py.test command line options.
CONFIG_SET = {
    'num_of_forwarders': 'Number of Splunkforwarders for a deployment server',
    'remote-splunk-home': 'Default SPLUNK_HOME for remote instances',
    'conf-file': 'User-defined _gobal-config.yml file',
    'ds_host': 'Available ds host',
    'dc_hosts': 'Available dc hosts',
    'ssh_user': 'Username of remote host',
    'branch': 'Which development branch you want to use (e.g. current)'
    }

YAML_HOLDER = {}


def pytest_generate_tests(metafunc):
    for funcargs in getattr(metafunc.function, 'funcarglist', ()):
        if 'testname' in funcargs:
            testname = "%s" % funcargs['testname']
        metafunc.addcall(funcargs=funcargs, id=testname)


def params(funcarglist):
    """
    method used with generated/parameterized tests, can be used to decorate
    your test function with the parameters.  Each dict in your list
    represents on generated test.  The keys in that dict are the parameters
    to be used for that generated test
    """
    def wrapper(function):
        function.funcarglist = funcarglist
        return function
    return wrapper


def pytest_addoption(parser):
    """
    Adds extra command line arguments to pytest
    """
    LOGGER.debug('Forwarder Mgmt ADDOPTIONS<< pytest_addoption >>')

    for key in CONFIG_SET:
        LOGGER.info("KEY: {k}".format(k=key))
        try:
            if key != 'username' and key != 'password' and key != 'new_password':
               parser.addoption('--'+key, dest=key, help=CONFIG_SET[key])
        except:
            LOGGER.info('{key} already an option.'.format(key=key))


def pytest_configure(config):
    """Setup configuration after command-line options are parsed"""
    LOGGER.debug('<< pytest_configure >>')
    LOGGER.debug('<< Loading configuration >>')

    user_global_conf = {}
    try:
        user_config_file = config.getvalue('conf-file')
        LOGGER.info('conf file: {}'.format(user_config_file))
        abspath = False
        if user_config_file.startswith('/'):
            abspath = True
        user_global_conf = load_yaml_file(user_config_file, abspath)
    except:
        LOGGER.debug('You did not specify a conf file.')

    default_global_conf = load_global_configuration_file()

    for key in CONFIG_SET:
        LOGGER.debug('  Config ' + key)
        value = None
        if config.getvalue(key) is not None:
            value = config.getvalue(key)
            LOGGER.debug('    CLA found: "%s"', value)
        elif key in user_global_conf:
            value = user_global_conf[key]                     
        elif key in default_global_conf:
            value = default_global_conf[key]
            LOGGER.debug('    YAML found: "%s"', value)
        else:
            LOGGER.warn('{key} not found in configs provided'.format(key=key))
        key = key.replace('-', '_')
        setattr(config, key, value)

    if not hasattr(config, 'splunk_home'):
        splunk_home = os.path.expanduser('~') + '/splunk'
        setattr(config, 'splunk_home', splunk_home)
        LOGGER.info('config splunk_home = %s' % splunk_home)

    if not hasattr(config, 'ds_host') or config.ds_host is None:
        setattr(config, 'ds_host', [socket.gethostbyname(socket.gethostname())])

    if not hasattr(config, 'dc_hosts') or config.dc_hosts is None:
        setattr(config, 'dc_hosts', [socket.gethostbyname(socket.gethostname())])

    items = ''
    for item in dir(config):
        if not item.startswith('_'):
            items += '\n{}: {}'.format(item, getattr(config, item))
    LOGGER.debug('\n\nAttributes of pytest config object: {}'.format(items))

@pytest.fixture(scope="class")
def splunk(request):
    '''
     Fixture for Deployment Server 
    '''
    CONFIG = request.config
    if CONFIG.ds_host:
        spl_instance = SplunkInstance(request, CONFIG.ds_host)
    else:
        spl_instance = SplunkInstance(request)
    spl = spl_instance.new_remotesplunk()
    LOGGER.info("Deployment Server:Installing nightly from current in temp directory")
    spl.install_nightly(branch='current')
    #work around helmut's inability to pass flags to start
    spl.COMMON_FLAGS = spl.COMMON_FLAGS + ' --auto-ports'
    LOGGER.info("Deployment Server: Starting splunk")
    spl.stop()
    spl.execute("clean locks -f")
    spl.start()
    spl.stop()
    spl.execute("clean locks -f")
    spl.start()
    #TODO: Replace hardcoded sleeps with polling method
    time.sleep(60) 
    username = 'admin'
    password = request.config.option.password
    if not password: password = 'changeme'
    if ('admin', 'changeme') == (username, password):
        password = request.config.option.new_password or 'changed'
        spl.execute('edit user admin -password {newpass} -auth '
                    'admin:changeme'.format(newpass=password))
    spl.restart()
    spl.create_logged_in_connector(set_as_default=True,
                                   contype=Connector.SDK,
                                   username=username,
                                   password=password)
    LOGGER.info("Deployment Server: Creating serverclass.conf")
    spl.confs().create('serverclass') 
    spl.confs()['serverclass'].create_stanza('global') 
    spl.confs()['serverclass']['global']['whitelist.0'] = '*'
    spl.confs()['serverclass'].create_stanza('serverClass:foobar') 
    spl.confs()['serverclass'].create_stanza('serverClass:foobar:app:linmess') 
    spl.confs()['serverclass']['serverClass:foobar:app:linmess']['stateOnClient'] = 'enabled'
    spl.confs()['serverclass']['serverClass:foobar:app:linmess']['restartSplunkd'] = 'true'
    LOGGER.info("Deployment Server: Creating deployment app linmes")
    path_result = result = spl.splunk_binary.split(os.sep)
    spl.splunk_home = os.sep.join(path_result[0:-2])
    appdir = os.path.join(spl.splunk_home,'etc','deployment-apps','linmess','default')
    if spl._file_utils.isdir(appdir): spl._file_utils.force_remove_tree(appdir)
    cmd = 'mkdir -p {0}'.format(appdir)
    assert spl.connection.execute(cmd)[0] == 0
    #os.makedirs(appdir) 
    LOGGER.info("Deployment Server: Creating inputs.conf")
    #Helmut requirement: create conf file in non /etc/system/local
    spl.confs().create('appinputs')
    monitor_log_path = os.path.abspath(os.path.curdir + os.sep + os.pardir + os.sep + os.pardir + os.sep + 'data' + os.sep + 'syslog_rest.log') 
    spl.confs()['appinputs'].create_stanza('monitor:%s' % monitor_log_path) 
    spl.confs()['appinputs']['monitor:%s' % monitor_log_path]['disabled'] = 'false'
    spl.confs()['appinputs']['monitor:%s' % monitor_log_path]['sourcetype'] = 'test_install'
    apppath = os.path.join(spl.splunk_home,'etc','system','local','appinputs.conf') 
    deploy_apppath = os.path.join(spl.splunk_home,'etc','deployment-apps','linmess','default','inputs.conf') 
    cmd = 'cp {0} {1}'.format(apppath, deploy_apppath)
    assert spl.connection.execute(cmd)[0] == 0
    #spl.fileutils.copy_file(apppath,deploy_apppath) 
    #fileutils.force_remove_file(apppath) 
    spl._file_utils.force_remove_file(apppath)
    spl.confs().create('outputs') 
    spl.confs()['outputs'].create_stanza('tcpout') 
    spl.confs()['outputs']['tcpout']['defaultGroup'] = 'splunk1'
    spl.confs()['outputs'].create_stanza('tcpout:splunk1') 
    spl.confs()['outputs']['tcpout:splunk1']['server'] = 'localhost:9997'
    outputspath = os.path.join(spl.splunk_home,'etc','system','local','outputs.conf') 
    deploy_outputspath = os.path.join(spl.splunk_home,'etc','deployment-apps','linmess','default','outputs.conf') 
    cmd = 'cp {0} {1}'.format(outputspath, deploy_outputspath)
    assert spl.connection.execute(cmd)[0] == 0
    #fileutils.copy_file(outputspath,deploy_outputspath) 
    spl._file_utils.force_remove_file(outputspath) 
    LOGGER.info("Deployment Server: Reloading splunk")
    spl.execute("reload deploy-server -auth admin:changeme")
    #TODO remove hardcoded sleeps, add polling method
    time.sleep(60)
     
    def fin():
        try:
            spl.stop()
            spl.uninstall()
        except CouldNotStopSplunk:
            LOGGER.warn("Failed to tear down splunk instance {0}".format(spl))
    request.addfinalizer(fin)
    return spl 

@pytest.fixture(scope="module")
def splunkforwarders(request, splunk):
    '''
    Splunk forwarder instances
    '''
    CONFIG = pytest.config
    key = 'num_of_forwarders'
    if CONFIG.getvalue(key) is not None:
        nums = int(CONFIG.getvalue(key))
    else:
        nums = 2
    tempfile.tempdir = os.environ['HOME']
    LOGGER.info("Inside deployment client fixture")
    splfwders = []
    for aNum in range(nums):
        splunk_fwder_home = os.path.join(os.getenv("HOME"), "tmpfwder%s" % aNum)
        splfwders.append(LocalSplunk(splunk_fwder_home))
        LOGGER.info("Client: Installing forwarder from nightly")
        splfwders[aNum].install_nightly_forwarder(branch="current")
        splfwders[aNum].COMMON_FLAGS = splfwders[aNum].COMMON_FLAGS + ' --auto-ports'
        splfwders[aNum].restart()
        time.sleep(60)
        LOGGER.info("Client: Creating developmentclient.conf ")
        splfwders[aNum].confs().create('deploymentclient1')
        splfwders[aNum].confs()['deploymentclient1'].create_stanza('deployment-client')
        splfwders[aNum].confs()['deploymentclient1'].create_stanza('target-broker:deploymentServer') 
        splfwders[aNum].confs()['deploymentclient1']['target-broker:deploymentServer']['targetUri'] ='localhost:%s' % splunk.splunkd_port()
        oldname = os.path.join(splfwders[aNum].splunk_home,'etc','system','local','deploymentclient1.conf') 
        newname = os.path.join(splfwders[aNum].splunk_home,'etc','system','local','deploymentclient.conf') 
        os.rename(oldname,newname) 
        LOGGER.info("Client: Restarting forwarder, sleeping for 2 min for client to poll server")
        splfwders[aNum].restart() 
    #sleep for client to poll to the server
    time.sleep(120)
     
    def fin():
        for aNum in range(nums):
            try:
                splfwders[aNum].stop()
                splfwders[aNum].uninstall()
            except CouldNotStopSplunk:
                LOGGER.warn("Failed to tear down splunk instance {0}".format(splfwders[aNum]))
    request.addfinalizer(fin)
    return splfwders 

@pytest.fixture(scope="class")
def splunkforwarder(request, splunk):
    '''
    Splunk forwarder instance (Client)
    '''
    CONFIG = request.config
    if CONFIG.dc_hosts:
        spl_instance = SplunkInstance(request, CONFIG.dc_hosts)
    else:
        spl_instance = SplunkInstance(request)
    splfwder = spl_instance.new_remotesplunk()

    LOGGER.info("Client:Installing forwarder from nightly")
    splfwder.install_nightly_forwarder(branch='current')
    splfwder.COMMON_FLAGS = splfwder.COMMON_FLAGS + ' --auto-ports'
    splfwder.restart() 
    time.sleep(60) 
    LOGGER.info("Client:Creating deploymentclient.conf ")
    #Helmut Bug: can't create stanza deployment-client in deploymentclient.conf
    splfwder.confs().create('deploymentclient1')
    splfwder.confs()['deploymentclient1'].create_stanza('deployment-client') 
    splfwder.confs()['deploymentclient1'].create_stanza('target-broker:deploymentServer') 
    splfwder.confs()['deploymentclient1']['target-broker:deploymentServer']['targetUri'] \
        ='%s:%s' % (splunk.splunkd_host(), splunk.splunkd_port())
    oldname = os.path.join(splfwder.splunk_home,'etc','system','local','deploymentclient1.conf') 
    newname = os.path.join(splfwder.splunk_home,'etc','system','local','deploymentclient.conf') 
    if type(splfwder) is SSHSplunk:
        cmd = 'mv {0} {1}'.format(oldname, newname)
        assert splfwder.connection.execute(cmd)[0] == 0
    else:
        os.rename(oldname,newname) 
    LOGGER.info("Client:Restarting forwarder, sleeping for 2 min for client to poll server")
    #splfwder.restart() 
    splfwder.stop()
    splfwder.execute("clean locks -f")
    splfwder.start()
    splfwder.stop()
    splfwder.execute("clean locks -f")
    splfwder.start()
    #sleep for client to poll to the server
    time.sleep(120)
     
    def fin():
        try:
            splfwder.stop()
            splfwder.uninstall()
        except CouldNotStopSplunk:
            LOGGER.warn("Failed to tear down splunk instance {0}".format(splfwder))
    request.addfinalizer(fin)
    return splfwder 

@pytest.fixture(scope="class")
def splunkindexer(request):
    '''
     Splunk indexer instance 
    '''
    tempfile.tempdir = os.environ['HOME']
    LOGGER.info("Inside Deployment Indexer fixture")
    splunk_indexer_home = os.getenv("HOME") + os.sep + 'tmpindexer'
    splindxr = LocalSplunk(splunk_indexer_home)
    LOGGER.info("Indexer:Installing splunk from nightly")
    splindxr.install_nightly(branch='current')
    splindxr.COMMON_FLAGS = splindxr.COMMON_FLAGS + ' --auto-ports --answer-yes'
    #splindxr.restart() 
    splindxr.stop()
    splindxr.execute("clean locks -f")
    splindxr.start()
    splindxr.stop()
    splindxr.execute("clean locks -f")
    splindxr.start()
    time.sleep(60) 
    splindxr.execute('enable listen 9997 -auth admin:changeme')
    def fin():
        try:
            splindxr.stop()
            splindxr.uninstall()
        except CouldNotStopSplunk:
            LOGGER.warn("Failed to tear down splunk indexer {0}".format(splindxr))
    request.addfinalizer(fin)
    return splindxr 

@pytest.fixture(scope="function")
def handletest(request, splunk):
    '''
     This is setup & teardown. Creates serverclass and returns restconnector,
     cleans connector and serverclass in finalizer.
    ''' 
    LOGGER.info("Inside handletest")
    username = 'admin'
    password = request.config.option.password
    if not password: password = 'changeme'
    if ('admin', 'changeme') == (username, password):
        password = request.config.option.new_password or 'changed'
    splunk.create_logged_in_connector(contype=Connector.REST,
                                      username=username,
                                      password=password)
    restconn = splunk.connector(Connector.REST, 'admin')
    if len(restconn._service.credentials.__dict__['credentials'][0]) == 0:
        restconn._service.add_credentials(restconn._username,
                 restconn._password)
    resp, cont = restconn.make_request(
       'POST', '/services/deployment/server/serverclasses',
         {'name':'foobar2'})
    assert resp['status'] == '201' or resp['status'] == '500'
    def fin():
        try:
            LOGGER.info("Teardown: removing connectors")
            splunk.remove_connector(Connector.REST, 'admin') 
            resp, cont = restconn.make_request(
                'DELETE', '/services/deployment/server/serverclasses/foobar2')
            assert resp['status'] == '200'
        except Exception, err:
            LOGGER.warn("Failed to tear down rest connectors %s" % err)
    request.addfinalizer(fin)
    return restconn 

def load_yaml_file(yaml_file, abs_path = False):
    """
    Loads and returns a yaml file.

    Since most of the yaml files are requested multiple times,
    they are buffered into the conftest variable YAML_HOLDER.

    NOTE:
    Do not change the content in a configuration file, the
    modifications made is persistant throughout the test session.
    """
    yaml_file = yaml_file if abs_path else os.path.join(YAMLPATH, yaml_file)
    if not yaml_file in YAML_HOLDER:
        LOGGER.debug('Loading configuration from "' + yaml_file + '"')
        yaml_dic = yaml.load( open( yaml_file ) )
        for item in yaml_dic:
            LOGGER.info('item in yaml file: {key}: {value}'.format(key=item, value=str(yaml_dic[item])))
        YAML_HOLDER[yaml_file] = yaml_dic
    return YAML_HOLDER[yaml_file]

def load_global_configuration_file():
    """
    Loads the global configuration file into memory.
    """

    LOGGER.debug('yaml configuration file location: %s' % DEFAULT_CONFIG_FILE)
    return load_yaml_file(DEFAULT_CONFIG_FILE, True)
