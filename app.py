from flask import Flask, render_template, request, redirect, session as flask_session, flash, send_file, url_for, jsonify
from database import add_new_column, db_session, User, WasteRecord, Category, delete_column
import bcrypt
import pandas as pd
from io import BytesIO
from dateutil.parser import parse
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from datetime import datetime
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Create Admin User if not present (using a helper function)
def create_admin_user():
    admin = db_session.query(User).filter_by(username='admin').first()
    if not admin:
        hashed_password = bcrypt.hashpw('adminpassword'.encode('utf-8'), bcrypt.gensalt())
        admin_user = User(username='admin', password=hashed_password.decode('utf-8'), role='admin')
        db_session.add(admin_user)
        db_session.commit()

# Initialize the app by creating an admin user
create_admin_user()

# Route to display the login page
@app.route('/')
def home():
    return render_template('login.html')

# Route to handle login
@app.route('/login', methods=['POST'])
def login():
  username = request.form['username']
  password = request.form['password'].encode('utf-8')

  # Query the database for the user efficiently
  user = db_session.query(User).filter_by(username=username).first()
  if user and bcrypt.checkpw(password, user.password.encode('utf-8')):
    flask_session['user_id'] = user.id
    flask_session['role'] = user.role
    return redirect('/log-waste')
  flash("Invalid credentials")
  return redirect('/')

# Route to manage users (only for admin)
@app.route('/manage-users', methods=['GET', 'POST'])
def manage_users():
    # Ensure only admin users can access this route
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Adding a user
        if 'add_user' in request.form:
            username = request.form['username']
            password = request.form['password'].encode('utf-8')
            role = request.form['role']

            # Check for existing user
            existing_user = db_session.query(User).filter_by(username=username).first()
            if existing_user:
                flash("Username already exists!", "danger")
            else:
                hashed_password = bcrypt.hashpw(password, bcrypt.gensalt())
                new_user = User(username=username, password=hashed_password.decode('utf-8'), role=role)
                db_session.add(new_user)
                try:
                    db_session.commit()
                    flash("User added successfully!", "success")
                except Exception as e:
                    flash(f"An error occurred: {e}", "danger")
                    db_session.rollback()

        # Deleting a user
        elif 'delete_user' in request.form:
            user_id = request.form['user_id']
            user_to_delete = db_session.query(User).get(user_id)
            if user_to_delete:
                db_session.delete(user_to_delete)
                try:
                    db_session.commit()
                    flash("User deleted successfully!", "success")
                except Exception as e:
                    flash(f"An error occurred: {e}", "danger")
                    db_session.rollback()
            else:
                flash("User not found.", "danger")

    # Query for users to display in the management page
    users = db_session.query(User).all()
    return render_template('manage_users.html', users=users)
  
# Add this custom filter
@app.template_filter('get_attribute')
def get_attribute(obj, attr):
    return getattr(obj, attr, '')
  
# Route to log and update waste data
@app.route('/log-waste', methods=['GET', 'POST'])
def log_waste():
    if 'user_id' not in flask_session:
        return redirect('/')
    
    user_id = flask_session['user_id']
    
    if request.method == 'GET':
        selected_date = request.args.get('date_view') or flask_session.get('selected_date') or datetime.today().date()
        
        if isinstance(selected_date, str):
            selected_date = parse(selected_date).date()

        existing_record_query = text("SELECT * FROM waste_records WHERE user_id = :user_id AND date_collected = :date_collected")
        existing_record = db_session.execute(existing_record_query, {'user_id': user_id, 'date_collected': selected_date}).fetchone()
        flask_session['selected_date'] = selected_date.isoformat()
        
        categories = db_session.query(Category).filter_by(parent_id=None).options(joinedload(Category.children)).all()
        
        return render_template('log_waste.html', show_form=True, selected_date=selected_date, record=existing_record, categories=categories)
    
    elif request.method == 'POST':
        selected_date = parse(request.form['selected_date']).date()
        
        # Get data from the form
        data = {}
        for key, value in request.form.items():
            if key != 'selected_date':
                try:
                    data[key] = float(value) if value else 0
                except ValueError:
                    # Handle non-numeric values (e.g., for any text fields you might add in the future)
                    data[key] = value
        
        # Check for existing record
        existing_record = db_session.query(WasteRecord).filter_by(user_id=user_id, date_collected=selected_date).first()
        
        if existing_record:
            # Update existing record
            # for key, value in data.items():
            #     setattr(existing_record, key, value)
            update_query = f"UPDATE waste_records SET {', '.join([f'{key} = :{key}' for key in data.keys()])} WHERE user_id = :user_id AND date_collected = :date_collected"
            db_session.execute(text(update_query), {**data, 'user_id': user_id, 'date_collected': selected_date})
            flash("Waste data updated successfully!")
        else:
            # Insert new record
          #  new_record = WasteRecord(date_collected=selected_date, user_id=user_id, **data)
            insert_query = f"INSERT INTO waste_records (user_id, date_collected, {', '.join(data.keys())}) VALUES (:user_id, :date_collected, {', '.join([f':{key}' for key in data.keys()])})"
            db_session.execute(text(insert_query), {**data, 'user_id': user_id, 'date_collected': selected_date})
               
          #  db_session.add(new_record)
            flash("Waste data created successfully!")
        
        db_session.commit()
        return redirect(url_for('log_waste', date_view=selected_date))
    
    return render_template('log_waste.html', show_form=False)

# Route to generate a report
@app.route('/generate-report', methods=['GET', 'POST'])
def generate_report():
    if 'user_id' not in flask_session or flask_session['role'] != 'admin':
        return redirect('/')

    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        # Query the database efficiently
        records = db_session.query(WasteRecord).filter(WasteRecord.date_collected.between(start_date, end_date)).all()

        # Create the DataFrame efficiently
        data = [{
            'Date': record.date_collected,
            'Food Compost': record.food_compost,
            'Food NonCompost': record.food_noncompost,
            'Cardboard': record.cardboard,
            'Paper Mixed': record.paper_mixed,
            'Paper Newspaper': record.paper_newspaper,
            'Paper White': record.paper_white,
            'Plastic Pet': record.plastic_pet,
            'Plastic Natural': record.plastic_natural,
            'Plastic Colored': record.plastic_colored,
            'Aluminum': record.aluminum,
            'Metal Other': record.metal_other,
            'Glass': record.glass
        } for record in records]

        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)

        output.seek(0)

        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name="Waste_Report.xlsx")

    return render_template('generate_report.html')



def is_valid_name(name):
    """Validate if the name contains only allowed characters (letters and numbers)."""
    # Allow only letters and numbers
    pattern = r'^[a-zA-Z0-9]+$'
    return bool(re.match(pattern, name))

@app.route('/add-category', methods=['GET', 'POST'])
def add_category():
    if 'user_id' not in flask_session:
        return redirect('/')

    if request.method == 'POST':
        category_name = request.form.get('category_name')
        subcategories = request.form.getlist('subcategories[]')
        
        # Don't strip spaces as they're not allowed in the new validation
        
        # Validate category name
        if not is_valid_name(category_name):
            flash("Category Name is invalid. Only letters and numbers are allowed.", "danger")
            return render_template('add_category.html')

        # Validate subcategories
        for subcategory in subcategories:
            if not is_valid_name(subcategory):
                flash("Subcategory names are invalid. Only letters and numbers are allowed.", "danger")
                return render_template('add_category.html')

        if category_name and subcategories:
            existing_category_name = db_session.query(Category).filter(Category.name.ilike(category_name)).first()
            if not existing_category_name:
                new_category = Category(name=category_name)
                db_session.add(new_category)
                db_session.flush()  # This assigns an ID to new_category
            else:
                new_category = existing_category_name
            
            for subcategory in subcategories:
                if subcategory:  # Only add non-empty subcategories
                    # Check if the subcategory already exists
                    existing_subcategory = db_session.query(Category).filter(
                        Category.name.ilike(subcategory),
                        Category.parent_id == new_category.id
                    ).first()
                    
                    if not existing_subcategory:
                        new_subcategory = Category(name=subcategory, parent_id=new_category.id)
                        db_session.add(new_subcategory)
                        
                        # Add a new column to the waste_records table for each subcategory
                        add_new_column(db_session, category_name + "_" + subcategory)
                    else:
                        flash("Subcategories already existed!", "warning")
                        return render_template('add_category.html')
                        
            db_session.commit()
            flash("Category and subcategories added successfully!", "success")
        
        # Redirect back to log-waste with the stored date
        return redirect(url_for('log_waste', date_view=flask_session.get('selected_date')))

    # For GET requests, just render the add_category template
    return render_template('add_category.html')

# New route for deleting categories
@app.route('/delete_category', methods=['POST'])
def delete_category():
    category_id = request.form.get('category_id')
    subcategory_id = request.form.get('subcategory_id')
    
    category = db_session.query(Category).get(category_id)
    if category is None:
        flash("Category not found.")
        return redirect(url_for('delete_category'))

    if subcategory_id:
        subcategory = db_session.query(Category).get(subcategory_id)
        if subcategory:
            column_name = (category.name + '_' + subcategory.name).replace(' ', '_')
            db_session.delete(subcategory)
            delete_column(db_session, column_name)  # Use db_session here
            db_session.commit()
            flash(f"Subcategory '{subcategory.name}' deleted successfully, along with its data.")
    else:
        for subcategory in category.children:
            column_name = (category.name + '_' + subcategory.name).replace(' ', '_')
            delete_column(db_session, column_name)  # Use db_session here
            db_session.delete(subcategory)
        
        db_session.delete(category)
        db_session.commit()
        flash(f"Category '{category.name}' and its subcategories deleted successfully.")

    return redirect(url_for('delete_category'))


@app.route('/delete_category')
def show_delete_category():
    # Fetch only top-level categories (where parent_id is None)
    categories = db_session.query(Category).filter(Category.parent_id == None).all()
    return render_template('delete_Category.html', categories=categories)

@app.route('/get-subcategories/<int:category_id>')
def get_subcategories(category_id):
    subcategories = db_session.query(Category).filter_by(parent_id=category_id).all()
    return jsonify([{'id': sub.id, 'name': sub.name} for sub in subcategories])

# Route for user logout
@app.route('/logout')
def logout():
    flask_session.clear()  # Clear the Flask session
    return redirect('/')
    
if __name__ == '__main__':
    app.run(debug=True)
