# interviewing_routes.py
import logging
from datetime import datetime
from flask import request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection

logger = logging.getLogger(__name__)

def register_interviewing_routes(app):

    @app.route("/interviewing", methods=["POST"])
    def create_interviewing_row():
        """
        Body JSON:
          - opportunity_id (int)
          - since_interviewing (YYYY-MM-DD)
        Inserts a new row into interviewing with incremental interviewing_id.
        """
        data = request.get_json(silent=True) or {}
        opportunity_id = data.get("opportunity_id")
        since_interviewing = data.get("since_interviewing")

        if opportunity_id is None or not since_interviewing:
            return jsonify({"error": "Missing opportunity_id or since_interviewing"}), 400

        try:
            # valida formato YYYY-MM-DD
            datetime.strptime(since_interviewing, "%Y-%m-%d")
        except Exception:
            return jsonify({"error": "since_interviewing must be YYYY-MM-DD"}), 400

        conn = None
        try:
            conn = get_connection()
            conn.autocommit = False

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 🔒 Evita colisiones de IDs en concurrencia
                cur.execute("LOCK TABLE interviewing IN EXCLUSIVE MODE;")

                cur.execute("SELECT COALESCE(MAX(interviewing_id), 0) + 1 AS next_id FROM interviewing;")
                next_id = int(cur.fetchone()["next_id"])

                cur.execute(
                    """
                    INSERT INTO interviewing (interviewing_id, since_interviewing, opportunity_id)
                    VALUES (%s, %s, %s)
                    RETURNING interviewing_id;
                    """,
                    (next_id, since_interviewing, int(opportunity_id))
                )

                new_row = cur.fetchone()
                conn.commit()

            return jsonify({
                "success": True,
                "interviewing_id": new_row["interviewing_id"],
                "opportunity_id": int(opportunity_id),
                "since_interviewing": since_interviewing
            }), 201

        except Exception as e:
            if conn:
                conn.rollback()
            logger.exception("Error inserting interviewing row")
            return jsonify({"error": str(e)}), 500

        finally:
            if conn:
                conn.close()
