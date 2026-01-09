
# Console Auto-login (Raspberry Pi OS Lite)

User: piviewer
Password: m3pp3L

## Activeren
/etc/systemd/system/getty@tty1.service.d/autologin.conf

[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin piviewer --noclear %I $TERM
