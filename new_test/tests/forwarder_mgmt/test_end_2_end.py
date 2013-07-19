"""
Meta
====
    $Id: //splunk/current/new_test/tests/forwarder_mgmt/test_end_2_end.py#4 $
    $DateTime: 2013/06/26 20:04:47 $
    $Author: wma $
    $Change: 169437 $
"""

import logging
import pytest
import time
import os
import feedparser
import glob
import shutil
import json

from helmut.connector.base import Connector
from helmut.util import fileutils

from conftest import params

LOGGER = logging.getLogger('TestEnd2End')

class TestEnd2End(object):
    uname = 'admin'
    passwd = 'changeme'

    def setup_method(self, splunk):
        pass

    def teardown_method(self, splunk):
        pass

    @pytest.mark.usefixtures("splunk", "splunkforwarders", "handletest")
    def test_large_number_apps(self, splunk, splunkforwarders,
                               handletest):
        '''
        One DS and multiple DCs, and test apps get pushed out
        '''
        LOGGER.info("Test test_large_number_apps")
        LOGGER.info("Number of DCs: %s" % len(splunkforwarders))
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=self.uname,
                                          password=self.passwd)
        restconn = splunk.connector(Connector.REST, self.uname)
        time.sleep(60)
        num_of_apps = 100
        # Create 100 apps
        for aApp in range(num_of_apps):
            app_name = 'wma-app_test%s' % aApp
            app_args = {'name' : app_name, 'label' : app_name, \
                        'template' : 'sample_app', 'visible' : '1', \
                        'version' : '1.0'}
            response, content = restconn.make_request('POST', \
                                '/services/apps/local', app_args)
            assert response['status'] == '201'
            # Copy two apps from /etc/apps to /etc/deployment-apps
            source_dir = os.path.join(splunk.splunk_home, 'etc', 'apps', \
                                      app_name)
            dest_dir = os.path.join(splunk.splunk_home, 'etc', \
                       'deployment-apps', source_dir.split(os.sep)[-1])
            fileutils.copy_directory(source_dir, dest_dir)
        # Need a restart
        splunk.restart()

        # Create a new serverclass
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=self.uname,
                                          password=self.passwd)
        restconn = splunk.connector(Connector.REST, self.uname)
        url_args = {'name': 'sc_test'}
        response, content = restconn.make_request('POST', \
            '/services/deployment/server/serverclasses', url_args)
        assert response['status'] == '201'
        # Map apps to sc_test
        for aApp in range(num_of_apps):
            app_name = 'wma-app_test%s' % aApp
            url_args = {'restartSplunkWeb': 'false', 'restartSplunkd': 'false', \
                        'stateOnClient': 'disabled', 'serverclass': 'sc_test'}
            response, content = restconn.make_request('POST', \
                '/services/deployment/server/applications/%s' \
                % app_name, url_args)
            assert response['status'] == '200'
        # Check apps on clients
        tries = 30
        time_to_wait = 40
        for aTry in range(tries):
            total_count = 0
            for aClient in splunkforwarders:
                aClient.create_logged_in_connector(contype=Connector.REST,
                                                   username=self.uname,
                                                   password=self.passwd)
                restconn = aClient.connector(Connector.REST, self.uname)
                for aApp in range(num_of_apps):
                    app_name = 'wma-app_test%s' % aApp
                    url_args = {'output_mode' : 'json'}
                    response, content = restconn.make_request('GET', \
                        '/services/apps/local', url_args)
                    if app_name in content: total_count += 1
            if total_count == len(splunkforwarders) * num_of_apps:
                LOGGER.info("Found all apps on all clients.")
                break
            elif aTry <= tries:
                time.sleep(time_to_wait)
            else:
                LOGGER.info("Not all apps shown on all clients in %s seconds." \
                            % 30 * 40)
                assert total_count == len(splunkforwarders) * num_of_apps


    @pytest.mark.usefixtures("splunk", "splunkforwarder", "handletest")
    def test_deployed_apps_column(self, splunk, splunkforwarder,
                                  handletest):
        '''
        One DS and one DC, test app status
        '''
        LOGGER.info("Test test_deployed_apps_column")
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=self.uname,
                                          password=self.passwd)
        restconn = splunk.connector(Connector.REST, self.uname)
        # Delete 100 apps
        num_of_apps = 100
        for aApp in range(num_of_apps):
            app_name = 'wma-app_test%s' % aApp
            response, content = restconn.make_request('DELETE', \
                                '/services/apps/local/%s' % app_name)
            assert response['status'] == '200'
        time.sleep(60)
        # Create two apps
        app1_args = {'name': 'wma-app_test1', 'label': 'wma-app_test1', \
                     'template': 'sample_app', 'visible': '1', 'version': '1.0'}
        app2_args = {'name': 'wma-app_test2', 'label': 'wma-app_test2', \
                     'template': 'sample_app', 'visible': '1', 'version': '1.0'}
        response, content = restconn.make_request('POST', \
                                          '/services/apps/local', app1_args)
        assert response['status'] == '201'
        response, content = restconn.make_request('POST', \
                                          '/services/apps/local', app2_args)
        assert response['status'] == '201'
        # Copy two apps from /etc/apps to /etc/deployment-apps
        source_dir = os.path.join(splunk.splunk_home, 'etc', 'apps', \
                                  'wma-app_test1')
        dest_dir = os.path.join(splunk.splunk_home, 'etc', \
                  'deployment-apps', source_dir.split(os.sep)[-1])
        fileutils.copy_directory(source_dir, dest_dir)
        source_dir = os.path.join(splunk.splunk_home, 'etc', \
                                  'apps', 'wma-app_test2')
        dest_dir = os.path.join(splunk.splunk_home, 'etc', 'deployment-apps', \
                                source_dir.split(os.sep)[-1])
        fileutils.copy_directory(source_dir, dest_dir)
        # Need a restart
        splunk.restart()

        # Create a new serverclass
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=self.uname,
                                          password=self.passwd)
        restconn = splunk.connector(Connector.REST, self.uname)
        url_args = {'name': 'sc_new'}
        response, content = restconn.make_request('POST', \
            '/services/deployment/server/serverclasses', url_args)
        assert response['status'] == '201'
        # Map wma-app_test1 and wma-app_test2 to sc_new
        url_args = {'restartSplunkWeb': 'false', 'restartSplunkd': 'false', \
                    'stateOnClient': 'disabled', 'serverclass': 'sc_new'}
        response, content = restconn.make_request('POST', \
            '/services/deployment/server/applications/%s' \
            % 'wma-app_test1', url_args)
        assert response['status'] == '200'
        response, content = restconn.make_request('POST', \
            '/services/deployment/server/applications/%s' \
            % 'wma-app_test2', url_args)
        assert response['status'] == '200'

        # Query list of clients which belong to servervlass sc_new
        url_args = {'serverclasses': 'sc_new'}
        response, content = restconn.make_request('GET', \
            '/services/deployment/server/clients', url_args)
        assert response['status'] == '200'

        # chmod bundles to '0000'
        bundle_loc = os.path.join(splunkforwarder.splunk_home, \
            'var', 'run', 'sc_new', 'wma-app_test1*.bundle')
        paths = glob.glob(bundle_loc)
        for aPath in paths:
            os.chmod(aPath, 0)
        # Remove an installed app
        path_to_app = os.path.join(splunkforwarder.splunk_home, \
                                   'etc', 'apps', 'wma-app_test1')
        tries = 30
        time_to_wait = 30
        for aTry in range(tries):
            try:
                shutil.rmtree(path_to_app)
                break
            except OSError, e:
                if aTry < tries:
                    time.sleep(time_to_wait)
                else:
                    raise e

        # Check DS on an unsuccessful install
        tries = 30
        time_to_wait = 30
        url_args = {'hasDeploymentError': 'false'}
        for aTry in range(tries):
            response, content = restconn.make_request('GET', \
                '/services/deployment/server/applications', url_args)
            assert response['status'] == '200'
            break
            try:
                assert 'wma-app_test1' not in content
                break
            except AssertionError, e:
                if aTry < tries:
                    time.sleep(time_to_wait)
                else:
                    raise e

    @pytest.mark.usefixtures("splunk", "splunkforwarder", "handletest")
    def test_clean_artifacts_cmd(self, splunk, splunkforwarder,
                                 handletest):
        '''
        One DS and one DC, run "splunk clean deployment-artifacts" command
        on both DS and DC, and check their effect
        '''
        LOGGER.info("Test test_clean_artifacts_cmd")
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=handletest.username,
                                          password=handletest.password)
        restconn = splunk.connector(Connector.REST, handletest.username)
        time.sleep(60)
        num_of_apps = 10
        # Create 100 apps
        for aApp in range(num_of_apps):
            app_name = 'wma-app_test%s' % aApp
            app_args = {'name' : app_name, 'label' : app_name, \
                        'template' : 'sample_app', 'visible' : '1', \
                        'version' : '1.0'}
            response, content = restconn.make_request('POST', \
                                '/services/apps/local', app_args)
            assert response['status'] == '201'
            # Copy two apps from /etc/apps to /etc/deployment-apps
            source_dir = os.path.join(splunk.splunk_home, 'etc', 'apps', \
                                      app_name)
            dest_dir = os.path.join(splunk.splunk_home, 'etc', \
                       'deployment-apps', source_dir.split(os.sep)[-1])
            cmd = 'cp -r {0} {1}'.format(source_dir, dest_dir)
            assert splunk.connection.execute(cmd)[0] == 0
            #fileutils.copy_directory(source_dir, dest_dir)
        # Need a restart
        splunk.restart()

        # Create a new serverclass
        splunk.create_logged_in_connector(contype=Connector.REST,
                                          username=handletest.username,
                                          password=handletest.password)
        restconn = splunk.connector(Connector.REST, handletest.username)
        url_args = {'name': 'sc_test'}
        response, content = restconn.make_request('POST', \
            '/services/deployment/server/serverclasses', url_args)
        assert response['status'] == '201'
        # Map apps to sc_test
        for aApp in range(num_of_apps):
            app_name = 'wma-app_test%s' % aApp
            url_args = {'restartSplunkWeb': 'false', 'restartSplunkd': 'false', \
                        'stateOnClient': 'disabled', 'serverclass': 'sc_test'}
            response, content = restconn.make_request('POST', \
                '/services/deployment/server/applications/%s' \
                % app_name, url_args)
            assert response['status'] == '200'
        # Check apps on clients
        tries = 30
        time_to_wait = 40
        for aTry in range(tries):
            total_count = 0
            splunkforwarder.create_logged_in_connector(contype=Connector.REST,
                                                       username=self.uname,
                                                       password=self.passwd)
            restconn = splunkforwarder.connector(Connector.REST, self.uname)
            for aApp in range(num_of_apps):
                app_name = 'wma-app_test%s' % aApp
                url_args = {'output_mode' : 'json'}
                response, content = restconn.make_request('GET', \
                    '/services/apps/local', url_args)
                if app_name in content: total_count += 1
            if total_count == num_of_apps:
                LOGGER.info("Found all apps on all clients.")
                break
            elif aTry <= tries:
                time.sleep(time_to_wait)
            else:
                LOGGER.info("Not all apps shown on all clients in %s seconds." \
                            % 30 * 40)
                assert total_count == num_of_apps
        # Run the clean deployment-artifacts command on DS
        splunk.stop()
        cmd  = ' clean deployment-artifacts -auth %s:%s' % (handletest.username, \
               handletest.password)
        assert splunk.execute(cmd)[0] == 0
        splunk.stop()
        path_to_bundle = os.path.join(splunk.splunk_home, 'var', 'run', 'tmp')
        assert not 'bundle' in splunk.connection.execute('ls %s' % \
                               path_to_bundle)[1]
        splunkforwarder.stop()
        cmd  = ' clean deployment-artifacts -auth %s:%s' % (self.uname, \
               self.passwd)
        assert splunkforwarder.execute(cmd)[0] == 0
        path_to_bundle = os.path.join(splunkforwarder.splunk_home, \
                         'var', 'run', 'sc_test')
        assert not 'bundle' in splunkforwarder.execute('ls -R %s' % \
                               path_to_bundle)[1]
        path_to_bundle = os.path.join(splunkforwarder.splunk_home, 'etc', 'apps')
        assert not 'wma-app_test' in splunkforwarder.execute('ls \
                                     -R %s' % path_to_bundle)[1]
