# Share the project ZIP on a local network

This workflow does not require internet access. Both devices must be connected
to the same Wi-Fi router, Ethernet network, or phone hotspot.

## Sender

From the project directory, run:

```bash
python3 scripts/share_project_lan.py
```

The command prints a temporary URL similar to:

```text
http://192.168.1.25:8765/download/random-token
```

Keep the terminal open and send that URL to the receiving device.

If port 8765 is already occupied, choose another port:

```bash
python3 scripts/share_project_lan.py --port 9000
```

To share a differently named ZIP:

```bash
python3 scripts/share_project_lan.py --file /absolute/path/project.zip
```

## Receiver

Open the displayed URL in a browser. Alternatively, download from a terminal:

```bash
curl -fL "DISPLAYED_URL" -o Github_bounty_dispenser-main.zip
```

Compare the downloaded file's SHA-256 value with the value printed by the
sender:

```bash
shasum -a 256 Github_bounty_dispenser-main.zip
```

On Linux, `sha256sum Github_bounty_dispenser-main.zip` provides the same check.

## Stop sharing

Press `Ctrl+C` in the sender's terminal. The URL stops working immediately.

If another device cannot connect:

1. Confirm both devices are on the same network and client isolation is off.
2. Allow incoming connections for Python if the operating-system firewall asks.
3. Try another port, such as `--port 9000`.
4. Confirm the displayed address is the sender's current Wi-Fi/Ethernet IPv4
   address. If necessary, pass it explicitly with `--host 192.168.x.x`.

The server exposes only the selected ZIP at a random tokenized URL. It does not
provide directory browsing, HTTPS, authentication, or internet-facing security.
Use it only on a trusted local network and stop it after the transfer.
