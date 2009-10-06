#!/usr/bin/env python

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from optparse import OptionParser

import zkclient
from zkclient import ZKClient, TIMEOUT, SequentialCountingWatcher, zookeeper

usage = "usage: %prog [options]"
parser = OptionParser(usage=usage)
parser.add_option("", "--servers", dest="servers",
                  default="localhost:2181", help="comma separated list of host:port")
parser.add_option("-v", "--verbose",
                  action="store_true", dest="verbose", default=False,
                  help="verbose output, include more detail")
parser.add_option("-q", "--quiet",
                  action="store_true", dest="quiet", default=False,
                  help="quiet output, basically just success/failure")

(options, args) = parser.parse_args()

zkclient.options = options

zookeeper.set_log_stream(open("cli_log.txt","w"))

class SmokeError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


if __name__ == '__main__':
    servers = options.servers.split(",")

    # create all the sessions first to ensure that all servers are
    # at least available & quorum has been formed. otw this will 
    # fail right away (before we start creating nodes)
    sessions = []
    # create one session to each of the servers in the ensemble
    for i, server in enumerate(servers):
        sessions.append(ZKClient(server, TIMEOUT))

    # create on first server
    zk = ZKClient(servers[0], TIMEOUT)

    rootpath = "/zk-smoketest"

    if zk.exists(rootpath):
        if not options.quiet:
            print("Node %s already exists, attempting reuse" % (rootpath))
    else:
        zk.create(rootpath,
                  "smoketest root, delete after test done, created %s" %
                  (datetime.datetime.now().ctime()))

    # make sure previous cleaned up properly
    children = zk.get_children(rootpath)
    if len(children) > 0:
        raise SmokeError("there should not be children in %s"
                         "root data is: %s, count is %d"
                         % (rootpath, zk.get(rootpath), len(children)))

    zk.close()

    def child_path(i):
        return "%s/session_%d" % (rootpath, i)

    # create znodes, one znode per session (client), one session per server
    for i, server in enumerate(servers):
        # ensure this server is up to date with leader
        sessions[i].async()

        ## create child znode
        sessions[i].create(child_path(i), "", zookeeper.EPHEMERAL)

    watchers = []
    for i, server in enumerate(servers):
        # ensure this server is up to date with leader
        sessions[i].async()

        children = sessions[i].get_children(rootpath)
        if len(children) != len(sessions):
            raise SmokeError("server %s wrong number of children: %d" %
                             (server, len(children)))

        watchers.append(SequentialCountingWatcher(child_path))
        for child in children:
            sessions[i].get(rootpath + "/" + child, watchers[i])

    # trigger watches
    for i, server in enumerate(servers):
        sessions[i].delete(child_path(i))

    # check all watches fired
    for i, watcher in enumerate(watchers):
        # ensure this server is up to date with leader
        sessions[i].async()
        if watcher.waitForExpected(len(sessions), TIMEOUT) != len(sessions):
            raise SmokeError("server %s wrong number of watches: %d" %
                             (server, watcher.count))

    # close sessions
    for i, server in enumerate(servers):
        # ephemerals will be deleted automatically
        sessions[i].close()

    # cleanup root node
    zk = ZKClient(servers[-1], TIMEOUT)
    # ensure this server is up to date with leader (ephems)
    zk.async()
    zk.delete(rootpath)

    zk.close()

    print("Smoke test successful")
