from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from .blueprints.instances import bp as instances_bp
from .blueprints.sql import bp as sql_bp
from .blueprints.schema import bp as schema_bp
from .blueprints.ai import bp as ai_bp
from .blueprints.imports import bp as imports_bp


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)
    app.register_blueprint(instances_bp)
    app.register_blueprint(sql_bp)
    app.register_blueprint(schema_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(imports_bp)
    return app


def main():
    app = create_app()
    app.run(host="0.0.0.0", port=5757, debug=True)


if __name__ == "__main__":
    main()
