#!/usr/bin/python2

import os
import sys
import hooking
import traceback
import fcntl
import ast
from xml.dom import minidom
try:
    # 3.0 compat
    import libvirtconnection
    libvirtconnection
except ImportError:
    # 3.1 compat
    from vdsm.common import libvirtconnection

'''
Placed in before_vm_start

vmfex hook:
Add Cisco VM-FEX Port Profile to Virtual Machine
since the only unique parameter passed from the engine to the VM is the
MAC, a dictionary-like mapping of MAC to port profile will be used
Sample:
vmfex={'00:11:22:33:44:55:66':'Profile1',
       '00:11:22:33:44:55:67':'Profile2',...} (one line)

Will add 2 virtual nics attached to profile1 and profile2 using
the vnic MAC addresses specified, replacing the actual NICs assigned
to the VM.

A VM NIC with a MAC that is not mentioned in this dictionary will not be
altered, and will remain attached to the bridge/logical network defined
for it in the engine.

Libvirt internals:
Replace the existing interface xml:
    <interface type="bridge">
        <mac address="<mac>"/>
        <model type="virtio"/>
        <source bridge="<logical network>"/>
    </interface>

with the following interface xml:
    <interface type='network'>
      <mac address='<mac>'/>
      <source network='direct-pool'/>
      <virtualport type='802.1Qbh'>
          <parameters profileid='<Port Profile>'/>
      </virtualport>
      <model type='virtio'/>
    </interface>

Dynamic network with libvirt (define a NIC pool, so libvirt can assign
VMs to NICs dynamically):

      <network>
        <name>direct-pool</name>
        <forward mode="passthrough">
          <interface dev="eth3"/>
          <interface dev="eth4"/>
          <interface dev="eth5"/>
          <interface dev="eth6"/>
          <interface dev="eth7"/>
          <interface dev="eth8"/>
          <interface dev="eth9"/>
          <interface dev="eth10"/>
          <interface dev="eth11"/>
        </forward>
      </network>

Using libvirt, the network is defined like this:

   virsh net-define /tmp/direct-pool.xml
   virsh net-start direct-pool
   virsh net-autostart direct-pool

(where /tmp/direct-pool.xml contains the xml above)

(everything else is autogenerated, and shouldn't be specified
when defining a guest (but whatever is there after definition
should be left in place, e.g. the PCI address)). Note that these
interface definitions are completely static - you never need to modify
them due to migration, or starting up/shutting down the guest.
'''


def getUsableNics():
    # Scan localhost for physical NICs and return list of physical nics
    # that have all zeroes MAC. These NICs are the ones that can be used
    # with VMFEX.
    # Example ['eth0','eth1']
    nics = []
    for root, dirs, names in os.walk('/sys/devices/'):
        if 'address' in names and 'pci' in root:
            with open(root + '/address', 'r') as f:
                mac = f.readlines()[0].strip()
            if mac == '00:00:00:00:00:00':
                eth = root.split('/')[-1]
                nics.append(eth)
    return nics


def createDirectPool(conn):
    if 'direct-pool' in conn.listNetworks():
        dpool = conn.networkLookupByName('direct-pool')
        # destroy and undefine direct-pool
        dpool.destroy()
        dpool.undefine()
        sys.stderr.write('vmfex: removed direct-pool \n')

    # create a new direct-pool
    xmlstr = '''<network>
        <name>direct-pool</name>
        <forward mode="passthrough">
    '''
    for i in getUsableNics():
        xmlstr += '<interface dev="' + i + '"/> \n'
    xmlstr += ' </forward> \n </network> '
    conn.networkDefineXML(xmlstr)
    dpool = conn.networkLookupByName('direct-pool')
    dpool.setAutostart(1)
    dpool.create()
    sys.stderr.write('vmfex: created Direct-Pool Net \n')
    sys.stderr.write(xmlstr + '\n')


def qbhInUse(conn):
    for vm in conn.listDomainsID():
        domxml = minidom.parseString(conn.lookupByID(vm).XMLDesc(0))
        for vport in domxml.getElementsByTagName('virtualport'):
            if vport.getAttribute('type') == '802.1Qbh':
                return True
    return False


def validateDPool(conn):
    # Compare direct-pool to the list of available NICs
    dpool = conn.networkLookupByName('direct-pool')
    definedNics = []
    dpoolxml = minidom.parseString(dpool.XMLDesc(0))
    for iface in dpoolxml.getElementsByTagName('interface'):
        definedNics.append(iface.getAttribute('dev'))
    if set(definedNics) == set(getUsableNics()):
        return True
    else:
        return False


def handleDirectPool(conn):
    with open('/var/run/vdsm/hook-vmfex.lock', 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            if 'direct-pool' not in conn.listNetworks():
                createDirectPool(conn)

            elif not qbhInUse(conn) and not validateDPool(conn):
                createDirectPool(conn)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


if 'vmfex' in os.environ:
    try:
        sys.stderr.write('vmfex: starting to edit VM \n')
        # connect to libvirtd and handle the direct-pool network
        conn = libvirtconnection.get()
        handleDirectPool(conn)
        # Get the vmfex line
        vmfex = os.environ['vmfex']
        sys.stderr.write('vmfex: customProperty: ' + str(vmfex) + '\n')
        # convert to dictionary
        vmfexd = ast.literal_eval(vmfex)
        # make sure the keys are lowercase
        vmfexd = dict((k.lower(), v) for k, v in vmfexd.iteritems())
        # Get the VM's xml definition
        domxml = hooking.read_domxml()

        for iface in domxml.getElementsByTagName('interface'):
            mac = iface.getElementsByTagName('mac')[0]
            macaddr = mac.getAttribute('address').lower()
            if macaddr in vmfexd:
                profile = vmfexd[macaddr]
                iface.setAttribute('type', 'network')
                source = iface.getElementsByTagName('source')[0]
                source.removeAttribute('bridge')
                source.setAttribute('network', 'direct-pool')
                virtualport = domxml.createElement('virtualport')
                virtualport.setAttribute('type', '802.1Qbh')
                iface.appendChild(virtualport)
                parameters = domxml.createElement('parameters')
                parameters.setAttribute('profileid', profile)
                virtualport.appendChild(parameters)
        hooking.write_domxml(domxml)
    except:
        sys.stderr.write('vmfex: ERROR %s\n' % traceback.format_exc())
        sys.exit(2)
