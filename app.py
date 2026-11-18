import os
import socket
from threading import Timer
import webbrowser

from backend import create_app

app = create_app()


def available_port(starting_port):
    for port in range(starting_port, 65536):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(f"No available local port at or above {starting_port}.")


if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        port = int(os.environ.get("PORT", "5000"))
    else:
        port = available_port(int(os.environ.get("PORT", "5000")))
        os.environ["PORT"] = str(port)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        Timer(1, webbrowser.open, args=(f"http://127.0.0.1:{port}",)).start()
    app.run(debug=True, host="127.0.0.1", port=port)
