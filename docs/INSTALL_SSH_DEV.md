# Installatie SSH-dev

## 1. Upload naar de Pi

Upload de map `PiViewer_SSH_dev` via SFTP naar bijvoorbeeld:

```text
/tmp/PiViewer_SSH_dev
```

## 2. Installeren

```bash
cd /tmp/PiViewer_SSH_dev
sudo bash scripts/install_dev.sh
```

## 3. Controleren

```bash
sudo systemctl status piviewer-dev
journalctl -u piviewer-dev -f
```

## 4. Webinterface

Open in je browser:

```text
http://<ip-van-pi>:8080
```

## 5. Config aanpassen

```bash
sudo nano /etc/piviewer-dev/piviewer.json
sudo systemctl restart piviewer-dev
```
