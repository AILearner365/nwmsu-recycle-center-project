from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, MetaData, text
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy import Float

# Create the database engine
engine = create_engine('sqlite:///recycle_center.db', connect_args={'timeout': 30})

# Define the base for the models
Base = declarative_base()

# User model
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)

# WasteRecord model
class WasteRecord(Base):
    __tablename__ = 'waste_records'
    id = Column(Integer, primary_key=True)
    date_collected = Column(Date, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))

    # Relationship to the User model
    user = relationship("User", back_populates="waste_records")

# Category model
class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey('categories.id'))
    
    # Relationship to parent and children
    parent = relationship("Category", back_populates="children", remote_side=[id])
    children = relationship("Category", back_populates="parent")

class RecyclingRevenue(Base):
    __tablename__ = 'recycling_revenue'
    id = Column(Integer, primary_key=True)
    sale_date = Column(Date, nullable=False)
    material_type = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    revenue = Column(Float, nullable=False)
    buyer = Column(String)


# Define the relationship between User and WasteRecord
User.waste_records = relationship("WasteRecord", order_by=WasteRecord.id, back_populates="user")

# Remember to create the table if it doesn’t exist
Base.metadata.create_all(engine)

# Create the session for interacting with the database
Session = sessionmaker(bind=engine)
db_session = Session()  # Renamed to db_session for clarity

# Function to add a new column
def add_new_column(db_session, column_name):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    waste_records_table = metadata.tables['waste_records']

    if column_name not in waste_records_table.columns:
        db_session.execute(text(f'ALTER TABLE waste_records ADD COLUMN {column_name} FLOAT DEFAULT 0'))
        db_session.commit()
        print(f"Column '{column_name}' added successfully.")
    else:
        print(f"Column '{column_name}' already exists.")

# Function to delete a column
def delete_column(db_session, column_name):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    waste_records_table = metadata.tables['waste_records']

    if column_name in waste_records_table.columns:
        db_session.execute(text(f'ALTER TABLE waste_records DROP COLUMN {column_name}'))
        db_session.commit()
        print(f"Column '{column_name}' deleted successfully.")
    else:
        print(f"Column '{column_name}' does not exist.")
