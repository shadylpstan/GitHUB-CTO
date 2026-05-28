import os

from github_cto.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=port, debug=debug, use_reloader=debug)
