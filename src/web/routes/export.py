"""
Export routes - Google Sheets export.
"""

from flask import Blueprint, jsonify, request

bp = Blueprint('export', __name__)


@bp.route('/api/export/sheets', methods=['POST'])
def export_to_sheets():
    """Export processed episodes to Google Sheets."""
    try:
        from ...sheets import export_to_sheets

        result = export_to_sheets()
        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
