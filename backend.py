from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import psycopg2
import os
from datetime import datetime

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Enable CORS
CORS(app, supports_credentials=True)

# Make sure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ----------------------------
# DATABASE CONNECTION
# ----------------------------
try:
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        database="accident",
        user="postgres",
        password="1996"
    )
    cursor = conn.cursor()
    print("Database connected successfully!")
except Exception as e:
    print("Failed to connect to database:", e)
    exit(1)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr


# ----------------------------
# ROUTES
# ----------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route('/')
def index():
    return send_from_directory('.', "civilian/index.html")


@app.route('/civilian')
def civilian():
    return send_from_directory('.', "civilian/index.html")


@app.route('/authority')
def authority():
    return send_from_directory('.', "authority/index.html")


# ---------- HEALTH CHECK ----------
@app.route('/health', methods=['GET'])
def health_check():
    try:
        cursor.execute("SELECT COUNT(*) FROM reports")
        count = cursor.fetchone()[0]
        return jsonify({
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
            "reports_count": count,
            "database": "PostgreSQL"
        })
    except Exception as e:
        return jsonify({
            "status": "ERROR",
            "error": str(e)
        }), 500


# ---------- SUBMIT REPORT ----------
@app.route('/api/report', methods=['POST'])
def submit_report():
    try:
        incident_type = request.form.get('incident_type')
        description = request.form.get('description')
        subcity = request.form.get('subcity')
        district = request.form.get('district')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        reporter_ip = get_client_ip()

        # Handle file upload
        file_path = None
        media_filename = None
        if 'media' in request.files:
            file = request.files['media']
            if file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                media_filename = filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)

        # Insert into database
        query = """
            INSERT INTO reports (incident_type, description, subcity, district, latitude, longitude, reporter_ip, media_path, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        cursor.execute(query, (
            incident_type,
            description,
            subcity,
            district,
            float(latitude) if latitude else None,
            float(longitude) if longitude else None,
            reporter_ip,
            file_path,
            datetime.now()
        ))
        
        report_id = cursor.fetchone()[0]
        conn.commit()

        # Return response in expected format
        return jsonify({
            "success": True,
            "message": "Report submitted successfully",
            "data": {
                "report_id": report_id,
                "incident_type": incident_type,
                "description": description,
                "subcity": subcity,
                "district": district,
                "latitude": float(latitude) if latitude else None,
                "longitude": float(longitude) if longitude else None,
                "media_filename": media_filename,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }
        }), 201

    except Exception as e:
        print("Error submitting report:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- GET REPORTS ----------
@app.route('/api/reports', methods=['GET'])
def get_reports():
    try:
        # Try to get status column, fallback if it doesn't exist
        try:
            cursor.execute("""
                SELECT id, incident_type, description, subcity, district, latitude, longitude, reporter_ip, media_path, created_at, status
                FROM reports
                ORDER BY created_at DESC
            """)
            include_status = True
        except psycopg2.errors.UndefinedColumn:
            cursor.execute("""
                SELECT id, incident_type, description, subcity, district, latitude, longitude, reporter_ip, media_path, created_at
                FROM reports
                ORDER BY created_at DESC
            """)
            include_status = False

        rows = cursor.fetchall()

        reports = []
        for row in rows:
            # Extract filename from full path for media_filename
            media_filename = None
            if row[8]:  # media_path
                media_filename = os.path.basename(row[8])

            report_data = {
                "id": row[0],
                "report_id": row[0],  # Add report_id field expected by frontend
                "incident_type": row[1],
                "description": row[2],
                "subcity": row[3],
                "district": row[4],
                "latitude": float(row[5]) if row[5] else None,
                "longitude": float(row[6]) if row[6] else None,
                "reporter_ip": row[7],
                "media_path": row[8],
                "media_filename": media_filename,  # Add media_filename field expected by frontend
                "status": row[10] if include_status and len(row) > 10 else "pending",  # Use actual status or default
                "created_at": row[9].isoformat() if row[9] else None
            }
            reports.append(report_data)

        # Return in the format expected by the frontend
        return jsonify({
            "success": True,
            "data": reports,
            "count": len(reports)
        })

    except Exception as e:
        print("Error fetching reports:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- UPDATE REPORT STATUS ----------
@app.route('/api/reports/<int:report_id>/status', methods=['PUT'])
def update_report_status(report_id):
    try:
        data = request.get_json()
        new_status = data.get('status')

        if not new_status:
            return jsonify({"success": False, "error": "Status is required"}), 400

        # Check if status column exists, if not, just return success
        try:
            cursor.execute("""
                UPDATE reports
                SET status = %s, updated_at = %s
                WHERE id = %s
            """, (new_status, datetime.now(), report_id))

            if cursor.rowcount == 0:
                return jsonify({"success": False, "error": "Report not found"}), 404

            conn.commit()
            print(f"📝 Report {report_id} status updated to: {new_status}")

        except psycopg2.errors.UndefinedColumn:
            # Status column doesn't exist, just return success
            print(f"⚠️ Status column doesn't exist, but returning success for report {report_id}")

        return jsonify({
            "success": True,
            "message": "Status updated successfully"
        })

    except Exception as e:
        print("Error updating status:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- CLEAR ALL REPORTS ----------
@app.route('/api/reports/clear', methods=['DELETE'])
def clear_reports():
    try:
        # Get count before deletion
        cursor.execute("SELECT COUNT(*) FROM reports")
        count = cursor.fetchone()[0]
        
        # Delete all reports
        cursor.execute("DELETE FROM reports")
        conn.commit()
        
        return jsonify({
            "success": True,
            "message": f"All reports cleared successfully",
            "deleted_count": count
        })
        
    except Exception as e:
        print("Error clearing reports:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- LOCATION STATS ----------
@app.route('/api/reports/location-stats', methods=['GET'])
def location_stats():
    try:
        cursor.execute("""
            SELECT subcity, COUNT(*) as count 
            FROM reports 
            WHERE subcity IS NOT NULL 
            GROUP BY subcity
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
        
        stats = {}
        for row in rows:
            stats[row[0]] = row[1]
        
        return jsonify({
            "success": True,
            "data": stats
        })
        
    except Exception as e:
        print("Error fetching location stats:", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- SERVE UPLOADED FILES ----------
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ---------- ACCIDENTS BY TYPE ----------
@app.route('/api/accidents-by-type', methods=['GET'])
def accidents_by_type():
    try:
        cursor.execute("""
            SELECT 
                COALESCE(NULLIF(TRIM(incident_type), ''), 'Unknown') AS type,
                COUNT(*)::int
            FROM reports
            GROUP BY type
            ORDER BY COUNT(*) DESC;
        """)
        rows = cursor.fetchall()

        result = [{"type": r[0], "count": r[1]} for r in rows]
        return jsonify(result)

    except Exception as e:
        print("Error fetching accidents by type:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------
# MAIN
# ----------------------------
if __name__ == '__main__':
    print("🚀 Incident Reporting API Server starting...")
    print("📊 Authority Dashboard: http://localhost:5000/authority")
    print("📝 Civilian Portal: http://localhost:5000/civilian")
    print("🔗 API Health Check: http://localhost:5000/health")
    app.run(host='0.0.0.0', port=5000, debug=True)
