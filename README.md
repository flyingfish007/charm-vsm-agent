# charm-vsm-agent
Charm of juju for Virtual-Storage-Manager(VSM) Agent.
- VSM consists of vsm-controller and vsm-agent nodes.
- The charm aims to deploy the vsm-agent with vsm-agent and vsm-physical.

### Prepare
* You should install the juju by youself at first [juju](https://jujucharms.com/).

### Steps of Install from Source
```sh
$ cd ~
$ mkdir -p charms/trusty
$ cd charms/trusty
$ git clone https://github.com/flyingfish007/charm-vsm-agent.git
$ mv charm-vsm-agent vsm-agent
$ juju deploy --repository=$HOME/charms local:trusty/vsm-agent
```
