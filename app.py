import matplotlib
matplotlib.use('Agg')  # Use Agg backend for non-GUI rendering
from flask import Flask, render_template, request, redirect, session as flask_session, flash, send_file, url_for, jsonify
from database import add_new_column, db_session, User, WasteRecord, Category, delete_column, engine, RecyclingRevenue, LandfillExpense
import bcrypt
import pandas as pd
from io import BytesIO
from dateutil.parser import parse
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from sqlalchemy import inspect
from datetime import datetime, timedelta
from sqlalchemy.sql import func  # Import func for date comparison
from database import LandfillExpense
from datetime import datetime
import re
import matplotlib.pyplot as plt
import io
import base64
from sqlalchemy import select, func
from flask import render_template, jsonify
from sqlalchemy import inspect, text, func
import logging



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
  flash("Invalid credentials!")
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

@app.route('/report/pie-chart')
def waste_pie_chart():
    # Get start and end dates from query parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if start_date and end_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('generate_report'))

    # Get columns dynamically from waste_records
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('waste_records') if col['name'] not in ('id', 'date_collected', 'user_id')]

    # Aggregate waste data within the date range
    landfill_weight = db_session.query(func.sum(LandfillExpense.weight))\
        .filter(LandfillExpense.landfill_date.between(start_date, end_date)).scalar() or 0

    # Check if Food_Compost column exists
    food_waste_weight = 0
    if 'Food_Compost' in columns:
        food_waste_weight = db_session.query(func.sum(text("Food_Compost")))\
            .filter(WasteRecord.date_collected.between(start_date, end_date)).scalar() or 0

    recycling_weight = db_session.query(func.sum(RecyclingRevenue.weight))\
        .filter(RecyclingRevenue.sale_date.between(start_date, end_date)).scalar() or 0

    # Prepare data for the pie chart
    labels = ['Landfill', 'Food Waste Compost', 'Recycling']
    weights = [landfill_weight, food_waste_weight, recycling_weight]
    filtered_labels = [label for label, weight in zip(labels, weights) if weight > 0]
    filtered_weights = [weight for weight in weights if weight > 0]
    colors = ['#4CAF50', '#FF9800', '#2196F3']  # Green for Landfill, Orange for Food Waste, Blue for Recycling

    # Create and save the pie chart
    plt.figure(figsize=(6, 6))
    plt.pie(
        filtered_weights,
        labels=filtered_labels,
        autopct=lambda p: f'{p:.1f}%\n({p * sum(filtered_weights) / 100:.0f} lbs)',
        startangle=140,
        colors=colors[:len(filtered_labels)]
    )

    # Add a legend with weights
    plt.legend(
        [f"{label}: {weight} lbs" for label, weight in zip(filtered_labels, filtered_weights)],
        title="Waste Type",
        loc="center left",
        bbox_to_anchor=(1, 0, 0.5, 1)
    )

    # Save the chart as an image
    img = BytesIO()
    plt.savefig(img, format='png', bbox_inches="tight")
    plt.close()
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode('utf8')

    return render_template('pie_chart_report.html', plot_url=plot_url)
    
@app.route('/report/monthly-waste-graphs')
def monthly_waste_graphs():
    # Retrieve start and end dates from request arguments
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Parse start and end dates for filtering
    if start_date and end_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('generate_report'))

    figures = []

    # 1. Recyclables by Type (Monthly)
    # 1. Recyclables by Type (Monthly)
    recyclables_data = (
        db_session.query(
            func.strftime('%Y-%m', RecyclingRevenue.sale_date).label('month'),
            RecyclingRevenue.material_type,
            func.sum(RecyclingRevenue.weight).label('total_weight')
        )
        .filter(RecyclingRevenue.sale_date.between(start_date, end_date))
        .group_by('month', RecyclingRevenue.material_type)
        .all()
    )

    # Prepare data for plotting
    recyclable_weights = {}
    for month, material_type, weight in recyclables_data:
        if material_type not in recyclable_weights:
            recyclable_weights[material_type] = []
        recyclable_weights[material_type].append((month, weight))

    # Ensure months are sorted in ascending order
    all_months = sorted({month for month, _, _ in recyclables_data})

    # Plot each recyclable type on a line chart
    plt.figure(figsize=(10, 6))
    for material_type, data in recyclable_weights.items():
        # Align data with sorted months
        month_weight_dict = dict(data)
        weights = [month_weight_dict.get(month, 0) for month in all_months]
        plt.plot(all_months, weights, marker='o', label=material_type)

    plt.xlabel("Month")
    plt.ylabel("Weight (lbs)")
    plt.xticks(rotation=45)
    plt.legend(loc="upper left")
    plt.tight_layout()

    # Save the plot to a buffer for rendering in the HTML
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches="tight")
    plt.close()
    img.seek(0)
    figures.append(base64.b64encode(img.getvalue()).decode('utf8'))


    # 2. Landfill, Compost, and Recycling Weights (Monthly)
    landfill_data = (
        db_session.query(
            func.strftime('%Y-%m', LandfillExpense.landfill_date).label('month'),
            func.sum(LandfillExpense.weight).label('total_weight')
        )
        .filter(LandfillExpense.landfill_date.between(start_date, end_date))
        .group_by('month')
        .order_by('month')
        .all()
    )

    # Get dynamic columns from the waste_records table for materials like Food_Compost
    inspector = inspect(engine)
    waste_record_columns = [col['name'] for col in inspector.get_columns('waste_records') if col['name'] not in ('id', 'date_collected', 'user_id')]

    # Create a dictionary to store compost data for each dynamic column
    compost_data = {}
    for column in waste_record_columns:
        column_data = (
            db_session.query(
                func.strftime('%Y-%m', WasteRecord.date_collected).label('month'),
                func.sum(text(column)).label('total_weight')
            )
            .filter(WasteRecord.date_collected.between(start_date, end_date))
            .group_by('month')
            .order_by('month')
            .all()
        )
        compost_data[column] = dict(column_data)

    recycling_data = (
        db_session.query(
            func.strftime('%Y-%m', RecyclingRevenue.sale_date).label('month'),
            func.sum(RecyclingRevenue.weight).label('total_weight')
        )
        .filter(RecyclingRevenue.sale_date.between(start_date, end_date))
        .group_by('month')
        .order_by('month')
        .all()
    )

    # Collect all unique months across landfill, compost, and recycling data
    all_months = sorted({month for month, _ in landfill_data} |
                        {month for compost_column in compost_data.values() for month, _ in compost_column.items()} |
                        {month for month, _ in recycling_data})

    landfill_weights = dict(landfill_data)
    compost_weights = {month: sum(compost_data[column].get(month, 0) for column in waste_record_columns) for month in all_months}
    recycling_weights = dict(recycling_data)

    weights_landfill = [landfill_weights.get(month, 0) for month in all_months]
    weights_compost = [compost_weights.get(month, 0) for month in all_months]
    weights_recycling = [recycling_weights.get(month, 0) for month in all_months]

    plt.figure(figsize=(10, 6))
    plt.plot(all_months, weights_landfill, marker='o', color='g', label='Landfill')
    plt.plot(all_months, weights_compost, marker='o', color='orange', label='Compost')
    plt.plot(all_months, weights_recycling, marker='o', color='b', label='Recycling')
    plt.xlabel("Month")
    plt.ylabel("Weight (lbs)")
    plt.xticks(rotation=45)
    plt.legend(loc="upper left")
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches="tight")
    plt.close()
    img.seek(0)
    figures.append(base64.b64encode(img.getvalue()).decode('utf8'))

    # 3. Diversion Rate (Monthly)
    diversion_data = []
    for month in all_months:
        total_waste = weights_landfill[all_months.index(month)] + weights_compost[all_months.index(month)] + weights_recycling[all_months.index(month)]
        diverted_waste = weights_compost[all_months.index(month)] + weights_recycling[all_months.index(month)]
        diversion_rate = (diverted_waste / total_waste * 100) if total_waste > 0 else 0
        diversion_data.append((month, diversion_rate))

    months_diversion, rates_diversion = zip(*diversion_data) if diversion_data else ([], [])
    plt.figure(figsize=(10, 6))
    plt.plot(months_diversion, rates_diversion, marker='o', color='purple', label='Diversion Rate (%)')
    plt.xlabel("Month")
    plt.ylabel("Diversion Rate (%)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches="tight")
    plt.close()
    img.seek(0)
    figures.append(base64.b64encode(img.getvalue()).decode('utf8'))

    # 4. Recycling Revenue (Monthly)
    revenue_data = (
        db_session.query(
            func.strftime('%Y-%m', RecyclingRevenue.sale_date).label('month'),
            func.sum(RecyclingRevenue.revenue).label('total_revenue')
        )
        .filter(RecyclingRevenue.sale_date.between(start_date, end_date))
        .group_by('month')
        .order_by('month')
        .all()
    )

    months_revenue, total_revenue = zip(*sorted(revenue_data)) if revenue_data else ([], [])
    plt.figure(figsize=(10, 6))
    plt.plot(months_revenue, total_revenue, marker='o', color='g')
    plt.xlabel("Month")
    plt.ylabel("Revenue (USD)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches="tight")
    plt.close()
    img.seek(0)
    figures.append(base64.b64encode(img.getvalue()).decode('utf8'))

    return render_template('monthly_waste_graphs.html', figures=figures)

from sqlalchemy import text

def calculate_diversion_rate():
    total_waste = (
        (db_session.query(func.sum(LandfillExpense.weight)).scalar() or 0) +
        (db_session.query(func.sum(text("Food_Compost"))).scalar() or 0) +  # Dynamic access for Food_Compost
        (db_session.query(func.sum(RecyclingRevenue.weight)).scalar() or 0)
    )

    diverted_waste = (
        (db_session.query(func.sum(text("Food_Compost"))).scalar() or 0) +  # Dynamic access for Food_Compost
        (db_session.query(func.sum(RecyclingRevenue.weight)).scalar() or 0)
    )

    if total_waste == 0:
        return 0
    return (diverted_waste / total_waste) * 100


#Summary Reports logic 
# Route to display the Generate Report form


@app.route('/generate-report', methods=['GET', 'POST'])
def generate_report():
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        return redirect(url_for('summary_table', start_date=start_date, end_date=end_date))
    return render_template('generate_report.html')

@app.route('/report/summary-table')
def summary_table():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # Ensure start_date and end_date are not None before using them
    if not start_date_str or not end_date_str:
        flash("Start date and end date are required.", "danger")
        return redirect(url_for('generate_report'))

    # Parse start and end dates for consistency
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

    summary_data, months = get_summary_data(start_date, end_date)
    
    # Pass start_date_str and end_date_str to the template
    return render_template(
        'summary_table.html', 
        summary_data=summary_data, 
        months=months, 
        start_date_str=start_date_str, 
        end_date_str=end_date_str
    )



#get_summary_data
def get_summary_data(start_date, end_date):
    summary_data = {
        'revenue': {}, 'landfill': {}, 'compost': {}, 'recycled': {}, 'diversion_rate': {},
        'recycled_total': {}, 'generated_total': {}, 'diverted_total': {}
    }
    
    months = []
    current = start_date
    while current <= end_date:
        month_str = current.strftime('%Y-%m')
        months.append(month_str)
        current = (current.replace(day=1) + timedelta(days=32)).replace(day=1)

    # Recycling Revenue
    for month in months:
        revenue = db_session.query(func.sum(RecyclingRevenue.revenue)) \
                            .filter(func.strftime('%Y-%m', RecyclingRevenue.sale_date) == month).scalar() or 0
        summary_data['revenue'][month] = revenue

    # Landfill and Compost
    for month in months:
        landfill_weight = db_session.query(func.sum(LandfillExpense.weight)) \
                                    .filter(func.strftime('%Y-%m', LandfillExpense.landfill_date) == month).scalar() or 0
        compost_weight = db_session.query(func.sum(text("Food_Compost"))) \
                                   .filter(func.strftime('%Y-%m', WasteRecord.date_collected) == month).scalar() or 0
        summary_data['landfill'][month] = landfill_weight
        summary_data['compost'][month] = compost_weight  # Add compost weight per month

    # Get dynamic columns for recyclable materials from `waste_records`
    inspector = inspect(db_session.bind)
    recyclable_columns = [col['name'] for col in inspector.get_columns('waste_records') if col['name'] not in ('id', 'date_collected', 'user_id')]

    # Calculate weights for each dynamic recyclable column and store total recycled weight per month
    for month in months:
        total_recycled = 0
        for column in recyclable_columns:
            weight = db_session.query(func.sum(text(column))) \
                               .filter(func.strftime('%Y-%m', WasteRecord.date_collected) == month).scalar() or 0
            summary_data['recycled'].setdefault(column, {})[month] = weight
            total_recycled += weight
        summary_data['recycled_total'][month] = total_recycled

    # Calculate total waste generated and total waste diverted per month
    for month in months:
        total_generated = summary_data['landfill'].get(month, 0) + summary_data['compost'].get(month, 0) + summary_data['recycled_total'].get(month, 0)
        total_diverted = summary_data['compost'].get(month, 0) + summary_data['recycled_total'].get(month, 0)
        summary_data['generated_total'][month] = total_generated
        summary_data['diverted_total'][month] = total_diverted
        summary_data['diversion_rate'][month] = (total_diverted / total_generated * 100) if total_generated > 0 else 0

    # Calculate overall totals
    summary_data['totals'] = {
        'revenue': sum(summary_data['revenue'].values()),
        'landfill': sum(summary_data['landfill'].values()),
        'compost': sum(summary_data['compost'].values()),
        'recycled': sum(summary_data['recycled_total'].values()),
        'waste_generated': sum(summary_data['generated_total'].values()),
        'waste_diverted': sum(summary_data['diverted_total'].values()),
        'diversion_rate': (sum(summary_data['diverted_total'].values()) / sum(summary_data['generated_total'].values()) * 100) if sum(summary_data['generated_total'].values()) > 0 else 0
    }

    return summary_data, months



# Route to download landfill expenses as an Excel file
@app.route('/download-landfill-expenses', methods=['GET'])
def download_landfill_expenses():
    # Get start and end dates from the query parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Convert start and end dates to datetime objects
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Query the landfill expenses within the date range
    expenses = db_session.query(LandfillExpense).filter(
        LandfillExpense.landfill_date.between(start_date, end_date)
    ).all()
    
    # Prepare data for Excel
    data = [{
        'Landfill Date': exp.landfill_date,
        'Weight (lbs)': exp.weight,
        'Expense (USD)': exp.expense,
        'Hauler': exp.hauler
    } for exp in expenses]
    
    # Create a DataFrame and export to Excel
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Landfill Expenses')
    output.seek(0)
    
    # Send the Excel file as a download
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name="Landfill_Expenses_Report.xlsx")


@app.route('/download-recycling-revenue', methods=['GET'])
def download_recycling_revenue():
    # Retrieve start and end dates from query parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # Validate the presence of start and end dates
    if not start_date_str or not end_date_str:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('generate_report'))

    try:
        # Convert string dates to datetime objects
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

        # Query the database for records within the date range
        revenues = db_session.query(RecyclingRevenue).filter(
            RecyclingRevenue.sale_date.between(start_date, end_date)
        ).all()

        # Check if any records were found
        if not revenues:
            flash("No recycling revenue records found for the selected date range.", "warning")
            return redirect(url_for('generate_report'))

        # Prepare data for the Excel file
        data = [{
            'Sale Date': rev.sale_date.strftime('%Y-%m-%d'),
            'Material Type': rev.material_type,
            'Weight (lbs)': rev.weight,
            'Revenue (USD)': rev.revenue,
            'Buyer': rev.buyer
        } for rev in revenues]

        # Create a DataFrame and write it to an Excel file in memory
        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Recycling Revenue')
        output.seek(0)

        # Send the Excel file as a downloadable attachment
        return send_file(output, as_attachment=True, download_name='Recycling_Revenue_Report.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        # Handle any exceptions that occur
        flash(f"An error occurred while processing your request: {e}", "danger")
        return redirect(url_for('generate_report'))
    

@app.route('/download-waste-records', methods=['GET'])
def download_waste_records():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not start_date or not end_date:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('generate_report'))

    try:
        # Parse the provided dates
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')

        # Reflect the table to get dynamic columns
        inspector = inspect(db_session.bind)
        all_columns = [col['name'] for col in inspector.get_columns('waste_records')]

        # Exclude 'user_id' and 'id' from the columns list
        columns_to_include = [col for col in all_columns if col not in ('user_id', 'id')]

        # Query the database for records within the date range with eager loading
        records = db_session.query(WasteRecord).options(joinedload(WasteRecord.user)).filter(
            WasteRecord.date_collected.between(start_date, end_date)
        ).all()

        if not records:
            flash("No waste records found for the selected date range.", "warning")
            return redirect(url_for('generate_report'))

        # Prepare data for the Excel file
        data = []
        for rec in records:
            # Access column values using the __table__ attribute
            record_data = {}
            for col in columns_to_include:
                # Use the column name to get the column object
                column_obj = WasteRecord.__table__.columns.get(col)
                if column_obj is not None:
                    # Retrieve the value of the column for the current record
                    record_data[col] = getattr(rec, col, None)
                else:
                    record_data[col] = None
            # Add user information if available
            record_data['User'] = rec.user.username if rec.user else 'N/A'
            data.append(record_data)

        # Create a DataFrame and write it to an Excel file in memory
        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Waste Records')
        output.seek(0)

        return send_file(output, as_attachment=True, download_name='Waste_Records_Report.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except ValueError as ve:
        flash(f"Date parsing error: {ve}", "danger")
        return redirect(url_for('generate_report'))
    except Exception as e:
        error_message = ''.join(traceback.format_exception(None, e, e.__traceback__))
        flash(f"An unexpected error occurred: {error_message}", "danger")
        return redirect(url_for('generate_report'))

@app.route('/download-summary-report', methods=['GET'])
def download_summary_report():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if not start_date_str or not end_date_str:
        flash("Start date and end date are required to download the report.", "danger")
        return redirect(url_for('generate_report'))
    
    # Parse dates
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    # Get the summary data using the updated get_summary_data function
    summary_data, months = get_summary_data(start_date, end_date)
    
    # Prepare data for Excel
    rows = []
    rows.append(['Metric'] + months + ['Item Totals'])
    
    # Add rows for various metrics
    revenue_row = ['Recycling Revenue ($)'] + [summary_data['revenue'].get(month, 0) for month in months] + [summary_data['totals'].get('revenue', 0)]
    rows.append(revenue_row)

    landfill_row = ['Landfill lbs.'] + [summary_data['landfill'].get(month, 0) for month in months] + [summary_data['totals'].get('landfill', 0)]
    rows.append(landfill_row)

    compost_row = ['Compost lbs.'] + [summary_data['compost'].get(month, 0) for month in months] + [summary_data['totals'].get('compost', 0)]
    rows.append(compost_row)

    for material, data in summary_data['recycled'].items():
        material_row = [f"{material} lbs."] + [data.get(month, 0) for month in months] + [sum(data.values())]
        rows.append(material_row)

    total_recycled_row = ['Total Recycled lbs.'] + [summary_data['recycled_total'].get(month, 0) for month in months] + [summary_data['totals'].get('recycled', 0)]
    rows.append(total_recycled_row)

    total_waste_generated_row = ['Total Waste Generated lbs.'] + [summary_data['generated_total'].get(month, 0) for month in months] + [summary_data['totals'].get('waste_generated', 0)]
    rows.append(total_waste_generated_row)

    total_waste_diverted_row = ['Total Waste Diverted lbs.'] + [summary_data['diverted_total'].get(month, 0) for month in months] + [summary_data['totals'].get('waste_diverted', 0)]
    rows.append(total_waste_diverted_row)

    # Corrected line for Waste Diversion Rate %
    diversion_rate_row = ['Waste Diversion Rate %'] + [summary_data['diversion_rate'].get(month, '-') for month in months] + [round(summary_data['totals'].get('diversion_rate', 0), 2)]
    rows.append(diversion_rate_row)

    # Convert to DataFrame for Excel output
    df = pd.DataFrame(rows[1:], columns=rows[0])

    # Save the DataFrame to an in-memory Excel file
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Summary Report')
    output.seek(0)

    # Send the file as a download
    return send_file(output, as_attachment=True, download_name='Summary_Report.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.template_filter('dateformat')
def dateformat(value, format='%b-%y'):
    """Format a string date (YYYY-MM) to MMM-YY"""
    date = datetime.strptime(value, '%Y-%m')
    return date.strftime(format)

# Route for user logout
@app.route('/logout')
def logout():
    flask_session.clear()  # Clear the Flask session
    return redirect('/')
    
if __name__ == '__main__':
    app.run(debug=True)
