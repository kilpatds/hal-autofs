You know how annoying it is to have to remember to unmount your USB Thumb drive before you unplug it?  Don't you wish Linux had some mechanism by which the system could realize you're no longer using it and auto unmount it for you?

Oh wait.  It does.  autofs.

This daemon runs in two modes, depending on it's UID:

**System
> Listens to HAL via DBUS, and edits /etc/auto.hal, creating lines for each removeable device that's added to the system and HUPing autofs**

**User
> Listens to HAL via DBUS, and created .desktop objects on your desktop for each removable device, using the same mount point as the system side added to auto.hal**

You'll need to change auto.master to reference auto.hal:
```
    /misc   /etc/auto.hal --timeout=1 --ghost
```

You'll need to add users to the "users" group (vfat partitions are made group readable/writeable, and the group is set to the users group)

And you'll need to make sure your desktop environment runs it in user mode at log in (~/.kde/Autostart, or use gnome-session-properties)

The current version is 0.5, which
  * Reloads autofs after changing the config file, so that the contents of /misc show up properly
  * Detects the desktop, and launches the right file manager
  * Properly exits when you log out.