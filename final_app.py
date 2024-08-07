import streamlit as st
import subprocess
import shlex
import os
import shutil
from pymongo import MongoClient
import boto3
from io import BytesIO
from PIL import Image
from datetime import datetime

# Load secrets from Streamlit
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

# S3 Client
s3_client = boto3.client(
    's3',
    aws_access_key_id=IMAGE_S3_ACCESS_KEY,
    aws_secret_access_key=IMAGE_S3_SECRET_KEY,
    region_name=IMAGE_S3_REGION_NAME
)

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

    command = f"python yolov7/detect1.py --weights \"{weights_path}\" --conf {confidence_threshold} --source \"{image_path}\""
    process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Command failed with error: {error.decode('utf-8')}")

    predictions = output.decode("utf-8").split('\n')

    # Find the line before "The image with the result is saved in..."
    result_line_index = None
    for i, line in enumerate(predictions):
        if "The image with the result is saved in:" in line:
            result_line_index = i - 1
            break

    if result_line_index is not None and 0 <= result_line_index < len(predictions):
        result_line = predictions[result_line_index].strip()
        # Remove "Done. (14.5ms) Inference, (595.8ms) NMS" part
        result_line = result_line.split(', Done.')[0]
        # Remove numbers and return labels
        labels = [label.strip() for label in result_line.split(',')]
        labels = [remove_numbers(label).strip() for label in labels]
        return labels
    else:
        return []

def save_image(image_path, is_good):
    # Define directories
    download_path = os.path.expanduser('~/Downloads')
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

def store_image_details_in_mongo(image_name, classification, labels):
    """Store image classification details in MongoDB."""
    details = {
        "image_name": image_name,
        "classification": classification,
        "labels": labels,
        "classified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    classification_collection.insert_one(details)

def download_file(file_path):
    """Utility function to download a file."""
    with open(file_path, "rb") as file:
        file_data = file.read()
    return file_data

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
    return [image['image_name'] for image in bad_images]

def fetch_image_from_s3(bucket_name, key):
    """Fetch an image from S3 by its key."""
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

def download_images_to_folders(image_keys, base_download_path, max_images_per_folder=100):
    """Download images to local folders, limiting to max_images_per_folder per folder."""
    os.makedirs(base_download_path, exist_ok=True)
    
    # Create a set to keep track of all existing images to avoid duplicates
    existing_images = set()
    
    # Initialize folder counter and image counter
    folder_counter = 1
    image_counter = 0
    current_folder = os.path.join(base_download_path, f"images_batch_{folder_counter}")
    os.makedirs(current_folder, exist_ok=True)
    
    for key in image_keys:
        try:
            filename = os.path.basename(key)
            
            # Check for duplicate images using a set
            if filename in existing_images:
                st.info(f"Duplicate image detected: {filename}. Skipping download.")
                continue
            
            local_filename = os.path.join(current_folder, filename)

            # Fetch the image from S3
            image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
            img = Image.open(BytesIO(image_data))
            img.save(local_filename)
            
            # Update existing images set and counters
            existing_images.add(filename)
            image_counter += 1
            
            # Check if the current folder has reached the maximum number of images
            if image_counter >= max_images_per_folder:
                folder_counter += 1
                current_folder = os.path.join(base_download_path, f"images_batch_{folder_counter}")
                os.makedirs(current_folder, exist_ok=True)
                image_counter = 0  # Reset counter for the new folder

        except Exception as e:
            st.error(f"Failed to download image {key}: {str(e)}")

    st.success(f"Downloads completed. Total folders created: {folder_counter}")

def fetch_details_from_mongo(image_name):
    """Fetch image details from MongoDB."""
    # Find the document in MongoDB that matches the image name
    return classification_collection.find_one({"image_name": image_name})

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

def get_existing_classification(image_name):
    """Check if the image is already classified and return its classification."""
    return classification_collection.find_one({"image_name": image_name})

def update_classification_in_mongo(image_name, new_classification):
    """Update the classification in MongoDB, removing the previous one."""
    classification_collection.delete_many({"image_name": image_name})
    # Insert new classification
    classification_collection.insert_one(new_classification)

def save_classification_to_mongo(image_name, classification, details):
    """Save the classification to MongoDB."""
    # Prepare the data to be inserted
    metadata = {
        "image_name": image_name,
        "classification": classification,
        "user_id": details.get('userid', 'N/A'),
        "uploaded_at": details.get('uploaded_at', 'N/A'),
        "timestamp": details.get('timestamp', 'N/A'),
        "language": details.get('language', 'N/A'),
        "predictions": details.get('detection_results', [])
    }
    # Remove old classifications and insert the new one
    classification_collection.delete_many({"image_name": image_name})
    classification_collection.insert_one(metadata)

def fetch_classification_counts():
    """Fetch classification counts from MongoDB."""
    good_count = classification_collection.count_documents({"classification": "Good"})
    bad_count = classification_collection.count_documents({"classification": "Bad"})
    return good_count, bad_count

# Streamlit App
st.set_page_config(page_title="Beehive Image Detection", page_icon="🐝", layout="wide")

st.title("🐝 Beehive Image Detection and Management")

# Sidebar for authentication and navigation
with st.sidebar:
    st.header("Menu")
    # Tabs for navigation, directly list as options with emojis
    menu_options = [
        "🔒 Login",
        "📸 Object Detection",
        "🗂️ Image Management"
    ]
    selected_tab = st.radio("Navigate to:", menu_options)

# Page: Login
if selected_tab == "🔒 Login":
    st.header("🔒 Login Page")
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.subheader("Authentication")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if authenticate(username, password):
                st.session_state.authenticated = True
                st.success("Authentication successful!")
            else:
                st.error("Invalid username or password.")
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
        weights_path = "yolov7/best_v4.pt"
        confidence_threshold = 0.1

        if uploaded_file is not None:
            # Save the uploaded file
            image_path = os.path.join("yolov7/uploads", uploaded_file.name)
            if not os.path.exists("yolov7/uploads"):
                os.makedirs("yolov7/uploads")
            with open(image_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # Detect labels
            try:
                labels = detect_labels(weights_path, confidence_threshold, image_path)
                st.image(image_path, caption='Uploaded Image.', use_column_width=True)
                st.write("Predicted Labels:")
                st.write(labels)
                
                # User options for classification
                classification = st.radio("Classify the predictions:", ("Good", "Bad"))
                
                if st.button("Submit Classification"):
                    is_good = classification == "Good"
                    save_image(image_path, is_good)

                    # Store classification details in MongoDB
                    store_image_details_in_mongo(uploaded_file.name, classification, labels)

                    st.success("Image classified and saved successfully!")

                    # Option to download image
                    image_data = download_file(image_path)
                    st.download_button(
                        label="Download Classified Image",
                        data=image_data,
                        file_name=uploaded_file.name,
                        mime='image/png'
                    )

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
                    st.image(img, caption=f"**Image:** {key}", use_column_width=True)

                    # Fetch and display detection results from MongoDB
                    details = fetch_details_from_mongo(key)
                    if details:
                        st.write("### Detection Results:")
                        predictions = details.get('predictions', [])
                        if predictions:
                            for prediction in predictions:
                                label = prediction.get('label', 'Unknown')
                                percentage = prediction.get('percentage', 0)
                                st.write(f"- **{label}**: {percentage}%")
                        else:
                            st.write("No detection results available")

                        # Check for existing classification
                        existing_classification = get_existing_classification(key)

                        if existing_classification:
                            st.markdown(f"<large>**Current Classification:** {existing_classification['classification']}</large>", unsafe_allow_html=True)
                            st.markdown(f"<medium>Do you want to change the classification for {key}?</medium>",unsafe_allow_html=True)
                            change_classification = st.radio(
                                "Select an option",
                                ('Keep Existing', 'Change'),
                                index=0
                            )
                            if change_classification == 'Change':
                                new_classification = st.radio(
                                    f"New Classification for {key}",
                                    ('Good', 'Bad'),
                                    index=0
                                )
                                if st.button(f"Update Classification for {key}", key=f"update_{key}"):
                                    # Update classification
                                    update_classification_in_mongo(key, {
                                        "image_name": key,
                                        "classification": new_classification,
                                        "user_id": details.get('userid', 'N/A'),
                                        "uploaded_at": details.get('uploaded_at', 'N/A'),
                                        "timestamp": details.get('timestamp', 'N/A'),
                                        "language": details.get('language', 'N/A'),
                                        "predictions": details.get('predictions', [])
                                    })
                                    st.success(f"Classification for {key} updated successfully to {new_classification}.")

                        else:
                            # Classification Section
                            st.write("### Classify the Image")
                            classification = st.radio(f"Classification for {key}", ('Good', 'Bad'), index=0)

                            # Button to save classification
                            if st.button(f"Save Classification for {key}", key=f"save_{key}"):
                                save_classification_to_mongo(key, classification, details)
                                st.success(f"Classification for {key} saved successfully as {classification}.")
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
                    if st.button("Download Bad Images to Local Folders"):
                        # Fetch all bad image keys from MongoDB
                        bad_image_keys = fetch_bad_images_from_mongo()
                        if not bad_image_keys:
                            st.warning("No bad images found in the MongoDB collection.")
                        else:
                            # Define the base download path (your local Downloads folder)
                            base_download_path = os.path.expanduser("~/Downloads/wrong_classification")

                            # Download images to local folders, ensuring no duplicates
                            download_images_to_folders(bad_image_keys, base_download_path, max_images_per_folder=100)

