"""
Flask application factory for Podcastwise web UI.

Run with: python -m src.web.app
"""

import os
from flask import Flask, render_template, jsonify, request


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Register blueprints
    from .routes import shows, episodes, processing, export
    app.register_blueprint(shows.bp)
    app.register_blueprint(episodes.bp)
    app.register_blueprint(processing.bp)
    app.register_blueprint(export.bp)

    # Index route
    @app.route('/')
    def index():
        return render_template('episodes.html')

    return app


# For running directly with: python -m src.web.app
if __name__ == '__main__':
    app = create_app()
    print("\n" + "=" * 50)
    print("  Podcastwise Web UI")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(debug=True, port=5000)
