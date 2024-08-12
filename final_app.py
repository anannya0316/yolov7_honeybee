import streamlit as st
import os
import shutil
import zipfile
from pymongo import MongoClient
import boto3
from io import BytesIO
from PIL import Image
from datetime import datetime
import platform
import pandas as pd
import subprocess
import shlex
import sys
import requests

# Accessing secrets from Streamlit's secrets.toml
IMAGE_S3_BUCKET_NAME = st.secrets["aws"]["bucket_name"]
IMAGE_S3_ACCESS_KEY = st.secrets["aws"]["access_key"]
IMAGE_S3_SECRET_KEY = st.secrets["aws"]["secret_key"]
IMAGE_S3_REGION_NAME = st.secrets["aws"]["region_name"]
MONGODB_URI = st.secrets["mongodb"]["uri"]

# MongoDB Client
client = MongoClient(MONGODB_URI)
db = client['humble_bee']
detection_collection = db['beehive_detection_records']
classification_collection = db['classification_of_results']
login_collection = db['login_credentials']

# S3 Client
s3_client = boto3.client(
    's3',
    aws_access_key_id=IMAGE_S3_ACCESS_KEY,
    aws_secret_access_key=IMAGE_S3_SECRET_KEY,
    region_name=IMAGE_S3_REGION_NAME
)

# Function to fetch image from URL and resize it
def get_resized_image(url, max_width=150):
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))
    img.thumbnail((max_width, max_width), Image.ANTIALIAS)
    return img
    
# Function to fetch image from S3
def fetch_image_from_s3(bucket_name, key):
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

# Function to display image from S3
def display_image_from_s3(bucket_name, key):
    image_data = fetch_image_from_s3(bucket_name, key)
    img = Image.open(BytesIO(image_data))
    st.image(img, caption=f"Image: {key}", use_column_width=False, width=150)  # Keep the image small

# Authentication
def authenticate(username, password):
    """Authenticate the user with predefined credentials."""
    return username == "beekind" and password == "beekind"

# Utility Functions
def remove_numbers(input_string):
    return input_string.translate(str.maketrans('', '', '0123456789'))

def detect_labels(weights_path, confidence_threshold, image_path):
    # Validate the file paths
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights file not found: {weights_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    command = f"{sys.executable} yolov7/detect3.py --weights \"{weights_path}\" --conf {confidence_threshold} --source \"{image_path}\""
    process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Command failed with error: {error.decode('utf-8')}")

    predictions = output.decode("utf-8").split('\n')
    detection_results = {}

    start_reading = False
    for line in predictions:
        if line.startswith("Object area percentages:"):
            start_reading = True
            continue
        if start_reading:
            if line.startswith("Done."):
                break
            parts = line.split(":")
            if len(parts) == 2:
                label = parts[0].strip()
                percentage = parts[1].strip()
                detection_results[label] = percentage

    return detection_results

def save_image(image_path, is_good):
    # Define directories
    download_path = get_downloads_folder()
    correct_folder = os.path.join(download_path, 'correct')
    incorrect_folder = os.path.join(download_path, 'incorrect')

    # Create folders if they do not exist
    if not os.path.exists(correct_folder):
        os.makedirs(correct_folder)
    if not os.path.exists(incorrect_folder):
        os.makedirs(incorrect_folder)

    # Move image to the correct folder
    if is_good:
        shutil.move(image_path, os.path.join(correct_folder, os.path.basename(image_path)))
    else:
        shutil.move(image_path, os.path.join(incorrect_folder, os.path.basename(image_path)))

def list_images_from_s3(bucket_name):
    """List image files from the specified S3 bucket, excluding certain prefixes."""
    response = s3_client.list_objects_v2(Bucket=bucket_name)
    images = []
    
    # Collect all image files
    for obj in response.get('Contents', []):
        key = obj['Key']
        # Filter image files, ignoring those with the prefix "qu13edjkbs"
        if key.endswith(('.png', '.jpg', '.jpeg')) and not key.startswith('qu13edjkbs'):
            images.append(key)
    
    return images

def fetch_bad_images_from_mongo():
    """Fetch image keys of bad images from MongoDB."""
    # Query MongoDB for images classified as "Bad"
    bad_images = classification_collection.find({"classification": "Bad"})
    
    # Safely access the 's3_filename' key using get() method to avoid KeyError
    return [image.get('s3_filename') for image in bad_images if 's3_filename' in image]

def fetch_good_images_from_mongo():
    """Fetch image keys of good images from MongoDB."""
    # Query MongoDB for images classified as "Good"
    good_images = classification_collection.find({"classification": "Good"})
    
    # Safely access the 's3_filename' key using get() method to avoid KeyError
    return [image.get('s3_filename') for image in good_images if 's3_filename' in image]

def fetch_image_from_s3(bucket_name, key):
    """Fetch an image from S3 by its key."""
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

def get_downloads_folder():
    """Get the path to the user's Downloads folder on any operating system."""
    system_name = platform.system()

    if system_name == 'Windows':
        # Use the HOME environment variable for Windows
        downloads_folder = os.path.join(os.getenv('USERPROFILE'), 'Downloads')
    elif system_name == 'Darwin':
        # Use the HOME environment variable for macOS (Darwin is the system name for macOS)
        downloads_folder = os.path.join(os.getenv('HOME'), 'Downloads')
    else:
        # Use the HOME environment variable for Linux and other Unix-like systems
        downloads_folder = os.path.join(os.getenv('HOME'), 'Downloads')

    return downloads_folder

def download_images_as_zip(good_image_keys, bad_image_keys):
    """Download images from S3 and provide them as a ZIP file download."""

    # Create a ZIP file in memory
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        # Create directories for Good and Bad classifications within the ZIP
        good_folder = "good/"
        bad_folder = "bad/"
        
        # Create a DataFrame to store details
        image_details = []

        for key in good_image_keys:
            try:
                # Fetch the image from S3
                image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
                img = Image.open(BytesIO(image_data))
                # Save the image to the Good folder in the ZIP archive
                with BytesIO() as img_buffer:
                    img.save(img_buffer, format=img.format)
                    zip_file.writestr(good_folder + os.path.basename(key), img_buffer.getvalue())
                
                # Add image details to DataFrame
                details = fetch_details_from_mongo(key)
                if details:
                    predictions = details.get('detection_results', [])
                    for prediction in predictions:
                        image_details.append({
                            "Filename": key,
                            "Classification": "Good",
                            "Label": prediction.get('label', 'Unknown'),
                            "Confidence": f"{prediction.get('percentage', 0):.2f}%"
                        })

            except Exception as e:
                st.error(f"Failed to download image {key}: {str(e)}")

        for key in bad_image_keys:
            try:
                # Fetch the image from S3
                image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
                img = Image.open(BytesIO(image_data))
                # Save the image to the Bad folder in the ZIP archive
                with BytesIO() as img_buffer:
                    img.save(img_buffer, format=img.format)
                    zip_file.writestr(bad_folder + os.path.basename(key), img_buffer.getvalue())
                
                # Add image details to DataFrame
                details = fetch_details_from_mongo(key)
                if details:
                    predictions = details.get('detection_results', [])
                    for prediction in predictions:
                        image_details.append({
                            "Filename": key,
                            "Classification": "Bad",
                            "Label": prediction.get('label', 'Unknown'),
                            "Confidence": f"{prediction.get('percentage', 0):.2f}%"
                        })

            except Exception as e:
                st.error(f"Failed to download image {key}: {str(e)}")
        
        # # Create a DataFrame for the image details and write to a CSV file in the ZIP archive
        # details_df = pd.DataFrame(image_details)
        # with BytesIO() as csv_buffer:
        #     details_df.to_csv(csv_buffer, index=False)
        #     zip_file.writestr("image_details.csv", csv_buffer.getvalue())

    # Provide a download link for the ZIP file
    st.download_button(
        label="Download Images and Details as ZIP",
        data=zip_buffer.getvalue(),
        file_name="classified_images.zip",
        mime="application/zip"
    )

def fetch_details_from_mongo(s3_filename):
    """Fetch image details from MongoDB."""
    # Find the document in MongoDB that matches the s3_filename
    return detection_collection.find_one({"s3_filename": s3_filename})

def extract_dates_from_keys(keys):
    """Extract unique dates from S3 image keys."""
    dates = set()
    for key in keys:
        # Assuming the filename format is "userid/images/YYYYMMDDHHMMSS.png"
        parts = key.split('/')
        if len(parts) > 1:
            date_str = parts[-1][:8]  # Extract YYYYMMDD from the filename
            try:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
                dates.add(date_obj)
            except ValueError:
                pass  # Skip any filenames that don't match the date format
    return sorted(dates)

def get_existing_classification(s3_filename):
    """Check if the image is already classified and return its classification."""
    return classification_collection.find_one({"s3_filename": s3_filename})

def update_classification_in_mongo(s3_filename, new_classification):
    """Update the classification in MongoDB, removing the previous one."""
    classification_collection.delete_many({"s3_filename": s3_filename})
    # Insert new classification
    classification_collection.insert_one(new_classification)

def save_classification_to_mongo(s3_filename, classification, details):
    """Save the classification to MongoDB."""
    # Prepare the data to be inserted
    metadata = {
        "s3_filename": s3_filename,
        "classification": classification,
        "user_id": details.get('userid', 'N/A'),
        "uploaded_at": details.get('uploaded_at', 'N/A'),
        "timestamp": details.get('timestamp', 'N/A'),
        "language": details.get('language', 'N/A'),
        "predictions": details.get('detection_results', [])
    }
    # Remove old classifications and insert the new one
    classification_collection.delete_many({"s3_filename": s3_filename})
    classification_collection.insert_one(metadata)

def fetch_classification_counts():
    """Fetch classification counts from MongoDB."""
    good_count = classification_collection.count_documents({"classification": "Good"})
    bad_count = classification_collection.count_documents({"classification": "Bad"})
    return good_count, bad_count

def extract_zip_file(uploaded_zip_file):
    """Extract the uploaded zip file to a local directory."""
    # Define the path to extract the files
    extract_path = "extracted_data"

    # Create the directory if it doesn't exist
    if not os.path.exists(extract_path):
        os.makedirs(extract_path)

    # Extract the uploaded zip file
    with zipfile.ZipFile(uploaded_zip_file, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    # Return the path where files were extracted
    return extract_path

def list_files_in_directory(directory_path):
    """List all files in a given directory."""
    files_list = []
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            files_list.append(os.path.join(root, file))
    return files_list

def display_image_details(key, details):
    """Display image details including classification and predictions."""
    # Check if predictions are available
    predictions = details.get('detection_results', [])
    
    # Format predictions as HTML list items
    prediction_list = [
        f"<li>{prediction.get('label', 'Unknown')}: {prediction.get('percentage', 0):.2f}%</li>"
        for prediction in predictions
    ]
    
    # Join predictions into an HTML unordered list
    detections = f"<ul>{''.join(prediction_list)}</ul>"

    # Fetch existing classification from MongoDB
    existing_classification = get_existing_classification(key)
    current_classification = existing_classification.get('classification', 'Unknown') if existing_classification else 'Unknown'

    # Construct HTML for the table
    html_table = f"""
    <table>
        <tr>
            <th>Category</th>
            <th>Details</th>
        </tr>
        <tr>
            <td>Detections</td>
            <td>{detections}</td>
        </tr>
        <tr>
            <td>Classification</td>
            <td>{current_classification}</td>
        </tr>
    </table>
    """

    # Render the table with st.markdown
    st.markdown(html_table, unsafe_allow_html=True)

    # Option to change classification without "Keep Existing"
    st.markdown("<h4 style='font-size: 20px;'>Do you want to change the classification?</h4>", unsafe_allow_html=True)

    # Radio button for new classification
    new_classification = st.radio(
        "If yes, choose an option:",
        ('Good', 'Bad'),
        index=0 if current_classification == 'Good' else 1
    )

    if st.button(f"Update Classification"):
        # Update classification
        update_classification_in_mongo(key, {
            "s3_filename": key,
            "classification": new_classification,
            "user_id": details.get('userid', 'N/A'),
            "uploaded_at": details.get('uploaded_at', 'N/A'),
            "timestamp": details.get('timestamp', 'N/A'),
            "language": details.get('language', 'N/A'),
            "predictions": details.get('detection_results', [])
        })
        st.success(f"Classification for {key} updated successfully to {new_classification}.")

# Function to hash passwords
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

# Function to verify passwords
def verify_password(password, hashed_password):
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password)

# Function to check if a username exists
def username_exists(username):
    return login_collection.find_one({"username": username}) is not None

# Function to create a new user
def create_user(username, password):
    if username_exists(username):
        return False, "Username already exists. Please choose another."
    
    hashed_password = hash_password(password)
    login_collection.insert_one({"username": username, "password": hashed_password})
    return True, "Account created successfully!"

# Function to authenticate the user
def authenticate(username, password):
    user = login_collection.find_one({"username": username})
    if user and verify_password(password, user['password']):
        return True
    return False

# Streamlit App
st.set_page_config(page_title="Beehive Image Detection", page_icon="🐝", layout="wide")

st.title("🐝 Beehive Image Detection and Management")

# Sidebar for authentication and navigation
with st.sidebar:
    st.header("Menu")
    menu_options = [
        "🔒 Login/Register",
        "📸 Object Detection",
        "🗂️ Image Management",
        "📚 Training",
        "🖼️ Image Validation"
    ]
    selected_tab = st.radio("Navigate to:", menu_options)

# Page: Login
# if selected_tab == "🔒 Login":
#     st.header("🔒 Login Page")
#     if 'authenticated' not in st.session_state:
#         st.session_state.authenticated = False

#     if not st.session_state.authenticated:
#         st.subheader("Authentication")
#         username = st.text_input("Username")
#         password = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if authenticate(username, password):
#                 st.session_state.authenticated = True
#                 st.success("Authentication successful!")
#             else:
#                 st.error("Invalid username or password.")
#     else:
#         st.success("You are already logged in!")

# Page: Login/Register
if selected_tab == "🔒 Login/Register":
    st.header("🔒 Login / Register")

    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if authenticate(username, password):
                st.session_state.authenticated = True
                st.success("Authentication successful!")
            else:
                st.error("Invalid username or password.")
        
        st.subheader("Or Register")
        reg_username = st.text_input("New Username")
        reg_password = st.text_input("New Password", type="password")

        if st.button("Register"):
            success, message = create_user(reg_username, reg_password)
            if success:
                st.success(message)
            else:
                st.error(message)
                
    else:
        st.success("You are already logged in!")

# Page: Object Detection
if selected_tab == "📸 Object Detection":
    if not st.session_state.get('authenticated', False):
        st.warning("Please log in to access this page.")
    else:
        st.header("📸 Object Detection with YOLOv7")

        # Upload image
        uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

        # Parameters
        weights_path = "best_v4.pt"
        confidence_threshold = 0.1

        if uploaded_file is not None:
            # Save the uploaded file
            image_path = os.path.join("yolov7/uploads", uploaded_file.name)
            if not os.path.exists("yolov7/uploads"):
                os.makedirs("yolov7/uploads")
            with open(image_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # Resize the image to half its original size
            img = Image.open(image_path)
            width, height = img.size
            new_size = (width // 1, height // 1)
            img_resized = img.resize(new_size)

            # Detect labels
            try:
                detections = detect_labels(weights_path, confidence_threshold, image_path)
                st.image(img_resized, caption='Uploaded Image (Resized).', width=new_size[0])  # Explicitly set the width
                st.write("Predicted Labels:")
                
                if detections:
                    for label, percentage in detections.items():
                        st.write(f"{label}: {percentage}")
                else:
                    st.write("No detections")

                # User options for classification
                classification = st.radio("Classify the predictions:", ("Good", "Bad"))
                
                if st.button("Submit Classification"):
                    is_good = classification == "Good"
                    save_image(image_path, is_good)
                    st.success("Image classified and saved successfully!")

            except Exception as e:
                st.error(f"Error: {str(e)}")



# Page: Image Management
if selected_tab == "🗂️ Image Management":
    if not st.session_state.get('authenticated', False):
        st.warning("Please log in to access this page.")
    else:
        st.header("🗂️ Beehive Image Classification and Management")

        # Fetch image keys from S3 bucket
        image_keys = list_images_from_s3(IMAGE_S3_BUCKET_NAME)

        # Extract available dates from image keys
        available_dates = extract_dates_from_keys(image_keys)

        if not available_dates:
            st.warning("No images found in the S3 bucket.")
        else:
            # Dropdown for selecting a date
            date_selected = st.selectbox("Select Date", available_dates, format_func=lambda x: x.strftime('%B %d, %Y'))

            # Convert the selected date to string format YYYYMMDD
            date_str = date_selected.strftime("%Y%m%d")

            # Filter image keys based on the selected date
            filtered_keys = [key for key in image_keys if date_str in key]

            # Debug: Display the number of images found for the selected date
            st.write(f"Number of images found for {date_selected.strftime('%B %d, %Y')}: {len(filtered_keys)}")

            if not filtered_keys:
                st.warning(f"No images found for the selected date: {date_selected.strftime('%B %d, %Y')}.")
            else:
                # Initialize session state for image index
                if 'image_index' not in st.session_state:
                    st.session_state.image_index = 0

                # Define navigation buttons with disabled state logic
                col1, col2, col3 = st.columns([1, 1, 1])

                with col1:
                    st.button("Previous", 
                            disabled=(st.session_state.image_index == 0),
                            on_click=lambda: st.session_state.update(image_index=st.session_state.image_index - 1)
                    )

                with col3:
                    st.button("Next", 
                            disabled=(st.session_state.image_index == len(filtered_keys) - 1),
                            on_click=lambda: st.session_state.update(image_index=st.session_state.image_index + 1)
                    )

                # Fetch the selected image
                if 0 <= st.session_state.image_index < len(filtered_keys):
                    key = filtered_keys[st.session_state.image_index]
                    image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
                    img = Image.open(BytesIO(image_data))
                    
                    col_image, col_details = st.columns([2.5, 1.5])  # Adjust column widths
                    with col_image:
                        st.image(img, caption=f"**Image:** {key}", use_column_width=True)

                    with col_details:
                        # Fetch and display detection results from MongoDB
                        details = fetch_details_from_mongo(key)
                        if details:
                            display_image_details(key, details)  # Call the function to display predictions and classification
                        else:
                            st.write("No detection results available.")

                # Only show classification and download buttons once
                st.write("---")  # Add a separator for clarity

                # Horizontal Layout for buttons
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Show Total Classifications"):
                        good_count, bad_count = fetch_classification_counts()
                        st.write(f"Total Good Classifications: {good_count}")
                        st.write(f"Total Bad Classifications: {bad_count}")

                with col2:
                    # Directly download good and bad images as ZIP when the button is clicked
                    bad_image_keys = fetch_bad_images_from_mongo()
                    good_image_keys = fetch_good_images_from_mongo()
                    if not bad_image_keys and not good_image_keys:
                        st.warning("No images found in the MongoDB collection.")
                    else:
                        download_images_as_zip(good_image_keys, bad_image_keys)

# Page: Training
if selected_tab == "📚 Training":
    if not st.session_state.get('authenticated', False):
        st.warning("Please log in to access this page.")
    else:
        st.header("📚 Training")

        # Upload zip file for training
        uploaded_zip_file = st.file_uploader("Upload Dataset Zip File:", type="zip")

        if uploaded_zip_file is not None:
            # Extract zip file
            st.info("Extracting zip file...")
            extracted_path = extract_zip_file(uploaded_zip_file)

            # List files
            files_list = list_files_in_directory(extracted_path)
            # st.write("Files Extracted:")
            # for file in files_list:
            #     st.write(file)

            st.success("Zip file extraction is complete! ")

# New Page: Image Validation
if selected_tab == "🖼️ Image Validation":
    if not st.session_state.get('authenticated', False):
        st.warning("Please log in to access this page.")
    else:
        st.header("🖼️ Image Validation Records")

        # CSS for the small image display
        st.markdown(
            """
            <style>
            .img-thumbnail {
                width: 50px; /* Adjust the size as needed */
                height: auto;
                margin-right: 10px;
                vertical-align: middle;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Fetch image validation data from MongoDB
        validation_records = detection_collection.find({})

        # Process and display the data in a table format
        data = []

        for record in validation_records:
            # Skip records with the ID 'qu13edjkbs'
            if 'qu13edjkbs' in record.get('s3_filename', ''):
                continue

            # Fetching classification status
            classification_record = classification_collection.find_one({"s3_filename": record.get("s3_filename")})
            validation_status = "Complete" if classification_record else "Pending"

            # Fetching the last validation date
            validated_on = classification_record.get("last_modified", "N/A") if classification_record else "N/A"

            # Convert timestamps to just dates
            uploaded_at = record.get("uploaded_at", "N/A")
            if isinstance(uploaded_at, datetime):
                uploaded_at = uploaded_at.strftime('%Y-%m-%d')

            if isinstance(validated_on, datetime):
                validated_on = validated_on.strftime('%Y-%m-%d')

            # System Output
            system_output = record.get("detection_results", "NA")
            if isinstance(system_output, list):
                try:
                    system_output = ", ".join([f"{det.get('label', 'Unknown')}: {det.get('percentage', '0')}%" for det in system_output])
                except (TypeError, KeyError) as e:
                    system_output = "NA"
            else:
                system_output = "NA"

            # Prepare the image display with the filename
            image_filename = record.get('s3_filename')
            image_url = f"https://{IMAGE_S3_BUCKET_NAME}.s3.amazonaws.com/{image_filename}"
            
            # Creating HTML for the image and filename
            image_html = f"""
            <div style="display: flex; align-items: center;">
                <img src="{image_url}" class="img-thumbnail" alt="{image_filename}"/>
                <span>{image_filename}</span>
            </div>
            """

            # Constructing the row
            row = {
                "Date": uploaded_at,
                "Uploaded by": record.get("userid", "N/A"),
                "Uploaded via": record.get("uploaded_via", "N/A"),
                "Location of upload": record.get("location", "N/A"),
                "Image file": image_html,
                "System Output": system_output,
                "Validation": validation_status,
                "Expert Output": "View" if record.get("expert_validated", False) else "Pending",
                "Expert Name": record.get("expert_name", "N/A"),
                "Validated on": validated_on,
                "Sys Accuracy": f"{record.get('system_accuracy', 0)}%",
                "Validate": "VALIDATE" if validation_status == "Pending" else "RE-VALIDATE"
            }
            data.append(row)

        # Convert the list of dictionaries to a DataFrame for display
        df = pd.DataFrame(data)

        # Display the DataFrame in Streamlit using HTML for the image link
        st.markdown(
            df.to_html(escape=False, index=False), 
            unsafe_allow_html=True
        )



