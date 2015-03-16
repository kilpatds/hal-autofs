# Help Text #
```
usage:
    hal_autofs.py [options]

    If run in client mode, it creates launcher files for mountable devices seen
    via dbus.  It creates launchers for kfmclient openprofile filemanagement
    that point to the right directory in /misc.

    If run in server, it edits /etc/auto.hal to create the same directories
    via the automounter.

    The default mode is server if its run as root, and client otherwise.


options:
  -h, --help        show this help message and exit
  -c, --client      Run in client mode (default based on UID)
  -s, --server      Run in server mode (default based on UID)
  -f, --foreground  Don't Daemonize
  -v, --verbose     Print more debug text
```
