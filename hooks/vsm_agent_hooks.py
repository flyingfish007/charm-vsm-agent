#!/usr/bin/python

import sys
import subprocess
import utils

from vsm_agent_utils import (
    initialize_ssh_keys,
    juju_log,
    register_configs,
    ssh_controller_key_add,
    PRE_INSTALL_PACKAGES,
    VSM_PACKAGES,
    VSM_CONF
)

from charmhelpers.contrib.openstack.utils import (
    get_host_ip,
    get_hostname
)

from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    network_get_primary_address,
    relation_get,
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
def agent_joined(relation_id=None):
    initialize_ssh_keys()
    host = unit_get('private-address')
    settings = {
        'hostname': get_hostname(host),
        'hostaddress': get_host_ip(host)
    }

    relation_set(relation_id=relation_id, **settings)


@hooks.hook('vsm-agent-relation-changed')
def agent_changed(rid=None, unit=None):
    if 'shared-db' not in CONFIGS.complete_contexts():
        juju_log('shared-db relation incomplete. Peer not ready?')
        return
    if 'amqp' not in CONFIGS.complete_contexts():
        juju_log('amqp relation incomplete. Peer not ready?')
        return

    rel_settings = relation_get(rid=rid, unit=unit)
    key = rel_settings.get('ssh_public_key')
    if not key:
        juju_log('peer did not publish key?')
        return
    ssh_controller_key_add(key, rid=rid, unit=unit)
    host = unit_get('private-address')
    hostname = get_hostname(host)
    hostaddress = get_host_ip(host)
    with open('/etc/hosts', 'a') as hosts:
        hosts.write('%s  %s' % (hostaddress, hostname) + '\n')

    token_tenant = rel_settings.get('token_tenant')
    rsync(
        charm_dir() + '/files/server.manifest',
        '/etc/manifest/server.manifest'
    )
    c_hostaddress = rel_settings.get('hostaddress')
    subprocess.check_call(['sudo', 'sed', '-i', 's/^controller_ip/%s/g' % c_hostaddress,
                           '/etc/manifest/server.manifest'])
    subprocess.check_call(['sudo', 'sed', '-i', 's/token-tenant/%s/g' % token_tenant,
                           '/etc/manifest/server.manifest'])
    subprocess.check_call(['sudo', 'service', 'vsm-agent', 'restart'])
    subprocess.check_call(['sudo', 'service', 'vsm-physical', 'restart'])


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        utils.juju_log('warn', 'Unknown hook {} - skipping.'.format(e))
