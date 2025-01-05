import psycopg2
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import logging
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from psycopg2.extras import RealDictCursor
from dropbox import Dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = "Downloads"
DOWNLOADS_FOLDER = 'Downloads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

INSERT_USERS_DATA = """
INSERT INTO USERS (name, email, password, date_of_birth, role) 
VALUES (%s, %s, %s, %s, %s) 
RETURNING id;
"""
CHECK_EMAIL_EXISTS = """
SELECT id FROM USERS WHERE email = %s;
"""

AUTHENTICATE_USER = """
SELECT id, name, date_of_birth, role FROM USERS WHERE email = %s AND password = %s;
"""

INSERT_PAYMENT = """
INSERT INTO payments (name, email, phone, file_path, section_name) 
VALUES (%s, %s, %s, %s, %s) 
RETURNING id;
"""


def get_db_connection():
    conn = psycopg2.connect(
        dbname='korsphaia_arabic_course',
        user='postgres',
        password='ali9141353',
        host='localhost',
        port='5432'
    )
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Configure a static folder for downloads
DOWNLOADS_FOLDER = os.path.join(os.path.dirname(__file__), 'Downloads')
app.config['DOWNLOADS_FOLDER'] = DOWNLOADS_FOLDER

@app.route('/files/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['DOWNLOADS_FOLDER'], filename)

@app.route('/api/course_materials', methods=['GET'])
def get_course_materials():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Updated SQL query to include section description, price, and category name
        query = '''
            SELECT 
                cs.name AS section_name, 
                cs.description AS section_description,
                cs.price AS section_price,
                cc.name AS category_name,
                cm.id AS material_id,
                cm.item_type, 
                cm.item_name, 
                cm.authorized, 
                cm.url, 
                cm.preview_url,
                cm.created_at
            FROM course_sections cs
            LEFT JOIN course_materials cm ON cs.id = cm.section_id
            LEFT JOIN course_categories cc ON cs.category_id = cc.id
            ORDER BY cs.name, cm.item_name
        '''
        
        cursor.execute(query)
        
        rows = cursor.fetchall()
    except psycopg2.Error as e:
        # More specific error handling
        app.logger.error(f"Database error: {e}")
        return jsonify({'error': 'Database query failed'}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # Group materials by section
    sections = {}
    for row in rows:
        section_name, section_description, section_price, category_name, material_id, item_type, item_name, authorized, url, preview_url, created_at = row
        
        # Skip rows with no materials
        if item_type is None:
            continue
        
        if section_name not in sections:
            sections[section_name] = {
                'name': section_name, 
                'description': section_description,
                'price': section_price,
                'category': category_name,
                'items': []
            }
        
        sections[section_name]['items'].append({
            'id': material_id,
            'type': item_type,
            'name': item_name,
            'authorized': authorized,
            'url': url,
            'previewUrl': preview_url,
            'created_at': created_at,
        })

    return jsonify({'sections': list(sections.values())})

@app.route('/api/register', methods=['POST'])
def create_user():
    try:
        data = request.get_json()
        logging.debug("Received data: %s", data)

        name = data["name"]
        email = data["email"]
        password = data["password"]
        date_of_birth = data["date_of_birth"]
        role = data["role"]

        if (role == ""):
            role = 'user'

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if the email already exists
        cursor.execute(CHECK_EMAIL_EXISTS, (email,))
        existing_user = cursor.fetchone()
        if existing_user:
            cursor.close()
            conn.close()
            return jsonify({"error": "This email is already registered."}), 409
        
        # Insert new user
        cursor.execute(INSERT_USERS_DATA, (name, email, password, date_of_birth, role))
        user_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "registered sucssesfuly"}), 201
    except Exception as e:
        logging.error("Error creating user", exc_info=True)
        return jsonify({"error": "An error occurred creating the user"}), 500
    


@app.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        logging.debug("Received login data: %s", data)

        email = data["email"]
        password = data["password"]

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Authenticate user
        cursor.execute(AUTHENTICATE_USER, (email, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            user_id, name, date_of_birth, role = user
            return jsonify({
                "id": user_id,
                "name": name,
                "date_of_birth": date_of_birth,
                "role": role,
                "message": "Login successful"
            }), 200
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    except Exception as e:
        logging.error("Error logging in user", exc_info=True)
        return jsonify({"error": "An error occurred during login"}), 500
    

@app.route('/api/materials', methods=['POST'])
def add_material():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Step 1: Check if the category exists
    cur.execute("SELECT id FROM course_categories WHERE name = %s", (data['category_name'],))
    category = cur.fetchone()
    
    if category is None:
        # If the category does not exist, create it
        cur.execute("""
            INSERT INTO course_categories (name) 
            VALUES (%s) RETURNING id
        """, (data['category_name'],))
        category_id = cur.fetchone()[0]
    else:
        # If the category exists, get the category_id
        category_id = category[0]
    
    # Step 2: Check if the section already exists
    cur.execute("SELECT id FROM course_sections WHERE name = %s", (data['section_name'],))
    section = cur.fetchone()
    
    if section is None:
        # If the section does not exist, create it with description and price
        cur.execute("""
            INSERT INTO course_sections (name, description, price, category_id) 
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (data['section_name'], data.get('description'), data.get('price'), category_id))
        section_id = cur.fetchone()[0]
    else:
        # If the section exists, get the section_id
        section_id = section[0]
    
    # Now insert the material with the section_id
    cur.execute("""
        INSERT INTO course_materials (section_id, item_type, item_name, authorized, url)
        VALUES (%s, %s, %s, %s, %s) RETURNING *
    """, (section_id, data['item_type'], data['item_name'], data['authorized'], data['url']))
    
    new_material = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify(new_material), 201


@app.route('/api/materials/<int:id>', methods=['PUT'])
def update_material(id):
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Check if the material exists
        cur.execute("SELECT * FROM course_materials WHERE id = %s", (id,))
        existing_material = cur.fetchone()
        if existing_material is None:
            return jsonify({'error': 'Material not found'}), 404

        # Check if the section exists
        cur.execute("SELECT id, description, price FROM course_sections WHERE name = %s", (data['section_name'],))
        section = cur.fetchone()            
        if section is None:
            return jsonify({'error': 'Section not found'}), 404
        
        section_id = section[0]
        
        # Update the section's description and price if provided
        if 'description' in data or 'price' in data:
            update_fields = []
            update_values = []
            if 'description' in data:
                update_fields.append("description = %s")
                update_values.append(data['description'])
            if 'price' in data:
                update_fields.append("price = %s")
                update_values.append(data['price'])
            update_values.append(section_id)

            if update_fields:
                cur.execute(f"""
                    UPDATE course_sections
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                """, update_values)

        # Update the material
        cur.execute("""
            UPDATE course_materials
            SET section_id = %s, item_type = %s, item_name = %s, authorized = %s, url = %s
            WHERE id = %s RETURNING *
        """, (section_id, data['item_type'], data['item_name'], data['authorized'], data['url'], id))

        updated_material = cur.fetchone()

        if updated_material is None:
            return jsonify({'error': 'Failed to update material'}), 500

        conn.commit()
    except psycopg2.Error as e:
        app.logger.error(f"Database error: {e}")
        return jsonify({'error': 'Database update failed'}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        cur.close()
        conn.close()

    return jsonify(updated_material), 200

@app.route('/api/materials/<int:id>', methods=['DELETE'])
def delete_material(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM course_materials WHERE id = %s RETURNING *", (id,))
    deleted_material = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if deleted_material:
        return '', 204
    else:
        return jsonify({'error': 'Material not found'}), 404
    


# Add these new endpoints to your existing Flask app

@app.route('/api/check-purchase/<section_name>')
def check_purchase(section_name):
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        
        # Validate section_name
        if not section_name:
            return jsonify({"error": "Section name is required"}), 400
            
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Use parameterized query to prevent SQL injection
            cursor.execute("""
                SELECT id, purchase_date, status, section_name 
                FROM purchases 
                WHERE user_id = %s AND section_name = %s AND status = 'COMPLETED'
                ORDER BY purchase_date DESC
                LIMIT 1
            """, (user_id, section_name))
            
            purchase = cursor.fetchone()
            
            return jsonify({
                "has_access": bool(purchase),
                "purchase_info": {
                    "id": purchase[0] if purchase else None,
                    "purchase_date": purchase[1].isoformat() if purchase and purchase[1] else None,
                    "status": purchase[2] if purchase else None,
                    "section_name": purchase[3] if purchase else None
                } if purchase else None
            })

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    except Exception as e:
        logger.error(f"Error checking purchase status: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while checking purchase status",
            "details": str(e) if app.debug else None
        }), 500

@app.route('/api/purchase-section', methods=['POST'])
def purchase_section():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        section_name = data.get('section_name')
        file_path = data.get('file_path')
        phone = data.get('phone')
        
        if not user_id or not section_name:
            return jsonify({"error": "Missing required fields"}), 400
            
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if purchase already exists
        cursor.execute("""
            SELECT id FROM purchases 
            WHERE user_id = %s AND section_name = %s
        """, (user_id, section_name))
        
        existing_purchase = cursor.fetchone()
        
        if existing_purchase:
            return jsonify({"error": "Section already purchased"}), 409
            
        # Create new purchase
        cursor.execute("""
            INSERT INTO purchases (user_id, section_name, file_path, phone, status)
            VALUES (%s, %s, %s, %s,'PENDING')
            RETURNING id, purchase_date, status
        """, (user_id, section_name, file_path, phone))
        
        new_purchase = cursor.fetchone()
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "message": "Purchase pending",
            "purchase": new_purchase
        }), 201
        
    except Exception as e:
        logger.error("Error processing purchase", exc_info=True)
        return jsonify({"error": "An error occurred processing the purchase"}), 500
    


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Return the relative path that will be stored in the database
        return jsonify({
            'message': 'File uploaded successfully',
            'filePath': os.path.join('Downloads', filename)
        }), 200
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/api/pending-payments', methods=['GET'])
def get_pending_payments():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Join the purchases table with the users table to get the user's name and id
        cursor.execute("""
            SELECT 
                purchases.id AS purchase_id,
                purchases.user_id,
                purchases.section_name,
                purchases.file_path,
                purchases.phone,
                purchases.purchase_date,
                purchases.status,
                users.name AS user_name
            FROM purchases
            JOIN users ON purchases.user_id = users.id
            WHERE purchases.status = 'PENDING'
        """)
        pending_payments = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify({"pending_payments": pending_payments}), 200
    except Exception as e:
        logger.error("Error fetching pending payments", exc_info=True)
        return jsonify({"error": "An error occurred fetching pending payments"}), 500



@app.route('/api/update-payment-status', methods=['POST'])
def update_payment_status():
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        new_status = data.get('status')

        if not payment_id or new_status not in ['COMPLETED', 'CANCELED']:
            return jsonify({"error": "Invalid data"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE purchases 
            SET status = %s 
            WHERE id = %s
        """, (new_status, payment_id))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Payment status updated successfully"}), 200
    except Exception as e:
        logger.error("Error updating payment status", exc_info=True)
        return jsonify({"error": "An error occurred updating payment status"}), 500

@app.route('/Downloads/<filename>')
def serveing_file(filename):
    try:
        # Secure the filename to prevent directory traversal attacks
        secure_name = secure_filename(filename)
        file_path = os.path.join(DOWNLOADS_FOLDER, secure_name)
        
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")  # Add this for debugging
            
        
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        print(f"Error serving file: {e}")
        


@app.route('/api/reviews', methods=['POST'])
def submit_review():
    try:
        data = request.get_json()
        section_name = data.get('section_id')  # This is now the section name
        user_id = data.get('user_id')
        rating = data.get('rating')

        # Validate input
        if section_name is None or user_id is None or rating is None:
            return jsonify({"error": "Missing required fields"}), 400

        # Validate rating
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            return jsonify({"error": "Rating must be an integer between 1 and 5"}), 400

        # Get the section ID from the section name
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM course_sections WHERE name = %s", (section_name,))
        section = cursor.fetchone()

        if section is None:
            return jsonify({"error": "Section not found"}), 404

        section_id = section[0]  # Get the section ID

        # Check if a review already exists for this user and section
        cursor.execute("""
            SELECT id FROM public.reviews 
            WHERE section_id = %s AND user_id = %s
        """, (section_id, user_id))
        existing_review = cursor.fetchone()

        if existing_review:
            # Update existing review
            cursor.execute("""
                UPDATE public.reviews 
                SET rating = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE section_id = %s AND user_id = %s
            """, (rating, section_id, user_id))
            message = "Review updated successfully"
        else:
            # Insert new review
            cursor.execute("""
                INSERT INTO public.reviews (section_id, user_id, rating) 
                VALUES (%s, %s, %s)
            """, (section_id, user_id, rating))
            message = "Review submitted successfully"

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": message}), 201
    except Exception as e:
        logger.error("Error submitting review", exc_info=True)
        return jsonify({"error": "An error occurred submitting the review"}), 500
    
@app.route('/api/reviews', methods=['GET'])
def get_reviews():
    try:
        section_name = request.args.get('section_name')
        user_id = request.args.get('user_id')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Modified query to join with course_sections to get the section name
        query = """
        SELECT cs.name AS section_name, r.user_id, r.rating 
        FROM public.reviews r
        JOIN public.course_sections cs ON r.section_id = cs.id
        WHERE 1=1
        """
        params = []

        if section_name:
            query += " AND cs.name = %s"
            params.append(section_name)

        if user_id:
            query += " AND r.user_id = %s"
            params.append(user_id)

        cursor.execute(query, params)
        reviews = cursor.fetchall()

        cursor.close()
        conn.close()

        # Format the response with section name
        response = [
            {
                "section_name": review[0], 
                "user_id": review[1], 
                "rating": review[2]
            } for review in reviews
        ]
        return jsonify(response), 200

    except Exception as e:
        logger.error("Error retrieving reviews", exc_info=True)
        return jsonify({"error": "An error occurred retrieving reviews"}), 500

        

if __name__ == '__main__':
    app.run(debug=True)
