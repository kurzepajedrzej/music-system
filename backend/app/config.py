import os

OWNTONE_URL = os.environ.get("OWNTONE_URL", "http://127.0.0.1:3689")
OWNTONE_WS_URL = os.environ.get("OWNTONE_WS_URL", "")
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
PIPE_URI = os.environ.get("PIPE_URI", "library:track:1")
PORT = int(os.environ.get("PORT", "3000"))
