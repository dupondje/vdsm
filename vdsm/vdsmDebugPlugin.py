#
# Copyright 2011 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Refer to the README and COPYING files for full details of the license
#

import os
import threading
import logging
from multiprocessing.managers import BaseManager

ADDRESS = "/var/run/vdsm/debugplugin.sock"
log = logging.getLogger("DebugInterpreter")

class DebugInterpreterManager(BaseManager): pass

class DebugInterpreter(object):
    def execute(self, code):
        exec(code)

def __turnOnDebugPlugin():
    log.warn("Starting Debug Interpreter. Tread lightly!")
    try:
        if os.path.exists(ADDRESS):
            os.unlink(ADDRESS)
        manager = DebugInterpreterManager(address=ADDRESS, authkey="KEY")
        interpreter = DebugInterpreter()
        manager.register('interpreter', callable=lambda:interpreter)
        server = manager.get_server()
        servThread = threading.Thread(target=server.serve_forever)
        servThread.setDaemon(True)
        servThread.start()
    except:
        log.error("Could not start debug plugin", exc_info=True)

__turnOnDebugPlugin()

