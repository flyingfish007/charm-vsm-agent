from copy import deepcopy
from collections import OrderedDict
import os
import pwd
import subprocess
from subprocess import (
    check_output
)
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
    log,
    relation_get
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

def public_ssh_key(user='root'):
    home = pwd.getpwnam(user).pw_dir
    try:
        with open(os.path.join(home, '.ssh', 'id_rsa.pub')) as key:
            return key.read().strip()
    except:
        return None


def initialize_ssh_keys(user='root'):
    home_dir = pwd.getpwnam(user).pw_dir
    ssh_dir = os.path.join(home_dir, '.ssh')
    if not os.path.isdir(ssh_dir):
        os.mkdir(ssh_dir)

    priv_key = os.path.join(ssh_dir, 'id_rsa')
    if not os.path.isfile(priv_key):
        log('Generating new ssh key for user %s.' % user)
        cmd = ['ssh-keygen', '-q', '-N', '', '-t', 'rsa', '-b', '2048',
               '-f', priv_key]
        check_output(cmd)

    pub_key = '%s.pub' % priv_key
    if not os.path.isfile(pub_key):
        log('Generating missing ssh public key @ %s.' % pub_key)
        cmd = ['ssh-keygen', '-y', '-f', priv_key]
        p = check_output(cmd).strip()
        with open(pub_key, 'wb') as out:
            out.write(p)
    check_output(['chown', '-R', user, ssh_dir])

def import_authorized_keys(user='root', prefix=None):
    """Import SSH authorized_keys + known_hosts from a cloud-compute relation.
    Store known_hosts in user's $HOME/.ssh and authorized_keys in a path
    specified using authorized-keys-path config option.
    """
    known_hosts = []
    authorized_keys = []
    if prefix:
        known_hosts_index = relation_get(
            '{}_known_hosts_max_index'.format(prefix))
        if known_hosts_index:
            for index in range(0, int(known_hosts_index)):
                known_hosts.append(relation_get(
                                   '{}_known_hosts_{}'.format(prefix, index)))
        authorized_keys_index = relation_get(
            '{}_authorized_keys_max_index'.format(prefix))
        if authorized_keys_index:
            for index in range(0, int(authorized_keys_index)):
                authorized_keys.append(relation_get(
                    '{}_authorized_keys_{}'.format(prefix, index)))
    else:
        # XXX: Should this be managed via templates + contexts?
        known_hosts_index = relation_get('known_hosts_max_index')
        if known_hosts_index:
            for index in range(0, int(known_hosts_index)):
                known_hosts.append(relation_get(
                    'known_hosts_{}'.format(index)))
        authorized_keys_index = relation_get('authorized_keys_max_index')
        if authorized_keys_index:
            for index in range(0, int(authorized_keys_index)):
                authorized_keys.append(relation_get(
                    'authorized_keys_{}'.format(index)))

    # XXX: Should partial return of known_hosts or authorized_keys
    #      be allowed ?
    if not len(known_hosts) or not len(authorized_keys):
        return
    homedir = pwd.getpwnam(user).pw_dir
    dest_auth_keys = config('authorized-keys-path').format(
        homedir=homedir, username=user)
    dest_known_hosts = os.path.join(homedir, '.ssh/known_hosts')
    log('Saving new known_hosts file to %s and authorized_keys file to: %s.' %
        (dest_known_hosts, dest_auth_keys))

    with open(dest_known_hosts, 'wb') as _hosts:
        for index in range(0, int(known_hosts_index)):
            _hosts.write('{}\n'.format(known_hosts[index]))
    with open(dest_auth_keys, 'wb') as _keys:
        for index in range(0, int(authorized_keys_index)):
            _keys.write('{}\n'.format(authorized_keys[index]))

def ssh_controller_key_add(public_key, rid=None, unit=None, user='root'):
    private_address = relation_get(rid=rid, unit=unit,
                                   attribute='private-address')
    if not ssh_authorized_key_exists(public_key, user):
        log('Saving SSH authorized key for controller host at %s.' %
            private_address)
        add_authorized_key(public_key, user)

def ssh_authorized_key_exists(public_key, user='root'):
    homedir = pwd.getpwnam(user).pw_dir
    dest_auth_keys = config('authorized-keys-path').format(
        homedir=homedir, username=user)
    with open(dest_auth_keys) as keys:
        return (' %s ' % public_key) in keys.read()

def add_authorized_key(public_key, user='root'):
    homedir = pwd.getpwnam(user).pw_dir
    dest_auth_keys = config('authorized-keys-path').format(
        homedir=homedir, username=user)
    with open(dest_auth_keys, 'a') as keys:
        keys.write(public_key + '\n')
