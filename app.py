from flask import Flask, render_template, request, redirect, session as flask_session, flash, send_file, url_for, jsonify
from database import add_new_column, db_session, User, WasteRecord, Category, delete_column, engine, RecyclingRevenue, LandfillExpense
import bcrypt
import pandas as pd
from io import BytesIO
from dateutil.parser import parse
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from sqlalchemy import inspect
from datetime import datetime
from sqlalchemy.sql import func  # Import func for date comparison
from database import LandfillExpense
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
                    data[key] = value
        
        # Check for existing record
        existing_record = db_session.query(WasteRecord).filter_by(user_id=user_id, date_collected=selected_date).first()
        
        if existing_record:
            # Update existing record
            update_query = f"UPDATE waste_records SET {', '.join([f'{key} = :{key}' for key in data.keys()])} WHERE user_id = :user_id AND date_collected = :date_collected"
            db_session.execute(text(update_query), {**data, 'user_id': user_id, 'date_collected': selected_date})
            flash("Waste data updated successfully!", "success")
        else:
            # Insert new record
            insert_query = f"INSERT INTO waste_records (user_id, date_collected, {', '.join(data.keys())}) VALUES (:user_id, :date_collected, {', '.join([f':{key}' for key in data.keys()])})"
            db_session.execute(text(insert_query), {**data, 'user_id': user_id, 'date_collected': selected_date})
            flash("Waste data created successfully!", "success")
        
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
            return render_template('add_category.html')  # Render the same page with the success message

    return render_template('add_category.html')

# New route for deleting categories
@app.route('/delete_category', methods=['POST'])
def delete_category():
    category_id = request.form.get('category_id')
    subcategory_id = request.form.get('subcategory_id')
    
    category = db_session.query(Category).get(category_id)
    if category is None:
        flash("Category not found!")
        return redirect(url_for('delete_category'))

    if subcategory_id:
        subcategory = db_session.query(Category).get(subcategory_id)
        if subcategory:
            column_name = (category.name + '_' + subcategory.name).replace(' ', '_')
            db_session.delete(subcategory)
            delete_column(db_session, column_name)  # Use db_session here
            db_session.commit()
            flash(f"Subcategory '{subcategory.name}' deleted successfully!", "success")
    else:
        for subcategory in category.children:
            column_name = (category.name + '_' + subcategory.name).replace(' ', '_')
            delete_column(db_session, column_name)  # Use db_session here
            db_session.delete(subcategory)
        
        db_session.delete(category)
        db_session.commit()
        flash(f"Category '{category.name}' and its subcategories deleted successfully!", "success")

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

#Code for revenue report and landfill report plus adding entries to the database

@app.route('/generate-landfill-expense-report', methods=['GET', 'POST'])
def generate_landfill_expense_report():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        # Query landfill expense records within the date range
        expense_records = db_session.query(LandfillExpense).filter(
            LandfillExpense.landfill_date.between(start_date, end_date)
        ).all()

        # Prepare data for summary
        total_expense = sum(record.expense for record in expense_records)
        expense_data = [{
            'Landfill Date': record.landfill_date,
            'Weight (lbs)': record.weight,
            'Expense (USD)': record.expense,
            'Hauler': record.hauler
        } for record in expense_records]

        # Optional: Generate Excel file
        if request.form.get('export') == 'excel':
            df = pd.DataFrame(expense_data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Landfill Expense Report')
            output.seek(0)
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             as_attachment=True, download_name="Landfill_Expense_Report.xlsx")
        
        return render_template('landfill_expense_report.html', total_expense=total_expense, expense_data=expense_data)

    return render_template('generate_landfill_expense_report.html')


@app.route('/generate-recycling-revenue-report', methods=['GET', 'POST'])
def generate_recycling_revenue_report():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        # Query recycling revenue records within the date range
        revenue_records = db_session.query(RecyclingRevenue).filter(
            RecyclingRevenue.sale_date.between(start_date, end_date)
        ).all()

        # Prepare data for summary
        total_revenue = sum(record.revenue for record in revenue_records)
        revenue_data = [{
            'Sale Date': record.sale_date,
            'Material Type': record.material_type,
            'Weight (lbs)': record.weight,
            'Revenue (USD)': record.revenue,
            'Buyer': record.buyer
        } for record in revenue_records]

        # Optional: Generate Excel file
        if request.form.get('export') == 'excel':
            df = pd.DataFrame(revenue_data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Recycling Revenue Report')
            output.seek(0)
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             as_attachment=True, download_name="Recycling_Revenue_Report.xlsx")
        
        return render_template('recycling_revenue_report.html', total_revenue=total_revenue, revenue_data=revenue_data)

    return render_template('generate_recycling_revenue_report.html')

@app.route('/add-landfill-expense', methods=['GET', 'POST'])
def add_landfill_expense():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))
    
    # Set today's date as the default for landfill_date
    today_date = datetime.today().date()
    
    if request.method == 'POST':
        # Get form values
        landfill_date = datetime.strptime(request.form['landfill_date'], '%Y-%m-%d').date()
        hauler = request.form['hauler']
        
        # Convert Weight and Expense directly to float, assuming valid numeric input
        weight = float(request.form['weight'])
        expense = float(request.form['expense'])
        
        # Validate Hauler to ensure it is alphanumeric
        if not re.match(r'^[a-zA-Z0-9 ]+$', hauler):
            flash("Hauler name must be alphanumeric and cannot contain special characters.", "danger")
            return render_template('add_landfill_expense.html', today_date=today_date)
        
        # Check for an existing record with the same date and hauler
        existing_expense = db_session.query(LandfillExpense).filter(
            func.date(LandfillExpense.landfill_date) == landfill_date,
            LandfillExpense.hauler == hauler
        ).first()
        
        if existing_expense:
            # Update the existing record with the same hauler
            existing_expense.weight = weight
            existing_expense.expense = expense
            flash("Landfill expenses updated successfully!", "success")
        else:
            # Add a new landfill expense record (different hauler or new entry)
            new_expense = LandfillExpense(
                landfill_date=landfill_date,
                weight=weight,
                expense=expense,
                hauler=hauler
            )
            db_session.add(new_expense)
            flash("Landfill expenses added successfully!", "success")
        
        # Commit the changes to the database
        try:
            db_session.commit()
            return redirect(url_for('add_landfill_expense'))  # Redirect to refresh the form
        except Exception as e:
            flash(f"An error occurred: {e}", "danger")
            db_session.rollback()
    
    return render_template('add_landfill_expense.html', today_date=today_date)

# Function to get relevant columns from waste_records table
def get_material_type_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns('waste_records')
    material_columns = [col['name'] for col in columns if col['name'] not in ('id', 'date_collected', 'user_id')]
    return material_columns

@app.route('/add-recycling-revenue', methods=['GET', 'POST'])
def add_recycling_revenue():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))
    
    # Get material types from the columns in waste_records table
    material_columns = get_material_type_columns()
    today_date = datetime.today().date()
    
    if request.method == 'POST':
        # Get form values
        sale_date = datetime.strptime(request.form['sale_date'], '%Y-%m-%d').date()
        material_type = request.form['material_type']
        buyer = request.form['buyer']
        
        # Convert Weight and Revenue directly to float, assuming valid numeric input
        weight = float(request.form['weight'])
        revenue = float(request.form['revenue'])
        
        # Validate Buyer to ensure it is alphanumeric
        if not re.match(r'^[a-zA-Z0-9 ]+$', buyer):
            flash("Buyer name must be alphanumeric and cannot contain special characters.", "danger")
            return render_template('add_recycling_revenue.html', material_columns=material_columns, today_date=today_date)
        
        # Check for an existing record with the same date, material type, and buyer
        existing_record = db_session.query(RecyclingRevenue).filter(
            func.date(RecyclingRevenue.sale_date) == sale_date,
            RecyclingRevenue.material_type == material_type,
            RecyclingRevenue.buyer == buyer
        ).first()
        
        if existing_record:
            # Update the existing record with the same buyer
            existing_record.weight = weight
            existing_record.revenue = revenue
            flash("Recycling revenue record updated successfully!", "success")
        else:
            # Add a new recycling revenue record (different buyer or new entry)
            new_revenue = RecyclingRevenue(
                sale_date=sale_date,
                material_type=material_type,
                weight=weight,
                revenue=revenue,
                buyer=buyer
            )
            db_session.add(new_revenue)
            flash("Recycling revenue record added successfully!", "success")
        
        # Commit the changes to the database
        try:
            db_session.commit()
            return redirect(url_for('add_recycling_revenue'))  # Redirect to refresh the form
        except Exception as e:
            flash(f"An error occurred: {e}", "danger")
            db_session.rollback()
    
    return render_template('add_recycling_revenue.html', material_columns=material_columns, today_date=today_date)


@app.route('/delete_landfill_expense', methods=['GET', 'POST'])
def delete_landfill_expense():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        hauler_name = request.form.get('hauler_name')
        landfill_date_str = request.form.get('landfill_date')
        
        if hauler_name and landfill_date_str:
            landfill_date = datetime.strptime(landfill_date_str, '%Y-%m-%d').date()

            # Query to delete the landfill expense record for the selected hauler and date
            expense_record = db_session.query(LandfillExpense).filter_by(hauler=hauler_name, landfill_date=landfill_date).first()
            
            if expense_record:
                db_session.delete(expense_record)
                try:
                    db_session.commit()
                    flash(f"Landfill expense record for hauler '{hauler_name}' on {landfill_date_str} deleted successfully!", "success")
                except Exception as e:
                    db_session.rollback()
                    flash(f"An error occurred: {e}", "danger")
            else:
                flash("No landfill expense record found for the selected hauler and date!", "warning")
        else:
            flash("Please select both a hauler and a date to delete!", "warning")

        return redirect(url_for('delete_landfill_expense'))

    # For GET request, execute raw SQL to fetch all distinct hauler names
    result = db_session.execute(text("SELECT DISTINCT hauler FROM landfill_expenses"))
    haulers = [row[0] for row in result]

    # Pass current date to the template
    current_date = datetime.today().strftime('%Y-%m-%d')
    return render_template('delete_landfill_expense.html', haulers=haulers, current_date=current_date)

@app.route('/delete_recycling_revenue', methods=['GET', 'POST'])
def delete_recycling_revenue():
    if 'role' not in flask_session or flask_session['role'] != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        sale_date_str = request.form.get('sale_date')
        material_type = request.form.get('material_type')
        buyer = request.form.get('buyer')
        
        if sale_date_str and material_type and buyer:
            sale_date = datetime.strptime(sale_date_str, '%Y-%m-%d').date()

            # Query to delete the recycling revenue record for the selected date, material type, and buyer
            revenue_record = db_session.query(RecyclingRevenue).filter_by(
                sale_date=sale_date,
                material_type=material_type,
                buyer=buyer
            ).first()
            
            if revenue_record:
                db_session.delete(revenue_record)
                try:
                    db_session.commit()
                    flash(f"Recycling revenue record for buyer '{buyer}' on {sale_date_str} deleted successfully!", "success")
                except Exception as e:
                    db_session.rollback()
                    flash(f"An error occurred: {e}", "danger")
            else:
                flash("No recycling revenue record found for the selected date, material type, and buyer!", "warning")
        else:
            flash("Please select a date, material type, and buyer to delete!", "warning")

        return redirect(url_for('delete_recycling_revenue'))

    # For GET request, fetch distinct material types and buyers
    material_columns = get_material_type_columns()
    buyers_result = db_session.execute(text("SELECT DISTINCT buyer FROM recycling_revenue"))
    buyers = [row[0] for row in buyers_result if row[0]]  # Exclude any None values

    # Pass current date to the template
    current_date = datetime.today().strftime('%Y-%m-%d')
    return render_template('delete_recycling_revenue.html', material_columns=material_columns, buyers=buyers, current_date=current_date)

# Route for user logout
@app.route('/logout')
def logout():
    flask_session.clear()  # Clear the Flask session
    return redirect('/')
    
if __name__ == '__main__':
    app.run(debug=True)
