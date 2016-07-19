from copy import deepcopy
from collections import OrderedDict
import os
import pwd
from subprocess import check_output

from charmhelpers.contrib.openstack import (
    templating,
    context,
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


def register_configs():
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


def resource_map():
    """
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    """
    r_map = deepcopy(BASE_RESOURCE_MAP)
    return r_map


def juju_log(msg):
    log('[vsm-agent] %s' % msg)


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
