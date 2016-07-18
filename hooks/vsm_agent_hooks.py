#!/usr/bin/python

import sys
import subprocess
import utils

from vsm_agent_utils import (
    auth_token_config,
    initialize_ssh_keys,
    juju_log,
    migrate_database,
    public_ssh_key,
    register_configs,
    service_enabled,
    PRE_INSTALL_PACKAGES,
    VSM_PACKAGES,
    VSM_CONF
)

from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    network_get_primary_address,
    open_port,
    relation_set,
    unit_get,
    UnregisteredHookError,
    Hooks
)

from charmhelpers.core.host import (
    rsync
)

from charmhelpers.fetch import (
    add_source,
    apt_install,
    apt_update
)

from socket import gethostname

hooks = Hooks()

CONFIGS = register_configs()


@hooks.hook('install.real')
def install():
    juju_log('**********install.real')
    rsync(
        charm_dir() + '/packages/vsm-dep-repo',
        '/opt'
    )
    rsync(
        charm_dir() + '/packages/vsmrepo',
        '/opt'
    )
    rsync(
        charm_dir() + '/files/apt.conf',
        '/etc/apt'
    )
    rsync(
        charm_dir() + '/files/vsm.list',
        '/etc/apt/sources.list.d'
    )
    rsync(
        charm_dir() + '/files/vsm-dep.list',
        '/etc/apt/sources.list.d'
    )
    apt_update()
    apt_install(VSM_PACKAGES)
    juju_log('**********finished to install vsm')
    add_source(config('ceph-source'), config('ceph-key'))
    apt_update(fatal=True)
    apt_install(packages=PRE_INSTALL_PACKAGES, fatal=True)


@hooks.hook('shared-db-relation-joined')
def db_joined(relation_id=None):
    juju_log('**********shared-db-relation-joined')
    try:
        # NOTE: try to use network spaces
        host = network_get_primary_address('shared-db')
    except NotImplementedError:
        # NOTE: fallback to private-address
        host = unit_get('private-address')
    conf = config()
    relation_set(database=conf['database'],
                 username=conf['database-user'],
                 hostname=host,
                 relation_id=relation_id)


@hooks.hook('shared-db-relation-changed')
def db_changed():
    juju_log('**********shared-db-relation-changed')
    juju_log('**********CONFIGS.complete_contexts(): %s' % str(CONFIGS.complete_contexts()))
    if 'shared-db' not in CONFIGS.complete_contexts():
        juju_log('shared-db relation incomplete. Peer not ready?')
        return
    juju_log('**********CONFIGS is %s' % str(CONFIGS))
    CONFIGS.write(VSM_CONF)


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    juju_log('**********amqp-relation-joined')
    juju_log('**********relation_id is %s' % str(relation_id))
    conf = config()
    relation_set(relation_id=relation_id,
                 username=conf['rabbit-user'], vhost=conf['rabbit-vhost'])


@hooks.hook('amqp-relation-changed')
def amqp_changed():
    juju_log('**********amqp-relation-changed')
    if 'amqp' not in CONFIGS.complete_contexts():
        juju_log('amqp relation incomplete. Peer not ready?')
        return
    juju_log('**********CONFIGS is %s' % str(CONFIGS))
    CONFIGS.write(VSM_CONF)


@hooks.hook('vsm-agent-relation-joined')
def agent_joined(rid=None):
    initialize_ssh_keys()

    settings = {
        'hostname': gethostname()
    }

    settings['ssh_public_key'] = public_ssh_key()
    relation_set(relation_id=rid, **settings)


@hooks.hook('vsm-agent-relation-changed')
def agent_changed():
    CONFIGS.write_all()


def keystone_agent_settings():
    ks_auth_config = _auth_config()
    rel_settings = {}
    rel_settings.update(ks_auth_config)
    return rel_settings

def _auth_config():
    '''Grab all KS auth token config from vsm.conf, or return empty {}'''
    cfg = {
        'service_host': auth_token_config('identity_uri').split('/')[2].split(':')[0],
        'admin_user': auth_token_config('admin_user'),
        'admin_password': auth_token_config('admin_password')
    }
    return cfg


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        utils.juju_log('warn', 'Unknown hook {} - skipping.'.format(e))
