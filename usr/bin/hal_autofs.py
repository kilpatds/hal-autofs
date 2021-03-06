#!/usr/bin/python

import re, os, sys, glob, resource, subprocess
import dbus, gobject
import logging, logging.handlers
from optparse import OptionParser

if getattr(dbus, 'version', (0,0,0)) >= (0,80,0):
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
elif getattr(dbus, 'version', (0,0,0)) >= (0,41,0):
    import dbus.glib

def daemonize():
    # Daemonize
    try:
        pid = os.fork()
    except OSError, e:
        raise Exception, "%s [%d]" % (e.strerror, e.errno)

    if (pid == 0):
        os.setsid()
        try:
            pid = os.fork()
        except OSError, e:
            raise Exception, "%s [%d]" % (e.strerror, e.errno)
        if (pid == 0):
            os.chdir("/")
            os.umask(022)
        else:
            os._exit(0)
    else:
        os._exit(0)

    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if (maxfd == resource.RLIM_INFINITY):
        maxfd = MAXFD

    for fd in range(0,maxfd):
        try:
            os.close(fd)
        except OSError: # not already open.  ignore
            pass

    os.open("/dev/null", os.O_RDWR)
    os.dup2(0, 1)
    os.dup2(0, 2)

callout_pattern    = re.compile("hald-autofs")
mount_name_pattern = re.compile("\W")

bus              = None         # dbus object
options          = None

devices          = {}           # indexed by udi
dev_by_dev       = {}           # indexed by /dev file

cd_index         = 0            # cdrom, cdrom1, cdrom2, ...
dve_index        = 0
vol_index        = 0

desk_to_launcher = {
    'kde' :    "kfmclient openProfile filemanagement %(URL)s",
    'kde4' :   "dolphin %(PATH)s",
    'gnome' :  "nautilus -n %(PATH)s"
}

desktop_environment = ""

type_to_icon     = {
    'cdrom':   "cdrom_unmount",
    'disk':    "usbpendrive_unmount",
    'ipod':    "ipod_unmount",
    'default': "hdd_unmount",
    'sd_mmc':  "media-flash-sd"
}

desktop          = os.path.expanduser('~/Desktop/')
desktop_template = """
[Desktop Entry]
Name=%(NAME)s
Type=Application
Exec=%(LAUNCHER)s
Icon=%(ICON)s
GenericName=Device Link
Terminal=false
Version=1.0
X-AUTOFS-HAL=true
"""

def get_name(props,proposed = False):
    """Given a hal object, figures out where we should mount it"""
    global vol_index,cd_index
    order = [ "volume.policy.desired_mount_point",
              "storage.policy.desired_mount_point",
              "volume.label" ]
    for key in order:
        if key in props and len(props[key]) > 0:
            if not proposed:
                logging.info("get_name("+props['block.device']+") = '" +
                        mount_name_pattern.sub("_",props[key])+"'!")
            return (mount_name_pattern.sub("_",props[key]),True)
    # er?
    base = ""
    if (props.has_key('volume.is_disc') and props['volume.is_disc']
            or (props.has_key('storage.drive_type') and
                props['storage.drive_type'] == 'cdrom')):
        if cd_index > 0:
            base = 'cdrom' + str(cd_index)
        else:
            base = 'cdrom'
        if not proposed:
            cd_index += 1
    else:
        base = 'volume' + str(vol_index)
        if not proposed:
            vol_index += 1
    if not proposed:
        logging.info("get_name("+props['block.device']+") = '" + base +"'?")
    return (base,False)

def device_filter(udi):
    global devices, dev_by_dev, bus
    volume = bus.get_object('org.freedesktop.Hal', udi)
    deviface = dbus.Interface(volume, 'org.freedesktop.Hal.Device')
    props = deviface.GetAllProperties()

    if not "block.device" in props:
        logging.info("can't find device: " + udi)
        return False

    device = props['block.device']

    if not "block.storage_device" in props:
        logging.info("can't find parent: " + udi + device)
        return False

    if (props['block.storage_device'] == udi and
            "storage.drive_type" in props and
            props['storage.drive_type'] != 'cdrom'):
        logging.info("skipping: parent same as device: " + udi + device)
        return False

    # we need certain properties from the storage device
    volume = bus.get_object('org.freedesktop.Hal',props['block.storage_device'])
    deviface = dbus.Interface(volume, 'org.freedesktop.Hal.Device')
    block_props = deviface.GetAllProperties()

    hotplug = 1
    removable = 1

    if ('storage.hotpluggable' in block_props) and (
            block_props['storage.hotpluggable'] != True):
        hotplug = 0
    if ('storage.removable' in block_props) and (
            block_props['storage.removable'] != True):
        removable = 0

    if (not hotplug and not removable):
        logging.info("not hotpluggable or removable: " + udi + ":" + device +
                   ":" + repr(block_props['storage.hotpluggable']))
        return False

    if ('volume.fsusage' in props                   and 
            props['volume.fsusage'] != 'filesystem' and
            props['volume.fsusage'] != ''):
        logging.info("didn't like fsusage: " + props['volume.fsusage']
                     + "\n\t" + udi + ":" + device)
        return False

    block = None
    if device in dev_by_dev:
        block = dev_by_dev[device]
    else:
        mount_name = mount_name_pattern.sub("_",device)
        block      = { 'device': device, 'mount_name': mount_name }

    if not 'fGood_name' in block:
        (name,fGood_name) = get_name(props,True)
        if fGood_name or not 'name' in block:
            (name,fGood_name)   = get_name(props,False)
            block['name']       = name
            block['fGood_name'] = fGood_name

    if not 'type' in block:
        if 'portable_audio_player.type' in block_props:
            block['type'] = 'ipod'
        elif "storage.drive_type" in block_props:
            block['type'] = block_props['storage.drive_type']
        else:
            block['type'] = 'default'

    if not ('fGood_fs' in block and block['fGood_fs']):
        if ('volume.fstype' in props and
                props['volume.fstype'] != ''):
            block['fs']       = props['volume.fstype']
            block['fGood_fs'] = True
        else:
            block['fs']      = 'auto'
            block['fGood_fs'] = False

    str = "Adding " + device + ":" + udi + " as '" + block['name'] + "'"
    if block['fGood_name']:
        str += "!"
    logging.info(str)

    devices[udi] = dev_by_dev[device] = block

    return True

def rewrite_autofs_file():
    global options
    if (not options.server):
        return False

    f = open("/etc/auto.hal", 'w'); # throws exception

    f.write("#\n# Autogenerated by hald_autofs.py\n#\n")
    for device,block in dev_by_dev.iteritems():
        if not block['active']:
            continue
        mount_options = "-fstype="+block['fs']+",nosuid,nodev"
        if block['fs'].find('fat') > -1:
            mount_options += ",uid=nobody,gid=users,umask=117,dmask=007"
        f.write(
                block['mount_name']
              + "\t" + mount_options
              + "\t:" + block['device']+"\n")
        if block['name'] != block['mount_name']:
            f.write(
                    block['name']
                + "\t" + mount_options
                + "\t:" + block['device']+"\n")
    f.close();

    # HUP autofs
    p = subprocess.Popen(["/sbin/service","autofs","reload"],
        stdout=subprocess.PIPE, close_fds=True)
    (stdout,stderr) = p.communicate();
    if stderr is not None:
        logging.warn("service stderr: %s" % stderr)
    if stdout is not None:
        logging.info("service stdout: %s" % stdout)

    return True

# Added
def device_added_desktop(udi):
    global desktop, desktop_template, mount_name_pattern, desk_to_launcher, desktop_environment

    if not device_filter(udi):
        return

    name       = devices[udi]['name']
    mount_name = devices[udi]['mount_name']
    url = "file:///misc/" + mount_name

    path = desktop + mount_name +  '.desktop'
    f = open(path, 'w')
    # New security policy... has to be +x to work.  Comes w/ newer python though
    try:
        os.fchmod(f.fileno(),0744)
    except (AttributeError):
        pass
    exec_str = desk_to_launcher[desktop_environment] % {
        'URL':url, 'PATH':("/misc/"+mount_name) };
    text = desktop_template % {
        'NAME':name, 'LAUNCHER':exec_str,
        'ICON':type_to_icon[devices[udi]['type']] };
    f.write(text);
    f.close();

    devices[udi]['path']   = path
    devices[udi]['active'] = True
    return 0

def device_added_server(udi):
    if not device_filter(udi):
        return
    devices[udi]['active'] = True
    rewrite_autofs_file()
    return 0

def device_added_callback(udi):
    global options 
    if options.server:
        return device_added_server(udi)
    else:
        return device_added_desktop(udi)

# Removed
def device_removed_server(udi):
    if not udi in devices:
        return
    devices[udi]['active'] = 0
    rewrite_autofs_file()
    return 0

def device_removed_desktop(udi):
    global options
    if not udi in devices:
        return
    if options.verbose:
        logging.info("nuking file " + devices[udi]['path'])
    os.unlink(devices[udi]['path'])
    devices[udi]['active'] = 0

def device_removed_callback(udi):
    global options
    if options.server: # root
        return device_removed_server(udi)
    else:
        return device_removed_desktop(udi)

def main():
    global options, bus, desktop_environment

    parser = OptionParser(usage="""
    %prog [options]

    If run in client mode, it creates launcher files for mountable devices seen
    via dbus.  It creates launchers for kfmclient openprofile filemanagement
    that point to the right directory in /misc.

    If run in server, it edits /etc/auto.hal to create the same directories
    via the automounter.

    The default mode is server if its run as root, and client otherwise.
    """)
    parser.add_option(
            "-c","--client",action="store_false", dest="server", default=False,
            help="Run in client mode (default based on UID)")
    parser.add_option(
            "-s","--server",action="store_true", dest="server",
            help="Run in server mode (default based on UID)")
    parser.add_option(
            "-f","--foreground", action="store_true", dest="foreground",
            help="Don't Daemonize")
    parser.add_option(
            "-v","--verbose", action="store_true", dest="verbose",
            help="Print more debug text")

    if os.getuid() == 0: # root
        parser.set_defaults(server=True)

    (options, args) = parser.parse_args()
    if len(args) != 0:
        parser.error("Incorrect number of arguments")

    # set up logging
    if options.foreground:
        logger = logging.StreamHandler()
        logger.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    else:
        logger = logging.handlers.SysLogHandler("/dev/log", 11)
        logger.setFormatter(logging.Formatter(
            '%(filename)s: %(levelname)s: %(message)s'))
    logging.getLogger().addHandler(logger)

    if options.verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARN)

    logging.info("Options: %s" % repr(options))

    # daemonizing after connecting to the dbus breaks that connection
    if not options.foreground:
        daemonize()

    bus = dbus.SystemBus()
    if not bus:
        logging.error("Failed to connect to system dbus.  Exiting.")
        sys.exit()

    logging.info("bus: %s" % str(bus))

    # Clean up ~/Desktop...
    if not options.server:
        # connect to the session bus, so we go exit at logout
        sessionbus = dbus.SessionBus()
        if not sessionbus:
            logging.error("Failed to connect to session dbus.  Exiting.")
            sys.exit()

        logging.info("sesbus: %s" % str(sessionbus))

        for file in glob.glob(desktop + "/*.desktop"):
            f = open(file,'r');
            for line in f:
                if re.match("X-AUTOFS-HAL=true",line):
                    os.unlink(file)
                    break
            f.close
        # Detect the environment
        if "DESKTOP_SESSION" in os.environ:
            desktop_environment = os.environ['DESKTOP_SESSION'];
        else:
            desktop_environment = "gnome"

        if (desktop_environment == "kde"
                and os.access("/usr/bin/dolphin",os.X_OK)):
            desktop_environment = "kde4";

        logging.info("Assuming desktop environment : %s" % desktop_environment)

    # Back to main
    hal_manager = bus.get_object('org.freedesktop.Hal',
                                '/org/freedesktop/Hal/Manager')

    # Do a first pass before I just start listening
    drives = hal_manager.FindDeviceByCapability('volume',
                        dbus_interface = 'org.freedesktop.Hal.Manager')
    drives.extend(hal_manager.FindDeviceByCapability('storage',
                        dbus_interface = 'org.freedesktop.Hal.Manager'))

    for udi in drives:
        device_added_callback(udi)

    #sys.exit()

    # Listen for new additions/removals
    bus.add_signal_receiver(device_added_callback,
            'DeviceAdded',
            'org.freedesktop.Hal.Manager',
            'org.freedesktop.Hal',
            '/org/freedesktop/Hal/Manager')
    bus.add_signal_receiver(device_removed_callback,
            'DeviceRemoved',
            'org.freedesktop.Hal.Manager',
            'org.freedesktop.Hal',
            '/org/freedesktop/Hal/Manager')

    mainloop = gobject.MainLoop()
    try:
        mainloop.run()
    except (KeyboardInterrupt):
        pass
    # TBD: logging, log exceptions to syslog

if __name__ == "__main__":
    main()
