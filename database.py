from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, MetaData, text
from sqlalchemy.orm import sessionmaker, relationship, declarative_base


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

# Define the relationship between User and WasteRecord
User.waste_records = relationship("WasteRecord", order_by=WasteRecord.id, back_populates="user")

# Create all tables
Base.metadata.create_all(engine)


# Create the session for interacting with the database
Session = sessionmaker(bind=engine)
session = Session()

def add_new_column(session, column_name):
    # Reflect the existing database schema
    metadata = MetaData()
    metadata.reflect(bind=engine)
    waste_records_table = metadata.tables['waste_records']

    # Check if the column already exists to avoid duplication
    if column_name not in waste_records_table.columns:
        # Add the new column with a default value of 0
        session.execute(text(f'ALTER TABLE waste_records ADD COLUMN {column_name} FLOAT DEFAULT 0'))
        print(f"Column '{column_name}' added successfully.")
    else:
        print(f"Column '{column_name}' already exists.")