#
# Copyright 2020 Red Hat, Inc.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

from collections import namedtuple

import pytest

from vdsm import utils
from vdsm.common import commands
from vdsm.storage import sanlock_direct
from vdsm.storage import constants as sc

from . import userstorage
from .marks import requires_root

# Wait 1 second for lockspace initialization for quick tests.
INIT_LOCKSPACE_TIMEOUT = 1

Storage = namedtuple("Storage", "path, block_size, alignment")


@pytest.fixture(
    params=[
        pytest.param(
            (userstorage.PATHS["file-512"], sc.ALIGNMENT_1M),
            id="file-512-1m"),
        pytest.param(
            (userstorage.PATHS["file-4k"], sc.ALIGNMENT_2M),
            id="file-4k-2m"),
    ]
)
def storage(request):
    storage, alignment = request.param
    if not storage.exists():
        pytest.xfail("{} storage not available".format(storage.name))

    with open(storage.path, "wb") as f:
        f.truncate()

    yield Storage(storage.path, storage.sector_size, alignment)


@requires_root
@pytest.mark.root
def test_dump_leases(storage):
    block_size = storage.block_size
    align = storage.alignment

    # Test empty leases store.
    dump = sanlock_direct.dump_leases(
        path=storage.path,
        offset=0,
        size=None,
        block_size=block_size,
        alignment=align)
    assert list(dump) == []

    # Initialize lockspace.
    _write_lockspace("LS", storage.path, 0, block_size, align)

    # Add resources.
    _write_resource("LS", "RS1", storage.path, 1 * align, block_size, align)
    _write_resource("LS", "RS2", storage.path, 2 * align, block_size, align)
    _write_resource("LS", "RS3", storage.path, 3 * align, block_size, align)

    expected = [{
        "offset": i * storage.alignment,
        "lockspace": "LS",
        "resource": "RS{}".format(i),
        "timestamp": 0,
        "own": 0,
        "gen": 0,
        "lver": 0
    } for i in range(1, 4)]

    dump = sanlock_direct.dump_leases(
        path=storage.path,
        offset=0,
        size=4 * align,
        block_size=block_size,
        alignment=align)
    assert list(dump) == expected


@requires_root
@pytest.mark.root
def test_dump_ids(storage):
    block_size = storage.block_size
    align = storage.alignment

    # Test empty ids store.
    dump = sanlock_direct.dump_lockspace(
        path=storage.path,
        offset=0,
        size=None,
        block_size=block_size,
        alignment=align)
    assert list(dump) == []

    # Initialize lockspace.
    _write_lockspace("LS", storage.path, 0, block_size, align)
    # Add lockspace lease entry.
    _add_lockspace("LS", storage.path, 0, block_size, align)

    dump = list(sanlock_direct.dump_lockspace(
        path=storage.path,
        offset=0,
        size=None,
        block_size=block_size,
        alignment=align))

    assert len(dump) == 1
    rec = dump[0]
    assert rec["offset"] == 0
    assert rec["lockspace"] == "LS"
    assert rec["own"] == 1
    assert rec["gen"] == 1


@requires_root
@pytest.mark.root
def test_dump_hole(storage):
    block_size = storage.block_size
    align = storage.alignment

    # Initialize lockspace.
    _write_lockspace("LS", storage.path, 0, block_size, align)

    # Add resource lease at 1 alignment offset.
    _write_resource("LS", "RS1", storage.path, align, block_size, align)

    # Add second resource lease at 3 alignments offset,
    # leaving the second offset empty.
    _write_resource("LS", "RS2", storage.path, 3 * align, block_size, align)

    # Without specifiying size the dump stops at the hole.
    dump = sanlock_direct.dump_leases(
        path=storage.path,
        offset=0,
        size=None,
        block_size=block_size,
        alignment=align)
    resources = [rec["resource"] for rec in dump]
    assert resources == ["RS1"]

    # With specified size the dump passes the hole.
    dump = sanlock_direct.dump_leases(
        path=storage.path,
        offset=0,
        size=4 * align,
        block_size=block_size,
        alignment=align)
    resources = [rec["resource"] for rec in dump]
    assert resources == ["RS1", "RS2"]


def _write_lockspace(ls_name, dev, offset, block_size, alignment):
    args = [
        "-o", str(INIT_LOCKSPACE_TIMEOUT),
        "-s", "{}:1:{}:{}".format(ls_name, dev, offset)
    ]
    _sanlock_direct("init", args, block_size, alignment)


def _add_lockspace(ls_name, dev, offset, block_size, alignment):
    args = ["-s", "{}:1:{}:{}".format(ls_name, dev, offset)]
    _sanlock_direct("acquire_id", args, block_size, alignment)


def _write_resource(ls_name, rs_name, dev, offset, block_size, alignment):
    args = ["-r", "{}:{}:{}:{}".format(ls_name, rs_name, dev, offset)]
    _sanlock_direct("init", args, block_size, alignment)


def _sanlock_direct(cmd, args, block_size, alignment):
    options = [
        "-Z", str(block_size),
        "-A", str(alignment // sc.ALIGNMENT_1M) + "M"
    ]

    with utils.stopwatch("sanlock direct {} {}".format(cmd, args)):
        commands.run(
            [sanlock_direct.SANLOCK.cmd, "direct", cmd] + args + options)