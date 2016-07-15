from copy import deepcopy
from collections import OrderedDict
import subprocess
import ConfigParser

from charmhelpers.contrib.openstack import (
    templating,
    context,
)

from charmhelpers.core.decorators import (
    retry_on_exception,
)

from charmhelpers.core.hookenv import (
    config,
    log
)


TEMPLATES = 'templates/'
VSM_CONF_DIR = "/etc/vsm"
VSM_CONF = '%s/vsm.conf' % VSM_CONF_DIR
PACKAGE_VSM = 'vsm'
PACKAGE_VSM_DASHBOARD = 'vsm-dashboard'
PACKAGE_PYTHON_VSMCLIENT = 'python-vsmclient'
PACKAGE_VSM_DEPLOY = 'vsm-deploy'
VSM_PACKAGES = [PACKAGE_VSM,
                PACKAGE_VSM_DEPLOY]
PRE_INSTALL_PACKAGES = ['ceph', 'ceph-mds', 'librbd1', 'rbd-fuse', 'radosgw',
                        'ntp', 'openssh-server', 'python-keystoneclient',
                        'expect', 'smartmontools']


BASE_RESOURCE_MAP = OrderedDict([
    (VSM_CONF, {
        'contexts': [context.SharedDBContext(),
                     context.AMQPContext()],
        'services': ['vsm-agent', 'vsm-physical']
    }),
])


def register_configs(release=None):
    """Register config files with their respective contexts.
    Regstration of some configs may not be required depending on
    existing of certain relations.
    """
    # if called without anything installed (eg during install hook)
    # just default to earliest supported release. configs dont get touched
    # till post-install, anyway.
    release = "vsm"
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)
    for cfg, rscs in resource_map().iteritems():
        configs.register(cfg, rscs['contexts'])
    return configs

def resource_map(release=None):
    """
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    """
    resource_map = deepcopy(BASE_RESOURCE_MAP)
    return resource_map

def restart_map():
    '''Determine the correct resource map to be passed to
    charmhelpers.core.restart_on_change() based on the services configured.

    :returns: dict: A dictionary mapping config file to lists of services
                    that should be restarted when file changes.
    '''
    return OrderedDict([(cfg, ['vsm-agent', 'vsm-physical'])
                        for cfg, v in resource_map().iteritems()])

# NOTE(jamespage): Retry deals with sync issues during one-shot HA deploys.
#                  mysql might be restarting or suchlike.
@retry_on_exception(5, base_delay=3, exc_type=subprocess.CalledProcessError)
def migrate_database():
    'Runs cinder-manage to initialize a new database or migrate existing'
    cmd = ['vsm-manage', 'db', 'sync']
    subprocess.check_call(cmd)

def service_enabled(service):
    '''Determine if a specific cinder service is enabled in
    charm configuration.

    :param service: str: cinder service name to query (volume, scheduler, api,
                         all)

    :returns: boolean: True if service is enabled in config, False if not.
    '''
    enabled = config()['enabled-services']
    if enabled == 'all':
        return True
    return service in enabled

def juju_log(msg):
    log('[vsm-agent] %s' % msg)

# TODO: refactor to use unit storage or related data
def auth_token_config(setting):
    """
    Returns currently configured value for setting in vsm.conf's
    authtoken section, or None.
    """
    config = ConfigParser.RawConfigParser()
    config.read('/etc/vsm/vsm.conf')
    try:
        value = config.get('keystone_authtoken', setting)
    except:
        return None
    if value.startswith('%'):
        return None
    return value
